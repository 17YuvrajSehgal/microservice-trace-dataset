# Blueprint: finding a thread starved of CPU on a bare-metal host from a kernel trace

| | |
|---|---|
| Problem class | Latency (scheduling) |
| Root cause this blueprint confirms or rejects | One latency-sensitive **thread** is ready to run but keeps waiting for its CPU, because too many threads of the **same or higher priority** share that core. There is no cgroup and no quota: this is priority competition on one core |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder |
| Also allowed | The list of event types the trace holds (read from `metadata`); the box's CPU topology (SMT siblings) if you know it |
| Not used | Logs, metrics, application counters (packet drops, late replies), request traces |

**How to use this blueprint.** Read Part 1 once, to learn what the fault is and what it looks like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

**When to reach for this instead of `svc_cpu_cap` or `noisy_neighbor`.** Those two blueprints are about containers: a cgroup quota (blueprint 1) or a co-tenant container taking the host (blueprint 2). A switch or router line card, or any bare-metal box, has **one pid namespace and no containers**. There, the unit of blame is a thread, and the usual CPU fault is one thread losing its core to a crowd of equal-priority threads while other cores sit idle. Use this blueprint when the trace has one `pid_ns` everywhere (or none), and the question is "why is this thread late?".

> **Honest status.** Calibrated on two labelled line-card traces of one real fault (partner case 1: the comms Tx thread at nice 0 starved by a same-priority crowd on its core; the engineers' fix was nice −10), plus one negative control (a third card where the same thread had already been raised to nice −20 and the tool correctly says NOT STARVED). The thresholds in Step 4 are a first pass from those three traces. Treat a verdict on a very different box (many cores, real-time threads everywhere) as needing a baseline.

---

## Part 1. Background

### 1.1 What the fault is

Linux shares a CPU between ready threads with the **CFS** scheduler (the normal, time-sharing class). Each thread has a **nice** value from −20 to 19, and each nice value maps to a **weight**. The CPU is split between the ready threads **in proportion to their weights**. Some weights:

| nice | weight | kernel prio | what LTTng prints |
|---|---|---|---|
| −20 | 88761 | 100 | `prio = 0` |
| −10 | 9548 | 110 | `prio = 10` |
| 0 | 1024 | 120 | `prio = 20` |
| 19 | 15 | 139 | `prio = 39` |

Each nice step is about 1.25×. So a thread at nice −10 gets about **9× the CPU share** of a thread at nice 0 on the same core. Real-time threads (`SCHED_FIFO` / `SCHED_RR`) sit above all of CFS: they run whenever they are ready, for as long as they want.

**How to read a priority in the trace.** LTTng prints `prio` as the kernel priority minus 100. So `20` means kernel 120 = nice 0, `10` means nice −10, and a **negative** number is a real-time thread (`-64` = real-time priority 63). The tools print this for you as `120 (nice 0)`, `110 (nice -10)`, `RT 63`.

The fault: a thread that must answer quickly (send a packet, serve a timer, poll a device) sits at nice 0 on a core where **many other threads also sit at nice 0**. Every time it wakes up it joins a queue of equals. CFS gives each of them a fair slice, so the thread waits — a few ms each time, tens of ms at the worst — before it runs. Meanwhile other cores can be mostly idle: the thread is pinned, or the scheduler keeps placing it on that core. Nothing is "saturated" in a host-level view. The box looks healthy. Only the one thread is late.

What the engineers change to fix it: raise the thread's priority (nice −10, or a real-time class), or move the crowd to other cores. The trace does not record the nice value directly as a setting; you read it from the `prio` fields on every `sched_switch`.

### 1.2 What it looks like in a kernel trace

For the starved thread (the **victim**):

- **Runnable waits.** It is woken (`sched_waking` / `sched_wakeup`) and then waits before its `sched_switch` in; or it is switched out while still runnable (`prev_state` 0 or the 0x100 flag) and waits to come back. Single waits of 10–30 ms appear many times per minute. These are *waits for a CPU*, not sleeps.
- **Small run share.** The victim uses a few percent of a core. It is not a hog.
- **One core.** It is seen on one CPU only ("pinned or always placed on cpu N").
- **No disk wait, no long sleeps.** Its blocks are short and come from interrupts (packets, timers). If its long blocks name another thread, that is a different fault — Step 5.

For the core it sits on:

- **A crowd.** Dozens of distinct threads at exactly the victim's priority ran on that core. While the victim waited, those threads held the core.
- **That core busier than the rest.** Often far busier (measured: 86% versus 31–47% on the other cores).

For the rest of the box:

- **Other cores idle** a large share of the time the victim waited. That is what tells placement from a full host.

### 1.3 Problems that look similar

Several causes make a thread wait. This blueprint must tell them apart. You will use this table in Step 5.

| Cause | What the kernel trace shows | How it differs from starvation by a crowd |
|---|---|---|
| **Starved by a crowd (this fault)** | Victim waits runnable behind many same-priority threads on its core; small run; other cores idle | — |
| Starved by a higher-priority thread | One real-time or better-priority thread holds the core while the victim waits | `runq_wait.py` says **STARVED BY HIGHER PRIORITY** and names it. The fix is different: move or shorten that thread, or give the victim a real-time class |
| Whole host saturated | Every core busy ≥ 90%; many threads wait on every core | The tool says **HOST SATURATED**. Hand to `2_noisy_neighbor` (cpu_saturation). A crowd on one core leaves the other cores idle |
| Noisy neighbour (container) | One co-tenant container takes the host | Needs containers (`pid_ns` differs). On a one-namespace box there is no co-tenant |
| CPU cap / quota | Burst-and-freeze rhythm, per-period ceiling, CPUs idle during the waits | Needs a cgroup. On a bare-metal box there is none; the waits here are irregular and the core is busy with others |
| The thread is **blocked**, not runnable | Long `S` or `D` intervals; `wait_chain.py` names the thread that releases it | Blocked is not waiting for a CPU. A sibling's long system call holding a lock is `9_syscall_stall` |
| Interrupt work on its core | `ksoftirqd/N` and softirq time high on that core | `10_irq_imbalance`. `thread_top.py` shows `kthr%`; if it is large, run that blueprint too |
| The victim already outranks the crowd | Victim at nice −20 waits a few ms behind nice-0 threads | Those waits are CFS slice granularity, not starvation. Raising its priority cannot help. The tool prints a NOTE and says NOT STARVED |
| Trace holes | 1–9 s "waits" that overlap a period with no events on that CPU | Lost trace data or a stalled CPU, not scheduling. The tools drop them and print a `trace holes:` line |

---

## Part 2. What you need

| Input | Why |
|---|---|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/` | Everything comes from here. `metadata` holds the clock and the event types. `index/` makes cutting time slices fast |
| `sched_switch` and `sched_waking` (or `sched_wakeup`) events | To measure running, runnable-waiting and sleeping time per thread, and the `prio` of every thread |
| `sched_process_fork` and `lttng_statedump_process_state`, if present | To group threads into processes. Without them (and without a pid context on the events) one row = one thread, which is still enough |
| A fault-free trace of the same box, if you have one | Starvation is usually steady, so there is often no quiet stretch inside the trace. A second trace is the baseline |
| `babeltrace2`, `python3`, GNU `date` | To read the trace and run the scripts |
| The scripts below, all in one folder | `tracelib.py` must sit next to the others: they import it |

The scripts:

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks. Reads only the index, so it takes seconds | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `idx_slice.py` | Copies only the packets that cover a time window into a small trace | used by `extract_slice.sh` |
| `extract_slice.sh` | Cuts one time slice and keeps only the events you name | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> '<events regex>'` |
| `pidmap.py` | Thread → process map from the trace's start-of-session state dump (tid, pid, ppid, name) | `pidmap.py <trace_dir> [--out FILE]` |
| `thread_top.py` | Every thread's time budget (run, runnable wait, sleep) with its priority and the CPUs it ran on, plus a per-CPU table of how crowded each core is at each priority class | `thread_top.py <slice> <secs> [--sort wait\|run\|max\|wakeups] [--top N] [--cpu N] [--pidmap FILE]` |
| `runq_wait.py` | **The decisive tool:** one thread's runnable waits, who held its core during each wait, the competitors ranked by priority class, and the verdict | `runq_wait.py <slice> <victim tid\|name> [--top N] [--min-ms X] [--pidmap FILE]` |
| `wait_chain.py` | One thread's **blocked** time: who woke it, and what the waker was doing. Used here to make sure the victim waits for a CPU and is not simply blocked | `wait_chain.py <slice> <victim tid\|name> [--top N] [--pidmap FILE]` |
| `sched_budget.py` | Per-process time budget, the older tool from blueprints 1–7; same numbers summed per process | `sched_budget.py <slice> <secs> [pid]` |
| `cpu_hogs.py` | Who used the CPU, and who held it while the victim waited, summed per process name | `cpu_hogs.py <slice> <secs> [victim_pid]` |
| `tracelib.py` | The shared parser the tools import. Not run by hand | `tracelib.py --selftest` |

The slice pattern this blueprint uses (the scheduling trio plus fork and state dump, so threads can be grouped into processes):

```bash
SCHEDEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state'
```

---

## Part 3. Setup

Run this block first, in every new terminal. Put your own paths in the first three lines.

```bash
TRACE=/path/to/trace       # the folder that holds `metadata`, `index/` and the channel files
TOOLS=/path/to/scripts     # the folder that holds the scripts (tracelib.py included)
WORK=/path/to/scratch      # an empty folder for slices and notes
SCHEDEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state'

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,idx_slice.py,extract_slice.sh,pidmap.py,thread_top.py,runq_wait.py,wait_chain.py,tracelib.py} > /dev/null && echo "scripts found"
```

Both lines must print OK.

- If `metadata` is missing, `TRACE` points to the wrong folder. Look one or two levels deeper (`kernel/`, `kernel/kernel/`).
- If `index/` is missing, the method still works, but cutting slices is slow.

---

## Part 4. Procedure

### Step 1. Check the trace

**Goal:** know when the trace starts and ends, whether it is healthy, and which events it holds.

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt

DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
SECS=$(awk '/^duration/ {print int($3)+2}' $WORK/summary.txt)
echo "DAY=$DAY TRACE_START=$TRACE_START SECS=$SECS"

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -x -E 'sched_(switch|waking|wakeup)|sched_process_fork|lttng_statedump_process_state' $WORK/event_names.txt
```

Read it:

- **Health.** `lost events` and `time gaps` tell you where data is missing. Do not panic over them: the tools below detect holes on their own and leave those stretches out. But write them down for the report.
- **Snapshot captures.** Line cards often record in snapshot mode: the trace spans 60–180 s but holds events for only the last 6–30 s. The tools print `note: events cover only X s of the Y s slice (snapshot-style trace); shares below use X s` and divide by the real span. Read the shares, not the slice length.
- If `sched_switch` is missing, or both `sched_waking` and `sched_wakeup` are missing, **stop**. Report that the trace has no scheduling events.
- If the metadata grep above lists CTF 1.8 text instead of JSON (older LTTng), run `grep -a -o 'name = "[^"]*"' $TRACE/metadata | sort -u` instead.

**Next:** Step 2.

### Step 2. Cut one slice over the whole trace, and map the threads

**Goal:** one decoded slice that holds every scheduling event, and a thread → process map.

Do **not** hunt for a window first. Starvation by a crowd is **steady**: it is there as long as the load is. A line-card trace is 30–180 s long, so one slice over the whole span is cheap and sees everything.

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $TRACE_START $SECS $WORK/all.txt "$SCHEDEV"
python3 $TOOLS/pidmap.py $TRACE --out $WORK/pidmap.tsv
```

- `extract_slice.sh` prints the slice bounds and the line count. A few hundred thousand to a few million lines is normal.
- `pidmap.py` prints how many threads and processes it mapped. If it maps none (no state dump in the trace), the tools still work: one row = one thread.

```bash
PM="--pidmap $WORK/pidmap.tsv"    # leave empty if pidmap.py mapped nothing
```

**Next:** Step 3.

### Step 3. Find the candidate victim and its crowd

**Goal:** name the thread that waits for a CPU, and see how crowded its core is.

```bash
python3 $TOOLS/thread_top.py $WORK/all.txt $SECS --sort wait --top 30 $PM
```

It prints three things:

1. **A header**: CPUs, slice seconds, the switch count, an `identity:` line (`comm from sched_switch; no pid context (one row = one thread)` or `pid context present`), the `prev_state` codes seen, the snapshot note and the `trace holes:` line when they apply.
2. **A per-CPU table**: `cpu  busy%  threads  RT  <120  =120  >120  kthr%  top occupants`. `threads` is how many distinct threads ran on that CPU; the four columns after it say how many of them were real-time, better than nice 0, exactly nice 0 (prio 120), or worse. `kthr%` is the `ksoftirqd` + `kworker` share.
3. **A per-thread table**, top N by waiting: `tid  pid  name  prio  cpus  run  wait  preempt  wakewait  S  D  >=10ms  >=50ms  max_ms  wakeups`. `run`, `wait`, `S`, `D` are average threads over the slice (1.00 = the whole time). `wait` is runnable time only; `preempt` and `wakewait` split it (switched out runnable vs woken and waiting). A `*` marks a **candidate victim**: 3 or more waits of 10 ms, or one wait of 25 ms or more — the same bars `runq_wait.py` uses for MILD and STARVED. How much the row ran does not matter.

Read it:

- **The candidates are every `*` row on the crowded core** — run the table once more with `--sort max` so a `*` row low in the wait order is not missed — plus the row with the most `wakeups` if it has any wait of 10 ms. Do not pick by `wait` share and do not stop at two. Measured twice on the same card: the agent tested the thread with the largest wait share (26%, longest 17 ms, MILD) and skipped the comms thread one row below it (9%, 7 waits ≥ 10 ms, longest 33 ms, STARVED BY CROWD) — the engineers' victim. A thread that runs a lot and waits a lot is a busy thread only when its waits are short.
- **Several candidates on one core are all victims.** A crowded core starves every latency-sensitive thread on it, and the trace cannot tell which one carries the business symptom (packet drops, late replies). Run `runq_wait.py` on each candidate on that core and name every one that comes back STARVED; the operator knows which one matters. Measured: the agent named the sibling with the larger wait share (26% of its time) and put the comms thread (9%, the one with the drops) in the crowd list - both were victims of the same crowd.
- Go to that CPU's row in the per-CPU table. **The crowd** is the `=120` count (or the count in the victim's own priority class). Measured on the fault: 75–99 threads at `=120` on the victim's core, against 20–50 on the others.
- Compare `busy%` across CPUs. The victim's core is usually the busiest; the others have room.
- `kthr%` large on that core means interrupt work is part of the story: note it for `10_irq_imbalance`.
- Threads with `max_ms` of hundreds or thousands of ms are **not** candidates if a `trace holes:` line was printed: those waits overlap lost data and the newer tools already leave them out. If you see such a row with no holes line, it is a real, rare event; run `runq_wait.py` on it too.

