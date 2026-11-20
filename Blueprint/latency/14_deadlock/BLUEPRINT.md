<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: threads that wait on each other forever (deadlock)

| | |
|---|---|
| Problem class | Concurrency bug (a service stops doing some of its work without dying) |
| Root cause this blueprint confirms or rejects | Two or more threads each hold a lock the other needs (AB-BA order). Each one calls `futex(FUTEX_WAIT)` with no timeout and never returns. The process stays alive and keeps its memory and connections, but the work those threads should do never happens. |
| Evidence | An LTTng kernel trace only, with `syscall_entry_futex` / `syscall_exit_futex` enabled |
| Not used | Logs, thread dumps (they would confirm it at once; use them if you have them) |

**When to use this.** A service still exists but part of it stops answering; requests time out with no CPU, disk or network cause; or the lock screen (blueprint 11) reports nothing because no lock wait ever ends.

**Status.** Calibrated on the 5 labelled Sock Shop v2 `deadlock` runs (a co-located container that starts a new AB-BA thread pair every 5 s) and checked against 15 runs of other faults and 3 normal runs. The first version also fired on every Java service: see Background. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, confirmed.

## Part 1. Background

`futex_wait.py` (blueprint 11) measures lock waits that **end**: who waited, who
released. A deadlock never ends, so that tool sees nothing. This blueprint looks for the
opposite: a futex wait with **no timeout** that is still open when the slice ends.

