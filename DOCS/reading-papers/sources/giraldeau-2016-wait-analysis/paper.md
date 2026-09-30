# Paper Context: Wait Analysis of Distributed Systems Using Kernel Tracing (IEEE TPDS 2016)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is the **method backbone** for blueprints 1, 2, 7 and 9. It is where "blocked vs
> running vs preempted" comes from. Read section 13 before citing it: the paper's event set
> is **not** the same as ours, and two of its required events are missing from our traces.

---

## 1. Bibliographic info

- **Title:** Wait Analysis of Distributed Systems Using Kernel Tracing
- **Authors:** Francis Giraldeau, Michel Dagenais (Polytechnique Montreal)
- **Venue:** IEEE Transactions on Parallel and Distributed Systems, vol. 27, no. 8, pp. 2450-2461
- **Date:** published online 8 Oct 2015; issue August 2016
- **DOI:** 10.1109/TPDS.2015.2488629
- **Open access:** PolyPublie, https://publications.polymtl.ca/3078/ (published version)
- **Code:** experiments are on GitHub (ref [21] in the paper)

```bibtex
@article{giraldeau2016wait,
  title   = {Wait Analysis of Distributed Systems Using Kernel Tracing},
  author  = {Giraldeau, Francis and Dagenais, Michel},
  journal = {IEEE Transactions on Parallel and Distributed Systems},
  volume  = {27}, number = {8}, pages = {2450--2461}, year = {2016},
  doi     = {10.1109/TPDS.2015.2488629}
}
```

---

## 2. One-paragraph summary

A normal profiler tells you where CPU time goes. It cannot tell you why a thread **waited**.
This paper recovers the wait. The idea is small and strong: when a thread blocks, the control
flow of the program changes, and the event that **wakes it up** tells you what it was waiting
for. Follow that wake-up backwards and you get the cause. Do it recursively and the chain
crosses threads, and across machines through network packets. It needs only operating system
events - scheduling, interrupts, network - so it works on unmodified programs in any language.
The output is the **active path** of a task: the timeline of what actually held it up. Tracing
cost was 18% in the worst case and about 5% typical. Both algorithms are linear in trace size.

---

## 3. Problem and motivation

- Instruction profilers (hardware counters, binary translation, call-graph timing) find hot
  code. They ignore time spent waiting.
- They also only see one machine. Each part of a distributed system must be studied alone.
- Instrumenting libraries and middleware works, but is tied to one language or framework.
  With many languages and frameworks, that cost is high.
- Tracing only system calls is not enough. Communication can happen from any kernel code -
  other system calls, interrupt context, kernel threads.
- Recording network traffic alone hides what happens **inside** each machine.
- Kernel tracing sees waits between threads, works on unmodified binaries, and is system-wide.

### Stated contributions

1. The kernel instrumentation the analysis needs (Linux loadable modules, unmodified kernel).
2. A graph model of execution built from the trace, plus the algorithm to extract a task's
   active path.
3. Experiments on real software, across host type, software architecture, network conditions.
4. Measurement of runtime overhead and trace-processing cost.
5. Two optimisations that make the analysis practical on real traces.

### Explicit non-goal

Recovering application-level requests. The payload of a network packet is treated as a black
box. If one thread handles several requests at once (user-space threads), you need extra
user-space instrumentation to tell them apart.

---

## 4. The core idea

A task is in one of four states:

| State | Meaning |
|---|---|
| running | executing on a CPU |
| preempted | ready, but not getting a CPU |
| interrupted | an interrupt handler is nested over the application code |
| blocked | waiting passively for an event; gave up the CPU |

Only `running` makes progress.

**Blocking is the one that matters.** Preemption and interrupts just slow a task down.
Blocking changes what the program does next. And the wake-up event says *why* it was waiting -
something you cannot know in advance.

Two kinds of blocking:

- **Woken by another task** (kernel mode). Examples: mutex contention, an empty or full pipe,
  other inter-process communication. Speed up that other task and the wait shrinks.
- **Woken by an interrupt.** The interrupt vector names the device - a timer, a disk. For a
  network interrupt, you can follow the packet back to the task that sent it.

