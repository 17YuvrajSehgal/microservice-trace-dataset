# Blueprint: finding a thread stuck inside one long system call on a bare-metal host from a kernel trace

| | |
|---|---|
| Problem class | Latency (kernel path / blocking) |
| Root cause this blueprint confirms or rejects | One **thread** sits inside **one system call** (`fork`/`clone`, `ioctl`, `mmap`, a `write` to a device...) for tens of milliseconds at a time, repeatedly. While it is in there, the threads that depend on it **freeze**: siblings of the same process block in D-state on a kernel lock the call holds, or threads it must wake stay asleep until it comes out |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder. The trace must hold the **system call** events (`syscall_entry_*` / `syscall_exit_*`, or `compat_syscall_*`) as well as the scheduling events |
| Also allowed | The list of event types the trace holds (read from `metadata`) |
| Not used | Logs, metrics, application counters (packet drops, late replies), request traces |

**How to use this blueprint.** Read Part 1 once, to learn what the fault is and what it looks like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

**When to reach for this instead of `8_cpu_starvation`.** Blueprint 8 is for a thread that is **ready to run and waiting for a CPU**. This blueprint is for a thread that is **blocked**: it sleeps in D-state until another thread finishes a system call. The two look alike from the outside (a late thread, dropped packets) and `wait_chain.py` tells them apart in one call: if the late thread's long blocks are **released by one other thread coming out of one call**, it is this blueprint. Use it on a bare-metal box (one `pid_ns` everywhere, or none) when the question is "what is this thread waiting *for*?".

> **Honest status.** Calibrated on one labelled line-card trace of one real fault (partner case 2: a status-polling thread's `clone` of 50–70 ms, freezing the comms Tx thread and two others in D for ~48 ms each time; the engineers measured 53.6 ms and fixed it with `posix_spawn`), plus four other cards where the tool correctly found no stall of this kind (only drivers sleeping inside `ioctl`, and the tracer's own disk flushes). The thresholds in Step 3 are a first pass from those five traces.

---

## Part 1. Background

### 1.1 What the fault is

A system call is the kernel doing work for a thread. Two kinds matter here:

- **WAIT-class calls** exist to wait: `poll`, `select`, `epoll_wait`, `futex`, `nanosleep`, `read` on a socket, `recvfrom`, `wait4`... A thread that sits in one of these for a second is simply idle. That is normal.
- **WORK-class calls** exist to do something: `clone`/`fork`, `execve`, `mmap`/`munmap`, `ioctl`, `write`, `sync`... They are expected to return quickly. When one of them takes tens of milliseconds, the thread is **stuck**, and often it is not the only one that pays.

The classic case is **`fork` in a big multithreaded process.** `fork` (the `clone` call without the `CLONE_VM` flag) copies the parent's whole address space: every page table of every thread's memory. For a process with hundreds of threads and a large heap that copy takes tens of milliseconds of pure CPU work. And while it runs, the kernel holds the process's **memory lock** (`mmap_lock`) for writing. Every sibling thread that touches memory in a way that needs that lock — a page fault, an `mmap`, a `brk` — stops dead in **D-state** (uninterruptible sleep) until the copy ends. A comms thread that must send a packet every few milliseconds misses its deadline every time its process forks. The usual trigger is a line like `system("ping ...")` or `popen()` in a helper thread: it forks the whole process to run a tiny command.

How to read the `clone_flags` the trace records:

| `clone_flags` | What it is | Cost |
|---|---|---|
| `0x100011` (no `CLONE_VM`) | A full `fork`: copy the whole address space | Tens of ms in a big process, and it holds the memory lock |
| `0x4111` (`CLONE_VM` + `CLONE_VFORK`) | `vfork`-style, what `posix_spawn` does: no copy, the parent waits until the child calls `exec` | About 1–2 ms |
| `0x3d0f00` (`CLONE_THREAD` + `CLONE_VM`) | A new thread of the same process | Well under 1 ms |

The tools decode the flags for you.

Other WORK-class calls can stall the same way: an `ioctl` that makes a driver do slow work, a `write` to a device file that blocks in D until hardware answers, a large `mmap`/`munmap`, a `sync`. The question is always the same: **was the thread working (on-CPU) or held (D-state) inside the call, and who froze meanwhile?**

**What is not a stall.** Many drivers on embedded boxes use `ioctl` as a *wait primitive*: the thread calls `ioctl` and the driver puts it to sleep in **S-state** (interruptible) until an event arrives, for seconds at a time. That is a wait wearing a WORK-class name. The tools measure the sleep share inside every call and leave such calls out. **D-state is the tell:** S means "waiting for something to happen", D means "held by the kernel".

### 1.2 What it looks like in a kernel trace