Write down:

```bash
VICTIM=<tid or thread name>     # the candidate (a name matches every thread with that comm)
VCPU=<cpu>                       # the core it sits on
CROWD=<count>                    # threads at the victim's priority on that core, from the per-CPU table
```

**Discipline.** One `runq_wait.py` call per `*` row on that core (usually two to four). Never drop a `*` row because another candidate looked worse.

**Next:** Step 4.

### Step 4. Prove or reject the starvation (the decisive step)

**Goal:** measure the victim's runnable waits, see who held its core during them, and read the verdict.

```bash
python3 $TOOLS/runq_wait.py $WORK/all.txt $VICTIM --top 12 $PM
```

It prints, in order:

1. **Identity**: name, tid(s), prio, `pinned or always placed on cpu X` (or `ran on cpus a-b`), `run R%, wait W% of the X s that hold events`.
2. **Wait distribution**: for woken waits, preempted waits and all: `count  p50  p90  p99  max  total  share`.
3. **Longest waits**: `start  ms  kind  cpu  idle-other  occupants of that cpu` — for each long wait, the threads that held the core meanwhile (name, tid, prio, ms) and how idle the other cores were during it.
4. **Competitors**: every thread that held the victim's core while it waited, ranked by ms, with its priority class relative to the victim (`same` / `better` / `worse`), then `by class: same .. ms, worse .. ms, better .. ms` and `N distinct same-priority competitors`.
5. An optional **NOTE** line, then the **VERDICT** line, a **second line** about the other CPUs, and a **FIX HINT**.

