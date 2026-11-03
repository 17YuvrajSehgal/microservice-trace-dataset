# Blueprint: finding a lock held by a thread that cannot run (priority inversion), or many threads fighting one lock (lock contention), from a kernel trace

| | |
|---|---|
| Problem class | Latency (locks) |
| Root cause this blueprint confirms or rejects | **Priority inversion:** a high-priority **thread** waits on a user-space lock held by a **low-priority thread** that cannot run, because **middle-priority threads** take its CPU. The high-priority work is blocked by work it never touches. **Lock contention** (its sibling): many threads queue on **one lock**, and every wait lasts as long as the holder's critical section |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder. The trace must hold the **`futex` system call** events (`syscall_entry_futex` / `syscall_exit_futex`, or `compat_syscall_*`) as well as the scheduling events |
| Also allowed | The list of event types the trace holds (read from `metadata`); a baseline capture of the same box without the problem, if there is one |
| Not used | Logs, metrics, application counters (late replies, timeouts), request traces, the program's source |

**How to use this blueprint.** Read Part 1 once, to learn what the two faults are and what they look like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

**When to reach for this instead of `8_cpu_starvation` or `9_syscall_stall`.** Blueprint 8 is for a thread that is **ready and waiting for a CPU**. Blueprint 9 is for a thread **held by a kernel lock inside another thread's system call**. This blueprint is for a thread that is **blocked in `futex`**: it waits for a user-space lock or condition that another thread must release. `wait_chain.py` tells the three apart in one call: if the late thread's long blocks are inside `futex` and are released by one other thread, it is this blueprint. Then the releaser's own scheduling state says which of the two faults it is. Use it on any host — bare-metal or container — when the question is "which lock, who holds it, and why does the holder not let go?".

> **Honest status.** Both branches are calibrated on our own labelled runs on a 12-CPU Sock Shop host, 60 s inside the injection. **Contention:** the `lock_contention` run — the injected lock found (16 waiters, each 92% of its time waiting), the two usual lookalikes set aside. **Inversion:** the `priority_inversion` run — the tool says PRIORITY INVERSION on the Python interpreter's own lock (a middle thread preempted while holding it, the nice −5 waiter stuck behind it), and lists the waiter's 730 ms and 445 ms waits on the application lock held by the sleeping nice 19 thread; `runq_wait.py` on that holder confirms it was kept off its CPU by the six middle threads. A textbook "holder preempted while holding the application lock" does not appear there, because that holder sleeps while it holds. On five partner line-card traces the tool correctly found **no** lock problem: three `NO LOCK PROBLEM` (small inversion-class waits under the bar, a held lock under the bar, a starvation effect) and two `NO LONG FUTEX WAITS`. The bars in Step 3 are a first pass from those seven traces.

---

## Part 1. Background

### 1.1 What the faults are

**A futex is the kernel half of a user-space lock.** A mutex, a semaphore or a condition variable in a program is a word in memory. When a thread must wait for it, the C library calls `futex(2)` and the kernel puts the thread to sleep on that address; when another thread releases the lock, it calls `futex` again to wake a sleeper. The trace records both calls. The `op` field says which: `WAIT` = 0, `WAKE` = 1, `WAIT_BITSET` = 9, `LOCK_PI` = 6, plus two flags, `PRIVATE` = `0x80` and `CLOCK_REALTIME` = `0x100`. So `op = 137` is `WAIT_BITSET|PRIVATE|CLOCK_REALTIME` (what `pthread_cond_timedwait` sends) and `op = 129` is `WAKE|PRIVATE`. The tools decode this for you; you read the result.

**Priority inversion.** Three threads: a high-priority one (H), a low-priority one (L) and one or more middle ones (M). L takes a lock. H wants the same lock and blocks. Now L must run to release it — but the scheduler keeps giving L's CPU to the M threads, because they outrank L. H waits for as long as the M threads keep L off the CPU, which can be hundreds of milliseconds. Nothing is saturated. L is simply **runnable-but-not-running** while it holds the lock. The fixes: **priority inheritance** on the lock (`PTHREAD_PRIO_INHERIT`, or `FUTEX_LOCK_PI` in the kernel: L is boosted to H's priority while it holds the lock), or give L a priority that cannot be preempted by M, or **do not hold the lock across a scheduling boundary** (make the critical section short and never sleep or yield inside it).

**Lock contention.** Many threads want one lock. Each gets it in turn, and each wait is about as long as the holder's critical section. Every waiter spends most of its life waiting; the holders are busy (running under the lock) or, on a box with fewer CPUs than threads, preempted while holding. The fixes: **shorten** the critical section, **split** the lock (one per shard, per queue, per connection), or **batch** the work done under it.

**What is not a lock problem.** The kernel cannot tell a lock from a condition variable from a worker waiting for its next job: all three are a thread asleep in `futex` until another thread wakes it. The difference is in the **releaser**:

- An **event wait** (condition variable, a worker waiting for work): the releaser **slept** until it had something to signal. The waiter was idle, not blocked. Not a problem.
- A **timed sleep**: the wait ended by timeout (`ret = -110`, `ETIMEDOUT`). The thread was sleeping on a timer that happens to be a futex. A 100 ms, 1 s or 5 s loop is a timer, not a lock.
- A **poll-run**: some programs wait with a short timeout in a loop — a Python interpreter re-waits in 5 ms pieces until its lock is free. Each piece is a timed wait; the whole run is one wait for the lock. The tool coalesces the pieces into one **logical wait** and judges it by how it ended.

**Priorities in the trace.** LTTng prints `prio` as the kernel priority minus 100: `20` = nice 0 (kernel 120), `10` = nice −10, `39` = nice 19, a negative number = real-time. The tools print `120 (nice 0)`, `139 (nice 19)`, `RT 63`. "Worse priority" means a larger number.

### 1.2 What it looks like in a kernel trace

For the thread that waits (the **waiter**):

