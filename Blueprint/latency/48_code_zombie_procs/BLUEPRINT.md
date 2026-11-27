<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a program never collects its child processes

| | |
|---|---|
| Problem class | Resource leak (process table) |
| Root cause this blueprint confirms or rejects | A program starts child processes and never waits for them, so each dead child stays in the process table as a zombie. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** The number of processes on a host or in a container climbs with no load change; or you look for the cause before a later 'cannot fork'.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

The kernel frees a dead process only when its parent has asked how it ended. `unreaped.py` follows each child created in the
slice: created (`sched_process_fork`), ended (`sched_process_exit`), freed (`sched_process_free`).

| | this fault | normal |
|---|---|---|
| children started in 60 s | 227-239 | |
| of those that ended, never freed | **220-232 of 220-232 (100%)** | 0 |

No metric shows this fault (the family runs with `no_metric_signature`): zombies use no CPU and almost no memory.

Problems that look similar:

- A process storm (blueprint 13): far more children, and they are collected.
- A shell script: the collection's own script started 1,034 children in a slice and collected every one.
- A thread leak (blueprint 35): threads of one process that are alive.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `unreaped.py` | Children started, ended and never freed, per parent; the verdict | `unreaped.py <baseline_slice> <fault_slice>` |

`EV='sched_process_fork|sched_process_exit|sched_process_free'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a suspect time and a baseline time, 60 s each. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. If you were given a suspect time, take a 60 s slice that starts at it.
The baseline slice is the same length, just before the suspect time, with the same traffic. Both must lie inside the trace.

Write down: `fault_time` (start of the suspect slice, HH:MM:SS), `base_time` (start of the baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Run the tool on the two slices. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 60 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 60 $WORK/f.txt $EV
unreaped.py $WORK/b.txt $WORK/f.txt
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads CHILD PROCESSES ARE NEVER COLLECTED | `VERDICT: CHILD PROCESSES ARE NEVER COLLECTED ...` | go to `report` Root cause **confirmed** (`code_zombie_procs`). |
| `no` | the tool reads NO UNREAPED CHILDREN | `VERDICT: NO UNREAPED CHILDREN ...` | **Stop.** Every child that ended was collected. Not this fault. Root cause **rejected**. |

### Report

fault_type: code_zombie_procs. Copy the VERDICT line. Fix: wait for every child you start, or use a helper that reaps them.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 45 runs** (0 unreaped children anywhere).
- **Not yet run on the earlier runs.**