The verdict strings are fixed. Quote the one you get:

| Line | Meaning |
|---|---|
| `VERDICT: STARVED BY CROWD: same-or-worse-priority threads held cpu X for M ms (P% of its waiting); N distinct threads at prio <label>` | **This fault.** The victim's waits are long and frequent, and ≥ 60% of its waiting time was under threads of its own class or worse. `N` is the crowd that actually held the core |
| `VERDICT: STARVED BY HIGHER PRIORITY: <name> tid T prio <label> held cpu X for M ms (P%)` | Starved, but by a real-time or better-priority thread. Different fix (Step 5) |
| `VERDICT: MIXED - same-or-worse P1%, higher-priority P2%, cpu idle/other P3% of its waiting (...)` | Starved, but no single class dominates. Report all three shares |
| `VERDICT: STARVATION PRESENT BUT MILD - waits are P% of its time, p99 X ms, longest M ms, N waits >= 10 ms; the crowd on cpu X is K distinct same-prio threads. Report it; call it the fault only if the operator named this thread or its deadline is under M ms` | Real waits, under the bar for an unprompted fault call. Write the numbers down; it is the verdict only when the operator named this thread |
| `D-state: P% of its time, longest block M ms - its biggest delays are D-state blocks, not runnable waits - run wait_chain.py (9_syscall_stall) before blaming the crowd` (after the identity line) | The thread is mostly **blocked**, not waiting for a CPU. Go to Step 5 (a) now |
| `VERDICT: NOT STARVED - waits are P% of the slice, p99 X ms, longest M ms, N waits >= 10 ms` | Below the thresholds. **Stop** on this candidate |
| `VERDICT: VICTIM NOT SEEN - '<x>' never appears in this slice` | Wrong name or tid. Check `thread_top.py` |
| `NOTE: the victim already outranks the threads it waited behind (prio A vs B): raising its priority will not help; the remaining waits are CFS slice granularity (max X ms)` | Printed before the verdict when the threads it waited behind are **worse** than it. Then CROWD is never given |
| `OTHER CPUS WERE IDLE K% OF THE TIME IT WAITED (placement/affinity, not a full host)` | Second line. The box had room; the victim was placed badly |
| `HOST SATURATED: all CPUs busy >= 90%` | Second line. Not this fault; hand to `2_noisy_neighbor` |
| `other CPUs idle K% while it waited; busy over the slice: cpu0 ..%, ...` | Second line when neither of the above holds |
| `trace holes: ...` | Waits over lost data were left out. Say so in the report |

