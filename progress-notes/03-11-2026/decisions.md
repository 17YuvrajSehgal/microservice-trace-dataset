# 2026-11-03 — scheduling-family blueprints for bare-metal hosts (from the partner comparison)

Follows the 02-11 comparison of our agent against an industry partner's own RCA on five
line-card kernel traces (NDA: traces, tickets and the comparison stay in the gitignored
`Blueprint/ciena_out/`): 0 of 4 faults root-caused, and all three fault classes were
CPU-scheduling ones that our six blueprints do not cover. The user asked for: fix the blueprints,
build the missing ones, make the agent name threads, and research what latency problems a
telecom vendor cares about. Naming rule for anything that goes to git: "partner case 1/2/3", no
company name, no ticket ids, no internal thread names.

## 1. Root cause of the empty tool output: the line shape, not the method
Every scheduling tool (`sched_budget`, `victim_info`, `rhythm`, `cpu_hogs`, `wake_graph`,
`cpu_ceiling`, `sleep_where`, `sock_lag`) printed an EMPTY table on all five partner traces (~60
calls) because their regexes assumed the Sock Shop line shape:
- a `{ pid = P, tid = T, procname = "X", *_ns = N }` context block on every event (three of the
  traces have none, one has only `procname`, one has `{ vtid, vpid, procname, prio }`),
- `prev_state = 256` as a number (the enum form `( "TASK_INTERRUPTIBLE" : container = 1 )` is
  what those traces print; the agent then read that `container = 1` as a cgroup), and
- `prev_prio = \d+` (real-time threads have NEGATIVE LTTng prio, so every switch-out of an RT
  thread was skipped - a latent bug on Sock Shop too: `cpu_hogs` over-charged `migration/0` and
  `multipathd`, busy 8% -> 5% after the fix).
Fix: parser-level edits in each tool (context optional; without it one row = one THREAD, pid := tid,
named by its comm; enum state; negative prio; `compat_syscall_*`). Regression on a real Sock Shop
slice (`Blueprint/agent/bp_work/t3_implement_cap25_r1`): byte-identical except the RT-prio fix;
a copy reshaped to the `vtid/vpid` form gives identical tables; a copy reshaped to the
context-less enum form now gives full tables where HEAD printed nothing. Script: scratchpad
`regress.sh`.

## 2. New tools read slices, not the count index
On context-less traces the index has `procname = ?` on every row, and snapshot-style captures
hold events for only part of the span (6.5 s of events inside a 69 s trace; 10 s of 34; 27 s
of 177). The babeltrace slice has everything. So the new tools take `extract_slice.sh` output
(with the events regex) and share one parser, `tracelib.py`: all three line shapes; `Cpus`
tracks who is on each CPU so tid-less events (syscalls, irq, softirq) are charged to a thread;
`Sched` is the per-thread state machine with wake-wait and preempt-wait kept apart;
`effective_secs()` divides by the event span, not the slice length. LTTng prio = kernel prio -
100 (20 = nice 0; 10 = nice -10; negative = real-time); `prio_label()` spells it out.

## 3. Trace holes are not latency
A CPU with a runnable thread waiting for it cannot be silent. Waits of 1-9 s on the partner
traces (`dhcpd`, `migration/0`, `jbd2`) all overlapped a period where that CPU showed no event
for >= 0.5 s (events_discarded on two CPUs, a 94 s packet gap). `Sched` now drops such intervals
into `skipped` and prints `skipped_note()`; `sched_budget.py` got the same rule (identical on
Sock Shop).