For the thread that is stuck (the **staller**):

- `syscall_entry_clone` (or `compat_syscall_entry_clone` on a 32-bit userspace) and the matching `syscall_exit_clone` tens of milliseconds later, on the same thread.
- Inside that window the thread is **on the CPU** (`sched_switch` shows it running: the copy is CPU work) and/or **in D-state** (switched out with `prev_state` 2). Little or no S-sleep.
- It repeats: every few seconds, the same thread, the same call, the same length.

For the threads that pay (the **dependants**):

- Siblings of the same process go to **D-state** during the window (`prev_state` 2) and are **woken by the staller** (`sched_waking` in the staller's context) at or just before the staller's `syscall_exit`. Their CPU use during the window drops to nearly nothing.
- A latency-sensitive dependant (a comms thread) shows a block of ~50 ms that ends exactly when the staller's call ends.

For the rest of the box: nothing. Other cores can be idle; nothing is saturated. Only the staller's process is hit.

### 1.3 Problems that look similar

Several things make a thread sit in a system call or wait for another thread. This blueprint must tell them apart. You will use this table in Step 5.

| Cause | What the kernel trace shows | How it differs from a stall |
|---|---|---|
| **Stall in a WORK-class call (this fault)** | One thread on-CPU or in D inside `clone` / `ioctl` / `mmap` / `write` for ≥ 10 ms; dependants frozen in D and released by it; repeats | — |
| Sleeping inside `ioctl` or `poll` | A long call that is ~100% S-state sleep; the thread was woken by an interrupt or another thread when the event came | A wait, not a stall. The tool lists it under "sleeping inside" and leaves it out |
| The tracer's own disk flush | `lttng-consumerd` in `sync_file_range2` / `splice` with D-state time | Instrumentation, not the system under test. The tool leaves `lttng*` threads out and says so |
| A thread starved of CPU | The late thread is **runnable** and waiting (`runq_wait.py`), not blocked | `8_cpu_starvation`. `wait_chain.py` on it says NO LONG BLOCKS |
| A lock held by a thread that cannot run | The late thread blocks in `futex`; the thread that releases it was runnable-but-not-running | `11_priority_inversion`. The waker's call is `futex` (WAIT-class), not a WORK-class call |
| Disk I/O stall of the caller itself | A thread in D inside `write` / `fsync` with `block_rq_*` activity, **no dependants frozen** | Real, but it hurts only that thread. The verdict says `no sibling or freeze effect measured` |
| Trace holes | "Blocks" or "calls" of seconds that overlap a period with no events on that CPU | Lost trace data or a stalled CPU. The tools drop them and print a `trace holes:` line |

---

## Part 2. What you need

| Input | Why |
|---|---|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/` | Everything comes from here. `metadata` holds the clock and the event types. `index/` makes cutting time slices fast |
| `syscall_entry_*` / `syscall_exit_*` events (or `compat_syscall_*`) | The system calls themselves. Without them this blueprint cannot be applied |
| `sched_switch` and `sched_waking` (or `sched_wakeup`) events | To know whether the staller was on-CPU, in D or asleep inside the call, and who woke whom |
| `sched_process_fork` and `lttng_statedump_process_state`, if present | To group threads into processes (siblings). Without them, and without a pid context, the tools still find the stall and the threads it released; only the "siblings starved" line is missing |
| `irq_handler_*` and `irq_softirq_*`, if present | So `wait_chain.py` can name a wakeup from an interrupt (`softirq NET_RX`) instead of blaming the idle thread |
| `babeltrace2`, `python3`, GNU `date` | To read the trace and run the scripts |
| The scripts below, all in one folder | `tracelib.py` must sit next to the others: they import it |

The scripts:

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks. Reads only the index, so it takes seconds | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `idx_slice.py` | Copies only the packets that cover a time window into a small trace | used by `extract_slice.sh` |
| `extract_slice.sh` | Cuts one time slice and keeps only the events you name | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> '<events regex>'` |
| `pidmap.py` | Thread → process map from the trace's start-of-session state dump (tid, pid, ppid, name) | `pidmap.py <trace_dir> [--out FILE]` |
| `syscall_stall.py` | **The decisive tool:** pairs every system call per thread, measures on-CPU / D / sleep inside each call, ranks the stalls, lists who was frozen and who was starved, and gives the verdict | `syscall_stall.py <slice> [--min-ms 10] [--top 20] [--only name,name] [--pidmap FILE]` |
| `wait_chain.py` | One thread's **blocked** time: who woke it, and what the waker was inside at that moment. Confirms the stall from the victim's side | `wait_chain.py <slice> <victim tid\|name> [--top N] [--pidmap FILE]` |
| `thread_top.py` | Every thread's time budget (run, runnable wait, S, D) with priority and CPUs | `thread_top.py <slice> <secs> [--sort wait\|run\|max\|wakeups] [--top N] [--cpu N] [--pidmap FILE]` |
| `runq_wait.py` | One thread's runnable waits (blueprint 8's decisive tool). Used here to rule starvation out | `runq_wait.py <slice> <victim tid\|name> [--top N] [--min-ms X] [--pidmap FILE]` |
| `tracelib.py` | The shared parser the tools import. Not run by hand | `tracelib.py --selftest` |