**The thresholds, and where they come from.** A thread is **starved** (the fault, unprompted) when its longest runnable wait is **≥ 25 ms** AND its runnable waits are **≥ 6%** of the time that holds events. It is **present but mild** when the longest wait is ≥ 10 ms or it had ≥ 3 waits of 10 ms or more without reaching that bar. The class split needs ≥ 60% of the waiting time under one class. Why the bar is this high: starvation is relative to a deadline the trace does not know; on the healthy control card the app thread waits 20 ms, 23 times, ~5% of its time - nobody calls that a fault - while the two real cases sit at 30-33 ms and 9-10%. Calibration (partner case 1, anonymised):

- Two line-card traces, 4 cores each, the comms Tx thread at nice 0 on core 2: longest waits **30–33 ms**, **9–10%** of its time waiting, 7 and 26 waits ≥ 10 ms, **92–93%** of the waiting under same-priority threads, **66–84** distinct same-priority competitors, the other cores idle **45–63%** of that time. Verdict STARVED BY CROWD. The engineers' fix was nice −10 on that thread.
- A third card where the same thread had already been raised to nice −20: longest wait **5.6 ms**, 0 waits ≥ 10 ms, 4.6% waiting, and every thread it waited behind was worse than it. Verdict NOT STARVED with the NOTE. The engineers had also found that raising it did not help there; the real cause was a sibling's long system call (blueprint 9).

