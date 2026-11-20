<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a workload creating processes at a runaway rate (fork_storm)

| | |
|---|---|
| Problem class | Resource abuse / scheduler pressure (host-wide) |
| Root cause this blueprint confirms or rejects | One workload creates new processes much faster than before: a crash-looping supervisor, a shell loop spawning a process per item, a runaway job. Each new process costs a `fork` (page tables copied), an `exec`, an `exit`, and scheduler work; the rest of the host pays in CPU and run-queue delay, often with no single resource clearly saturated. |
| Evidence | An LTTng kernel trace only: `metadata`, the channel files, `index/` |
| Not used | Logs, metrics (cAdvisor's process count would show it too), request traces |

**When to use this.** The event rate of the whole host rose with no obvious culprit in CPU tables; or `sched_process_fork` / `sched_process_exec` dominate a slice; or many short-lived processes appear and vanish.

**Status.** Calibrated on the 5 labelled Sock Shop v2 `fork_storm` runs (a co-located container running a bounded fork loop for 120 s) and checked against 15 runs of other faults and 3 normal runs. See Measured for the numbers. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, confirmed on the second try; the first try cut its slice 1 s after the fault ended and rejected.

## Part 1. Background

`sched_process_fork` fires for every new task. The kernel does not tell processes and
threads apart by name, but the event does: **`child_pid == child_tid` is a new process**,
`child_pid != child_tid` is a new **thread** inside an existing process. The difference
matters:

| what | measured in our runs | is it a fault? |
|---|---|---|
| a JVM thread pool | 70-90 **threads** per second, in every run, every slice | no, normal |
| the tracer's own scripts (`collect_trace.s`) and `docker` / `runc` on the host | 5-45 processes per second, steady | no, our own machinery, never the culprit |
| **fork_storm** | **~100 processes per second** from one new container, none at baseline | yes |

This fault: one namespace creates processes at >= 20/s and >= 10x its baseline.

Problems that look similar:

- Noisy neighbour (blueprint 2): one process burns CPU; few or no new processes. CPU time, not process count.
- fd_exhaustion restart loop (blueprint 12): the same comm `exec`s every few seconds after EMFILE. A handful of restarts, not 100/s; EMFILE first.
- A thread pool growing: many `sched_process_fork` with `child_pid != child_tid`. Threads, not processes; the tool counts them apart.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `proc_spawn.py` | Process vs thread creation per (namespace, parent comm), execs, exits, against a baseline; the verdict | `proc_spawn.py <slice> <secs> --baseline <base> <secs>` |
| `sched_budget.py` | Who waited for CPU meanwhile (the victims) | `sched_budget.py <slice> <secs>` |

`PEV='sched_process_fork|sched_process_exec|sched_process_exit'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find where the event rate steps up, and choose a time inside it and a quiet baseline time before it. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. window_start is where the event
rate steps up. A fork storm raises the whole event rate; it is usually visible here.
base_start is a quiet stretch before the change. The baseline is required: the host
always creates some processes (the tracer, docker), and only the jump says something.

Write down: `window_start` (where the event rate steps up; start of the 10 s fault slice, HH:MM:SS only (no date)), `base_start` (start of a 10 s slice in a quiet stretch before the change, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | the two times are chosen |  | go to `spawn` |

### Step 3. Count new processes per namespace and parent in the fault slice against the baseline, and read the verdict. (`spawn`)

```
extract_slice.sh $TRACE <day> <window_start> 10 $WORK/pf.txt $PEV
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/pb.txt $PEV
proc_spawn.py $WORK/pf.txt 10 --baseline $WORK/pb.txt 10
```

proc_spawn.py prints one row per (namespace, parent comm) and one verdict line. Run
it with --baseline: without it the tool prints a NOTE and no verdict, because a rate
alone is not proof. Many exits on the verdict line mean short-lived children (a
loop), not a growing population. A large `thread/s` column with `proc/s` near 0 is a
thread pool, not a storm (read the table, do not call it).

Write down: `storm_process` (the parent comm and namespace on the verdict line, and the program they run).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `storm` | the tool reads PROCESS STORM (a namespace creates processes at >= 20/s and >= 10x its baseline) | `VERDICT: PROCESS STORM ...` | go to `victims` Root cause **confirmed**. |
| `none` | the tool reads NO PROCESS STORM | `NO PROCESS STORM ...` | **Stop.** Not this fault. Report the line word for word. Root cause **rejected**. |

### Step 4. Name the services that waited for CPU during the storm (one call). (`victims`)

```
extract_slice.sh $TRACE <day> <window_start> 10 $WORK/sched.txt
sched_budget.py $WORK/sched.txt 10
```

Services whose runnable `wait` rose are the ones paying for the storm. Name them.

Write down: `victims` (the services whose runnable wait rose).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `victims_read` | the scheduling table was read |  | go to `report` |

### Report

fault_type: fork_storm. Root cause: the container of the storming namespace (its name,
or comm + pid_ns); the culprit thread is the parent comm. The incident window is from
window_start while the rate stays up. Evidence: the verdict line, the baseline rate, and
the victims. Fix: find what spawns (the `exec` column names the program); cap it (a PID
limit on the container, a backoff in the supervisor).

## Part 4. Measured, and limits

- On the 5 labelled runs: see `RESULTS.md` next to this file for the per-run lines.
- The bar (>= 20 processes/s and >= 10x baseline) is set between the host's own steady process creation (up to ~45/s from docker and the tracer, steady, so the ratio stays near 1) and the storm (~100/s from nothing).
- A slow leak (a few extra processes per second) stays under the bar. Lower `RATE_MIN` only with a baseline from the same host.