**Why this is better than tracing system calls.** Take `select()`. It returns when a file
descriptor is ready, or on timeout. The wake-up source tells you which happened: a local
thread's `write()`, the timer interrupt, or a remote message. You learn this without knowing
the system call, its arguments or its return value.

---

## 5. Events the method needs (Table 1)

| Category | Event | How it is collected |
|---|---|---|
| scheduler | `sched_ttwu` | **kprobe** on `try_to_wake_up()` |
| scheduler | `sched_switch` | tracepoint |
| interrupt | `hrtimer_expire_entry` / `_exit` | tracepoint |
| interrupt | `irq_handler_entry` / `_exit` | tracepoint |
| interrupt | `softirq_entry` / `_exit` | tracepoint |
| network | `inet_sock_local_in` / `_out` | **netfilter** hook |

**Why `sched_ttwu` and not `sched_wakeup`.** The standard `sched_wakeup` tracepoint runs on
the *destination* CPU, inside an inter-processor interrupt. That loses the source of the
wake-up - which is the whole point. So they add a kprobe on `try_to_wake_up()`, which fires at
the real call site before the IPI is sent.

LTTng is the tracer used. The paper says this is an implementation detail: any tracer with
precise monotonic timestamps (such as Perf) would do.

---

## 6. Trace synchronisation (only needed for multi-host)

Distributed traces have no shared clock. The analysis needs message order preserved and local
durations kept accurate.

| Method | Why it was rejected or chosen |
|---|---|
| NTP | accurate to ~milliseconds. Ethernet message latency is microseconds, so messages can appear out of order. Rejected |
| Lamport logical clock | gives order, not absolute elapsed time. Also invasive - clock values ride along with messages. Rejected |
| Controlled Logical Clock | gives global time and is non-invasive, but corrects locally at each packet. Less precise. Rejected |
| **Convex hull** | **chosen.** Fits a linear offset+drift relation per pair of hosts, using many send/receive points at once |

For three or more hosts, transforms compose along a graph of hosts. If that graph is
connected, global time can be recovered.

---

## 7. The execution graph and the active path

**Graph.** A DAG stored as a two-dimensional doubly linked list.

- **Horizontal edges** = task states over time.
- **Vertical edges** = signals between tasks: a wake-up, or a network packet.
- A vertex is an event with a timestamp; every edge goes forward in time.

**Algorithm 1 (build the graph)** walks the trace once:
- `sched_switch` → two edges: the previous task stops running, the next task was preempted.
- `sched_ttwu` → the target was blocked, the source was running, plus a vertical wake-up edge.
- interrupt entry/exit → maintain a per-CPU stack of placeholder interrupt "tasks", so nested
  interrupts are handled.
- packet out → new vertex on the sender, held in an unmatched-packet set.
- packet in → find the match, new vertex on the receiver, vertical `network` edge between them.

A design detail worth copying: the transmit vertex is added **immediately**, not when the match
is found. Waiting would need a graph seek and would break linear time.

**Algorithm 2 (active path).** The active path is the execution path with every blocking edge
replaced by the work that ended it. Walk forward through the task's states. On hitting a
blocked state, follow the incoming wake-up edge and walk **backward**, collecting what you
pass. If you meet an incoming packet, follow it back to the sender. If you meet another
blocking edge, recurse. Stop when you reach the start of the blocking interval, then resume
forward.

**Complexity: O(n) for both**, n = number of events. Each connected component is visited once.

---

## 8. Evaluation setup

- Ubuntu 14.04, Linux 3.13, LTTng 2.4.
- Local and VM tests: Intel i7-4770, 16 GB RAM, 1 TB SSD. KVM as hypervisor.
- Bare-metal cluster: 4 nodes, dual-core AMD Opteron 246, 4 GB RAM, Gigabit Ethernet.
- Analyzer written in Java, as Eclipse plug-ins.

### 8.1 Host type makes no difference

Same RPC workload run three ways: one host, two VMs, two physical machines. **All three give
the same structural result.** Loopback traffic produces the same event structure as a real
interface. So the method does not care where the peer is.