Decide:

- **STARVED BY CROWD** with `OTHER CPUS WERE IDLE`: this fault. Write down the numbers and go to Step 5.
- **STARVED BY CROWD** with `HOST SATURATED`: the whole box is short of CPU. Hand to `2_noisy_neighbor` (cpu_saturation) and **stop**.
- **STARVED BY HIGHER PRIORITY**: go to Step 5; the fix is different and the report must name that thread.
- **MIXED**: go to Step 5 and report the shares; say the cause is not single.
- **NOT STARVED**: this candidate is fine. Try the next candidate from Step 3. If none is starved, report "no CPU starvation found" and **stop**. Do not write "no fault": this blueprint looks for one cause only.

```bash
WAIT_MAX=<ms>  WAIT_SHARE=<%>  WAIT_GE10=<count>
CROWD_MS=<ms>  CROWD_SHARE=<%>  CROWD_N=<distinct same-priority competitors>
IDLE_ELSEWHERE=<%>
TOP_COMPETITORS="<name tid prio> ; <name tid prio> ; <name tid prio>"
```

**Next:** Step 5.

### Step 5. Rule out the lookalikes

**This step is not optional.** Measured on the partner traces: run stand-alone, this blueprint called "starvation" on a thread whose long delays were really D-state freezes caused by a sibling's `clone` (blueprint 9's fault), and on the healthy control card's app thread (20 ms waits that nobody considered a fault). Two rules before any STARVED verdict: (a) run `wait_chain.py` on the victim - if its long blocks name a waker and `THE WAKER WAS STUCK IN <syscall>` prints, the waits are a consequence of that stall: hand to `9_syscall_stall` and say so; (b) if `runq_wait.py` printed `STARVATION PRESENT BUT MILD`, report the numbers but do not call it the fault unless the operator named this thread or its deadline is shorter than the longest wait.

