<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a thread starved of CPU on a bare-metal host

| | |
|---|---|
| Problem class | Latency (scheduling) |
| Root cause this blueprint confirms or rejects | One latency-sensitive thread is ready to run but keeps waiting for its CPU, because too many threads of the same or higher priority share that core. There is no cgroup and no quota: this is priority competition on one core. |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder. Also allowed: the box's CPU topology (SMT siblings) if you know it |
| Not used | Logs, metrics, application counters (packet drops, late replies), request traces |

**When to use this.** A bare-metal box has one pid namespace and no containers. There, the unit of blame is a thread, and the usual CPU fault is one thread losing its core to a crowd of equal-priority threads while other cores sit idle. Use this blueprint when the trace has one `pid_ns` everywhere (or none), and the question is "why is this thread late?". Blueprints 1 and 2 are about containers: a cgroup quota, or a co-tenant container taking the host.

**Status.** Calibrated on the partner traces, whose evidence is not public: two labelled traces of one real fault (partner case 1), plus one negative control where the tool correctly says NOT STARVED. None of our own labelled runs were used. The thresholds are a first pass from those traces. Treat a verdict on a very different box (many cores, real-time threads everywhere) as needing a baseline. Agent: not run in the new form yet.

## Part 1. Background

Linux shares a CPU between ready threads with the **CFS** scheduler (the normal,
time-sharing class). Each thread has a **nice** value from −20 to 19, and each nice value
maps to a **weight**. The CPU is split between the ready threads in proportion to their
weights.

| nice | weight | kernel prio | what LTTng prints |
|---|---|---|---|
| −20 | 88761 | 100 | `prio = 0` |
| −10 | 9548 | 110 | `prio = 10` |
| 0 | 1024 | 120 | `prio = 20` |
| 19 | 15 | 139 | `prio = 39` |

A thread at nice −10 gets about 9× the CPU share of a thread at nice 0 on the same core.
Real-time threads (`SCHED_FIFO` / `SCHED_RR`) sit above all of CFS: they run whenever
they are ready.

**How to read a priority in the trace.** LTTng prints `prio` as the kernel priority minus
100. A negative number is a real-time thread. The tools print `120 (nice 0)`,
`110 (nice -10)`, `RT 63`.

**The fault.** A thread that must answer quickly sits at nice 0 on a core where many
other threads also sit at nice 0. Every time it wakes up it joins a queue of equals. CFS
gives each of them a fair slice, so the thread waits, a few ms each time, tens of ms at
the worst. Meanwhile other cores can be mostly idle: the thread is pinned, or the
scheduler keeps placing it on that core. Nothing is "saturated" in a host-level view.
Only the one thread is late.

**What it looks like.** The victim has runnable waits: single waits of 10–30 ms, many
times per minute. These are waits for a CPU, not sleeps. It uses a few percent of a core
and is seen on one CPU only. Its blocks are short and come from interrupts (packets,
timers). On its core, dozens of distinct threads at exactly the victim's priority ran.
That core is busier than the rest. The other cores are idle a large share of the time
the victim waited. That is what tells placement from a full host.

There is no container to name. Do not report a `pid_ns`. The number inside an enum such
as `prev_state = ( "TASK_INTERRUPTIBLE" : container = 1 )` is the enum's integer, not a
cgroup.

Problems that look similar:

- Starved by a higher-priority thread: one real-time or better-priority thread holds the core while the victim waits. `runq_wait.py` says STARVED BY HIGHER PRIORITY and names it. The fix is different: move or shorten that thread, or give the victim a real-time class.
- Whole host saturated: every core busy ≥ 90%. The tool says HOST SATURATED. Hand to `2_noisy_neighbor` (cpu_saturation). A crowd on one core leaves the other cores idle.
- Noisy neighbour (container): needs containers (`pid_ns` differs). On a one-namespace box there is no co-tenant.
- CPU cap / quota: needs a cgroup. On a bare-metal box there is none; the waits here are irregular and the core is busy with others.
- The thread is blocked, not runnable: long `S` or `D` intervals; `wait_chain.py` names the thread that releases it. A sibling's long system call holding a lock is `9_syscall_stall`.
- Interrupt work on its core: `ksoftirqd/N` and softirq time high on that core. That is `10_irq_imbalance`. `thread_top.py` shows `kthr%`; if it is large, run that blueprint too.
- The victim already outranks the crowd: those waits are CFS slice granularity, not starvation. Raising its priority cannot help. The tool prints a NOTE and says NOT STARVED.
- Trace holes: 1–9 s "waits" that overlap a period with no events on that CPU. Lost trace data or a stalled CPU. The tools drop them and print a `trace holes:` line.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time slice and keeps only the events you name | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> '<events regex>'` |
| `pidmap.py` | Thread to process map from the trace's start-of-session state dump (tid, pid, ppid, name) | `pidmap.py <trace_dir> [--out FILE]` |
| `thread_top.py` | Every thread's time budget (run, runnable wait, sleep) with its priority and the CPUs it ran on, plus a per-CPU table of how crowded each core is at each priority class | `thread_top.py <slice> <secs> [--sort wait|run|max|wakeups] [--top N] [--cpu N] [--pidmap FILE]` |
| `runq_wait.py` | The decisive tool: one thread's runnable waits, who held its core during each wait, the competitors ranked by priority class, and the verdict | `runq_wait.py <slice> <victim tid|name> [--top N] [--min-ms X] [--pidmap FILE]` |
| `wait_chain.py` | One thread's blocked time: who woke it, and what the waker was doing. Used here to make sure the victim waits for a CPU and is not simply blocked | `wait_chain.py <slice> <victim tid|name> [--top N] [--pidmap FILE]` |

`SCHEDEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state'`

`CHAINEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_|irq_handler_|irq_softirq_'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `candidates`.

### Step 2. Cut one slice over the whole trace, then name the threads that wait for a CPU and see how crowded their core is. (`candidates`)

```
extract_slice.sh $TRACE <day> <trace_start> <secs> $WORK/all.txt $SCHEDEV
pidmap.py $TRACE --out $WORK/pidmap.tsv
thread_top.py $WORK/all.txt <secs> --sort wait --top 30 --pidmap $WORK/pidmap.tsv
thread_top.py $WORK/all.txt <secs> --sort max --top 30 --pidmap $WORK/pidmap.tsv
```

Do not hunt for a window first. Starvation by a crowd is steady: it is there as long
as the load is. One slice over the whole span is cheap and sees everything. <secs> is
the whole seconds of the trace duration, plus 2.
`lost events` and `time gaps` tell you where data is missing. The tools detect holes
on their own and leave those stretches out, but write them down for the report.
Snapshot captures: the trace can span 60–180 s but hold events for only the last
6–30 s. The tools print `note: events cover only X s of the Y s slice (snapshot-style
trace); shares below use X s`. Read the shares, not the slice length.
If `pidmap.py` maps none (no state dump in the trace), the tools still work: one row
is one thread. Then leave `--pidmap` out.

thread_top.py prints a header, a per-CPU table and a per-thread table.
- Per-CPU table: `cpu  busy%  threads  RT  <120  =120  >120  kthr%  top occupants`.
  `threads` is how many distinct threads ran on that CPU. The four columns after it
  say how many of them were real-time, better than nice 0, exactly nice 0 (prio 120),
  or worse. `kthr%` is the `ksoftirqd` + `kworker` share.
- Per-thread table: `run`, `wait`, `S`, `D` are average threads over the slice (1.00 =
  the whole time). `wait` is runnable time only. A `*` marks a candidate victim: 3 or
  more waits of 10 ms, or one wait of 25 ms or more. How much the row ran does not
  matter.

Read it:
- The candidates are every `*` row on the crowded core, plus the row with the most
  `wakeups` if it has any wait of 10 ms. Run the table once more with `--sort max` so
  a `*` row low in the wait order is not missed. Do not pick by `wait` share and do
  not stop at two. Measured: the thread with the largest wait share (26%, longest
  17 ms) was MILD, and the thread one row below it (9%, 7 waits ≥ 10 ms, longest
  33 ms) was STARVED BY CROWD.
- Several candidates on one core are all victims. The trace cannot tell which one
  carries the business symptom.
- The crowd is the `=120` count on that CPU's row (or the count in the victim's own
  priority class). Measured on the fault: 75–99 threads at `=120` on the victim's
  core, against 20–50 on the others.
- Compare `busy%` across CPUs. The victim's core is usually the busiest.
- `kthr%` large on that core means interrupt work is part of the story: note it for
  `10_irq_imbalance`.
- Threads with `max_ms` of hundreds or thousands of ms are not candidates if a
  `trace holes:` line was printed. With no holes line such a row is a real, rare
  event: it is a candidate too.

Write down: `secs` (length of the one slice over the whole trace, in whole seconds (the whole seconds of the trace duration, plus 2)), `candidates` (the candidate victims, each as `name tid prio cpu` (every `*` row on the crowded core, plus the row with the most `wakeups` if it has any wait of 10 ms)), `vcpu` (the core the candidates sit on), `crowd` (the number of threads at the victim's priority on that core, from the per-CPU table (the `=120` count)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `candidates_named` | at least one candidate row is named, with its core and the crowd count |  | go to `starved` |
| `no_candidate` | no row carries a `*` in either sort order, and the row with the most `wakeups` has no wait of 10 ms |  | **Stop.** Report "no CPU starvation found". Do not write "no fault". This blueprint looks for one cause only. Root cause **rejected**. |
| `no_sched_events` | the slice holds no `sched_switch`, or neither `sched_waking` nor `sched_wakeup` | `no sched_switch lines in ...` | **Stop.** Report that the trace has no scheduling events. Root cause **inconclusive**. |

### Step 3. Measure each candidate's runnable waits, see who held its core during them, and read the verdict. (`starved`)

```
runq_wait.py $WORK/all.txt <candidate tid or name> --top 12 --pidmap $WORK/pidmap.tsv
```

One runq_wait.py call per `*` row on that core (usually two to four). Never drop a
`*` row because another candidate looked worse. A name matches every thread with
that comm.

It prints the identity (name, tid, prio, `pinned or always placed on cpu X`, run and
wait share), the wait distribution, the longest waits with the occupants of that CPU,
the competitors by class (`same` / `better` / `worse`), an optional NOTE line, the
VERDICT line, a second line about the other CPUs, and a FIX HINT. Quote the verdict
line.

- STARVED BY CROWD: this fault. The waits are long and frequent, and ≥ 60% of the
  waiting time was under threads of its own class or worse. `N distinct threads` is
  the crowd that actually held the core.
- STARVED BY HIGHER PRIORITY: starved, but by a real-time or better-priority thread.
  The fix is different and the report must name that thread.
- MIXED: starved, but no single class dominates. Report all three shares and say the
  cause is not single.
- STARVATION PRESENT BUT MILD: real waits, under the bar for an unprompted fault
  call. Write the numbers down. It is the verdict only when the operator named this
  thread or its deadline is shorter than the longest wait.
- A `D-state:` line after the identity line (`its biggest delays are D-state blocks,
  not runnable waits`): the thread is mostly blocked, not waiting for a CPU. Go to
  the next step now.
- NOT STARVED: this candidate is fine. Try the next candidate.
- VICTIM NOT SEEN: wrong name or tid. Check thread_top.py.
- `NOTE: the victim already outranks the threads it waited behind`: printed before
  the verdict when the threads it waited behind are worse than it. Then CROWD is
  never given. Raising its priority will not help.
- Second line `OTHER CPUS WERE IDLE K% OF THE TIME IT WAITED`: the box had room; the
  victim was placed badly. `HOST SATURATED: all CPUs busy >= 90%`: not this fault.
  `other CPUs idle K% while it waited; busy over the slice: ...`: neither holds.
- `trace holes: ...`: waits over lost data were left out. Say so in the report.

The thresholds. A thread is starved when its longest runnable wait is ≥ 25 ms AND its
runnable waits are ≥ 6% of the time that holds events. It is present but mild when
the longest wait is ≥ 10 ms or it had ≥ 3 waits of 10 ms or more without reaching
that bar. The class split needs ≥ 60% of the waiting time under one class.
Calibration (partner case 1): the two fault traces had longest waits of 30–33 ms,
9–10% of the time waiting, 7 and 26 waits ≥ 10 ms, 92–93% of the waiting under
same-priority threads, 66–84 distinct same-priority competitors, the other cores idle
45–63% of that time. The control: longest wait 5.6 ms, 0 waits ≥ 10 ms, 4.6% waiting,
every thread it waited behind was worse than it, NOT STARVED with the NOTE. On the
healthy control card an app thread waits 20 ms, 23 times, ~5% of its time, and nobody
calls that a fault.

Write down: `victims` (every candidate that `runq_wait.py` called STARVED, each as `name tid prio`, comma-separated, the one with the largest wait share first), `vcpu` (the core the candidates sit on), `wait_numbers` (the first victim's longest wait (ms), wait share (%), and count of waits of 10 ms or more), `crowd_numbers` (from the verdict line, the ms and share of the waiting under the crowd, and the number of distinct same-priority competitors), `idle_elsewhere` (the share on the second line (`OTHER CPUS WERE IDLE K%`), or the second line as printed), `top_competitors` (the top competitors as `name tid prio`, separated by `;`).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `crowd` | for at least one candidate the tool reads STARVED BY CROWD, and the second line is `OTHER CPUS WERE IDLE` (or the other cores are well below 90% busy) | `VERDICT: STARVED BY CROWD ...` | go to `rule_out` Root cause **confirmed**. |
| `host_saturated` | the tool reads STARVED BY CROWD with the second line HOST SATURATED | `HOST SATURATED: all CPUs busy >= 90% ...` | **Stop.** The whole box is short of CPU. Not this fault. Hand the case to blueprint `2_noisy_neighbor`. Root cause **rejected**. |
| `higher_priority` | the tool reads STARVED BY HIGHER PRIORITY for a candidate, and no candidate reads STARVED BY CROWD | `VERDICT: STARVED BY HIGHER PRIORITY ...` | go to `rule_out` Root cause **confirmed**. |
| `mixed` | the tool reads MIXED for a candidate, and no candidate reads STARVED BY CROWD or STARVED BY HIGHER PRIORITY | `VERDICT: MIXED ...` | go to `rule_out` Root cause **unconfirmed**. |
| `blocked_in_d` | the `D-state:` line is printed after the identity line (the thread is mostly blocked, not waiting for a CPU) | `its biggest delays are D-state blocks ...` | go to `rule_out` Root cause **unconfirmed**. |
| `mild_named` | the best verdict of any candidate is STARVATION PRESENT BUT MILD, and the operator named this thread or its deadline is shorter than the longest wait |  | go to `rule_out` Root cause **confirmed**. |
| `mild` | the best verdict of any candidate is STARVATION PRESENT BUT MILD, and the operator did not name this thread | `VERDICT: STARVATION PRESENT BUT MILD ...` | **Stop.** Real waits, under the bar for an unprompted fault call. Report the numbers, but do not call it the fault. Root cause **unconfirmed**. |
| `not_starved` | the tool reads NOT STARVED for every candidate (with or without the NOTE that the victim already outranks the threads it waited behind) | `VERDICT: NOT STARVED ...` | **Stop.** Report "no CPU starvation found". Do not write "no fault". This blueprint looks for one cause only. Root cause **rejected**. |

### Step 4. Check the other causes with what is already printed, plus one call that shows whether the victim is blocked rather than waiting for a CPU. (`rule_out`)

```
extract_slice.sh $TRACE <day> <trace_start> <secs> $WORK/chain.txt $CHAINEV
wait_chain.py $WORK/chain.txt <victim tid or name> --top 12 --pidmap $WORK/pidmap.tsv
```

This step is not optional. Measured on the partner traces: run stand-alone, this
blueprint called "starvation" on a thread whose long delays were really D-state
freezes caused by a sibling's `clone` (blueprint 9's fault).
wait_chain.py needs the system-call events to name what the waker was inside, and
the interrupt events to name a wakeup from an interrupt. So cut the slice again with
$CHAINEV.

It prints the victim's blocked time (total, share, count, p50, max), the blocked time
by waker, its longest blocks, and verdict lines.
- `NO LONG BLOCKS (max X ms; ...)` together with `BLOCKED ON INTERRUPTS/SOFTIRQ
  (network or timer driven)`: the victim sleeps only for its normal packets and
  timers. Its problem is waiting for the CPU, not being blocked. Starvation stands.
- `BLOCKED MOSTLY ON <thread>` with `THE WAKER WAS STUCK IN <syscall> ...`: the
  victim is being held by another thread's long system call. That is
  `9_syscall_stall`, not this fault.

The other checks use what you already have:
- Is the whole host saturated? The second line is `OTHER CPUS WERE IDLE K%` with K
  large, or at least other cores well below 90%.
- Is it one higher-priority thread? `better` is a small share. If the verdict said
  HIGHER PRIORITY, name that thread and switch the fix.
- Does the victim outrank the crowd? No NOTE. If there is one, raising priority is
  not the fix; look for another cause.
- Is interrupt work on its core? `kthr%` on the victim's core is small. If large,
  run `10_irq_imbalance` as well: the crowd may be `ksoftirqd/N`.
- Trace holes? Note the `trace holes:` line; the verdict already excludes those
  waits.
If a check does not fit, say which one in your report, and treat the starvation as
unconfirmed.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `stands` | wait_chain.py reads NO LONG BLOCKS (no long block names another thread) and the other checks fit | `NO LONG BLOCKS ...` | go to `report` |
| `stall` | wait_chain.py reads BLOCKED MOSTLY ON a thread and THE WAKER WAS STUCK IN a system call | `THE WAKER WAS STUCK IN ...` | **Stop.** The waits are a consequence of that stall. Hand to `9_syscall_stall` and say so. (Both can be true at once on a busy card. Then report both, each with its own numbers.) Hand the case to blueprint `9_syscall_stall`. Root cause **rejected**. |
| `check_fails` | one of the checks does not fit (for example a long block names another thread, or the NOTE was printed) |  | **Stop.** A check does not fit. Say which one in your report, and treat the starvation as unconfirmed. Root cause **unconfirmed**. |

### Report

fault_type: `cpu_starvation`. Name the victim thread, its core, the crowd, and the span.
The victims: every candidate on that core that runq_wait.py called STARVED, as thread
name (comm), tid, `prio` label, its core, wait share and longest wait. Name the one with
the largest wait share first, and say that they share one crowd. With the pid map, name
their process (pid and process name).
The crowd: the top competitors (name, tid, prio, ms), the distinct count, and the
per-CPU `=120` count. The culprit is the crowd (the top competitors by name, or "the N
nice-0 threads on cpu X") and is never one of the victims. In a crowd the top competitor
of one victim is often STARVED itself. Then name the crowd collectively and keep that
thread on the victim side only.
The core: its `busy%` against the other cores, and the idle-elsewhere share.
For a HIGHER PRIORITY verdict, say "held off its core by [thread, tid, prio] for [ms]
([%])".
Evidence: at least two independent pieces: the wait distribution, the competitors and
the idle-elsewhere share, the per-CPU crowd count. Quote the verdict line word for word.
Mark each claim Measured or Inferred. What the victim does (woken by `softirq NET_RX` =
a packet path; by `softirq TIMER` = a periodic job) is Inferred. The fix is Inferred.
Fix, crowd: raise the victim's priority (nice −10 = CFS weight 9548 vs 1024 at nice 0,
~9×) or move the crowd off that CPU. Fix, higher priority: reduce or move the
RT/higher-priority thread, or give the victim a real-time class.
Say what you ruled out (host saturation, a higher-priority thread, being blocked,
interrupt work) and why. Say what you did not test.
Say what the trace cannot show. The symptom the operator reported (packet drops, late
replies, a counter in the application) usually lives in an application-layer counter the
kernel trace does not record. Your verdict is the scheduling cause, not the drop itself.
There is no container to name. Do not report a `pid_ns`.

## Part 4. Measured, and limits

- It confirms or rejects one cause: one thread starved of its core by same-or-higher-priority threads. If a step points elsewhere, it stops and tells you so. It does not diagnose that other cause.
- It cannot read the nice value as a setting, the thread's affinity mask, or the SMT topology. It reads priorities from `sched_switch` and placement from where the thread was seen.
- It works on one slice over the whole trace. A fault that lasts under a second inside a long, otherwise healthy trace is diluted; cut a shorter slice around the time of interest and run Steps 3–4 again.
- The thresholds (25 ms and 6% for the fault; 10 ms or 3 waits for "mild"; 60% class share; 80% outrank) come from four labelled traces of one box family: two faults, one healthy control, one card whose waits were a stall's consequence. They are first-pass. On a box with many cores or many real-time threads, compare with a healthy trace of the same box before you commit.
- It does not see the application symptom. A line card counts its drops in its own software; the kernel trace holds the cause (the waits), not the drop.
- Trace holes (snapshot buffers, discarded events) are left out of every number, and the tools say so. A trace that is mostly holes gives weak numbers; say so.
- Without a pid context, a state dump, or fork events, threads cannot be grouped into processes. The verdict still names the thread, which is what the fix needs.
