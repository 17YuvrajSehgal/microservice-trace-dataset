<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a client releases its calls from a timer (an in-process queue)

| | |
|---|---|
| Problem class | Code defect (queueing) |
| Root cause this blueprint confirms or rejects | A service puts its calls to other services in an in-process queue that a timer drains at a fixed rate; when more arrive, they wait in the queue. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service got slower while its dependencies answer as fast as before and its CPU did not rise.

**Status.** Calibrated on its 5 v3 runs; tested on all 70 runs of groups 5-8. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

`paced_calls.py` looks at the gaps between the calls a client sends to one server. Calls that follow requests come in
bursts, with gaps of every length. Calls released by a timer leave on its clock: one gap length becomes common.

| | this fault (front-end to catalogue) | the same pair before |
|---|---|---|
| gaps of 8.0 to 11.0 ms | **17-20% of all gaps** | 4-5% |
| the timer | about 10 ms | |

The front-end's p50 rises from about 70 to about 147 ms (collection check). Its memory does not grow: the 150 users
wait for their answers, so the queue cannot grow without limit.

Problems that look similar:

- A queue served by a pool of workers that never sleep: no clock, not seen by this tool.
- Busy traffic: most gaps are short; the peak must be a bump at 4 ms or more.
- A lock held across a call (blueprint 25): calls stop overlapping, no clock.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `paced_calls.py` | Gaps between calls per client and server; the verdict | `paced_calls.py <fault_slice> <secs> <baseline_slice>` |

`EV='net_dev_queue'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a suspect time and a baseline time, 20 s each. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. If you were given a suspect time, take a slice that starts 40 s after it.
The baseline slice is the same length, just before the suspect time, with the same traffic. Both must lie inside the trace.

Write down: `fault_time` (start of the suspect slice, HH:MM:SS), `base_time` (start of the baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Run the tool on the two slices. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/f.txt $EV
paced_calls.py $WORK/f.txt 20 $WORK/b.txt
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads CALLS LEAVE ON A CLOCK | `VERDICT: CALLS LEAVE ON A CLOCK ...` | go to `report` Root cause **confirmed** (`code_unbounded_queue`). |
| `no` | the tool reads NO PACED CALLS | `VERDICT: NO PACED CALLS ...` | **Stop.** No client sends its calls on a clock. Not this fault (a queue without a timer is not seen). Root cause **rejected**. |

### Report

fault_type: code_unbounded_queue. Copy the VERDICT line. Fix: bound the queue and shed load when it is full; size the worker to the arrival rate.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 65 runs.**
- **Changed after the first 70-run test**: the server of a connection is now the side with a port below 32768 (the first version sometimes took the server for the client). Also changed then: the clock is looked for from 4 ms and must be a bump (one reversed run had fired on busy traffic).
- **It sees a queue only when a timer drains it.**
- **Not yet run on the earlier runs.**