- `syscall_entry_futex` with a `WAIT`-type `op` on address `uaddr`, then `syscall_exit_futex` with `ret = 0` much later. Between them the thread is asleep (`sched_switch` with `prev_state` 1) and is woken (`sched_waking`) in the releaser's context.
- For a poll-run: many short entry/exit pairs on the same `uaddr`, each `ret = -110`, back to back, then one that ends with `ret = 0`.

For the thread that releases (the **releaser**, the holder):

- A `futex` call with a `WAKE`-type `op` on the same `uaddr`, inside the waiter's wait window. That is what names it.
- Its own scheduling state **during the wait** is the verdict:
  - **running** most of the time → it was **holding the lock and working**: contention.
  - **runnable-but-not-running** (switched out with `prev_state` 0 or the `0x100` flag, waiting for a CPU) for a large share, and its priority is **worse** than the waiter's → **inversion**. The threads that occupied its CPU meanwhile are the middle-priority threads.
  - **sleeping** most of the time → an **event wait**. Not a lock problem.

For the box: nothing. Other CPUs can be idle. Only the waiter is late.

### 1.3 Problems that look similar

Several things make a thread sleep in `futex`. This blueprint must tell them apart. You will use this table in Step 5.

| Cause | What the kernel trace shows | How it differs from a lock problem |
|---|---|---|
| **Priority inversion (this fault)** | Few long woken waits; the releaser has worse priority and was runnable-but-not-running for ≥ 30% of the wait; named middle threads held its CPU | — |
| **Lock contention (this fault)** | Many woken waits on one address by ≥ 2 threads; each waiter spends a large share of its time there; the releaser was running or preempted while holding | — |
| Event / condition-variable wait | A long woken wait whose releaser **slept** until it signalled (≥ 70% asleep) | Idle, not blocked. The tool says `event` and `NO LOCK PROBLEM` |
| Timed sleep | `ret = -110`; 100 ms / 1 s / 5 s pieces that never end with a wake | A timer. Counted under `timed sleeps`, never a lock wait |
| Poll-run that ends by timeout | A run of short timed waits that ends with another timeout and the thread goes on | The thread polled until the lock was free. Listed under `poll-runs`, not a woken lock wait |
| One idle worker on one futex | A single waiter spends ~100% of its time on one address, p50 a few ms, releaser running | One thread waiting for work. One waiter is never contention (`CONTENTION_MIN_WAITERS = 2`) |
| Runtime parking futexes (Go, Java) | Many waiters on one address, waits of any length, the releaser asleep | Parked worker threads: an event wait with many waiters. The tool classes it `event` |
| The holder is starved, no lock involved | The late thread is **runnable**, not in `futex` | `8_cpu_starvation`. `wait_chain.py` on it says NO LONG BLOCKS |
| A kernel lock inside a system call | The late thread blocks in **D-state**, released by a thread inside `clone` / `ioctl` | `9_syscall_stall`. The waker's call is a WORK-class call, not `futex` |
| Trace holes | "Waits" of seconds that overlap a period with no events on that CPU | Lost trace data or a stalled CPU. The tools drop them and print a `trace holes:` line |

---

## Part 2. What you need

| Input | Why |
|---|---|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/` | Everything comes from here. `metadata` holds the clock and the event types. `index/` makes cutting time slices fast |
| `syscall_entry_futex` / `syscall_exit_futex` events (or `compat_syscall_*`) | The lock waits and wakes. Without them this blueprint cannot be applied |
| `sched_switch` and `sched_waking` (or `sched_wakeup`) events | The releaser's state during the wait, and who woke whom |
| `sched_process_fork` and `lttng_statedump_process_state`, if present | To group threads into processes. Without them, and without a pid context, the tools still name threads by comm and tid |
| A baseline window (before the problem, or a second capture without it), if there is one | Lock waits that are also in the baseline are the program's normal life |
| `babeltrace2`, `python3`, GNU `date` | To read the trace and run the scripts |
| The scripts below, all in one folder | `tracelib.py` must sit next to the others: they import it |

The scripts:

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks. Reads only the index, so it takes seconds | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `idx_slice.py` | Copies only the packets that cover a time window into a small trace | used by `extract_slice.sh` |
| `extract_slice.sh` | Cuts one time slice and keeps only the events you name | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> '<events regex>'` |
| `pidmap.py` | Thread → process map from the trace's start-of-session state dump (tid, pid, ppid, name) | `pidmap.py <trace_dir> [--out FILE]` |
| `futex_wait.py` | **The decisive tool:** pairs every `futex` wait per thread, coalesces poll-runs, finds the releaser of each wait and its scheduling state, classes the waits, and gives the verdict | `futex_wait.py <slice> <secs> [--top 10] [--min-ms 1] [--pidmap FILE]` |
| `runq_wait.py` | One thread's runnable waits and who held its CPU meanwhile (blueprint 8's decisive tool). Used here on the **releaser**: was it runnable-but-not-running, and behind whom? | `runq_wait.py <slice> <victim tid\|name> [--top N] [--min-ms X] [--pidmap FILE]` |
| `wait_chain.py` | One thread's **blocked** time: who woke it, and what the waker was inside at that moment. Used on the **waiter** | `wait_chain.py <slice> <victim tid\|name> [--top N] [--pidmap FILE]` |
| `thread_top.py` | Every thread's time budget (run, runnable wait, S, D) with priority and CPUs | `thread_top.py <slice> <secs> [--sort wait\|run\|max\|wakeups] [--top N] [--cpu N] [--pidmap FILE]` |
| `tracelib.py` | The shared parser the tools import. Not run by hand | `tracelib.py --selftest` |

The slice pattern this blueprint uses (scheduling, fork and state dump, and the `futex` calls only):

```bash
LOCKEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_entry_futex|syscall_exit_futex'
```

`syscall_entry_futex` also matches `compat_syscall_entry_futex`: a 32-bit userspace on a 64-bit kernel emits the `compat_` names, and the tools accept both.