**Goal:** check the other causes in the table in 1.3, using what you already have, plus one call.

| Check | Where to look | Starvation by a crowd looks like this |
|---|---|---|
| Is the whole host saturated? | Step 4, second line | `OTHER CPUS WERE IDLE K%` with K large, or at least other cores well below 90% |
| Is it one higher-priority thread? | Step 4, competitors `better` class | `better` is a small share. If the verdict said HIGHER PRIORITY, name that thread and switch the fix |
| Does the victim outrank the crowd? | Step 4, the NOTE line | No NOTE. If there is one, raising priority is not the fix; look for another cause |
| Is the victim blocked rather than runnable? | `wait_chain.py` (below) | Its blocks are short and come from `softirq NET_RX` / `softirq TIMER` / interrupts. No long block names another thread |
| Is interrupt work on its core? | Step 3, per-CPU `kthr%` on `VCPU` | Small. If large, run `10_irq_imbalance` as well: the crowd may be `ksoftirqd/N` |
| Trace holes? | the `trace holes:` line | Note it; the verdict already excludes those waits |

The one call:

```bash
python3 $TOOLS/wait_chain.py $WORK/all.txt $VICTIM --top 12 $PM
```

It prints the victim's blocked time (total, share, count, p50, max), the blocked time **by waker** (who woke it, and the waker's system call at that moment), its longest blocks, and verdict lines.

- **`NO LONG BLOCKS (max X ms; ...)`** together with **`BLOCKED ON INTERRUPTS/SOFTIRQ (network or timer driven)`**: the victim sleeps only for its normal packets and timers. Its problem is waiting for the CPU, not being blocked. Starvation stands.
- **`BLOCKED MOSTLY ON <thread>`** with **`THE WAKER WAS STUCK IN <syscall> ...`**: the victim is being held by another thread's long system call. That is `9_syscall_stall`, not this fault. Hand it over and say so. (Both can be true at once on a busy card: report both, each with its own numbers.)

If a check does not fit, say which one in your report, and treat the starvation as unconfirmed.

**Next:** Step 6.

### Step 6. Identify the victim and the crowd by name

**Goal:** describe the victim, its core, and the crowd as precisely as the trace allows.

Everything you need is already printed; collect it:

- **The victims:** every candidate on that core that `runq_wait.py` called STARVED — thread name (comm), tid, `prio` label, its core, wait share and longest wait, from each identity line. Put all of them in `victim_thread` (comma-separated), the one with the largest wait share first, and say in `what_is_wrong` that they share one crowd. With `pidmap.tsv`, their process (pid and process name): `grep -P "^$TID\t" $WORK/pidmap.tsv`.
- **The crowd:** the top competitors from Step 4 (name, tid, prio, ms), the distinct count, and the per-CPU `=120` count from Step 3. Group them by process with the pid map; often most of the crowd are threads of the **same process** as the victim. `culprit_thread` is the crowd - the top competitor(s) by name, or "the N nice-0 threads on cpu X" - and is **never one of the victims**; a verdict that names the same thread as culprit and victim is wrong by construction.
- **The core:** `VCPU`, its `busy%` from Step 3 against the other cores, and `IDLE_ELSEWHERE`.

How to name things in the report, most specific first:

1. **Thread name + tid + priority + core** for the victim: "thread `<comm>` (tid `<n>`, prio 120 (nice 0)) on cpu `<c>`". Always.
2. **The process it belongs to**, from the pid map, when known.
3. **The competitors** by name, tid and priority, and how many distinct ones there were.
4. **What the victim does**, inferred from its wakers in `wait_chain.py` (woken by `softirq NET_RX` = a packet path; by `softirq TIMER` = a periodic job). Mark it Inferred.

There is no container to name. Do not report a `pid_ns`. The number inside an enum such as `prev_state = ( "TASK_INTERRUPTIBLE" : container = 1 )` is the enum's integer, not a cgroup.

