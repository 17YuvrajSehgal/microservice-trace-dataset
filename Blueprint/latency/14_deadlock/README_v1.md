# Blueprint: threads that wait on each other forever (deadlock)

| | |
|---|---|
| Problem class | Concurrency bug (a service stops doing some of its work without dying) |
| Root cause this blueprint confirms or rejects | Two or more threads each hold a lock the other needs (AB-BA order). Each one calls `futex(FUTEX_WAIT)` with **no timeout** and never returns. The process stays alive and keeps its memory and connections, but the work those threads should do never happens |
| Evidence | An LTTng kernel trace only, with `syscall_entry_futex` / `syscall_exit_futex` enabled |
| Not used | Logs, thread dumps (they would confirm it at once - use them if you have them) |

**When to use this.** A service still exists but part of it stops answering; requests time out
with no CPU, disk or network cause; or the lock screen (blueprint 11) reports nothing because no
lock wait ever *ends*.

> **Honest status.** Calibrated on the 5 labelled Sock Shop v2 `deadlock` runs (a co-located
> container that starts a new AB-BA thread pair every 5 s) and checked against 15 runs of other
> faults and 3 normal runs. The first version also fired on every Java service: see Part 1.

---

## Part 1. Background

`futex_wait.py` (blueprint 11) measures lock waits that **end**: who waited, who released. A
deadlock never ends, so that tool sees nothing. This blueprint looks for the opposite: a futex
wait with **no timeout** that is still open when the slice ends.

That alone is not enough. **Every JVM and Go service has threads parked like this all the time**
(an idle executor waiting for work, the Go runtime's spare threads). Measured: in every one of
our runs, 9-10 Java threads per service sit in an untimed futex wait for the whole minute. They
are idle, not stuck. The difference that separates a deadlock in our data:

| | deadlocked threads | parked pool threads |
|---|---|---|
| created inside the slice | **yes, all of them** | no (they existed before) |
| time from creation to the final wait | **~50 ms** | — |
| new ones keep appearing | **yes, steady (8 / 8 / 6 per third of a minute)** | no |
| distinct lock addresses | one per thread, pairs | — |

So the verdict needs threads that were **born inside the slice and hung within 1 s**, on at
least **two** lock addresses (a deadlock needs two locks).

| Lookalike | What the trace shows | How it differs |
|---|---|---|
| **deadlock (this)** | new threads enter an untimed futex wait and never return; their number grows | — |
| lock contention (`11`) | many short futex waits that END | waits end; `futex_wait.py` sees them |
| priority inversion (`11`) | long waits that END when the holder finally runs | waits end |
| a paused / frozen service (`15`) | the whole namespace emits nothing | silence, not threads stuck in futex |
| idle thread pools | untimed waits by threads that existed before | not new; the tool lists them as NOTE only |

**Limit, stated plainly:** a deadlock among threads that were already running before the slice
began looks like idle parked threads. To catch it, cut the slice so it starts **before** the
service stopped answering.

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `futex_hang.py` | Untimed futex waits still open at the slice end, per process, split into new vs parked threads; the verdict | `futex_hang.py <slice> <secs> [--min-s 5]` |
| `futex_wait.py` | Waits that end (to rule out contention / inversion) | `futex_wait.py <slice> <secs>` |

```bash
FEV='syscall_entry_futex|syscall_exit_futex|sched_process_fork|sched_process_exit'
```

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
Note where the service's activity drops (`WINDOW_START`).

### Step 2. One long slice (60 s), starting at the change
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 60 $WORK/f.txt "$FEV"
```
Long, because "never returns" needs time: a wait is only counted when it is still open 5 s or
more before the slice ends.

### Step 3. The decisive check
```bash
python3 $TOOLS/futex_hang.py $WORK/f.txt 60
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: DEADLOCK: <comm> (pid P, ns N): K threads blocked forever in futex (no timeout) on L distinct locks, longest X s; new hung threads per third a/b/c; K of them were created inside the slice and hung M ms after birth` | **This fault.** That process deadlocks; the per-third counts show it is ongoing |
| `NOTE: HUNG ON ONE LOCK: ...` | threads stuck on one address: a lost wake-up or a holder that died. A finding, not a deadlock |
| `NOTE: parked threads (existed before the slice; idle pool threads are normal): ...` | ignore for the verdict |
| `NO HUNG LOCK WAITS AMONG NEW THREADS (...)` | Not this fault |

### Step 4. Rule out the lookalikes (one call)
```bash
python3 $TOOLS/futex_wait.py $WORK/f.txt 60
```
A `LOCK CONTENTION` or `PRIORITY INVERSION` verdict means the waits end: hand to blueprint 11.

### Step 5. Submit
- `fault_type`: `deadlock`.
- `root_cause_service`: the container / process from the verdict line.
- `culprit_thread`: `comm (pid P)`; `victim_thread`: the callers that time out, if known, else `none`.
- `incident_window`: from the first hung thread's wait to the end of the slice (still ongoing).
- `evidence`: the verdict line word for word, with the per-third counts and the birth-to-hang time.
- Fix: a thread dump of that process names the two locks; take them in one fixed order.

---

## Part 4. Measured, and limits

- Per-run lines on the labelled runs and the controls: `RESULTS.md` next to this file.
- Python's `threading.Lock` and glibc mutexes both block in `FUTEX_WAIT` with `utime = 0` when
  there is no timeout; a lock taken with a timeout returns and is never counted.
- A deadlock among long-lived threads (Part 1, last paragraph) needs a slice that starts before
  the hang.
