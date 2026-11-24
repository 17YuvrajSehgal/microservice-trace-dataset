# Decisions, 24-11-2026

## 1. A scan tool finds the fault time (TO-FIX B0)

Problem: 6 of the 10 failed first runs chose the wrong slice time. The rate table shows
data volume; for many faults it shows nothing, and twice its step was the end of the fault.

Decision: the agent gets `scan_times` (`Blueprint/agent/bp_graph.py`). One call cuts slices
over the whole trace, runs the step's own check on each and returns the verdict line per
time. Generic: the agent gives the check and the slice length from the step, so no
blueprint file changed. The agent decides when to use it; a rejection that rests on one
slice is sent back with a pointer to it.

Three changes came from testing it, each from a named run:

| change | run that showed it |
|---|---|
| Slices end to end by default; the output states the coverage | `error_storm`: 8 slices of 20 s with 10 s gaps showed no reset; a slice in a gap shows 12 of 12. The signal is bursty (about every 30 s) |
| Baselines are the first and the last slice of the trace, not the agent's choice (its own is added) | `noisy_neighbor`, `code_n_plus_one`: the agent's baseline was inside the fault, every time read the same |
| A scan whose check fails on every slice does not count; the tool description gives no flag in its example | `code_n_plus_one`: the agent copied a `--baseline` flag from my example, the check crashed 12 times, the harness counted it as a scan |

Result on the six runs that had failed on the slice time (Sock Shop r1, gpt-6-luna):

| run | before | with the scan tool | truth |
|---|---|---|---|
| `svc_mem_cap` | wrongly rejected | confirmed, `java`, reclaim from 23:20:02 | carts, 23:18:48 to 23:20:49 |
| `fork_storm` | second try | confirmed first try | |
| `anomaly_disk` | second try | confirmed first try | |
| `noisy_neighbor` | inconclusive, twice | confirmed: `stress-ng-cpu`, new at 13:12:03 to 13:13:39 | 13:11:54 to 13:13:55 |
| `error_storm` | second try | confirmed: resets at 12:31:29, 12:31:49, 12:32:28 | 12:31:06 to 12:33:06 |
| `code_n_plus_one` | rejected, three times | confirmed: `app` makes 3.1-3.2 calls per request to the database, 2.0-2.1 before (1.5-1.6x), 03:15:01 to 03:16:38 | catalogue, 03:14:57 to 03:17:00 |

How to read this result: 6 of 6, but not an independent test. The tool was changed between
tries on these same runs. It shows the tool can find these six; the rate over all families
is still to be measured.

Findings that matter beyond the tool:

- **A fault signal can be bursty.** `error_storm` resets come in bursts; 1 of 4 end-to-end
  slices inside the fault shows none. Our sweep count (16 of 16) used one slice at a fixed
  offset from the injection. Other "found N of N" counts may depend on the slice position
  in the same way (TO-FIX C32).
- **The baseline is a "when" problem too.** Against the first slice of the trace (load
  ramp-up) two healthy JVMs read CALL AMPLIFICATION in `code_n_plus_one`; against the last
  slice only the faulty service does. The agent chose the right one. Nothing checks that
  choice (TO-FIX B13).

Two harness faults found in the last run and fixed, not re-run: lines quoted from the scan
table failed the evidence check (the table was not in the checked output); and the harness
copied the last verdict line for the outcome into the evidence, here a line about another
process, which made the report writer dispute a correct verdict. Now it copies a line only
if the agent quoted none.

Cost: a scan is about 12 slices and 12 to 36 check runs. Runs took 3 to 7 minutes on the
login node. Too heavy there for the lock blueprints.