**Next:** Step 7.

### Step 7. Write the RCA statement

**Goal:** a short statement that another person can check.

Template:

> Over **[span with events]** (UTC), thread **[comm, tid, prio]** on **cpu [N]** was **starved of CPU by a crowd of same-priority threads**: its runnable waits reached **[max] ms** (**[share]%** of its time, **[count]** waits ≥ 10 ms), and **[crowd share]%** of that waiting was under **[N] distinct threads at prio [label]** (mainly **[top competitors]**), while the other cores were idle **[K]%** of that time. We ruled out **[host saturation / a higher-priority thread / being blocked / interrupt work]** because **[reason]**. We did not check **[what was not tested]**. Fix: **raise the victim's priority (nice −10 = CFS weight 9548 vs 1024 at nice 0, ~9×) or move the crowd off that CPU.**

For a HIGHER PRIORITY verdict, replace the mechanism with "held off its core by **[thread, tid, prio]** for **[ms] ([%])**" and the fix with **reduce or move the RT/higher-priority thread, or give the victim a real-time class**.

Rules:

- Name the victim thread, its core, the crowd, and the span.
- Give at least two independent pieces of evidence: the wait distribution (Step 4), the competitors and the idle-elsewhere share (Step 4), the per-CPU crowd count (Step 3).
- Mark each claim **Measured** (seen in the trace) or **Inferred** (reasoned from what you saw). What the victim *does* is Inferred. The fix is Inferred.
- **Say what the trace cannot show.** The symptom the operator reported (packet drops, late replies, a counter in the application) usually lives in an application-layer counter the kernel trace does not record. Your verdict is the **scheduling cause**, not the drop itself. Say that plainly.
- Say what you did not test.

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects one cause: one thread starved of its core by same-or-higher-priority threads. If a step points elsewhere, it stops and tells you so. It does not diagnose that other cause.
- It cannot read the nice value as a setting, the thread's affinity mask, or the SMT topology. It reads priorities from `sched_switch` and placement from where the thread was seen.
- It works on one slice over the whole trace. A fault that lasts under a second inside a long, otherwise healthy trace is diluted; cut a shorter slice around the time of interest and run Steps 3–4 again.
- The thresholds (25 ms and 6% for the fault; 10 ms or 3 waits for "mild"; 60% class share; 80% outrank) come from four labelled traces of one box family: two faults, one healthy control, one card whose waits were a stall's consequence. They are first-pass. On a box with many cores or many real-time threads, compare with a healthy trace of the same box before you commit.
- It does not see the application symptom. A line card counts its drops in its own software; the kernel trace holds the cause (the waits), not the drop.
- Trace holes (snapshot buffers, discarded events) are left out of every number, and the tools say so. A trace that is mostly holes gives weak numbers; say so.
- Without a pid context, a state dump, or fork events, threads cannot be grouped into processes. The verdict still names the thread, which is what the fix needs.

---

## Part 6. References

The scheduler and priorities:

