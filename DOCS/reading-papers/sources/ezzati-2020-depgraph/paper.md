# Paper Context: DepGraph — Localizing Performance Bottlenecks in Multi-Core Applications Using Waiting Dependency Graphs and Software Tracing (SCAM 2020)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited by blueprint 4 for "a waiting-dependency graph; a cycle in it = deadlock". **The paper
> never says that** — see §9. What it actually contributes is the thing Giraldeau's critical
> path leaves out: **which thread is holding the resource you are waiting on.**

---

## 1. Bibliographic info

- **Title:** DepGraph: Localizing Performance Bottlenecks in Multi-Core Applications Using
  Waiting Dependency Graphs and Software Tracing
- **Authors:** Naser Ezzati-Jivan (Brock), Quentin Fournier (Polytechnique Montreal),
  Michel R. Dagenais (Polytechnique Montreal), Abdelwahab Hamou-Lhadj (Concordia)
- **Venue:** IEEE International Working Conference on Source Code Analysis and Manipulation
  (SCAM) 2020
- **DOI:** 10.1109/SCAM51674.2020.00022
- **arXiv:** 2103.04933v1 [cs.SE], 8 March 2021

```bibtex
@inproceedings{ezzatijivan2020depgraph,
  title     = {DepGraph: Localizing Performance Bottlenecks in Multi-Core Applications Using Waiting Dependency Graphs and Software Tracing},
  author    = {Ezzati-Jivan, Naser and Fournier, Quentin and Dagenais, Michel R. and Hamou-Lhadj, Abdelwahab},
  booktitle = {SCAM 2020}, year = {2020},
  doi       = {10.1109/SCAM51674.2020.00022}
}
```

---

## 2. One-paragraph summary

A critical path tells you a thread was **blocked**. It does not tell you **who was holding the
thing it was blocked on**. DepGraph fixes that. It takes LTTng kernel traces, turns them into
per-thread states (running, waiting for disk, waiting for another thread, waiting for CPU,
contended on a lock), and builds a **Waiting Dependency Graph** covering every dependency a
thread has — not only the ones on its critical path. Because it merges the critical paths of
*all* interacting threads into a history of resource usage, it can name the blocking thread.
It also compares runs of the same task against each other, so you can ask what was different
this time. Overhead in its own tracing mode **never exceeded 10.1%**.

---

## 3. The problem, in their framing

They split root-cause work into **on-CPU** and **off-CPU** analysis:

- **On-CPU** — profilers and debuggers. Covers only the time a thread is actually executing,
  which "does not cover 100% of the duration of the program". Thread scheduling and thread
  collaboration are **outside a profiler's scope**, and debuggers require pausing the
  application.
- **Off-CPU** — waiting for disk, I/O, network, timer, or for another thread to release a lock.
  *"In many cases, most of the runtime duration lies not inside the CPU."*

Their diagnosis of what each tells you:
- **Significant on-CPU latency** usually means bad code design or an algorithmic problem.
  A profiler will find it.
- **Significant off-CPU latency** usually means system overuse or a hardware problem. **Profilers
  cannot help** — "they only rank functions or modules based on statistical metrics without
  mentioning the nature of those issues".

---

## 4. The gap they identify in Giraldeau 2016 — and it is precise

Quoted in substance from their §II:

> Giraldeau's critical path algorithm estimates the minimal active path of a task and extracts
> execution states along it. Using their tool one can see whether a thread is running or waiting
> for a resource. **Their method does not show automatically which thread is currently using the
> blocking resource at the time of the waiting.** It still requires manual investigation of the
> generated critical path to find the root cause. It shows that there is a possible blocking
> state but **does not show why this is happening and which thread is responsible.**

DepGraph's answer: aggregate the critical paths of *all* interacting threads, merge them into a
history of resource usage, and extract the thread causing the block.

A second stated limitation of critical-path analysis they address: it does not tell you whether
a waiting state is **normal** — common to all similar executions. DepGraph compares runs to
answer that.

**And the scope difference:** DepGraph provides "all dependencies between the relevant threads
and resources, **regardless of whether they are within the critical path**".

---

## 5. Method — six steps

1. **Collect** system-level traces with LTTng.
2. **Transform the trace into states**, to cut size while keeping meaning. A state is a thread
   status: *running, waiting for disk, waiting for another thread, waiting for CPU, contended
   on a lock*.
3. **Build the Waiting Dependency Graph** from those states.
4. **Group, merge, compare and analyse** graphs automatically to find root causes.

A trace event is a timestamped interaction, e.g. `(tid1, syscall_open, file1, cpu1, t1)`.

The user delimits the task of interest with start/end events, because a trace holds many
concurrent threads and you usually want one task (opening a browser tab, a compilation) rather
than everything.

---

## 6. Use cases

Three, all described as industry-level:

- **A. Lock contention**
- **B. CPU contention** — solved *"without any prior knowledge about the latency root cause"*
- **C. Disk contention**

---

## 7. Overhead (their Table I)

