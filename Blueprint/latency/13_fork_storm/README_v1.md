# Blueprint: a workload creating processes at a runaway rate (fork_storm)

| | |
|---|---|
| Problem class | Resource abuse / scheduler pressure (host-wide) |
| Root cause this blueprint confirms or rejects | One workload creates **new processes** much faster than before: a crash-looping supervisor, a shell loop spawning a process per item, a runaway job. Each new process costs a `fork` (page tables copied), an `exec`, an `exit`, and scheduler work; the rest of the host pays in CPU and run-queue delay, often with no single resource clearly saturated |
| Evidence | An LTTng kernel trace only: `metadata`, the channel files, `index/` |
| Not used | Logs, metrics (cAdvisor's process count would show it too), request traces |

**When to use this.** The event rate of the whole host rose with no obvious culprit in CPU tables;
or `sched_process_fork` / `sched_process_exec` dominate a slice; or many short-lived processes
appear and vanish.

> **Honest status.** Calibrated on the 5 labelled Sock Shop v2 `fork_storm` runs (a co-located
> container running a bounded fork loop for 120 s) and checked against 15 runs of other faults and
> 3 normal runs. See Part 4 for the numbers.

---

## Part 1. Background

`sched_process_fork` fires for every new task. The kernel does not tell processes and threads
apart by name, but the event does: **`child_pid == child_tid` is a new process**, `child_pid !=
child_tid` is a new **thread** inside an existing process. The difference matters:

| what | measured in our runs | is it a fault? |
|---|---|---|
| a JVM thread pool | 70-90 **threads** per second, in every run, every slice | no - normal |
| the tracer's own scripts (`collect_trace.s`) and `docker` / `runc` on the host | 5-45 processes per second, steady | no - our own machinery, never the culprit |
| **fork_storm** | **~100 processes per second** from one new container, none at baseline | yes |

| Lookalike | What the trace shows | How it differs |
|---|---|---|
| **fork storm (this)** | one namespace creates processes at >= 20/s and >= 10x its baseline | — |
| noisy neighbour (`2`) | one process burns CPU; few or no new processes | CPU time, not process count |
| fd_exhaustion restart loop (`12`) | the same comm `exec`s every few seconds after EMFILE | a handful of restarts, not 100/s; EMFILE first |
| a thread pool growing | many `sched_process_fork` with `child_pid != child_tid` | threads, not processes - the tool counts them apart |

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `proc_spawn.py` | Process vs thread creation per (namespace, parent comm), execs, exits, against a baseline; the verdict | `proc_spawn.py <slice> <secs> --baseline <base> <secs>` |
| `sched_budget.py` | Who waited for CPU meanwhile (the victims) | `sched_budget.py <slice> <secs>` |

```bash
PEV='sched_process_fork|sched_process_exec|sched_process_exit'
```

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
Write down `DAY`, the span, and where the event rate steps up (`WINDOW_START`). A fork storm
raises the whole event rate; it is usually visible here.

### Step 2. A fault slice and a quiet baseline
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/pf.txt "$PEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/pb.txt "$PEV"
```
`BASE_START` = a quiet stretch before the change. **The baseline is required**: the host always
creates some processes (the tracer, docker), and only the jump says something.

### Step 3. The decisive check
```bash
python3 $TOOLS/proc_spawn.py $WORK/pf.txt 10 --baseline $WORK/pb.txt 10
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: PROCESS STORM: <comm> (ns N) created P processes in S s (R/s; baseline B/s); they run <prog> (E execs); X exits in that namespace` | **This fault.** That namespace is the culprit. Many exits = short-lived children (a loop), not a growing population |
| `NO PROCESS STORM: top process creator ...` | Not this fault. Stop; report the line word for word |
| a large `thread/s` column with `proc/s` near 0 | a thread pool, not a storm (read the table, do not call it) |

### Step 4. The victims (one call)
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/sched.txt
python3 $TOOLS/sched_budget.py $WORK/sched.txt 10
```
Services whose runnable `wait` rose are the ones paying for the storm. Name them.

### Step 5. Submit
- `fault_type`: `fork_storm`.
- `root_cause_service`: the container of the storming namespace (its name, or `comm` + pid_ns).
- `culprit_kind`: `container`; `culprit_thread`: the parent comm; `victim_thread`: `none` or the slowed services.
- `incident_window`: from `WINDOW_START` while the rate stays up.
- `evidence`: the verdict line, the baseline rate, and the victims from Step 4.
- Fix: find what spawns (the `exec` column names the program); cap it (a PID limit on the container, a backoff in the supervisor).

---

## Part 4. Measured, and limits

- On the 5 labelled runs: see `RESULTS.md` next to this file for the per-run lines.
- The bar (>= 20 processes/s and >= 10x baseline) is set between the host's own steady
  process creation (up to ~45/s from docker and the tracer, steady, so the ratio stays near 1)
  and the storm (~100/s from nothing).
- A slow leak (a few extra processes per second) stays under the bar. Lower `RATE_MIN` only with
  a baseline from the same host.