1. Linux kernel documentation, *CFS Scheduler* (the nice-to-weight table, fair sharing). https://docs.kernel.org/scheduler/sched-design-CFS.html
2. `sched(7)` man page (scheduling policies, nice, `SCHED_FIFO`, priority ranges). https://man7.org/linux/man-pages/man7/sched.7.html
3. Linux kernel documentation, *CPU isolation* (`isolcpus`, `nohz_full`, `irqaffinity`: the standard fixes for keeping a latency-sensitive thread's core clear). https://docs.kernel.org/admin-guide/cpu-isolation.html

The method, measuring waits for a CPU:

4. LTTng, *lttng-analyses* (scheduler latency = `sched_waking` → `sched_switch`; `lttng-schedtop`, `lttng-cputop`). https://github.com/lttng/lttng-analyses
5. B. Gregg, bcc `runqlat` (run-queue latency per thread: wakeup → on-CPU, and preempt → resume). https://github.com/iovisor/bcc/blob/master/tools/runqlat_example.txt
6. B. Gregg, *Off-CPU Analysis* (telling runnable waits from blocked time). https://brendangregg.com/offcpuanalysis.html
7. F. Giraldeau and M. Dagenais, *Wait analysis of distributed systems using kernel tracing*, IEEE TPDS 27(8), 2016 (what `wait_chain.py` computes, one level deep). https://publications.polymtl.ca/3078/

The tools and the trace format:

8. LTTng documentation (the `sched_*` kernel events; the `prio` field is kernel priority − 100). https://lttng.org/docs/
9. Babeltrace 2, `source.ctf.fs` component. https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What the tools measure

You do not need this to follow the steps. It explains the columns.

**Two kinds of runnable wait.** A thread waits for a CPU in two situations, and the tools keep them apart:

- **wake-wait** (`wakewait`, kind `woken`): from `sched_waking` / `sched_wakeup` of the thread until its `sched_switch` in. This is the classic run-queue latency (`runqlat`).
- **preempt-wait** (`preempt`, kind `preempted`): the thread was switched out while still runnable (`prev_state` 0, or the 0x100 "preempted" flag) and waits until it is switched back in.

`wait` is the sum. Sleeping (`S`, `D`) is never counted in it: a sleeping thread does not want a CPU.

**Per-CPU priority classes.** For each CPU, `thread_top.py` counts the distinct threads that ran there and sorts them by LTTng `prio`: negative = `RT`; 0–19 = `<120` (better than nice 0); exactly 20 = `=120` (nice 0); 21–39 = `>120` (worse). The victim's class is where the crowd lives.

**Occupants during a wait.** For each of the victim's waits, `runq_wait.py` looks at the run intervals on the CPU the victim waited for (its `target_cpu` for a wake-wait; the CPU it was switched out of for a preempt-wait) and charges each occupant the overlap. `same` / `better` / `worse` compare the occupant's `prio` with the victim's. `idle-other` is the idle time on the other CPUs during that wait, as a share of (wait × other CPUs).

**Holes.** A CPU with a runnable thread waiting for it cannot be silent: it would switch to that thread. So a wait that overlaps a period with no event at all on that CPU for 0.5 s or more is lost trace data (snapshot buffers, discarded events) or a stalled CPU. Both tools drop such intervals from every number and print a `trace holes:` line.

**Snapshot span.** When the events cover much less than the slice you cut, the tools divide by the span that holds events and say so. Otherwise a 16% run share reads as 2%.

**Enum states.** Some traces print `prev_state` as a number (`256`), others as an enum (`( "TASK_INTERRUPTIBLE" : container = 1 )`). The tools read both. The `container` number is the enum's integer, nothing more.

## Appendix B. One solved case

This is how one investigation went (partner case 1, in rough, anonymised terms). Read your own slices by comparison with your own box, not against this story.

- **Trace:** a 4-core telecom line card, a 70 s capture in snapshot mode holding about 6.5 s of events, no lost events. No pid context on the events; `pidmap.py` mapped about 570 threads into 200 processes.
- **Step 3:** `thread_top.py` showed core 2 with about 80 distinct threads, about 75 of them at prio 120 (nice 0), against 20–30 per core elsewhere. Core 2 was the busiest core. The comms Tx thread sat at nice 0, on core 2 only, with a small run share and several waits above 10 ms.
- **Step 4:** `runq_wait.py` on that thread: 9% of its time waiting, longest wait 33 ms, 7 waits ≥ 10 ms. 93% of that waiting was under same-priority threads — a polling thread, a status thread, a receive thread, all at nice 0, all of the same process — 66 distinct ones. The other three cores were idle 63% of the time it waited. Verdict **STARVED BY CROWD**, second line **OTHER CPUS WERE IDLE 63%**.
- **Step 5:** `wait_chain.py`: no long blocks; 100% of its wakeups came from `softirq NET_RX` — it is a packet path, and it was waiting for the CPU, not blocked. `kthr%` on core 2 was 0. No real-time thread held the core for more than a few percent.
- **A second card** of the same family, a 27 s span of events: the same thread, 10% waiting, longest 30 ms, 26 waits ≥ 10 ms, 92% under 84 same-priority threads, core 2 at 86% busy against 31–47% on the others. Same verdict.
- **The negative control:** a third card where the thread had already been raised to nice −20. Longest wait 5.6 ms, no wait ≥ 10 ms; every thread it waited behind was at nice 0, worse than it. The tool printed the NOTE and **NOT STARVED**. That matched the engineers: raising the priority there had not helped, because the real cause was a sibling thread's 50 ms `clone` (blueprint 9).
- **Check afterwards:** the engineers' fix for the first two cards was the one the tool suggests — raise the thread to nice −10. The symptom (packets dropped by the card's own traffic shaper) was counted in application software; the kernel trace showed the cause, not the drop.
