<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a service makes more calls to a healthy dependency per request (N+1 queries)

| | |
|---|---|
| Problem class | Too much work (a code defect) |
| Root cause this blueprint confirms or rejects | One service makes more calls to one dependency for each request it receives than it did before, while that dependency answers as fast as before. |
| Evidence | An LTTng kernel trace only, with the `net_dev_queue` event |
| Not used | Logs, metrics, packet contents, source code |

**When to use this.** A service got slower or busier after a release. Its database looks healthy: fast answers, no errors, no loss. CPU, disk and memory checks find nothing.

**Status.** **This is the weakest blueprint in the set.** Calibrated on the 6 labelled `code_n_plus_one` runs (Sock Shop catalogue: one extra query per row of a list). The signal is the same in all 6 runs, but it is small (1.45 to 1.57 times), the bar (1.35) is fitted between it and the nearest healthy pair (1.28), and it only works with a baseline at the same steady load. Tool only; the agent has not been run on it. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, wrongly rejected twice; the agent could not find a baseline outside the fault at steady load.

## Part 1. Background

The packets show, for every connection, when the client sends data and when the server
answers. A call is one such exchange. For each service the tool counts the calls it makes to
each dependency and divides by the requests the service itself received in the same slice.

| catalogue -> its database | healthy | this fault |
|---|---|---|
| calls per request received | 2.0-2.8 | **3.15-3.83** |
| the same, against a slice after the fault | 0.97-1.23 times | **1.45-1.57 times** |
| time per answer | 0.4-0.5 ms | 0.35-0.38 ms (not slower) |

Problems that look similar:

- More calls to a slow or lossy dependency: those are retries. The tool requires that the answers did not get slower.
- A different mix of user actions: calls per request depend on what the users do. A baseline cut while the load was still ramping up gave 1.6 times for a healthy service (a Java service -> its MongoDB) in many runs. The baseline must be at the same steady load.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `call_fanout.py` | Calls per request received, answer time and overlap, per client and server; the verdict | `call_fanout.py <slice> <secs> <baseline_slice>` |
| `victim_info.py` | Who a pid is | `victim_info.py <sched_slice> <secs> <pid>` |

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a time inside the suspect window and a healthy time at the same steady load, for two 20 s slices. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. Pick a time inside the suspect
window (slice_time) and a healthy time (base_time) where the data rate is flat and
at the same level. The healthy time may be after the fault: the results of this
blueprint were measured against a slice after the fault, at steady load. A baseline
cut while the load was still ramping up is not usable: it gave 1.6 times for a
healthy service in many runs. If the only healthy period is a ramp-up, say so (set
baseline_kind to `ramp-up`) and treat the verdict as weak. Both slices are 20 s and
must lie inside the trace.

Write down: `slice_time` (start of the 20 s slice inside the suspect window, HH:MM:SS only (no date)), `base_time` (start of a 20 s healthy slice where the data rate is flat and at the same level, HH:MM:SS only (no date)), `baseline_kind` (`steady` if the healthy slice is at the same steady load, `ramp-up` if the only healthy period is a ramp-up).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `steady_baseline` | a suspect time and a healthy time at the same steady load are chosen |  | go to `fanout` |
| `ramp_up_baseline` | the only healthy period is a ramp-up; two times were chosen anyway and the verdict will be weak |  | go to `fanout` |

### Step 3. Measure the calls each service makes to each dependency per request it receives, against the baseline, and read the verdict. (`fanout`)

```
extract_slice.sh $TRACE <day> <slice_time> 20 $WORK/net.txt net_dev_queue
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/base.txt net_dev_queue
call_fanout.py $WORK/net.txt 20 $WORK/base.txt
```

call_fanout.py prints one row per client and server pair (calls per request
received, answer time, both with the baseline value) and VERDICT lines. A pair is
judged only if the client made 200 calls to the server and received 200 requests
itself, in both slices. The verdict needs calls per request to rise 1.35 times while
the answers are at most 1.1 times slower: more calls to a slow or lossy dependency
are retries, a different fault.
A CALL AMPLIFICATION line is this fault only if the baseline was at steady load.
More than one verdict line in one run points at a bad baseline (the mix of user
actions changed), not at several defects.
The margin is thin: fault runs are at 1.45 to 1.57 times, the highest healthy pair
at 1.28, and the bar of 1.35 is fitted to this data.
On the line, the client is the culprit; the server is healthy.

Write down: `culprit` (the client on the verdict line (comm, pid_ns, address)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `bad_baseline` | the tool reads CALL AMPLIFICATION, but the baseline was cut in a load ramp-up, or there is more than one verdict line in the run |  | **Stop.** The baseline is not usable, so the verdict is weak. With a baseline in the load ramp-up a healthy pair rises 1.58 to 1.65 times in many runs of other families. More than one verdict line points at a bad baseline (the mix of user actions changed), not at several defects. Cut a baseline at the same steady load and run the check again. Root cause **inconclusive**. |
| `amplification` | the tool reads CALL AMPLIFICATION on one line, and the baseline was at the same steady load | `VERDICT: CALL AMPLIFICATION ...` | go to `report` Root cause **confirmed**. |
| `no_amplification` | the tool reads NO CALL AMPLIFICATION and names the largest rise with answers not slower | `VERDICT: NO CALL AMPLIFICATION ...` | **Stop.** No service makes more calls per request to a dependency that answers as fast as before. Not this fault. Root cause **rejected**. |
| `not_judged` | the tool reads NO CALL AMPLIFICATION (no baseline given, or no pair is in both slices) - no client and server pair has 200 calls and 200 received requests in both slices | `no baseline given, or no pair is in both slices ...` | **Stop.** The run could not be judged. No client and server pair has 200 calls and 200 received requests in both slices. Root cause **inconclusive**. |

### Report

fault_type: code_n_plus_one. Root cause service: the client on the verdict line (comm,
pid_ns, address). The server on the line is healthy. Evidence: the verdict line word for
word. Say whether the baseline was at steady load. Fix: in the code of that service,
fetch the rows in one query (or one batched query) and not one query per row. The trace
cannot name the function.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Against a slice after the fault (steady load): 6 of 6, 0 false alarms in the 175 other runs that could be judged.** 123 runs could not be judged: no client and server pair has 200 calls and 200 received requests in both slices (104 Train Ticket runs and 19 Sock Shop runs; 3 of them are failed slice cuts).
- **Against a slice before the fault (in the load ramp-up): not usable.** The 6 fault runs are found, but a healthy pair rises 1.58 to 1.65 times in many runs of other families.
- **The margin is thin.** Fault runs: 1.45 to 1.57. Highest healthy pair that passes the other conditions: 1.28. The bar of 1.35 is fitted to this data.
- **The rule was changed twice after sweeps.** First guess: 3 times, any pair. Final: 1.35 times, answers at most 1.1 times slower, 200 calls and 200 received requests. The final rule was applied to the saved tables of job 2880078, not run again on the slices.
- **One defect in one service.** The size of the rise depends on how often the list endpoint is called and how many rows it returns. Another service would give another number.
- A call is counted as "client data, then server data" on one connection. Commands that get no answer (a statement close) are merged into the next call.