One difference: for large local transfers the client may be *preempted* inside `sendto()` by
the server, where remotely it would *block*. The preemption is visible in the trace anyway.

### 8.2 Network latency

Traffic shaping with `tc` at natural latency, 10 ms and 100 ms. The network share of the
active path grows with latency, as expected.

Note: the DNS lookups at the start show as **unresolved** network wait, because the UDP packets
and the DNS server were not traced.

### 8.3 Asynchronous processing shrinks what you can see

With a busy-loop between send and receive at 0%, 50% and 100% async:
- more async work → smaller blocking window → less of the server's work is visible;
- at 100%, the task never blocks, so the active path shows no control-flow change at all.

**Event loops distort this too.** A `poll()` loop with a 16 ms timeout (60 Hz UI refresh) turns
one long wait into many small timeouts. Only the last interval is attributed to the server. The
paper says the resulting blocking window "will not reflect the actual wait for the resource"
and calls better handling future work.

---

## 9. Five real systems (Section 3.4)

| System | What it showed |
|---|---|
| **Java RMI** | Client waits twice on the registry, three times on the compute engine. Synchronous by nature, so results are accurate |
| **CIFS / Samba share** | `ls` waits twice on the file server - in `newstat()` and `getdents()`. Even `ls` can be a distributed program. Also caught `cifsd` receiving the reply and waking the client, visible only because tracing is system-wide |
| **Django Poll web app** (Apache + PostgreSQL, each in its own KVM) | Control flow bounces between the Apache worker and the database; near the end `postgres` blocks in `fdatasync()` |
| **Erlang echo server** | Works for the Erlang runtime. In one of ten round trips the path did **not** reach the server, because the client was preempted just before blocking, shrinking the window |
| **MPI (OpenMPI)** | `MPI_Barrier()` is a **busy wait**. It looks like ordinary CPU work to the kernel. Needed user-space instrumentation to see the wait at all |

**The MPI result is the important caveat.** Busy waiting is invisible to this method. OpenMP
has the same issue, but setting `OMP_WAIT_POLICY=PASSIVE` makes it block, and then the method
works with no user-space help.

---

## 10. Cost (Section 3.5)

**Tracing overhead**

| Workload | Result |
|---|---|
| `netperf`, 16 kio messages | 424 Mbit/s **with and without** tracing - no measurable impact |
| `wk-rpc` tight loop, 32-byte messages | **+18.3%** latency, 155.9 → 190.8 µs (95% CI 34.7-35.1, p < 0.01). This is the worst case |
| Django web app | **+5.1%** latency, 116.3 → 122.5 ms (95% CI 4.8-7.7, p < 0.01). This is the typical case |

- About **200 ns per event**. Total cost scales with event *rate*, not just count.
- Trace consumer daemon used **0.8-8.2% of one CPU**, proportional to event rate (R² = 0.91).
- **Interrupts are the most frequent event type in all three workloads.** To cut overhead,
  target interrupt events first.

**Analysis scalability**

- Both algorithms are linear in the number of requests. Largest trace ~500 MB.
- Graph construction dominates - about **two orders of magnitude** more time than extracting
  the path.
- Roughly **half** of graph-construction time is just reading the trace.
- Once built, the active path for the largest trace returns in **under 0.5 s**.

---

## 11. Two optimisations (Section 3.6)

**Two-step synchronisation with packet expiry.** Matching packets across skewed traces can hold
every packet in memory. Fix: shift traces to a common origin, run a coarse convex-hull pass
until the host graph is connected at better than 1% precision, dropping packets left unmatched
after a delay. Then synchronise normally.
- **319× lower peak memory** on a 126 MB three-tier trace, same precision.
- Costs **+16.8%** processing time (95% CI 14.5-19.1).

**Fast integer timestamp transform.** Nanosecond epoch timestamps are ~10¹⁸. Multiplying in
double precision breaks monotonicity, so the baseline used Java `BigDecimal`. Rewriting the
linear function so the changing part fits in 32 bits, with the slope scaled by 2³⁰, lets it run
in 64-bit integers with a bit shift for the division.
- **155× faster** on a microbenchmark (10.1 s → 65 ms for 2²⁵ timestamps).
- **-20.8%** trace reading time overall (95% CI -16.4 to -25.3).

