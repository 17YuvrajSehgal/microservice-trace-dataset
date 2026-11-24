# Decisions, 23-11-2026

## 1. All 25 blueprints are in the new form

Converted the last eight: 1 (document fields added to the prototype file), 3, 5, 7, and
the bare-metal ones 0, 8, 9, 10. All 25 pass `bp_check.py`, and each has a `BLUEPRINT.md`
generated from its `blueprint.yaml`. Open items are in `Blueprint/latency/TO-FIX.md`
(C23 to C30 are new).

Decisions:

- **Tools were not changed.** In 1, 3, 5, 7 the decisive tools print tables, not a verdict
  line. A verdict line needs bars, and bars need sweeps. So those steps rest on the agent
  reading a table, and each file's status says so. Stays in TO-FIX (C11).
- **Triage is its own kind.** Blueprint 0 confirms nothing; it sends the case to 8, 9, 10
  or 11 through hand-offs. `fault_type: triage`; the checker does not ask it for a
  confirming outcome.
- **Where README and tool disagree, the yaml follows the tool**, as before. The bare-metal
  READMEs had the same drift as 11 (a verdict that is no longer printed, verdicts that are
  printed but not listed).
- **Blueprint 5 covers `svc_net` and `anomaly_net`**: one-path loss against host-wide loss.
  The README does not use the family names; the mapping comes from its run counts.
- **Blueprint 5 "no loss shown" is inconclusive**, not rejected: added delay leaves no
  drops, the README says so.
- **Partner rule kept**: the bare-metal files were built only from READMEs and tools already
  in git, with the READMEs' neutral wording.

State of evidence, which the status line of each file now states:

| blueprints | labelled sweep | agent run in the new form |
|---|---|---|
| 12 to 24, 2, 4, 6, 11 | yes | one run per family (20-11) |
| 1 | no (older evaluation only) | one run, confirmed |
| 3, 5 | 3: no. 5: counts in the README, no results file | not run |
| 7 | none, never calibrated | cannot be run (no labelled family) |
| 0, 8, 9, 10 | partner traces, not public | not run; local model only |

Not done today: any agent run. The Trillium connection was closed, so 3 and 5 are
untested, and the tools of 3, 5, 7 are not copied to the cluster yet.

## 2. Agent runs of blueprints 3 and 5 (gpt-6-luna, Trillium login node)

| blueprint | run | result | truth |
|---|---|---|---|
| 5 | `svc_net_aggressive_steady_r1` | confirmed `svc_net`: 100% of the drops at the queue of one `java` container, window 16:58:40 to 17:00:40 | carts (Java), 4% loss, 16:58:42 to 17:00:42 |
| 5 | `anomaly_net_aggressive_steady_r1` | confirmed `anomaly_net`: 12 senders drop at their own queues, window 21:01:00 to 21:03:00 | all 18 containers, 2% loss, 21:01:05 to 21:03:06 |
| 3 | `slow_db_aggressive_steady_r1` | inconclusive | 500 ms added at the catalogue-db proxy, 14:38:01 to 14:40:01 |

Blueprint 5's two-family split works in a run for the first time.

Blueprint 3: the agent's findings were all right (window 14:38 to 14:40, gaps of 471 to 547
ms on ten connections, `toxiproxy` as the path component and `mysqld` as the dependency,
which answers its own requests at 502 ms). The verdict is inconclusive because the agent
left two steps through `other`: the step outcomes do not fit a Go victim (its pool
connections change between slices; it sleeps in locks, which the README lists as a
look-alike). This is a gap in the blueprint, not a misreading. The report writer disputed
the verdict and gave these reasons. First time the dispute path was used.

Not changed: the two steps of blueprint 3. A fix needs a rule that is checked on the
`slow_db` runs, not written from this one run. Listed as TO-FIX C31.

Count so far over first runs in the new form: 25 runs on 20 blueprints, 15 right.