## 4. Four blueprints, each tied to a labelled fault - and what the real traces taught the tools
| blueprint | fault it confirms | labelled evidence | decisive tool |
|---|---|---|---|
| 8_cpu_starvation | one thread runnable-but-waiting behind a same-prio crowd on its core | partner case 1 (two cards): comms thread prio 120, 66-84 same-prio threads on its core, max waits 30 ms, 7-26 waits >= 10 ms, other cores 45-63% idle; fix prio 120 -> 110 | `runq_wait.py` (+ `thread_top.py`) |
| 9_syscall_stall | one thread stuck in one WORK-class syscall that freezes dependants | partner case 2: `clone` 0x100011 of 49-53 ms by a status thread; the comms thread blocked in D 48.5 / 46.8 ms and released by it (engineers: 53.6 ms); fix `posix_spawn` (1.9 ms) | `wait_chain.py` + `syscall_stall.py` |
| 10_irq_imbalance | softirq/RX piled on one CPU, app threads on it or its SMT sibling | partner case 3: with load 100% of NET_RX on cpu 0, `ksoftirqd/0` 42% of a CPU (engineers: 43.4%), baseline 6 -> 486 ms/s; baseline alone "SPREAD EVENLY" | `irq_balance.py` (`--baseline` diff) |
| 11_priority_inversion | lock held by a thread that cannot run | our own `priority_inversion_*` / `lock_contention_*` v2 runs | `futex_wait.py` |

Calibration decisions from the first real run (all encoded as module constants):
- STARVED needs max >= 10 ms AND (share >= 2% OR >= 3 waits of 10 ms); and when the victim
  already outranks the threads it waited behind, raising its priority cannot help (the third
  card had the comms thread at prio 100 and still dropped packets - the engineers had already
  tried that; the tool must say NOT STARVED there, and now does).
- A WORK-class syscall that is >= 90% interruptible sleep is a wait, not a stall (drivers use
  `ioctl` as a wait primitive: 1-30 s sleeps, 0.1 ms on-CPU). A stall is on-CPU or D-state time
  inside the call, or a dependant blocked in D.
- A futex wait that ends by timeout (ret -110) is a timer sleep, not a lock wait (100 ms, 1 s,
  5 s loops on every trace); only waits released by an identified wake (ret 0) count.
Method sources: lttng-analyses' own analysis set, Trace Compass wait analysis (Giraldeau &
Dagenais 2016), bcc `runqlat` / off-CPU analysis, kernel `scaling.rst` (RSS/RPS), the
`fork`/`mmap_lock` mechanism, CPU-isolation docs. Summarised in `Blueprint/latency/FAMILIES.md`.
Packet drops on these boxes are application counters, so the scheduling side is the only
kernel-visible cause - `packet_drop` correctly stays "normal" on them.

## 5. Agent changes - additive, Sock Shop prompts unchanged
- `FAULT_TYPES` + `cpu_starvation`, `syscall_stall`, `irq_imbalance`; `FAULT_VOCAB` now defines
  these plus the four that were in the enum with no definition (conn_pool, lock_contention,
  priority_inversion, deadlock).
- `submit_diagnosis` gains OPTIONAL `culprit_thread` / `victim_thread` ('comm tid N (prio P)')
  and `culprit_kind: thread`; old transcripts and scorers stay valid.
- `agent_v2._host_profile()`: measured from the count index, when every row has the same pid_ns
  the prompt gets a HOST PROFILE paragraph (no containers; name threads; the enum `container = N`
  is not a cgroup; the scheduling family is the usual suspect). Multi-namespace hosts get nothing.
- `datasets.py` / `score.py` / `eval_one.py` know the four new families.

