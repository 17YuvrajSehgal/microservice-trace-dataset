<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: triage of a bare-metal host from one kernel trace (which scheduling fault, if any)

| | |
|---|---|
| Problem class | Triage for a bare-metal host: one pid namespace, no containers, no cgroup limits |
| Root cause this blueprint confirms or rejects | Which of the scheduling-family faults the trace shows (a thread starved of CPU, a thread frozen by a sibling's system call, interrupt work piled on one CPU, a lock held by a thread that cannot run), or that none of them shows and the box looks normal. It names the threads either way, and names the deep-dive blueprint that confirms the finding. |
| Evidence | An LTTng kernel trace only. Also allowed: the names of the threads the operator cares about (passed to `--watch`); the box's SMT pairs if known |
| Not used | Logs, metrics, application counters (packet drops, late replies), request traces |

**When to use this.** The trace comes from a host with one `pid_ns` everywhere (or none), or you do not know which family to try. On a microservice host with containers, use blueprints 1–5 instead. If an operator already told you the family, go straight to that blueprint (8, 9, 10 or 11).

**Status.** Calibrated on the partner traces, whose evidence is not public. This screen was run on five of them: three real faults, which it routes to blueprints 8, 9 and 10 with the right thread names; one healthy baseline capture, which it calls normal; and one where the suspected starvation is correctly rejected because the thread had already been given a high priority. The lock branch (blueprint 11) is being validated on our own labelled runs; no other branch used our own labelled runs. The precedence rules are a first pass from those traces. Agent: not run in the new form yet.

## Part 1. Background

A microservice host has a cgroup and a container to blame. A bare-metal host has
neither: **the thread is the unit of blame**, and the question is which core, which
priority, which kernel path. Four scheduling faults cover what the partner traces
showed, plus one network fault:

- **`cpu_starvation` (blueprint 8).** One latency-sensitive thread is ready to run but
  keeps waiting, because many threads of the same or higher priority share its core.
  Other cores sit idle. Fix: raise its priority or move the crowd.
- **`syscall_stall` (blueprint 9).** One thread sits inside one system call
  (`clone`/`fork`, `ioctl`, `mmap`, `write`) for tens of ms, on-CPU or in D state, and
  the threads that depend on it freeze in D meanwhile. Fix: a cheaper call
  (`posix_spawn`), or move the call out of the latency-critical process.
- **`irq_imbalance` (blueprint 10).** Network receive softirqs (`NET_RX`) all land on
  one CPU; `ksoftirqd/N` eats that core, and the application threads placed on it or on
  its SMT sibling get slow. Fix: spread RX (RSS / IRQ affinity / RPS) and pin the
  threads elsewhere.
- **`priority_inversion` / `lock_contention` (blueprint 11).** A thread waits on a lock
  held by a thread that cannot run (its CPU is taken by middle-priority threads), or
  many threads queue on one lock. Fix: priority inheritance, or a shorter critical
  section.
- **`packet_drop` (blueprint 7).** The kernel itself drops packets (`skb_kfree` with a
  reason). Not part of this screen: on these boxes the drop counter usually lives in
  the application, and the kernel trace holds the scheduling cause, not the drop.

**Priorities in the trace.** LTTng prints `prio` as the kernel priority minus 100: `20`
= nice 0 (kernel 120), `10` = nice −10, a negative number = a real-time thread. The
tools print `120 (nice 0)`, `110 (nice -10)`, `RT 63`.

Problems that look similar:

- A thread sleeping inside `ioctl`, `poll` or `futex` with a timeout is waiting for an event, not stalled; the tools leave those out and say so.
- A wait of seconds that overlaps a stretch where its CPU shows no event at all is lost trace data (snapshot buffers), not latency; the tools drop those and print a `trace holes:` line.
- Kernel packet drops (`skb_kfree` with a reason, bursts) are `packet_drop`, not in this screen. Run `7_packet_drop` when the question is "does the kernel drop packets".

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, start, end, length, CPUs, health checks; reads only the index | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time slice and keeps only the events you name | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> '<events regex>'` |
| `pidmap.py` | Thread to process map from the state dump | `pidmap.py <trace_dir> [--out FILE]` |
| `thread_top.py` | Every thread's run / runnable-wait / sleep with its priority and CPUs, and a per-CPU crowd table | `thread_top.py <slice> <secs> [--sort wait|run|max|wakeups] [--top N] [--cpu N] [--pidmap FILE]` |
| `irq_balance.py` | Hardirq and softirq time per CPU, concentration, `ksoftirqd/N`, the threads on the hot CPU (interrupt screen) | `irq_balance.py <slice> <secs> [--baseline <slice2> <secs2>] [--siblings "0,1 2,3"] [--watch name,name] [--top N]` |
| `syscall_stall.py` | Long system calls that burn CPU or sit in D, and the threads they froze (stall screen) | `syscall_stall.py <slice> [--min-ms 10] [--top 20] [--only name,name] [--pidmap FILE]` |
| `futex_wait.py` | Lock waits per futex, who released them and what the releaser was doing (lock screen) | `futex_wait.py <slice> <secs> [--top N] [--min-ms X] [--pidmap FILE]` |
| `runq_wait.py` | One thread's runnable waits, who held its core, the verdict (starvation screen) | `runq_wait.py <slice> <victim tid|name> [--top N] [--min-ms X] [--pidmap FILE]` |
| `wait_chain.py` | One thread's blocked time: who woke it and what the waker was doing | `wait_chain.py <slice> <victim tid|name> [--top N] [--pidmap FILE]` |

`ALLEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_|irq_handler_|irq_softirq_'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `threads`.

### Step 2. Cut one slice over the whole trace, then name the candidate victims and see how each core is loaded. (`threads`)

```
extract_slice.sh $TRACE <day> <trace_start> <secs> $WORK/all.txt $ALLEV
pidmap.py $TRACE --out $WORK/pidmap.tsv
thread_top.py $WORK/all.txt <secs> --sort wait --top 30 --pidmap $WORK/pidmap.tsv
```

Do not hunt for a window first. These faults are steady: they are there as long as
the load is. One slice over the whole span sees everything, and one slice serves
every screen. <secs> is the whole seconds of the trace duration, plus 2. Leave
`--pidmap` out if `pidmap.py` mapped nothing.
`lost events` and `time gaps` say where data is missing. The tools detect holes on
their own and leave those stretches out; write the health lines down for the report.
Snapshot captures: the trace can span 60–180 s but hold events for only the last
6–30 s. The tools print `note: events cover only X s of the Y s slice` and divide by
the real span. Read the shares, not the slice length.

thread_top.py:
- Header: the `identity:` line, the snapshot note, the `trace holes:` line if any.
  Write them down.
- Per-CPU table (`cpu busy% threads RT <120 =120 >120 kthr% top occupants`): write
  down each CPU's `busy%`, its `=120` count (the crowd at nice 0), and `kthr%`. A
  `kthr%` of tens of percent on one CPU means the interrupt screen will matter.
- Per-thread table: the candidate victims come from three columns, not one: (a)
  rows marked `*` (3 or more waits of 10 ms, or one wait of 25 ms or more; how much
  the row ran does not matter); (b) the two or three rows with the largest `>=10ms`
  count; (c) the two rows with the most `wakeups` (a latency-sensitive thread wakes
  often and runs briefly). A thread that runs more than it waits can still be the
  starved one. Measured: one thread had the most waits of 10 ms or more of any
  thread (26) and no `*`, and a screen that tested only `*` rows called the card
  normal. Write down up to four: `name tid prio cpu`.
- Also write down the three or four busiest application threads (large `run`); those
  go to `--watch` in the next step.

Write down: `secs` (length of the one slice over the whole trace, in whole seconds (the whole seconds of the trace duration, plus 2)), `cpu_table` (each CPU's `busy%`, its `=120` count (the crowd at nice 0), and `kthr%`), `candidates` (up to four candidate victims, each as `name tid prio cpu` (the `*` rows, the rows with the largest `>=10ms` count, the rows with the most `wakeups`)), `watch` (the three or four busiest application threads (large `run`), or the ones the operator named, comma-separated).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `threads_named` | the per-CPU facts and the candidate victims are written down |  | go to `screens` |
| `no_sched_switch` | the trace has no `sched_switch` | `no sched_switch lines in ...` | **Stop.** The trace cannot be triaged. Root cause **inconclusive**. |

### Step 3. Run the interrupt, stall and lock screens on the same slice, and read rows 1 to 4 of the decision table from their verdict lines. (`screens`)

```
irq_balance.py $WORK/all.txt <secs> --watch <watch>
syscall_stall.py $WORK/all.txt --min-ms 10 --top 20 --pidmap $WORK/pidmap.tsv
futex_wait.py $WORK/all.txt <secs> --top 10 --pidmap $WORK/pidmap.tsv
wait_chain.py $WORK/all.txt <victim> --top 12 --pidmap $WORK/pidmap.tsv
```

Quote each `VERDICT:` / `STALL:` / `NO ...` line word for word. The decision is made
from them, not from impressions.
A screen whose events are not in the trace is skipped; say so in the report. No
`irq_softirq_entry`: skip the interrupt screen (irq_balance.py reads `VERDICT: NO
IRQ EVENTS IN SLICE`). No `syscall_entry_*`: skip the stall and lock screens
(futex_wait.py reads `VERDICT: NO FUTEX WAITS IN SLICE`).

- Interrupt screen. `VERDICT: RX CONCENTRATED ON CPU N: ...` with the `APP THREADS
  ON THAT CPU/ITS SIBLING:` line, or `VERDICT: IRQ/SOFTIRQ SPREAD EVENLY`. A `(but
  <kind> on cpu N is concentrated ...)` tail is a different, smaller finding: name
  the kind.
- Stall screen. `STALL: <thread> tid N spent X ms in <syscall> (... on-CPU + ... D;
  ...) - n times, every ~Z s; it froze K threads in D for up to X ms (names);
  siblings starved: ...; released at exit: ...`, or `NO WORK-CLASS SYSCALL >= 10 ms
  (...)`. The lines `WORK-class calls >= 10 ms that were sleeping (...)` and
  `tracer's own activity (left out): ...` are not findings. A `STALL:` with `no
  sibling or freeze effect measured` and under 50 ms is a finding, never the
  verdict.
- Lock screen. `VERDICT: PRIORITY INVERSION: ...` (also the `(chained)` form),
  `VERDICT: LOCK CONTENTION on futex 0x..: ...`, or one of the negatives: `NO LONG
  FUTEX WAITS (...)`, `NO LOCK PROBLEM: ...`.
- When a stall names a victim, one wait_chain.py call on that victim shows who
  releases that thread and what the releaser was doing (`BLOCKED MOSTLY ON ...`,
  `THE WAKER WAS STUCK IN ...`, `NO LONG BLOCKS`). Use it to connect two findings,
  not as a fifth screen.

Walk the decision table from the top; the first row that matches gives the lead.
1. `VERDICT: RX CONCENTRATED ON CPU N`: `irq_imbalance`. Culprit: the RX softirq
   load on cpu N (`ksoftirqd/N`). Victims: the `APP THREADS ON THAT CPU/ITS
   SIBLING:` line. A thread starved on the RX CPU while this fires is a consequence
   of the interrupt imbalance.
2. `STALL: ... it froze K threads in D ...`, only when a frozen or starved dependant
   is a candidate victim or the operator's thread: `syscall_stall`. Culprit: the
   staller. Victims: the frozen threads. A victim `BLOCKED MOSTLY ON <thread>` that
   is itself the `STALL:` thread is one fault, not two.
3. `VERDICT: PRIORITY INVERSION`: culprit the releaser (and the threads that took
   its CPU), victim the waiter.
4. `VERDICT: LOCK CONTENTION on futex 0x..`: culprit the holders, victim the top
   waiter.
A `STALL:` whose dependants are not a candidate victim, or with `no sibling or
freeze effect measured`, is a second finding, not the verdict. Measured: on one
card a thread was STARVED BY CROWD and, on the same slice, another thread spent
364 ms in `write` (all D state) six times and froze a daemon for 249 ms. The stall
was real but touched nobody that mattered; the root cause was the starvation.

Write down: `irq_line` (the interrupt screen's verdict line, word for word, or `skipped` and why), `stall_line` (the stall screen's `STALL:` or `NO WORK-CLASS SYSCALL` line, word for word, or `skipped` and why), `lock_line` (the lock screen's verdict line, word for word, or `skipped` and why).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `irq_imbalance` | the interrupt screen reads RX CONCENTRATED ON CPU N (row 1) | `VERDICT: RX CONCENTRATED ON CPU ...` | **Stop.** The lead is `irq_imbalance`. Name `ksoftirqd/N` and the threads on the `APP THREADS ON THAT CPU/ITS SIBLING:` line. Blueprint 10 confirms it. Hand the case to blueprint `10_irq_imbalance`. Root cause **unconfirmed**. |
| `syscall_stall` | row 1 does not match, and the stall screen prints a `STALL:` line with an `it froze` clause whose frozen or starved dependants include a candidate victim or the operator's named thread (row 2) | `it froze ...` | **Stop.** The lead is `syscall_stall`. Name the staller and the frozen threads. Blueprint 9 confirms it. Hand the case to blueprint `9_syscall_stall`. Root cause **unconfirmed**. |
| `priority_inversion` | rows 1 and 2 do not match, and the lock screen reads PRIORITY INVERSION (row 3) | `VERDICT: PRIORITY INVERSION ...` | **Stop.** The lead is `priority_inversion`. Name the waiter, the releaser and the threads that took its CPU. Blueprint 11 confirms it. Hand the case to blueprint `11_priority_inversion`. Root cause **unconfirmed**. |
| `lock_contention` | rows 1 to 3 do not match, and the lock screen reads LOCK CONTENTION on a futex (row 4) | `VERDICT: LOCK CONTENTION on futex ...` | **Stop.** The lead is `lock_contention`. Name the holders and the top waiter. Blueprint 11 confirms it. Hand the case to blueprint `11_priority_inversion`. Root cause **unconfirmed**. |
| `no_lead_yet` | none of rows 1 to 4 matches (the screens gave negatives, a second finding, or were skipped) |  | go to `starvation` |

### Step 4. Run the starvation screen once per candidate, and decide from rows 5 to 10 of the decision table. (`starvation`)

```
runq_wait.py $WORK/all.txt <candidate tid or name> --top 12 --pidmap $WORK/pidmap.tsv
wait_chain.py $WORK/all.txt <victim> --top 12 --pidmap $WORK/pidmap.tsv
```

One runq_wait.py call per candidate. It prints `VERDICT: STARVED BY CROWD: ...`,
`VERDICT: STARVED BY HIGHER PRIORITY: ...`, `VERDICT: MIXED - ...`, `VERDICT:
STARVATION PRESENT BUT MILD - ...`, `VERDICT: NOT STARVED - ...` or `VERDICT:
VICTIM NOT SEEN - ...`; then the second line, `OTHER CPUS WERE IDLE K% OF THE TIME
IT WAITED (...)` or `HOST SATURATED: all CPUs busy >= 90%`; and a `NOTE: the victim
already outranks ...` line when it applies.
When a starvation verdict surprises you, one wait_chain.py call on that thread
shows who releases it and what the releaser was doing.

Go on down the decision table:
5. `VERDICT: STARVED BY CROWD`: `cpu_starvation`. Culprit: the crowd on cpu X (name
   the top competitors). Victim: the thread you passed.
6. `VERDICT: STARVED BY HIGHER PRIORITY: <name> tid T ...`: `cpu_starvation`.
   Culprit: `<name> tid T`.
7. Second line `HOST SATURATED: all CPUs busy >= 90%`: `cpu_saturation`. Culprit:
   the host. Victims: every waiting thread.
8. A `STALL:` whose dependants are not a candidate victim, or with `no sibling or
   freeze effect measured`: a second finding, not the verdict.
9. `VERDICT: IRQ/SOFTIRQ SPREAD EVENLY (but <kind> on cpu N is concentrated - see
   above)`: a second finding (`other` if alone). Name the device in `top irq` or
   the kind, and the threads on that CPU.
10. `VERDICT: IRQ/SOFTIRQ SPREAD EVENLY`; `NO WORK-CLASS SYSCALL >= 10 ms (...)`;
    `NO LONG FUTEX WAITS (...)` or `NO LOCK PROBLEM: ...`; `VERDICT: NOT STARVED -
    ...` for every candidate: `normal`.
A `VERDICT: MIXED - ...` with a large idle-elsewhere share is reported as
`cpu_starvation` with lower confidence. `VERDICT: NOT STARVED - ...` (also with the
`NOTE: the victim already outranks ...` line) closes that candidate.
If no row matches, the verdict is normal: list every negative line you got, word
for word, plus the screens you had to skip and why.

Write down: `starve_lines` (the starvation screen's verdict line and second line for each candidate, word for word).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `starved_by_crowd` | the tool reads STARVED BY CROWD for a candidate, and the second line is not HOST SATURATED (row 5) | `VERDICT: STARVED BY CROWD ...` | **Stop.** The lead is `cpu_starvation`. Name the thread you passed and the top competitors on its core. Blueprint 8 confirms it. A stall or a concentrated kind seen before is a second finding. Hand the case to blueprint `8_cpu_starvation`. Root cause **unconfirmed**. |
| `starved_by_higher_priority` | no candidate reads STARVED BY CROWD, and the tool reads STARVED BY HIGHER PRIORITY for a candidate (row 6) | `VERDICT: STARVED BY HIGHER PRIORITY ...` | **Stop.** The lead is `cpu_starvation`. Name the thread you passed and the higher-priority thread on the verdict line. Blueprint 8 confirms it. Hand the case to blueprint `8_cpu_starvation`. Root cause **unconfirmed**. |
| `mixed` | rows 5 and 6 do not match, and the tool reads MIXED for a candidate with a large idle-elsewhere share | `VERDICT: MIXED ...` | **Stop.** Reported as `cpu_starvation` with lower confidence. Blueprint 8 confirms it. Hand the case to blueprint `8_cpu_starvation`. Root cause **unconfirmed**. |
| `host_saturated` | the second line reads HOST SATURATED (row 7) | `HOST SATURATED: all CPUs busy >= 90% ...` | **Stop.** The lead is `cpu_saturation`. The culprit is the host; every waiting thread is a victim. Hand the case to blueprint `2_noisy_neighbor`. Root cause **unconfirmed**. |
| `mild` | rows 5 to 7 do not match, and the best verdict of any candidate is STARVATION PRESENT BUT MILD | `VERDICT: STARVATION PRESENT BUT MILD ...` | **Stop.** Report it. Call it the fault only if the operator named this thread or its deadline is under the longest wait; then blueprint 8 applies. Root cause **unconfirmed**. |
| `stall_finding` | rows 5 to 7 do not match, and the stall screen printed a `STALL:` whose dependants are not a candidate victim, or with `no sibling or freeze effect measured` (row 8) |  | **Stop.** The stall is a second finding, not the verdict. Blueprint `9_syscall_stall` applies if the operator cares about that thread. Root cause **rejected**. |
| `other_kind_concentrated` | rows 5 to 8 do not match, and the interrupt screen read SPREAD EVENLY with the tail `(but <kind> on cpu N is concentrated - see above)` (row 9) |  | **Stop.** A second finding (`other` if alone). Name the device in `top irq` or the kind, and the threads on that CPU. See the lookalikes table of `10_irq_imbalance`. Root cause **unconfirmed**. |
| `normal` | every screen that ran gave its negative line, and every candidate reads NOT STARVED (row 10) | `VERDICT: NOT STARVED ...` | **Stop.** The verdict is normal. List every negative line you got, word for word, plus the screens you had to skip and why. Root cause **rejected**. |

### Report

fault_type: one of `irq_imbalance`, `syscall_stall`, `priority_inversion`,
`lock_contention`, `cpu_starvation`, `cpu_saturation`, `normal`, `other`.
The culprit is a thread (or a per-CPU kernel thread such as `ksoftirqd/0`), or the host
for saturation. Name the culprit thread and the victim thread as `comm tid N (prio P)`,
exactly as the tools print them. Several victims: name the first, list the rest in the
evidence.
Incident window: the span of the slice that holds events. These faults are steady, not
a step change; say so.
Evidence: the quoted verdict lines and their numbers, the per-CPU facts, and the screens
you skipped.
Add one sentence naming the deep-dive blueprint that confirms the finding.
Add this sentence, always: the user-visible symptom (packet drops, late replies) usually
lives in an application counter the kernel trace cannot show; the verdict is the
scheduling cause behind it.

## Part 4. Measured, and limits

- It screens the four scheduling families and nothing else. A disk fault, a memory fault or a kernel hot path inside one system call (a syscall that is 10–30 ms on-CPU every time) needs other instruments.
- A snapshot trace that holds only a few seconds of events can miss a fault that comes every 7–8 s. Say how many seconds of events the tools reported.
- The trace does not know SMT pairs. Without `--siblings` the interrupt screen names the threads on the hot CPU only; read `/sys/devices/system/cpu/cpuN/topology/thread_siblings_list` on the box.
- Thresholds come from five traces of one vendor's boxes. A very different host (many cores, real-time threads everywhere) needs a baseline capture before a `normal` verdict means much.