The slice pattern this blueprint uses (scheduling, fork and state dump, **every system call**, and the interrupt events):

```bash
STALLEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_|irq_handler_|irq_softirq_'
```

`syscall_` matches both `syscall_entry_x` and `compat_syscall_entry_x`: a 32-bit userspace on a 64-bit kernel emits the `compat_` names, and the tools accept both.

---

## Part 3. Setup

Run this block first, in every new terminal. Put your own paths in the first three lines.

```bash
TRACE=/path/to/trace       # the folder that holds `metadata`, `index/` and the channel files
TOOLS=/path/to/scripts     # the folder that holds the scripts (tracelib.py included)
WORK=/path/to/scratch      # an empty folder for slices and notes
STALLEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_|irq_handler_|irq_softirq_'

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,idx_slice.py,extract_slice.sh,pidmap.py,syscall_stall.py,wait_chain.py,thread_top.py,runq_wait.py,tracelib.py} > /dev/null && echo "scripts found"
```

Both lines must print OK.

- If `metadata` is missing, `TRACE` points to the wrong folder. Look one or two levels deeper (`kernel/`, `kernel/kernel/`).
- If `index/` is missing, the method still works, but cutting slices is slow.

---

## Part 4. Procedure

### Step 1. Check the trace

**Goal:** know when the trace starts and ends, whether it is healthy, and whether it holds system calls.

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt

DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
SECS=$(awk '/^duration/ {print int($3)+2}' $WORK/summary.txt)
echo "DAY=$DAY TRACE_START=$TRACE_START SECS=$SECS"

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -c -E '^(compat_)?syscall_entry_' $WORK/event_names.txt
grep -x -E '(compat_)?syscall_(entry|exit)_clone|sched_(switch|waking|wakeup)|sched_process_fork|lttng_statedump_process_state' $WORK/event_names.txt
```

Read it:

- **Health.** `lost events` and `time gaps` tell you where data is missing. The tools detect holes on their own and leave those stretches out, but write them down for the report.
- **Snapshot captures.** Line cards often record in snapshot mode: the trace spans 30–180 s but holds events for only the last 6–30 s. The tools print `note: events cover only X s of the Y s slice (snapshot-style trace)` and use the real span. Read the numbers against that span.
- The first `grep -c` must print a number well above 0: the count of system-call event types. If it prints `0`, **stop**: the trace has no system-call events and this blueprint cannot be applied. Say so; `8_cpu_starvation` and `10_irq_imbalance` still can.
- If `sched_switch` is missing, **stop** as well.
- If the metadata grep lists nothing (CTF 1.8 text metadata, older LTTng), run `grep -a -o 'name = "[^"]*"' $TRACE/metadata | sort -u` instead.

**Next:** Step 2.

### Step 2. Cut one slice over the whole trace, and map the threads

**Goal:** one decoded slice that holds every scheduling, system-call and interrupt event, and a thread → process map.

Do **not** hunt for a window first. A stall of this kind **repeats** (every few seconds, every time the helper runs), so one slice over the whole span catches several instances and shows the period. Line-card traces are short; the slice is a few hundred thousand to a few million lines.

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $TRACE_START $SECS $WORK/all.txt "$STALLEV"
python3 $TOOLS/pidmap.py $TRACE --out $WORK/pidmap.tsv
```

- `extract_slice.sh` prints the slice bounds and the line count.
- `pidmap.py` prints how many threads and processes it mapped. This is what makes "siblings of the same process" answerable on a trace whose events carry no pid. If it maps none, the tools still work; the siblings line is simply absent.

```bash
PM="--pidmap $WORK/pidmap.tsv"    # leave empty if pidmap.py mapped nothing
```

**Next:** Step 3.

### Step 3. Find the stall (the decisive step)

**Goal:** find the thread stuck inside one call, measure the call, and see who paid for it.

```bash
python3 $TOOLS/syscall_stall.py $WORK/all.txt --min-ms 10 --top 20 $PM
```

It prints, in order:

1. **A per-syscall table**: `syscall  class  count  p50_ms  p99_ms  max_ms  sleep%  unmatched`. `class` is WAIT or WORK. `sleep%` (WORK rows only) is the share of the call's time spent in S-state sleep; a WORK row with `sleep%` near 100 is a driver waiting, not a stall.
2. **Two lines of things left out**: `WORK-class calls >= 10 ms that were sleeping (>= 90% S-state, left out as waits): ioctl x300 (max 7296.8 ms, <thread>)` and `tracer's own activity (left out): sync_file_range2 x1 (max 199 ms wall, 175 ms D) by lttng-consumerd`.
3. **The stall table**, headed `stalls >= 10 ms (on-CPU + D inside one WORK-class call, or a D-state thread frozen by it): top N of M`, with columns `start  wall  on-CPU  D  sleep%  froze_ms  thread | syscall | args`. It is ranked by `froze_ms` (the longest D-state block of a thread the call froze) first, then by `on-CPU + D`. For `clone` the args column decodes the flags: `0x100011 = fork of the whole address space (no CLONE_VM) - slow for a big multithreaded process, and it holds the memory lock the siblings need`, `0x4111 = vfork-style (CLONE_VM|CLONE_VFORK): no address-space copy, fast`, `0x3d0f00 = new thread (CLONE_THREAD|CLONE_VM)`.
4. **`repeat:`** how often the top staller's call recurs.
5. **The impact of each top stall**: `sibling <name> tid N: X ms on-CPU during the stall vs Y ms expected  <- STARVED` for the threads of the same process (STARVED = under 25% of expected, when expected is ≥ 1 ms), then `frozen in D and released by the caller: <name> tid N blocked X ms`, then `also woken by the caller (S-state: their own timers / condvars, not freezes): ...`.
6. **The verdict** in CAPS, plus a line about the long WAIT-class calls.

The verdict strings are fixed. Quote the one you get:

| Line | Meaning |
|---|---|
| `STALL: <thread> tid N spent X ms in <syscall> (A ms on-CPU + B ms D; <flags decode>) - n times, every ~Z s; it froze K threads in D for up to X ms (names); siblings starved: names; released at exit: name (X ms blocked)` | **This fault.** The top row of the stall table, with its period (`n times, every ~Z s`, `2 times, Z s apart`, or `once`), the threads it held in D, the siblings that got no CPU, and who it released |
| `STALL: ... (A ms on-CPU + B ms D, P% sleeping; ...) - ...; it froze K threads in D ...` | The staller itself mostly slept inside the call, but a thread sat in D during it and was woken by it: the memory-lock signature still holds. Report both facts |
| `STALL: ... - once; during it: no sibling or freeze effect measured` | A real long call, but nobody else paid. Report it as a finding on that thread only |
| `NO WORK-CLASS SYSCALL >= 10 ms (longest on-CPU+D inside one call: <syscall> X ms of a Y ms call by <thread>)` | No stall. **Stop**: this is not the fault. The longest call is named so you can say what you checked |
| `long waits are in WAIT-class calls (poll/futex/...) = normal sleeping, not a stall (longest: <call> X ms by <thread>, 100% asleep)` | Always printed. Says that the long calls are waits |
| `long waits are in sleeping inside WORK-class calls (ioctl) = normal sleeping, not a stall (longest: ...)` | The long WORK-class calls were drivers sleeping. Not a stall |
| `trace holes: ...` | Intervals over lost data were left out. Say so in the report |

**The rule, and where it comes from.** A call is a **stall** when its **on-CPU + D time inside the call is ≥ 10 ms** (`--min-ms`), or when the call is ≥ 10 ms long and **held a dependant in D-state for ≥ 10 ms** that it then woke. Time asleep in S inside the call never counts. `lttng*` threads never count. Calibration (partner case 2, anonymised):

- A 4-core line card, a 33 s capture holding about 10 s of events. A status-polling thread ran `system("ping ...")` — a `clone` with flags `0x100011` — twice in that span, 2.3 s apart: **56.6 ms** and **69.6 ms** wall, **47 ms on-CPU** each (the page-table copy), 0 ms D, 0% sleep. Each call **froze 3 threads in D for up to 49.4 ms**: the comms Tx thread (46.8 and 48.5 ms in D), a timer thread and a monitor thread; 3–5 siblings were marked STARVED (0–0.3 ms on-CPU against 2–7 ms expected). Verdict STALL on that `clone`. The engineers had measured the same call at 53.6 ms, every 7–8 s under load, and fixed it with `posix_spawn` (1.9 ms); the drops went to zero.
- Four other cards of the same family: the only long WORK-class calls were `ioctl` sleeps of 1–30 s (100% S-state; drivers waiting) and the tracer's own flushes. The tool listed them under "sleeping inside" and "tracer's own activity" and gave no STALL — or named a small, real, unrelated one (see below).

Read it:

- **A STALL in `clone` with `0x100011`, from a thread of a big process, with `it froze K threads in D` and `siblings starved`:** this fault. The fix is in Step 7. Write down the staller, the call, the length, the period, the frozen threads.
- **A STALL in `ioctl` / `write` / `mmap` with D-state time:** also a real stall, on that call. Report it. Read the `froze` clause to see who paid: it names who sat in D because of it. Measured on a second card: `STALL: a base thread spent 364.2 ms in write (0.1 ms on-CPU + 364.1 ms D; fd=36, count=4) - 6 times, every ~4.3 s; it froze 1 thread in D for up to 249.1 ms (systemd-journal)` — a 4-byte write to a device file blocking in D. That is a genuine finding to report, but a D-state stall whose frozen dependant is **not a latency-critical thread** does not by itself explain a comms-path symptom. Say what it froze, and keep looking for the symptom's cause if the frozen thread is not on that path.
- **A STALL with `no sibling or freeze effect measured`:** a slow call that hurt only its own thread. Report it as a minor finding unless that thread is the one the operator complained about.
- **`NO WORK-CLASS SYSCALL >= 10 ms`:** not this fault. **Stop** and report what the longest call was. Say so plainly; do not write "no fault" — this blueprint looks for one cause only.
- The `sleeping inside` line can be long (hundreds of `ioctl` sleeps). That is the box's normal life. Do not report those as stalls.

Write down:

```bash
STALLER=<thread name or tid>      # the thread in the top row
CALL=<syscall>  FLAGS=<decode>    # e.g. clone, 0x100011 = full fork
STALL_MS=<wall> ONCPU_MS=<on-CPU> D_MS=<D>  REPEAT="<n times, every ~Z s>"
FROZEN="<name tid ms> ; <name tid ms>"      # from the froze clause
STARVED="<name> ; <name>"                   # siblings marked STARVED
VICTIM=<the frozen thread the operator cares about, tid or name>
```

**Next:** Step 4.

### Step 4. Confirm it from the victim's side

**Goal:** show that the victim's long blocks end exactly when the staller comes out of that call.

```bash
python3 $TOOLS/wait_chain.py $WORK/all.txt $VICTIM --top 12 $PM
```

It prints the victim's blocked time (total, share, count, p50, max) and the calls it was blocked in; the blocked time **by waker**, over all blocks and over the long blocks (≥ 10 ms) — routine packet and timer waits dominate the total and would hide the stall; the longest blocks one by one (`start  ms  state  woken by | waker was inside`, e.g. `48.5  D  <staller> tid N prio 120 (nice 0) | clone for 49.2 ms (49.2 ms on-CPU+D)`); and verdict lines.

| Line | Meaning |
|---|---|
| `BLOCKED MOSTLY ON <waker> (P% of long-block time; Q% of all blocked time)` | The thread that released the victim from its long blocks. `Q%` is usually small: the victim's *total* sleep is packets and timers; its *long* blocks are the stall |
| `THE WAKER WAS STUCK IN <syscall> FOR MOST OF THE LONGEST BLOCKS (<waker>; P% of the top-5 block time overlaps that call)` | **The confirmation.** The victim's longest blocks sit inside the waker's call, and that call was on-CPU or in D (a sleeping call never earns this line) |
| `BLOCKED ON INTERRUPTS/SOFTIRQ (network or timer driven): P% of N wakeups come from interrupt context` | The victim's *ordinary* wakeups are packets and timers. On its own, this means a normal packet path — not a fault |
| `NO LONG BLOCKS (max X ms; the victim is not being held off the CPU by anyone)` | The victim is never blocked for long. **Not this fault.** If it is late, it is waiting for a CPU (`8_cpu_starvation`) or simply busy |

Decide:

- **`BLOCKED MOSTLY ON <staller>` + `THE WAKER WAS STUCK IN <call>`**, with the longest blocks in **D** and the same length as `STALL_MS`: confirmed. Go to Step 5.
- **`NO LONG BLOCKS`** on every candidate victim, while Step 3 did print a STALL: the stall is real but it did not block that thread. Report the stall with the threads it *did* freeze (Step 3's list), and say the operator's thread was not among them.
- **`BLOCKED MOSTLY ON <other thread>` in a WAIT-class call** (`futex`, `poll`): the victim waits for a message or a lock from that thread, not for a stuck call. Hand to `11_priority_inversion` if the waker was runnable-but-not-running, otherwise run `wait_chain.py` on the waker.

```bash
BLOCK_MAX=<ms>  BLOCK_STATE=<S or D>  WAKER="<name tid prio>"  WAKER_CALL="<call> for <ms>"
```

**Next:** Step 5.

### Step 5. Rule out the lookalikes

**Goal:** check the other causes in the table in 1.3, using what you already have, plus one or two calls.

| Check | Where to look | A stall looks like this |
|---|---|---|
| Was the long call a driver sleeping? | Step 3, `sleep%` and the "sleeping inside" line | The STALL row has `sleep%` low and on-CPU or D high. A row with `sleep%` ~100 never reaches the verdict |
| Was it the tracer? | Step 3, "tracer's own activity (left out)" | The STALL thread is not `lttng-*`. The tracer's flushes are listed apart |
| Is the victim starved of CPU instead? | `runq_wait.py` (below) | NOT STARVED, or its runnable waits are small next to `BLOCK_MAX` |
| Are the frozen threads in D, not runnable? | `thread_top.py` (below): the `D` column of the frozen threads | Their `D` is non-zero during the stall; their `wait` (runnable) is not the story |
| Is it a lock, not a call? | Step 4, the waker's call | The waker was inside a WORK-class call (`clone`, `ioctl`, `write`), not `futex` |
| Did only the caller suffer? | Step 3, the `froze` clause and siblings | At least one other thread frozen or starved. If none, report a minor finding on the caller only |
| Trace holes? | the `trace holes:` line | Note it; the tools already left those intervals out |

The calls:

```bash
python3 $TOOLS/runq_wait.py $WORK/all.txt $VICTIM --top 8 $PM
python3 $TOOLS/thread_top.py $WORK/all.txt $SECS --sort max --top 30 $PM
```

- `runq_wait.py` on the victim should say **`NOT STARVED`** (or a NOTE that it outranks everything around it). If it says STARVED BY CROWD with long waits, both faults are present: report both, each with its own numbers (`8_cpu_starvation` for that one).
- In `thread_top.py`, the frozen threads show time in the **`D`** column and a `max_ms` of blocked time near `STALL_MS`. They are not `*` rows (they did not wait for a CPU; they were held).

If a check does not fit, say which one in your report, and treat the stall as unconfirmed.

**Next:** Step 6.

### Step 6. Identify the staller, the dependants and the process by name

**Goal:** describe who stalled, who paid, and how they are related, as precisely as the trace allows.

Everything you need is already printed; collect it:

- **The staller:** thread name (comm), tid, `prio`, from the stall table. With `pidmap.tsv`, its process: `grep -P "^$TID\t" $WORK/pidmap.tsv` (tid, pid, ppid, name). Note the **ppid chain** if the pid map shows the child it spawned (`sched_process_fork` gives `child_pid`).
- **The call:** name, flags decode, `STALL_MS`, `ONCPU_MS`, `D_MS`, `REPEAT`.
- **The dependants:** the `froze` list (name, tid, ms in D) and the STARVED siblings. With the pid map, confirm they share the staller's pid: that is what makes the memory-lock explanation hold.
- **The victim the operator cares about:** its name, tid, prio, `BLOCK_MAX`, `BLOCK_STATE`, and the fact that its block ended at the staller's exit (Step 4).

How to name things in the report, most specific first:

1. **Thread name + tid + the call + its length + its period** for the staller. Always.
2. **The process** (pid, process name) and that the frozen threads are its siblings, when the pid map shows it.
3. **The frozen threads** by name, tid and ms in D; the starved siblings by name.
4. **What the staller does**, inferred from the child it spawned (`sched_process_fork` → `execve` of `ping`, `sh`...) or from its name. Mark it Inferred.

There is no container to name. Do not report a `pid_ns`. The number inside an enum such as `prev_state = ( "TASK_UNINTERRUPTIBLE" : container = 2 )` is the enum's integer, not a cgroup.

**Next:** Step 7.

### Step 7. Write the RCA statement

**Goal:** a short statement that another person can check.

Template:

> Over **[span with events]** (UTC), thread **[staller comm, tid]** of process **[pid, name]** spent **[STALL_MS] ms** inside **[call]** (**[flags decode]**; **[ONCPU_MS] ms on-CPU + [D_MS] ms D**), **[REPEAT]**. While it was in there it held **[K] threads of the same process in D-state for up to [X] ms** (**[frozen names]**), and **[starved siblings]** got almost no CPU. Thread **[victim comm, tid]** was blocked for **[BLOCK_MAX] ms** in D each time and was released exactly when **[staller]** came out of **[call]**. We ruled out **[a driver sleeping / the tracer / CPU starvation / a lock]** because **[reason]**. We did not check **[what was not tested]**. Fix: **[see below]**.

The fix, by kind of call:

- **`clone` without `CLONE_VM` (a `fork`) from a big multithreaded process:** replace `fork()`+`exec` (`system()`, `popen()`) with **`posix_spawn()`** or `vfork()` (measured: 53 ms → 1.9 ms), or move the spawning out of the latency-critical process into a small helper process.
- **`ioctl` / `write` / `mmap` stalls:** shorten the call (smaller buffers, fewer pages, a non-blocking variant) or move it off the critical path to a thread nobody waits for.

Rules:

- Name the staller thread, the call, its length and period, the frozen threads, and the span.
- Give at least two independent pieces of evidence: the stall table and impact block (Step 3), and the victim's longest blocks ending at the staller's exit (Step 4).
- Mark each claim **Measured** (seen in the trace) or **Inferred** (reasoned from what you saw). "It holds the memory lock" is Inferred from the flags and the D-state siblings; the ms values are Measured. The fix is Inferred.
- **Say what the trace cannot show.** The symptom the operator reported (packet drops, late replies, a counter in the application) usually lives in an application-layer counter the kernel trace does not record. Your verdict is the **blocking cause**, not the drop itself. Say that plainly.
- Say what you did not test.

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects one cause: one thread stuck inside one WORK-class system call, and the threads that froze because of it. If a step points elsewhere, it stops and tells you so. It does not diagnose that other cause.
- It needs the system-call events. A trace recorded without `--syscall` cannot be judged.
- It sees the call's boundaries and the scheduler's view inside it (on-CPU, D, S). It does not see *which* kernel lock was held or *which* function was slow; "the memory lock" is inferred from `clone` flags plus siblings in D. A kernel function profile (ftrace `function_graph`, kprobes) is the next instrument if that matters.
- The `sleep% ≥ 90%` rule that sets driver waits aside is a first-pass number from five traces of one box family. A driver that spins briefly between sleeps could slip under it; check the `sleep%` column yourself when a call looks suspicious.
- The impact block needs a pid map or pid context to say "siblings"; without one it still says who was frozen and released.
- Trace holes (snapshot buffers, discarded events) are left out of every number, and the tools say so. A trace that is mostly holes gives weak numbers; say so.
- It does not see the application symptom. A line card counts its drops in its own software; the kernel trace holds the cause (the blocks), not the drop.

---

## Part 6. References

The mechanism:

1. `fork(2)`, `clone(2)` man pages (the `clone_flags`: `CLONE_VM`, `CLONE_VFORK`, `CLONE_THREAD`). https://man7.org/linux/man-pages/man2/clone.2.html
2. `posix_spawn(3)` and `vfork(2)` man pages (spawning without copying the address space). https://man7.org/linux/man-pages/man3/posix_spawn.3.html , https://man7.org/linux/man-pages/man2/vfork.2.html
3. Linux kernel source, `kernel/fork.c` (`dup_mmap()` copies the parent's memory map under `mmap_lock`). https://elixir.bootlin.com/linux/latest/source/kernel/fork.c
4. `ioctl(2)` man page (drivers may block in it; the semantics are the driver's). https://man7.org/linux/man-pages/man2/ioctl.2.html

The method, measuring calls and waits:

5. LTTng, *lttng-analyses* (per-thread system-call duration statistics, `lttng-syscallstats`). https://github.com/lttng/lttng-analyses
6. Trace Compass user guide, *System Call Latency Analysis* and *Critical Flow View* (wait analysis). https://archive.eclipse.org/tracecompass/doc/stable/org.eclipse.tracecompass.doc.user/LTTng-Kernel-Analysis.html
7. F. Giraldeau and M. Dagenais, *Wait analysis of distributed systems using kernel tracing*, IEEE TPDS 27(8), 2016 (what `wait_chain.py` computes, one level deep). https://publications.polymtl.ca/3078/
8. B. Gregg, *Off-CPU Analysis* (blocked time and wakeup stacks). https://brendangregg.com/offcpuanalysis.html

The tools and the trace format:

9. LTTng documentation (`--syscall` tracing; the `sched_*` kernel events; `prev_state` 2 = D). https://lttng.org/docs/
10. Babeltrace 2, `source.ctf.fs` component. https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What the tools measure

You do not need this to follow the steps. It explains the columns.

**Pairing a call to a thread.** A system-call event carries no thread id on a switch/router trace (there is no process context on the events). `syscall_stall.py` keeps track of who `sched_switch` put on each CPU and charges the entry to that thread; the exit is matched to the same thread's open call. On traces that do carry a context block, that tid is used directly. The `unmatched` column counts exits with no open entry (a call that began before the slice; the child's own exit from `clone`).

**Inside the call.** From the thread's scheduling intervals between entry and exit: **on-CPU** (running), **D** (switched out uninterruptible: a kernel lock, a disk), **sleep** (S-state and other sleeps). `sleep%` = sleep / wall. A WORK-class call with `sleep% ≥ 90` is "sleeping inside" and is set aside.

**`froze_ms`.** For each long call, the longest D-state block of any thread that was in D during the call and was woken by the caller (a `sched_waking` fired in the caller's context, during the call or within 2 ms after its exit). That is the memory-lock signature: the dependant could not proceed until the caller let go. Only D-blocks of at least `--min-ms` count.

**Ranking.** The stall table is sorted by `froze_ms` first, then by on-CPU + D. A call that held other threads is what costs latency; a call that only burned its own CPU comes after.

**Tracer exclusion.** Threads whose name starts with `lttng` (`lttng-consumerd`, `lttng-sessiond`) are the instrumentation. Their flushes (`sync_file_range2`, `splice`) show real D-state time, but they are not the system under test; they are printed on their own line and never ranked.

**Siblings starved.** With a pid map (or a pid context), each sibling's on-CPU time during the stall is compared with its average over the same length elsewhere in the slice; under 25% of that (when the expectation is ≥ 1 ms) is marked STARVED.

**Period.** The gaps between the top staller's instances of the same call give `n times, every ~Z s`; with two instances, `2 times, Z s apart`.

**`wait_chain.py`.** For the victim, every block (S or D) is attributed to the thread that woke it — the `sched_waking` event fires in the waker's context, so this is recorded, not guessed. When the slice holds system-call events, the waker's open call at that moment is named, with its own on-CPU + D share; when it holds interrupt events, a wakeup from a softirq or hardirq is named as such. Long blocks (≥ 10 ms) are reported apart from the total, because routine packet and timer waits are most of any thread's sleep.

**Holes and snapshot span.** A CPU with a runnable thread waiting for it cannot be silent, so an interval that overlaps a period with no event at all on its CPU for 0.5 s or more is lost data or a stalled CPU; the tools drop it and print a `trace holes:` line. When the events cover much less than the slice you cut, the tools divide by the span that holds events and say so.

## Appendix B. One solved case

This is how one investigation went (partner case 2, in rough, anonymised terms). Read your own slices by comparison with your own box, not against this story.

- **Trace:** a 4-core telecom line card, a 33 s capture in snapshot mode holding about 10 s of events, no lost events. No pid context on the events; `pidmap.py` mapped about 570 threads into 200 processes. The userspace is 32-bit, so every call is a `compat_syscall_*` event.
- **The complaint:** the card dropped a small share of packets under load. Raising the comms Tx thread's priority had already been tried (it sat at nice −20) and had not helped — blueprint 8 on this trace correctly says NOT STARVED.
- **Step 3:** `syscall_stall.py` set 300 `ioctl` calls aside as "sleeping inside" (the longest 7.3 s, 100% S — drivers waiting), and the tracer's own `sync_file_range2` flushes (175 ms of D) on their own line. The stall table's top rows were two `clone` calls by a status-polling thread, `0x100011` (a full fork): 56.6 ms and 69.6 ms wall, about 47 ms on-CPU each, 2.3 s apart. Each had frozen three threads in D for up to 49 ms — the comms Tx thread (46.8 and 48.5 ms in D), a timer thread and a monitor thread — and three to five siblings of the same process got almost no CPU meanwhile. Verdict **STALL** on that `clone`.
- **Step 4:** `wait_chain.py` on the comms thread: 100% of its long-block time was released by the status thread, and the longest blocks (48.5 ms and 46.8 ms, both in D) sat inside that thread's `clone` call of 49–53 ms, 94% overlap. The rest of its sleep — thousands of short blocks — came from `softirq NET_RX`: a packet path, as expected.
- **Step 5:** the comms thread was not starved (`runq_wait.py`: longest runnable wait 5.6 ms). The frozen threads showed D-state time, not runnable waits. The `clone`'s on-CPU share ruled out a sleeping driver; the staller was not the tracer.
- **Step 6:** the pid map put the status thread and the comms thread in the same process (about 190 threads). The child the fork produced ran `sh` and then `ping`: the status thread was calling `system("ping ...")` to test reachability.
- **Check afterwards:** the engineers had measured the same `clone` at 53.6 ms with a trace viewer, every 7–8 s under load, and found the `system()` call in the status code. Their fix was `posix_spawn` (`clone_flags` `0x4111`, 1.9 ms), and the packet loss went to zero. Raising the comms thread's priority could never have helped: it was not waiting for a CPU, it was held by a kernel lock.
- **The negatives:** on four other cards of the same family the tool found no stall of this kind — only `ioctl` sleeps (1–30 s, 100% S) and the tracer's flushes, both set aside. On one of them it found a genuine but unrelated stall: a 4-byte `write` to a device file blocking 364 ms in D, six times, every 4.3 s, freezing the system journal thread for up to 249 ms. Real, reported, and not on the comms path.