## 6. Validation of the tools on the five partner traces (tool-only, no LLM; `sched_validate/`)
Three rounds; each round's false positives became a rule (section 4). Final round:
| trace | runq_wait | syscall_stall | irq_balance | futex_wait |
|---|---|---|---|---|
| case 1, card A | STARVED BY CROWD (66 same-prio threads, 93%, other cores idle 63%) | 24 ms D-state `write`, no freeze (minor) | SPREAD EVENLY | NO LOCK PROBLEM (event wait) |
| case 1, card B | STARVED BY CROWD (84 threads, 92%; its core 86% busy, others 31-47%) | 364 ms D-state `write` x6 freezing systemd-journal (real, unrelated) | SPREAD EVENLY | NO LOCK PROBLEM |
| case 2, card C | NOT STARVED (prio already 100; max 5.6 ms) | STALL: clone 0x100011 57-70 ms, 2x, 47 ms on-CPU, froze 3+ threads in D up to 49 ms | SPREAD EVENLY | NO LOCK PROBLEM |
| case 3, no load | VICTIM NOT SEEN (name not in trace) | NO WORK-CLASS SYSCALL | SPREAD EVENLY | NO LOCK PROBLEM |
| case 3, with load | VICTIM NOT SEEN | 31 ms execve by pgrep (minor) | RX CONCENTRATED ON CPU 0, 100% of NET_RX, ksoftirqd/0 42% | NO LOCK PROBLEM |
So: 3 of 3 faults reproduced with the engineers' own numbers (crowd on the comms thread's core;
the 53 ms clone; ksoftirqd/0 43%), 1 healthy control clean, 1 negative control correct. The
leftovers are true-but-minor findings; the triage blueprint ranks them below the fault
signatures ("who is affected decides between two hits"). The agent itself has not run on these
yet - that needs the LLM re-hosted (`Blueprint/latency/CLUSTER-RUN.md`).

## 7. The triage blueprint (autonomy for bare-metal hosts)
`0_host_triage`: one slice over the whole capture, `thread_top` to name candidates, the four
screens, a fixed decision table (Appendix A) and `culprit_thread` / `victim_thread` in the
verdict. It is a blueprint like any other (`run_trace.sh "<trace>" Blueprint/latency/0_host_triage`),
so the matrix scripts on Trillium list it first.

## 8. Blueprint 11 on our own labelled runs (`futex_wait.py`, five rule rounds)
What the real data forced into the rules, in order: timed-out waits are sleeps (ret -110);
back-to-back short timed waits by one thread are ONE logical wait (a Python GIL loop does 5 ms
pieces; the cap is 50 ms per piece so 1 s heartbeats stay sleeps); a single idle worker on one
futex is not contention (>= 2 waiters); a releaser that slept the whole wait is an event
signaller, unless it is itself a waiter on that futex (a HAND-OFF = a real lock, even when the
holder sleeps while holding); a critical section has a bounded tail (p99/p50 <= 50; runtime
parking futexes are 150+); tracer threads are left out; an inversion needs a wait >= 20 ms.
Final readings:
- lock_contention run: "LOCK CONTENTION on futex 0x59951ebb5c40: 202064 held lock waits by 16
  threads, p50 4.20 ms, p99 7.1 ms, max 15.7 ms; top waiter 92% of its time; holders sleep while
  holding" - the injected lock, with its mechanism (the recipe sleeps under the lock). The
  Go-runtime parking futex and a Node.js idle worker in the same slice are correctly left out.
- priority_inversion run: "PRIORITY INVERSION: the nice -5 waiter waited 34.3 ms (a run of 7
  timed waits) on the interpreter lock; the releaser (a nice-0 middle thread) was
  runnable-but-not-running 36% of it (908 such waits)". The application lock shows too: the
  nice -5 thread waiting 445-730 ms on the nice-19 holder, which slept 97% of it while holding.
  `runq_wait` on the holder: STARVED BY HIGHER PRIORITY by the six middle threads (2.1 s of 60 s
  runnable-but-not-running). Honest reading: the kernel shows the inversion on the interpreter
  lock and the long app-lock waits on a sleeping holder, not the textbook "holder preempted while
  holding the app lock" - the recipe's holder sleeps while holding.
- the five partner traces: three NO LOCK PROBLEM lines (10 ms inversion-class waits between
  background threads on two healthy cards, below the bar; a 78 ms wait released by an
  equal-priority preempted thread; a 306 ms held lock under the 5% bar) and NO LONG FUTEX WAITS -
  true negatives.

## Open
- Agent runs on the partner traces need the vLLM re-hosted on Trillium (no job running now).
- The agent itself has not yet been scored with the new blueprints; the tool verdicts above are
  the ceiling it should reach.
