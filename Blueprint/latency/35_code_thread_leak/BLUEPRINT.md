<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one process starts threads that never end (a thread leak)

| | |
|---|---|
| Problem class | Resource leak (a code defect) |
| Root cause this blueprint confirms or rejects | One process keeps starting threads and none of them ends, so its thread count only grows while it works normally. |
| Evidence | An LTTng kernel trace only, with `sched_process_fork` and `sched_process_exit` |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service's thread count or memory climbs slowly with no other symptom; or it later fails to start a thread.

**Status.** Calibrated on its 5 v3 runs; tested on all 20 group-2 runs. Not yet checked on the earlier 349 runs. Not run by an agent yet.

## Part 1. Background

Programs start threads all the time: a Java service here starts about 75-85 per second when nothing is
wrong, and ends as many. `thread_growth.py` counts per process the threads started and the threads that
ended. A leak starts threads and ends none.

| | `code_thread_leak` (catalogue) | a busy Java service (orders) |
|---|---|---|
| started in 10 s | **40-42** | 749-854 |
| ended | **0** | all but 0-1 |
| net, baseline | 0 | 0-1 |

Problems that look similar:

- A busy service that starts and ends threads: high start rate, net about 0.
- A pile-up behind a frozen dependency: threads started per waiting request that end later (blueprint 15).
- Short-lived helper processes (`docker exec`, `runc`): new processes, not threads; up to 11 per slice here.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `thread_growth.py` | Threads started and ended per process; the verdict | `thread_growth.py <baseline_slice> <fault_slice> <secs>` |

`EV='sched_process_fork|sched_process_exit'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a suspect time and a baseline time, 10 s each. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. If you were given a suspect time, take a slice that
starts 40 s after it, and a baseline slice that starts 30 s before it. If not, take the stretch where the
rate changes and a stretch before it with the same traffic. Both slices are 10 s.

Write down: `fault_time` (start of the 10 s suspect slice, HH:MM:SS), `base_time` (start of the 10 s baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Count threads started and ended per process. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 10 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 10 $WORK/f.txt $EV
thread_growth.py $WORK/b.txt $WORK/f.txt 10
```

One row per process and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `leak` | the tool reads THREADS ARE STARTED AND NOT ENDED | `VERDICT: THREADS ARE STARTED AND NOT ENDED ...` | go to `report` Root cause **confirmed** (`code_thread_leak`). |
| `none` | the tool reads NO THREAD GROWTH | `VERDICT: NO THREAD GROWTH ...` | **Stop.** No process keeps its threads. Not this fault. Root cause **rejected**. |

### Report

fault_type: code_thread_leak. The process on the verdict line. Fix: give every started thread a way to end; do
not lock goroutines to threads. The trace cannot name the code that starts them.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5** (40-42 threads kept in 10 s, 0 before); reversed quiet.
- **Quiet on the other 15 group-2 runs**, where orders starts and ends 749-854 threads per slice.
- **The margin is small**: 40-42 kept against a bar of 30. A slower leak needs a longer slice.
- **Not yet run on the earlier 349 runs.**