---

## 12. Stated limits and future work

1. **Busy waiting is invisible.** Spinlocks and polling do not enter the kernel. The paper
   argues network delays usually dwarf CPU speed, so most distributed apps block anyway.
2. **Event loops with timeouts** split one wait into many, so the blocking window misstates the
   real wait.
3. **Memory scalability.** Graph size grows with state-changing events. Traces bigger than RAM
   need a different approach - they suggest resolving blocking intervals bottom-up and deleting
   vertices once resolved.
4. **Untraced peers show as unresolved**, as the DNS server did.
5. **No source-code link.** Relating the active path to source would need user-space tracing,
   stack sampling or performance counters.
6. Tracing interrupts is the biggest overhead. Replacing interrupt entry/exit events with
   per-event context could help, but was not measured.

---

## 13. What this means for our work (read before citing)

**What it supports.** This is the citation for the claim that scheduler, interrupt and network
events are enough to explain where time goes, and that blocked / running / preempted is a
sound decomposition. It also supports host-only diagnosis without touching the application.

**Where our setup differs - this matters.**

| The paper needs | We have | Consequence |
|---|---|---|
| `sched_ttwu` via kprobe | `sched_wakeup` tracepoint | We lose the wake-up **source** on cross-CPU wake-ups, which is exactly what the method depends on |
| `inet_sock_local_in` / `_out` via netfilter | `net_dev_xmit`, `net_if_receive_skb` | Ours are device-level, not socket-level. Matching a packet to a *task* is harder |
| Multi-host traces + convex hull sync | one host, one trace | The whole synchronisation half of the paper does not apply to us |

So we **cannot** claim we implemented active-path analysis. We can cite the paper for the
principle - the wake-up tells you the wait cause - and we should say plainly which events we
enabled.

**Two findings we can use directly.**

- **Interrupts dominate event volume.** The paper measured this across three workloads. Our own
  traces run about 1.56 million events per second, which is consistent. If we ever need to cut
  trace size, interrupt events are the first target.
- **Overhead numbers to compare against.** 18% worst case, ~5% typical, ~200 ns per event.
  These are the reference numbers for any overhead claim we make.

**One caveat for our JVM services.** The paper shows busy-wait is invisible. Our blueprint 6
makes the opposite-facing point: JVM parking is *always* visible as futex, even with no
contention. Both are true and they are different failure modes of "futex means contention".

---

## 14. Safe claims

- Kernel scheduling, interrupt and network events are sufficient to recover why a task waited,
  without instrumenting the application.
- Blocking - not preemption - is what changes control flow; the wake-up event identifies the
  cause.
- The approach is runtime-independent: demonstrated on C/C++, Java, Python and Erlang.
- Tracing overhead: 18.3% worst case, 5.1% on a typical web workload, ~200 ns per event.
- Graph construction and active-path extraction are both linear in trace size.
- Busy-wait synchronisation (OpenMPI barriers, spinlocks) is invisible to the method.

## 15. Do NOT claim

- That the method recovers application-level requests. It explicitly does not.
- That it works without the kprobe on `try_to_wake_up()`. The stock `sched_wakeup` tracepoint
  loses the source.
- Any accuracy or precision number. The paper reports **no** detection accuracy - it is a
  visualisation and attribution method, not a classifier.
- That we reproduced it. We have neither its event set nor its multi-host setup.

## 16. Reusable ideas

- **Wake-up source as the cause of a wait.** One rule, applied recursively, crosses threads and
  machines.
- **Graph with two edge kinds:** horizontal for state over time, vertical for causality between
  tasks. Simple and linear to build.
- **Insert the transmit vertex before its match arrives**, to keep construction linear.
- **Decide what a system call was waiting for from the wake-up**, not from its arguments.
- **Coarse-then-fine synchronisation** with packet expiry, when memory is the limit.
- **Report worst-case and typical overhead separately.** A tight RPC loop and a web app give
  very different answers (18% vs 5%).