Relative duration, average of **50 executions**, three benchmark profiles:

| Setting | CPU | IO | Multithread |
|---|---|---|---|
| No tracing | 100.0% | 100.0% | 100.0% |
| Full tracing | 101.0% | **142.3%** | 123.5% |
| Syscall tracing | 100.5% | 108.7% | 107.3% |
| **Dependency tracing** (their mode) | **100.7%** | **110.1%** | **108.5%** |

Findings worth keeping:

- On a **CPU-bound** benchmark, tracing overhead **never exceeded 1%** regardless of setting.
- On **IO**, full tracing cost **42%** — and they diagnose why: *"the trace itself generating
  many disk IO operations, thus competing with the benchmark over the disk"*. They confirmed it
  by sending the trace over the network to a relay instead.
- Restricting to the events they need cuts system-call events by **40%**.
- **Their mode never exceeded 10.1%.**

They also note that **trace reading time dominates the analysis time**.

---

## 8. The self-competition finding is worth its own line

Full tracing on an IO benchmark cost 42% **because the tracer's own disk writes competed with
the benchmark**, not because instrumentation is expensive. Sending the trace elsewhere removed
it.

That is directly relevant to us: `CAMPAIGN-ISSUES` already records that `iops_per_irq` on
`nagle_delayed_ack` was **our own tracer's disk writes**. This paper is the citation for that
being a known artifact rather than a mistake unique to our setup.

---

## 9. What this means for our work — including a citation to fix

**Blueprint 4 currently cites this as: "a waiting-dependency graph; a cycle in it = deadlock."**

The paper does **not** say that. It never discusses deadlock, never mentions cycle detection,
and its three use cases are lock contention, CPU contention and disk contention — none of them
a deadlock. The inference is reasonable (a cycle in a wait-for graph *is* the textbook deadlock
condition) but it is **our inference, not theirs**, and the blueprint presents it as theirs.

Two honest options:
- cite it for what it does say — *waiting dependencies between threads and resources can be
  recovered from kernel traces, and the blocking thread can be named* — and state the cycle
  argument as our own reasoning; or
- cite a wait-for-graph deadlock-detection source for the cycle claim instead.

**What it genuinely supports.** This is the best citation we have for the *ambition* of our
WHERE axis. Giraldeau tells you a thread waited; DepGraph names **who was holding the
resource**. Our blueprints stop at "this container is the culprit", which sits between the two.

**What we do not have.** DepGraph names the blocking thread by merging critical paths across
all interacting threads. We do not build critical paths at all — no `sched_ttwu`, no per-thread
dependency graph. So we cannot claim to do what DepGraph does; we approximate the *outcome*
(naming a culprit) by a different route (per-container rates against a baseline).

**One idea worth taking seriously.** Their point that critical-path analysis cannot tell you
whether a waiting state is **normal** is exactly why our discriminators compare against a
baseline rather than a fixed threshold. They solve it by comparing executions of the same task;
we solve it by comparing a window against the run's own quiet period. Same problem, same shape
of answer.

---

## 10. Safe claims

- Off-CPU time — waiting for disk, I/O, network, timer, or another thread — is where most of a
  program's duration often lies, and profilers cannot explain it.
- Critical-path analysis shows **that** a thread blocked, but not **which thread held the
  blocking resource**; that still required manual investigation.
- DepGraph builds a Waiting Dependency Graph from LTTng kernel traces covering all
  dependencies, not only those on the critical path, and names the blocking thread.
- Thread states used: running, waiting for disk, waiting for another thread, waiting for CPU,
  contended on a lock.
- Comparing executions of the same task distinguishes a normal waiting state from an abnormal
  one.
- Overhead: **never above 10.1%** in dependency-tracing mode; under **1%** on CPU-bound work;
  full tracing cost **42%** on IO, caused by the tracer's own disk writes competing with the
  benchmark.
- Restricting to the needed events cut system-call events by 40%.
- Trace reading time dominates analysis time.
- Evaluated on three industry use cases: lock, CPU and disk contention.

## 11. Do NOT claim

- **That the paper detects deadlock by finding a cycle.** It does not discuss deadlock at all.
- That we implement DepGraph. We build no dependency graph and have no `sched_ttwu`.
- That 10.1% is our overhead. It is theirs, on their event set.
- Any detection accuracy. Like the other DORSAL papers, it reports use cases and overhead, not
  precision or recall.

## 12. Reusable ideas

- **Name the blocker, not just the block.** The most useful thing a diagnosis can add is who
  was holding the resource.
- **Compare a run against other runs of the same task** to tell a normal wait from an abnormal
  one.
- **Trace states, not events.** Converting to states first is what keeps the graph small enough
  to merge and compare.
- **Check whether the tracer is competing with the workload.** Their 42% IO figure was an
  artifact of the tracer's own writes, proven by relaying the trace off-box.
- **Report overhead per workload class.** 1% on CPU and 10% on IO is far more useful than one
  averaged number.
