<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a busy thread keeps stopping for one fixed time

| | |
|---|---|
| Problem class | Code defect (blocking call) |
| Root cause this blueprint confirms or rejects | The one thread that does a service's work makes a blocking call of a fixed length, so everything queued behind it waits. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A single-threaded service (Node) is slower at the median and the tail while its CPU use did not rise.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

An event-loop thread is on the CPU most of the time and sleeps for well under a millisecond. `busy_sleep.py` looks at threads
that are on the CPU at least half the slice and counts their sleeps of 15 ms or more.

| | this fault | the same thread before |
|---|---|---|
| sleeps of 15 ms or more in 10 s | **26-39, all about 30 ms** | 0 |
| time lost in them | 0.78-1.17 s | |
| on the CPU | 83-86% of the slice | |

Problems that look similar:

- A blocked event loop (blueprint 17) or regex backtracking (blueprint 38): the thread is ON the CPU for the whole stall.
- A thread that waits for its next piece of work: a database connection thread was on the CPU 52-56% of two healthy slices and slept 44-51 times for 18 to 182 ms. Sleeps of mixed length are listed without a verdict.
- A CPU limit (blueprint 1): the thread is runnable and waits, it does not sleep.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `busy_sleep.py` | Long sleeps of threads that are mostly on the CPU; the verdict | `busy_sleep.py <baseline_slice> <fault_slice> <secs>` |

`EV='sched_switch'`

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

The last table is the trace data written per 10 s. If you were given a suspect time, take a slice that starts 40 s after it.
The baseline slice is the same length, just before the suspect time, with the same traffic. Both must lie inside the trace.

Write down: `fault_time` (start of the suspect slice, HH:MM:SS), `base_time` (start of the baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Run the tool on the two slices. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 10 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 10 $WORK/f.txt $EV
busy_sleep.py $WORK/b.txt $WORK/f.txt 10
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads A BUSY THREAD KEEPS STOPPING | `VERDICT: A BUSY THREAD KEEPS STOPPING ...` | go to `report` Root cause **confirmed** (`code_blocking_wait`). |
| `no` | the tool reads NO BUSY THREAD STOPS | `VERDICT: NO BUSY THREAD STOPS ...` | **Stop.** No busy thread has long sleeps of one fixed length. Not this fault (a blocking call of varying length is not judged). Root cause **rejected**. |

### Report

fault_type: code_blocking_wait. Copy the VERDICT line. Fix: never block the event loop; use the asynchronous form of the call.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 45 runs.**
- **The bars were set on run 1, and the rule was narrowed after the 50-run test**; see RESULTS.
- **A blocking call whose length varies is not confirmed by this tool.**
- **Not yet run on the earlier runs.**
