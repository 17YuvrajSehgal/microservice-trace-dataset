<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one process has hundreds of threads that wake up all the time

| | |
|---|---|
| Problem class | CPU (scheduler load) |
| Root cause this blueprint confirms or rejects | One process runs a large pool of threads that each wake up, do almost nothing and sleep again, so the scheduler is busy with them. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service is slower and uses more CPU with no more requests; or the host's context-switch rate jumped.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

Each wake-up and each sleep of a thread is a context switch. `switch_rate.py` counts, per process, how often its threads left the
CPU, how many threads did so, and how long each stayed on the CPU.

| | this fault | the same process before |
|---|---|---|
| context switches per second | **85,970-92,483** | 4,550-4,707 |
| threads that ran | 415-420 | |
| time on the CPU each time (median) | 13-14 microseconds | |
| CPU used | 1.35-1.47 cores | |

Problems that look similar:

- A thread leak (blueprint 35): many threads, all asleep, almost no switches.
- A spin loop (blueprint 36): one thread that never sleeps, long runs.
- A busy proxy: toxiproxy made up to 16,407 switches per second over 17 threads; the thread bar keeps it out.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `switch_rate.py` | Context switches, threads and run length per process; the verdict | `switch_rate.py <baseline_slice> <fault_slice> <secs>` |

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
switch_rate.py $WORK/b.txt $WORK/f.txt 10
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads MANY THREADS WAKE UP ALL THE TIME | `VERDICT: MANY THREADS WAKE UP ALL THE TIME ...` | go to `report` Root cause **confirmed** (`code_ctxswitch_storm`). |
| `no` | the tool reads NO THREAD STORM | `VERDICT: NO THREAD STORM ...` | **Stop.** No process has a storm of short thread wake-ups. Not this fault. Root cause **rejected**. |

### Report

fault_type: code_ctxswitch_storm. Copy the VERDICT line. Fix: size the thread pool to the number of cores; wait on an event, do not poll with a short sleep.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 45 runs.**
- **The service was slowed more in the traced runs than in the calibration without tracing** (catalogue p95 about 87 ms against 32 ms). A likely reason is the tracing cost per context switch; this was not checked.
- **Not yet run on the earlier runs.**
