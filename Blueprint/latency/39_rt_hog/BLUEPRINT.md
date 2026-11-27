<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one CPU is held by a real-time task

| | |
|---|---|
| Problem class | CPU (scheduling policy) |
| Root cause this blueprint confirms or rejects | A task with a real-time policy spins on one CPU, so normal threads on that CPU get only what the kernel's real-time throttling leaves. |
| Evidence | An LTTng kernel trace only, with `sched_switch` |
| Not used | Logs, metrics, spans, source code |

**When to use this.** One CPU is busy all the time with no service using more CPU; or threads pinned to one CPU slow down.

**Status.** Calibrated on its 5 v3 runs; tested on all 20 group-4 runs. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

A real-time task (SCHED_FIFO or SCHED_RR) always runs before normal tasks on its CPU. LTTng prints its priority as a
negative number (normal tasks are 0-39). `rt_cpu.py` adds up, per CPU, the time the running task had a negative
priority and was not a kernel thread (migration, watchdog and other kernel helpers are real-time too).

| | this fault | normal |
|---|---|---|
| one CPU held by a user real-time task | **88-98% of the slice** | 0% |
| task | `python3`, priority -51 | |
| services | no change in rate, errors or answer time | |

Problems that look similar:

- A busy normal process on one CPU: priority 0-39, the scheduler shares the CPU.
- Kernel real-time threads (migration/N, priority -100): left out by name.
- A CPU quota or a low CPU weight: waits in one container, not one CPU held.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `rt_cpu.py` | Time each CPU ran a user real-time task; the verdict | `rt_cpu.py <baseline_slice> <fault_slice> <secs>` |

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

### Step 3. Measure the time each CPU ran a user real-time task. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 10 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 10 $WORK/f.txt $EV
rt_cpu.py $WORK/b.txt $WORK/f.txt 10
```

One row per CPU and one VERDICT line naming the task.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `held` | the tool reads A REAL-TIME TASK HOLDS A CPU | `VERDICT: A REAL-TIME TASK HOLDS A CPU ...` | go to `report` Root cause **confirmed** (`rt_hog`). |
| `none` | the tool reads NO CPU HELD BY A REAL-TIME TASK | `VERDICT: NO CPU HELD BY A REAL-TIME TASK ...` | **Stop.** No CPU is held by a user real-time task. Not this fault. Root cause **rejected**. |

### Report

fault_type: rt_hog. The task and CPU on the verdict line. Fix: stop it, or give it the normal policy (chrt -o -p 0 <pid>).

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5** (88-98% of the slice, 0% before); reversed quiet.
- **Quiet on the other 15 group-4 runs.**
- **No service was slowed** at this load: the tasks on that CPU moved to others. This is a kernel and host-metric family.
- **Not yet run on the earlier runs.**