---

## Part 3. Setup

Run this block first, in every new terminal. Put your own paths in the first three lines.

```bash
TRACE=/path/to/trace       # the folder that holds `metadata`, `index/` and the channel files
TOOLS=/path/to/scripts     # the folder that holds the scripts (tracelib.py included)
WORK=/path/to/scratch      # an empty folder for slices and notes
LOCKEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_entry_futex|syscall_exit_futex'

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,idx_slice.py,extract_slice.sh,pidmap.py,futex_wait.py,runq_wait.py,wait_chain.py,thread_top.py,tracelib.py} > /dev/null && echo "scripts found"
```

Both lines must print OK.

- If `metadata` is missing, `TRACE` points to the wrong folder. Look one or two levels deeper (`kernel/`, `kernel/kernel/`).
- If `index/` is missing, the method still works, but cutting slices is slow.

---

## Part 4. Procedure

### Step 1. Check the trace

**Goal:** know when the trace starts and ends, whether it is healthy, and whether it holds the `futex` calls.

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt

DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
SECS=$(awk '/^duration/ {print int($3)+2}' $WORK/summary.txt)
echo "DAY=$DAY TRACE_START=$TRACE_START SECS=$SECS"

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -x -E '(compat_)?syscall_(entry|exit)_futex|sched_(switch|waking|wakeup)|sched_process_fork|lttng_statedump_process_state' $WORK/event_names.txt
```

Read it:

- **Health.** `lost events` and `time gaps` tell you where data is missing. The tools detect holes on their own and leave those stretches out, but write them down for the report.
- **Snapshot captures.** The trace may span more time than it holds events for. The tools print `note: events cover only X s of the Y s slice (snapshot-style trace)` and divide by the real span.
- The last `grep` must list both `syscall_entry_futex` and `syscall_exit_futex` (with or without `compat_`). If it does not, **stop**: the trace has no `futex` events and this blueprint cannot be applied. Say so; blueprints 8, 9 and 10 still can.
- If `sched_switch` is missing, **stop** as well.
- If the metadata grep lists nothing (CTF 1.8 text metadata, older LTTng), run `grep -a -o 'name = "[^"]*"' $TRACE/metadata | sort -u` instead.

**Next:** Step 2.

### Step 2. Cut one slice over the window, and a baseline if you can

**Goal:** one decoded slice that holds the scheduling and `futex` events for the time you suspect, a second one from a quiet time, and a thread → process map.

These faults are **steady while they last**: a lock that is contended, or a holder that cannot run, stays that way for as long as the load is on. So one slice over the suspect window (or over the whole capture, when it is short) is enough; you do not need to find an edge first. A baseline from **before** the window — or a second capture of the same box without the load — is what separates the program's normal locking from the fault.

```bash
START=$TRACE_START          # or the start of the window you suspect, HH:MM:SS
LEN=60                       # seconds; use $SECS for a short capture
bash $TOOLS/extract_slice.sh $TRACE $DAY $START $LEN $WORK/fault.txt "$LOCKEV"
# baseline, when the capture has a quiet stretch before the window (or a second capture):
# bash $TOOLS/extract_slice.sh $TRACE $DAY <quiet HH:MM:SS> $LEN $WORK/base.txt "$LOCKEV"
python3 $TOOLS/pidmap.py $TRACE --out $WORK/pidmap.tsv
PM="--pidmap $WORK/pidmap.tsv"    # leave empty if pidmap.py mapped nothing
```

- `extract_slice.sh` prints the slice bounds and the line count. A busy host with many threads gives millions of lines; the tool reads them in a few minutes.
- `pidmap.py` prints how many threads and processes it mapped. On a trace whose events carry no pid, this is what lets the tools say which process a thread belongs to.

**Next:** Step 3.

### Step 3. Find the lock waits and who releases them (the decisive step)

**Goal:** find the address threads wait on, measure the waits, name the releaser, and read its state.

```bash
python3 $TOOLS/futex_wait.py $WORK/fault.txt $LEN --top 10 $PM
# and the same on $WORK/base.txt when you have one
```

It prints, in order:

1. **A header**: `futex syscalls: N entries, M exits; K completed waits coalesced into L logical waits on F futexes, P still open at the end; slice S s`, then the `note:` and `trace holes:` lines when they apply.
2. **A per-futex table**, one row per address, sorted by total wait time: `futex  woken  held  poll  timed  other  runs  waiters  /s  p50 ms  p99 ms  max ms  total ms  pattern  released by`. `woken` = logical waits that ended with a wake from another thread (the lock waits); `held` = those whose releaser was running or runnable meanwhile; `poll` = runs of timed waits that ended by timeout; `timed` = single timed sleeps; `other` = `EINTR` / `EAGAIN` / restarts, or a wake nobody issued; `runs` = logical waits made of two or more pieces; `waiters` = distinct threads; `pattern` = `many short` / `few long` / `mixed`; `released by` = the threads that issued the wakes, with priority.
3. **One line per kind of non-lock wait**: `poll-runs: N logical waits on M futexes, p50 X ms, made of P timed pieces - the thread kept re-waiting with a timeout until it could go on (not a woken lock wait)`, `timed sleeps: N waits on M futexes (timeouts 100 ms, 1 s, 5 s) - not lock waits`, `other returns: ...`, and `releaser unseen: ...` for waits whose releaser's state could not be measured.
4. **`waiter shares on futex 0x..:`** for the busiest address: `<name> tid N: S% of its time waiting on it, ...` — the number an engineer wants.
5. **The longest actionable lock waits** (classes `held`, `starved`, `inversion` only), each with its class tag — `[held]`, `[inversion, run of 21]`, `[starved]`, `[mixed]` — and a line under it: `released by <name> tid H (pid P) prio Q at HH:MM:SS; during the wait it was running A ms (a%), runnable-but-not-running B ms (b%), sleeping C ms (c%)`. Then one line for the longest **event** wait, so you can see what was set aside.
6. **The verdict** in CAPS, with a `FIX:` line when it is a fault.

The verdict strings are fixed. Quote the one you get:

| Line | Meaning |
|---|---|
| `VERDICT: PRIORITY INVERSION: <w> tid T (prio P) waited X ms[ (a run of N timed waits)] on futex 0x..; the thread that released it, <h> tid H (prio Q), was runnable-but-not-running for Y ms (R%) of that wait, its CPU taken by a (prio ..), b (prio ..) (K such waits in all, T ms = S% of the slice; the waiter spends W% of its time in them)` + `FIX: priority inheritance on the lock (PTHREAD_PRIO_INHERIT / FUTEX_LOCK_PI), or raise the holder / do not hold the lock across a scheduling boundary` | **Inversion.** `<w>` is the waiter, `<h>` the holder with the worse priority, and `a`, `b` the middle threads that kept it off its CPU. The tail says how often it happens and how much of the waiter's life it costs |
| `VERDICT: LOCK CONTENTION on futex 0x..: N held lock waits (R/s[, K of them runs of timed waits]) by W threads, p50 X ms, p99 Z ms, max Y ms; lock-wait time T% of the slice, top waiter <name> tid K spends S% of its time on it; holders run while holding \| holders preempted while holding \| holders sleep while holding (a lock held across a sleep or I/O) (release by names)` + `FIX: shorten the critical section, split the lock, or batch the work done under it` — or, for the sleeping case, `FIX: do not sleep or do I/O while holding the lock ...` | **Contention.** One address, ≥ 2 waiters, each wait as long as the holder's critical section. `preempted while holding` means fewer CPUs than threads wanting them; `sleep while holding` means the critical section contains a sleep or an I/O, and the fix is to take that out of it. `lock-wait time T%` can exceed 100%: it adds up every waiter's time |
| `VERDICT: NO LOCK PROBLEM: longest lock wait X ms[ (a run of N timed waits)] by <w> tid T on futex 0x.. was an event wait (the releaser <h> slept until it signalled) - not a held lock` | The longest waits are condition variables or workers waiting for work. **Stop**: not this fault |
| `VERDICT: NO LOCK PROBLEM: longest lock wait X ms by <w> tid T on futex 0x.. was a held lock (releaser <h> ran while holding), but held waits total only A% of the slice (bar 5%) and the top waiter spends B% of its time on it (bar 20%)` | A real lock, lightly used. **Stop**: below the bars. Report the numbers if the operator asks about that lock |
| `VERDICT: FUTEX WAITS WITHOUT A SCHEDULING CAUSE: longest X ms by <w> tid T on futex 0x..; released by <h> prio .., which was running a% / runnable b% / sleeping c% of it [starved\|mixed]` | Long waits whose releaser's state fits none of the three pictures. Read the percentages and Step 4 before you decide |
| `VERDICT: NO LONG FUTEX WAITS (longest lock wait X ms)` / `VERDICT: NO LONG FUTEX WAITS (no lock wait at all: P poll-runs, N timed sleeps, M other returns)` | Nothing waited for a lock for 1 ms or more. **Stop**: not this fault |
| `VERDICT: NO FUTEX WAITS IN SLICE - check the events regex (see Usage)` | The slice holds no `futex` calls. Re-cut it with `$LOCKEV` |

**The rules, and where they come from.** A **lock wait** is a logical wait that ended with `ret = 0` and a wake issued by another thread on that address inside the window; a run of timed pieces (each ≤ 50 ms, the next starting within 1 ms of the previous exit) counts as one logical wait. Its **class** comes from the releaser's state during it: running ≥ 50% → `held`; runnable-but-not-running ≥ 30% and a worse priority than the waiter → `inversion`; runnable ≥ 30% with no worse priority → `starved`; sleeping ≥ 70% → `event`, or `held-asleep` when that sleeping releaser was itself holding the lock the waiter wanted; else `mixed`. **INVERSION** needs one `inversion`-class wait of ≥ 20 ms (`INVERSION_MIN_MS`): shorter ones are the scheduler's normal granularity between background threads. **CONTENTION** needs, on one address, ≥ 2 distinct waiters, a median wait ≥ 0.2 ms, and either the held waits summing to ≥ 5% of the slice or one waiter spending ≥ 20% of its time in them. Calibration:

- **Our own labelled `lock_contention` run** (a 12-CPU host running a microservice stack, 60 s inside the injection): the injected lock is one futex with **16 `python3` waiters**, about 202,000 held lock waits (3,368 per second), p50 4.2 ms, p99 7.1 ms, max 15.7 ms, lock-wait time 1477% of the slice (every waiter about **92% of its time waiting** on it), holders **sleep while holding** — the recipe holds the lock across a sleep. Verdict **LOCK CONTENTION** on that address, with the `do not sleep or do I/O while holding the lock` fix. The same slice holds the two lookalikes the rules set aside: a Go-runtime parking futex with 18 waiters whose releaser was asleep and whose waits spread over three orders of magnitude (p99/p50 = 158: parked workers, not a critical section), and a single Node.js worker waiting 100% of its time on one futex (one waiter).
- **Our own labelled `priority_inversion` run** (same host): a Python program with a nice −5 waiter (prio 115), a nice 19 holder (prio 139) that sleeps about 50 ms while holding an application lock, and six nice 0 middle threads burning CPU under a 2-CPU cap. Verdict **PRIORITY INVERSION** — on the interpreter's own lock: `python3 tid 2996395 (prio 115 (nice -5)) waited 34.3 ms (a run of 7 timed waits) on futex 0x7bcc90d32ec0; the thread that released it, python3 tid 2996424 (prio 120 (nice 0)), was runnable-but-not-running for 12.4 ms (36%) of that wait ... (908 such waits in all)`. The interpreter lock is held by whichever thread runs Python code; here a middle thread had it and was preempted. The application lock shows up as the waiter's longest actionable waits: `729.8 ms ... futex 0x5b7ba7e6c780 [held-asleep] - released by python3 tid 2996394 (prio 139 (nice 19)), which was ... sleeping 707.3 ms (97%)`, and a 444.7 ms one like it — the high-priority thread waiting on the low-priority holder, which sleeps while it holds. Step 4 then confirms the scheduling side: `runq_wait.py` on that holder says `STARVED BY HIGHER PRIORITY: python3 tid 2996424 prio 120 (nice 0) held cpu 10 for 104.7 ms` with the six middle threads as its top competitors (2.1 s of its 60 s runnable-but-not-running), and the waiter itself runs 0.2% and waits 1.0% (blocked, not runnable). Honest reading: the kernel shows the inversion on the interpreter lock plus the long waits on the application lock; the textbook "holder preempted while holding the application lock" does not appear, because that holder sleeps while holding.
- **Five partner line-card traces** (no lock fault): three **NO LOCK PROBLEM** — two healthy cards with inversion-class waits of 10.1 and 10.5 ms between background threads (under the 20 ms bar), one card with a 78 ms wait released by an equal-priority thread that had been preempted (a CPU-starvation effect, blueprint 8's territory), and the loaded control card with a 306 ms held lock under the 5% bar — and two **NO LONG FUTEX WAITS**. The longest woken waits on them were 3 s and 10 s condition-variable waits whose releaser slept until it signalled, plus 100 ms, 1 s and 5 s timer loops. True negatives, all five.

Read it:

- **PRIORITY INVERSION:** this fault. Write down the waiter, the holder, the middle threads, the address, the wait length and the `runnable-but-not-running` share. Go to Step 4 to confirm from the scheduler's side.
- **LOCK CONTENTION:** this fault's sibling. Write down the address, the waiters, the p50 and the top waiter's share. Compare with the baseline slice: a lock that shows the same numbers in the baseline is the program's normal life, not the incident; one that appears or grows with the window is the finding. Go to Step 4.
- **NO LOCK PROBLEM / NO LONG FUTEX WAITS:** not this fault. **Stop** and report what the longest wait was and why it does not count (event wait, timer loop, below the bars). Say so plainly; do not write "no fault" — this blueprint looks for one cause only.
- **FUTEX WAITS WITHOUT A SCHEDULING CAUSE:** look at the percentages. A releaser that was running part of the time and asleep the rest is a lock handed over inside a condition variable; run Step 4 on the releaser and decide from there, and say the verdict was not clean.
- The `poll-runs`, `timed sleeps` and `other returns` lines can be large. That is the box's normal life. Do not report them as lock waits.

Write down:

```bash
FUTEX=0x...                                # the address in the verdict
WAITER="<name tid prio>"  HOLDER="<name tid prio>"   # <w> and <h>
WAIT_MS=<X>  RUNNABLE_SHARE=<R%>  MIDDLE="<a>, <b>"   # inversion
WAITERS=<W>  P50_MS=<X>  TOP_SHARE="<name> <S%>"      # contention
```

**Next:** Step 4.

### Step 4. Confirm the mechanism from the scheduler's side

**Goal:** show, with the scheduling tools, that the holder really could not run (inversion), or really was busy or preempted under the lock (contention), and that the waiter was woken by it.

```bash
python3 $TOOLS/runq_wait.py $WORK/fault.txt $HOLDER --top 8 $PM
python3 $TOOLS/wait_chain.py $WORK/fault.txt $WAITER --top 12 $PM
```

`runq_wait.py` on the **holder** prints its runnable waits (count, p50, p99, max, share), the longest ones with the threads that occupied its CPU meanwhile, and a verdict:

| Line | Meaning for this blueprint |
|---|---|
| `VERDICT: STARVED BY CROWD: same-or-worse-priority threads held cpu X for M ms (P% of its waiting); N distinct threads at prio ...` | The holder was kept off its CPU by threads of its own or worse priority — for an inversion these are the middle threads, and they outrank it only because the holder's own priority is low. Their names must match `MIDDLE` |
| `VERDICT: STARVED BY HIGHER PRIORITY: <name> ... held cpu X for M ms` | One better-priority thread kept the holder off. Same mechanism, one culprit |
| `VERDICT: NOT STARVED - waits are P% of the slice, p99 X ms, longest M ms ...` | The holder ran whenever it wanted. Then it was **working under the lock**: contention, not inversion |
| `OTHER CPUS WERE IDLE K% OF THE TIME IT WAITED` | Placement, not a full host: the holder was pinned or kept on a crowded core |

`wait_chain.py` on the **waiter** prints its blocked time by waker and its longest blocks (`start ms state woken by | waker was inside`):

| Line | Meaning |
|---|---|
| `BLOCKED MOSTLY ON <holder> (P% of long-block time; Q% of all blocked time)` | The waiter's long blocks end when the holder wakes it. `Q%` is often small: a waiter also sleeps on packets and timers |
| longest blocks in **S** with `woken by <holder> | futex ...` | The waiter slept in `futex` and the holder's `futex` wake released it. The confirmation |
| `NO LONG BLOCKS (max X ms ...)` | The waiter is never blocked for long. **Not this fault** |
| `BLOCKED MOSTLY ON <other thread>` inside `clone` / `ioctl` / `write`, blocks in **D** | A kernel lock in a system call: `9_syscall_stall` |

Decide:

- **Inversion:** `runq_wait.py` on the holder says STARVED (by the middle threads named in Step 3) **and** `wait_chain.py` on the waiter is BLOCKED MOSTLY ON the holder in `futex`. Confirmed. Go to Step 5.
- **Contention:** `runq_wait.py` on a holder says NOT STARVED (or STARVED only because the box has fewer CPUs than waiting threads — `holders preempted while holding`), or the verdict says `holders sleep while holding` and the holder's `thread_top.py` row shows mostly S time (the critical section contains a sleep or an I/O); the waiters are BLOCKED MOSTLY ON the holders in `futex`; and the baseline shows the lock quieter. Confirmed. Go to Step 5.
- **The holder was neither starved nor busy** (it slept): the wait was an event, whatever Step 3 said. Treat the verdict as unconfirmed and say so.

```bash
HOLDER_VERDICT="<runq_wait line>"   WAITER_VERDICT="<wait_chain line>"   BASELINE="<the lock's numbers in base.txt, or 'no baseline'>"
```

**Next:** Step 5.

### Step 5. Rule out the lookalikes

**Goal:** check the other causes in the table in 1.3, using what you already have, plus one call.

| Check | Where to look | A lock problem looks like this |
|---|---|---|
| Was the longest wait an event wait? | Step 3, the class tags and the `NO LOCK PROBLEM ... event wait` line | The verdict wait is `held`, `starved` or `inversion`; the releaser was not asleep |
| Timed sleeps and poll-runs? | Step 3, the `timed sleeps:` / `poll-runs:` lines | They are listed apart and never make the verdict |
| One idle worker? | Step 3, `waiters` column | The verdict address has ≥ 2 waiters (contention) or a named holder with a worse priority (inversion) |
| A runtime parking futex? | Step 3, `released by` and the class | Many waiters **and** a releaser that slept = `event`, set aside |
| Is the waiter starved, not blocked? | `runq_wait.py` on the **waiter** (below) | NOT STARVED, or its runnable waits are small next to `WAIT_MS`; its time is in `futex` |
| Is it a kernel lock in a system call? | Step 4, `wait_chain.py` | The waker was inside `futex`, the blocks are in S, not D |
| Does the baseline show the same lock? | `futex_wait.py` on `base.txt` | The verdict address is absent or far quieter in the baseline |
| Trace holes? | the `trace holes:` line | Note it; the tools already left those intervals out |

The call:

```bash
python3 $TOOLS/runq_wait.py $WORK/fault.txt $WAITER --top 8 $PM
```

- It should say **`NOT STARVED`** for the waiter: it is blocked in `futex`, not waiting for a CPU. If it says STARVED with long waits, both faults are present; report both, each with its own numbers (`8_cpu_starvation` for that one).

If a check does not fit, say which one in your report, and treat the verdict as unconfirmed.

**Next:** Step 6.

### Step 6. Identify the waiter, the holder and the lock by name

**Goal:** describe who waited, who held, who got in the way, and how they are related, as precisely as the trace allows.

Everything you need is already printed; collect it:

- **The waiter:** thread name (comm), tid, `prio`, from the verdict; its share of time on the lock from `waiter shares`.
- **The holder (releaser):** name, tid, `prio`, from the verdict and the `released by` line; its state during the wait (running / runnable / sleeping, in ms and %).
- **The middle threads** (inversion): the `its CPU taken by` list, with priorities; `runq_wait.py` on the holder gives their time share.
- **The lock:** its address (`FUTEX`), the pattern, the waiter count, p50 / p99 / max, the total share.
- **The process:** with `pidmap.tsv`, `grep -P "^$TID\t" $WORK/pidmap.tsv` for each tid (tid, pid, ppid, name). Waiter and holder in the same process is the usual picture.

How to name things in the report, most specific first:

1. **Waiter name + tid + prio, holder name + tid + prio, the futex address, the wait length** — always.
2. **The middle threads** by name and priority (inversion), or **the waiters** by count and the top one's share (contention).
3. **The process** (pid, name) when the pid map shows it.
4. **What the lock protects**, inferred from the thread names and the pattern. Mark it Inferred: the trace does not record which mutex this is.

On a bare-metal box there is no container to name. Do not report a `pid_ns`. The number inside an enum such as `prev_state = ( "TASK_INTERRUPTIBLE" : container = 1 )` is the enum's integer, not a cgroup.

**Next:** Step 7.

### Step 7. Write the RCA statement

**Before writing:** this blueprint answers `priority_inversion`, `lock_contention` or `normal`, nothing else. A `NO LOCK PROBLEM` line whose text points elsewhere ("a CPU-starvation effect - see 8_cpu_starvation", "an event wait") means **`fault_type: normal` for this blueprint** with the pointer in `what_is_wrong`; do not switch to that other family from here. Measured: on one card the agent read "a CPU-starvation effect" and answered `cpu_starvation` from inside this blueprint, naming the thread the engineers had just promoted as the culprit - wrong on both counts.

**Goal:** a short statement that another person can check.

Template, inversion:

> Over **[window]** (UTC), thread **[waiter comm, tid, prio]** waited **[WAIT_MS] ms** (longest; **[count]** waits ≥ 1 ms) on futex **[address]** held by **[holder comm, tid, prio]**. During that wait the holder was **runnable-but-not-running for [R%]**, kept off its CPU by **[middle threads, prio]**, which outrank it. The waiter was released only when the holder finally ran and called `futex` wake. We ruled out **[an event wait / a timer loop / CPU starvation of the waiter / a kernel lock]** because **[reason]**. We did not check **[what was not tested]**. Fix: **priority inheritance on the lock (`PTHREAD_PRIO_INHERIT` / `FUTEX_LOCK_PI`), or raise the holder, or do not hold the lock across a scheduling boundary**.

Template, contention:

> Over **[window]** (UTC), **[W] threads** of **[process]** queued on futex **[address]**: **[N] lock waits**, p50 **[X] ms**, max **[Y] ms**; the top waiter **[name, tid]** spent **[S%]** of its time waiting on it, and lock waits were **[T%]** of the slice. The holders were **[running under the lock / preempted while holding / sleeping while holding]**. In the baseline the same lock showed **[numbers, or 'was absent']**. We ruled out **[...]** because **[...]**. We did not check **[...]**. Fix: **shorten the critical section, split the lock, or batch the work done under it** — or, when the holders sleep while holding, **do not sleep or do I/O while holding the lock**.

Rules:

- Name the waiter, the holder, the lock address and the window. For an inversion, name the middle threads; for contention, the waiter count and the top waiter's share.
- Give at least two independent pieces of evidence: the futex verdict with the releaser's state (Step 3), and the scheduler's view of the holder and the waiter (Step 4).
- Mark each claim **Measured** (seen in the trace) or **Inferred** (reasoned from what you saw). The wait lengths, the releaser's state shares and the priorities are Measured. "It is the lock around X" is Inferred. The fix is Inferred.
- **Say what the trace cannot show.** The symptom the operator reported (late replies, a timeout) lives in the application. Your verdict is the **lock cause**, not the symptom.
- Say what you did not test.

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects two causes: a lock held by a thread that cannot run, and a lock many threads fight over. If a step points elsewhere, it stops and tells you so. It does not diagnose that other cause.
- It needs the `futex` events. A trace recorded without `--syscall` (or without `futex` in the list) cannot be judged.
- It sees the kernel half of the lock: the address, the waits, the wakes, the releaser's scheduling state. It does not see which mutex in the program that address is, nor what the critical section does. A user-space trace (LTTng-UST, `pthread` tracepoints) is the next instrument if that matters.
- The releaser is "the thread that issued the wake inside the wait". For a condition variable with many waiters, the wake may come from a thread that did not hold any lock; the class rules (`event`) catch most of that, not all. Step 4 is the check.
- Interpreter locks (Python's GIL, Ruby's GVL) show as one hot futex among the interpreter's threads. The tool reports them honestly as contention; whether that is the fault or the language's normal behaviour needs the baseline.
- The bars (5% / 20% / 0.2 ms, 30% / 50% / 70%) are first-pass numbers from one labelled contention run, synthetic inversion data and five negatives. Check the raw percentages the tool prints when a verdict looks borderline.
- Trace holes (snapshot buffers, discarded events) are left out of every number, and the tools say so.

---

## Part 6. References

The mechanism:

1. `futex(2)` man page (the operations and flags). https://man7.org/linux/man-pages/man2/futex.2.html
2. `pthread_mutexattr_setprotocol(3)` (`PTHREAD_PRIO_INHERIT`) and the kernel's `FUTEX_LOCK_PI` (priority-inheritance futexes). https://man7.org/linux/man-pages/man3/pthread_mutexattr_setprotocol.3.html , https://docs.kernel.org/locking/pi-futex.html
3. L. Sha, R. Rajkumar, J. Lehoczky, *Priority inheritance protocols: an approach to real-time synchronization*, IEEE Trans. Computers 39(9), 1990 (the original description of the fault and the fix).
4. `sched(7)` man page (nice values, real-time classes; what "priority" means to the scheduler). https://man7.org/linux/man-pages/man7/sched.7.html

The method, measuring lock waits:

5. Trace Compass user guide, *Futex Contention Latency Analysis* (waits per address, waiter vs address view) and *Critical Flow View*. https://archive.eclipse.org/tracecompass/doc/stable/org.eclipse.tracecompass.doc.user/LTTng-Kernel-Analysis.html
6. F. Giraldeau and M. Dagenais, *Wait analysis of distributed systems using kernel tracing*, IEEE TPDS 27(8), 2016 (what `wait_chain.py` computes, one level deep). https://publications.polymtl.ca/3078/
7. B. Gregg, *Off-CPU Analysis* and *offwaketime* (blocked time with the waker's context). https://brendangregg.com/offcpuanalysis.html
8. The Linux kernel's `sched_pi_setprio` tracepoint (priority boosts applied by PI futexes; on a kernel that uses them, it is the direct evidence). https://docs.kernel.org/trace/events.html

The tools and the trace format:

9. LTTng documentation (`--syscall` tracing; the `sched_*` kernel events). https://lttng.org/docs/
10. Babeltrace 2, `source.ctf.fs` component. https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What the tools measure

You do not need this to follow the steps. It explains the columns, the classes and the bars.

**Pairing a wait to a thread.** A `futex` event carries no thread id on a switch/router trace (no process context on the events). `futex_wait.py` keeps track of who `sched_switch` put on each CPU and charges the entry to that thread; the exit is matched to the same thread's open call. On traces that carry a context block, that tid is used directly.

**Logical waits.** Consecutive waits by the same thread on the same address, each piece ≤ `COALESCE_PIECE_MS` (50 ms) and the next entered within `COALESCE_GAP_MS` (1 ms) of the previous exit, with intermediate returns `-110` or `-11`, are one logical wait from the first entry to the last exit. A wake issued by the same thread in between does not break the run. The last exit decides: `ret = 0` with a wake found → a lock wait; a timeout after two or more pieces → a **poll-run**; a single `-110` → a **timed sleep**; `-4` / `-11` / `-512` / `-514`, or `ret = 0` with no wake found → **other**.

**The releaser.** The last thread that issued a `WAKE`-type `futex` op on that address inside the wait window (wakes by the waiter itself are skipped). Its scheduling intervals are overlapped with the wait to get running / runnable-but-not-running / sleeping shares. When those intervals cover less than half of the wait, the wait is **releaser unseen** and is not judged.

**Classes.** `held` = releaser running ≥ `HOLDER_RUNNING_SHARE` (50%); `inversion` = releaser runnable-but-not-running ≥ `INVERSION_RUNNABLE_SHARE` (30%) and its priority worse than the waiter's; `starved` = runnable ≥ 30%, priority not worse; `event` = sleeping ≥ `EVENT_SLEEP_SHARE` (70%), or `held-asleep` when that sleeping releaser was holding the lock the waiter wanted (it sleeps inside its critical section); `mixed` = none of these. Only waits of ≥ `LONG_WAIT_MS` (1 ms) are examined, and an `inversion` wait counts toward the verdict only from `INVERSION_MIN_MS` (20 ms).

**The table.** `woken  held  poll  timed  other  runs  waiters  /s  p50  p99  max  total  pattern  released by`: counts per class of logical wait; `runs` = logical waits of two or more pieces; `/s`, `p50`, `p99`, `max`, `total` are over the lock waits; `pattern` is `many short` (≥ `PATTERN_MANY_PER_S` = 20 per second), `few long`, or `mixed`; `released by` lists the releasers with their priority.

**The bars.** `CONTENTION_MIN_WAITERS` = 2; `CONTENTION_MIN_P50_MS` = 0.2; `CONTENTION_TOTAL_SHARE` = 0.05 (held waits on one address ≥ 5% of the effective slice) or `CONTENTION_WAITER_SHARE` = 0.20 (one waiter ≥ 20% of its time in them). `INVERSION_MIN_MS` = 20: one `inversion`-class wait of 20 ms or more is the fault (the verdict then counts all of them: `K such waits in all, T ms = S% of the slice; the waiter spends W% of its time in them`); 10 ms ones between background threads are the scheduler's normal granularity and were measured on healthy cards.

**Ranking.** The "longest lock waits" list holds the actionable classes only (`held`, `starved`, `inversion`), so that long condition-variable waits (50 s, 60 s) do not fill it; the single longest `event` wait is printed on its own line.

**Holes and snapshot span.** A CPU with a runnable thread waiting for it cannot be silent, so an interval that overlaps a period with no event at all on its CPU for 0.5 s or more is lost data or a stalled CPU; the tools drop it and print a `trace holes:` line. When the events cover much less than the slice you cut, the tools divide by the span that holds events and say so.

## Appendix B. Solved cases

Read your own slices by comparison with your own box, not against these stories.

**Contention (our own labelled run).** A 12-CPU host running a microservice stack; a container injected 16 Python threads fighting one lock under a 2-CPU cap for two minutes. The 60 s slice inside the window: `futex_wait.py` listed about 7,000 futex addresses, coalesced 1.78 million completed waits into 1.68 million logical waits, and put the injected lock first: `LOCK CONTENTION on futex 0x59951ebb5c40: 202064 held lock waits (3368/s) by 16 threads, p50 4.20 ms, p99 7.1 ms, max 15.7 ms; lock-wait time 1477% of the slice, top waiter python3 tid 1668406 spends 92% of its time on it; holders sleep while holding (a lock held across a sleep or I/O)`, with the fix `do not sleep or do I/O while holding the lock`. That is the recipe exactly: each holder sleeps a few milliseconds inside its critical section, and the other fifteen queue. The same slice showed the two lookalikes the rules set aside: a Go-runtime parking futex with 18 waiters at 99% share whose releaser slept and whose waits spanned three orders of magnitude (p99/p50 = 158), and a single Node.js worker that waited 100% of its time on one futex, p50 8 ms (one waiter — present in the baseline too). The baseline slice, cut 70 s before the injection, had no such lock.

**Inversion (our own labelled run).** The same host; a container injected a nice −5 waiter (prio 115), a nice 19 holder (prio 139) that sleeps about 50 ms while holding an application lock, and six nice 0 middle threads burning CPU, all in one Python process under a 2-CPU cap. The tool's verdict: `PRIORITY INVERSION: python3 tid 2996395 (prio 115 (nice -5)) waited 34.3 ms (a run of 7 timed waits) on futex 0x7bcc90d32ec0; the thread that released it, python3 tid 2996424 (prio 120 (nice 0)), was runnable-but-not-running for 12.4 ms (36%) of that wait ... (908 such waits in all)`. That address is the interpreter's own lock (its 5 ms timed waits coalesced into runs); whoever runs Python code holds it, and here a middle thread had it and was preempted — a real inversion of the interpreter lock, 908 times in 60 s. The application lock appears as the waiter's longest actionable waits: `729.8 ms python3 tid 2996395 (prio 115) futex 0x5b7ba7e6c780 [held-asleep] - released by python3 tid 2996394 (prio 139 (nice 19)), which was running 2.4 ms (0%), runnable-but-not-running 20.1 ms (3%), sleeping 707.3 ms (97%)`, and a 444.7 ms one like it: the high-priority thread waiting on the low-priority holder, which sleeps while it holds. Step 4 confirmed the mechanism from the scheduler's side: `runq_wait.py` on the holder (tid 2996394) said `STARVED BY HIGHER PRIORITY: python3 tid 2996424 prio 120 (nice 0) held cpu 10 for 104.7 ms (5%)`, with the six middle threads as its top competitors (all better than nice 19; 2.1 s of its 60 s runnable-but-not-running), and `runq_wait.py` on the waiter showed run 0.2%, wait 1.0% — blocked, not runnable. The honest reading: the kernel shows the inversion on the interpreter lock plus the high-priority thread's long waits on the application lock held by the sleeping low-priority thread; the textbook "holder preempted while holding the application lock" does not appear, because that holder sleeps while holding. Report both facts; the fix (priority inheritance, or do not hold a lock across a sleep) covers both.

**The negatives (five partner line-card traces).** No lock fault on any of them, and the tool said so. Three `NO LOCK PROBLEM`: two healthy cards with inversion-class waits of 10.1 and 10.5 ms between background threads (under the 20 ms bar), one card with a 78 ms wait released by an equal-priority thread that had been preempted (a CPU-starvation effect, which blueprint 8 found on that card), and the loaded control card with a 306 ms held lock under the 5% bar. Two `NO LONG FUTEX WAITS`. The longest woken waits were 3 s and 10 s condition-variable waits whose releaser slept until it signalled, and the busiest addresses were 100 ms, 1 s and 5 s timer loops (`timed sleeps`). The real faults on those cards were a CPU crowd (blueprint 8), a `clone` stall (blueprint 9) and an interrupt pile-up (blueprint 10); this blueprint stayed quiet, as it should.