That alone is not enough. **Every JVM and Go service has threads parked like this all
the time** (an idle executor waiting for work, the Go runtime's spare threads). Measured:
in every one of our runs, 9-10 Java threads per service sit in an untimed futex wait for
the whole minute. They are idle, not stuck. The difference that separates a deadlock in
our data:

| | deadlocked threads | parked pool threads |
|---|---|---|
| created inside the slice | **yes, all of them** | no (they existed before) |
| time from creation to the final wait | **~50 ms** | |
| new ones keep appearing | **yes, steady (8 / 8 / 6 per third of a minute)** | no |
| distinct lock addresses | one per thread, pairs | |

So the verdict needs threads that were **born inside the slice and hung within 1 s**, on
at least **two** lock addresses (a deadlock needs two locks), born in **two or more
bursts** (births more than 1 s apart). One burst is a program starting up: a Go program
that starts inside the slice creates about 10 runtime threads at once and parks them all
(seen on a normal run, the `docker` CLI). The price: a deadlock that happens only once,
in one burst, gets a NOTE and needs a second slice to confirm.

**Limit, stated plainly:** a deadlock among threads that were already running before the
slice began looks like idle parked threads. To catch it, cut the slice so it starts
**before** the service stopped answering.

Problems that look similar:

- Lock contention (blueprint 11): many short futex waits that END; `futex_wait.py` sees them.
- Priority inversion (blueprint 11): long waits that END when the holder finally runs.
- A paused / frozen service (blueprint 15): the whole namespace emits nothing. Silence, not threads stuck in futex.
- Idle thread pools: untimed waits by threads that existed before. Not new; the tool lists them as NOTE only.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `futex_hang.py` | Untimed futex waits still open at the slice end, per process, split into new vs parked threads; the verdict | `futex_hang.py <slice> <secs> [--min-s 5]` |
| `futex_wait.py` | Waits that end (to rule out contention / inversion) | `futex_wait.py <slice> <secs>` |

`FEV='syscall_entry_futex|syscall_exit_futex|sched_process_fork|sched_process_exit'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find where the service's activity drops and choose the start of one 60 s slice. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. Note where the service's activity
drops: that is window_start. The slice is 60 s and starts at the change. A deadlock
among threads that were already running before the slice began looks like idle
parked threads, so the slice must start before the service stopped answering.

Write down: `window_start` (where the service's activity drops; start of the 60 s slice, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `time_chosen` | a slice time is chosen |  | go to `hang` |

### Step 3. Find threads that entered a futex wait with no timeout and never returned, and read the verdict. (`hang`)

```
extract_slice.sh $TRACE <day> <window_start> 60 $WORK/f.txt $FEV
futex_hang.py $WORK/f.txt 60
```

The slice is long (60 s) because "never returns" needs time: a wait is only counted
when it is still open 5 s or more before the slice ends. futex_hang.py prints one row
per process and one verdict or NOTE line. Lines that start with `NOTE: parked threads`
(threads that existed before the slice; idle pool threads are normal) are ignored for
the verdict. On a DEADLOCK line the per-third counts show it is ongoing. The fault
starts at the `first hung at` time on the verdict line, NOT at the start of your
slice. If the first hung thread is in the first 10 s of the slice, the fault may have
started earlier: cut a slice 60 s before and run the check again to find the real
start. On ONE BURST, only if that process is your suspect: cut the next 60 s and run
the check again; a real ongoing deadlock keeps adding hung threads.

Write down: `deadlock_process` (the process on the verdict line (comm, pid, ns)), `first_hung_at` (the `first hung at` time on the verdict line).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `deadlock` | the tool reads DEADLOCK (new threads blocked forever in futex with no timeout, on two or more distinct locks) | `VERDICT: DEADLOCK ...` | go to `rule_out` Root cause **confirmed**. |
| `one_burst` | the tool reads ONE BURST OF NEW PARKED THREADS (all the new hung threads were born within 1 s of each other) | `NOTE: ONE BURST OF NEW PARKED THREADS ...` | **Stop.** Not this fault. A program that started inside the slice and parked its runtime threads (measured, the `docker` CLI, 10 threads, on a normal run). Root cause **rejected**. |
| `one_lock` | the tool reads HUNG ON ONE LOCK (threads stuck on one address) | `NOTE: HUNG ON ONE LOCK ...` | **Stop.** Threads stuck on one address, a lost wake-up or a holder that died. A finding, not a deadlock. Root cause **rejected**. |
| `none` | the tool reads NO HUNG LOCK WAITS (also NO HUNG LOCK WAITS AMONG NEW THREADS) | `NO HUNG LOCK WAITS ...` | **Stop.** Not this fault. Root cause **rejected**. |

### Step 4. Rule out the lookalikes whose lock waits end (one call). (`rule_out`)

```
futex_wait.py $WORK/f.txt 60
```

futex_wait.py measures lock waits that end. A LOCK CONTENTION or PRIORITY INVERSION
verdict means the waits end: that is blueprint 11, not a deadlock. Any other verdict
line (NO LOCK PROBLEM, NO LONG FUTEX WAITS, NO FUTEX WAITS IN SLICE) leaves the
deadlock verdict as it is. The README does not say what to do when the verdict is
about another process than the one on the DEADLOCK line: that is a second finding,
not a reason to drop the deadlock. Use `no_ending_waits` then and say so.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `no_ending_waits` | the tool does not read LOCK CONTENTION or PRIORITY INVERSION |  | go to `report` |
| `contention` | the tool reads LOCK CONTENTION for the process on the DEADLOCK verdict line | `VERDICT: LOCK CONTENTION ...` | **Stop.** The waits end. Not a deadlock; the case goes to blueprint 11. Root cause **unconfirmed**. |
| `inversion` | the tool reads PRIORITY INVERSION for the process on the DEADLOCK verdict line | `VERDICT: PRIORITY INVERSION ...` | **Stop.** The waits end. Not a deadlock; the case goes to blueprint 11. Root cause **unconfirmed**. |

### Report

fault_type: deadlock. Root cause: the container / process from the verdict line; the
culprit thread is `comm (pid P)`. The victims are the callers that time out, if known.
The incident window starts at the `first hung at` time on the verdict line, NOT at the
start of the slice, and ends at the end of the slice (still ongoing). Evidence: the
verdict line word for word, with the per-third counts and the birth-to-hang time. Fix: a
thread dump of that process names the two locks; take them in one fixed order.

## Part 4. Measured, and limits

- Per-run lines on the labelled runs and the controls: `RESULTS.md` next to this file.
- Python's `threading.Lock` and glibc mutexes both block in `FUTEX_WAIT` with `utime = 0` when there is no timeout; a lock taken with a timeout returns and is never counted.
- A deadlock among long-lived threads (Part 1, last paragraph) needs a slice that starts before the hang.
