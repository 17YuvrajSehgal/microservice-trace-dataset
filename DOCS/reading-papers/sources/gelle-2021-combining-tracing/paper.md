# Paper Context: Combining Distributed and Kernel Tracing for Performance Analysis of Cloud Applications (Electronics 2021)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is the **closest paper in the whole pack to what we do**: same tracer, same clock trick,
> same application type, and a use case that is our blueprint 10 almost exactly. It is also by
> Ezzati-Jivan (Brock) and Dagenais (Polytechnique). Read §8 carefully — it both supports us and
> tells us what our contribution actually is.

---

## 1. Bibliographic info

- **Title:** Combining Distributed and Kernel Tracing for Performance Analysis of Cloud
  Applications
- **Authors:** Loïc Gelle (Polytechnique Montréal), Naser Ezzati-Jivan (Brock University),
  Michel R. Dagenais (Polytechnique Montréal)
- **Venue:** *Electronics* (MDPI), 2021, 10(21), 2610. Open access, CC BY.
- **DOI:** 10.3390/electronics10212610
- **Published:** 26 October 2021

```bibtex
@article{gelle2021combining,
  title   = {Combining Distributed and Kernel Tracing for Performance Analysis of Cloud Applications},
  author  = {Gelle, Lo{\"i}c and Ezzati-Jivan, Naser and Dagenais, Michel R.},
  journal = {Electronics}, volume = {10}, number = {21}, pages = {2610}, year = {2021},
  doi     = {10.3390/electronics10212610}
}
```

---

## 2. One-paragraph summary

Distributed tracing tells you **where** a request spent its time, but not **why** — it only sees
high-level spans, so kernel-level contention on CPU, disk, network or mutexes is invisible to it.
Kernel tracing sees the why but has no idea which user request it belongs to. This paper joins
them: it **instruments the Jaeger client with LTTng-UST** so that starting or finishing a span
emits a user-space event carrying the request ID. Because **LTTng uses the same clock for kernel
and user-space events**, the two streams are synchronised for free, with no kernel-mode
transition per span. On top of the joined trace they extend Trace Compass's **critical path**
analysis from threads to requests. Overhead is **about 5% for HotROD** and **18-30% for
Cassandra**; analysis of a 500 MB trace takes about **15 seconds**.

---

## 3. The problem, in their words

- Cloud applications pile on abstraction layers — RPC middleware, containers, VMs, language
  runtimes with their own threading and GC. Each one makes deployment easier and **debugging
  harder**.
- Distributed tracing gives **correct information about the flow and duration of requests but
  cannot explain why some subrequests are too long** when the cause is OS-level contention:
  waiting on CPU, disk, network or mutexes.
- Kernel tracers see those events but **cannot carry the tracing context** the way a distributed
  tracer does — propagating it would cost too much.

So: a hybrid is necessary, and the hard part is joining the two **without paying for it**.

---

## 4. The collection design — the part most relevant to us

Three pieces:

1. **Instrument the distributed tracer, not the application.** They patch the **Jaeger client**
   (Java and Go) to emit an **LTTng-UST event on every span start and span finish**. The event
   carries the minimum needed: **the unique request identifier**.
2. **Let LTTng do the clock work.** *"Because LTTng uses the same clock for kernel and user-space
   events, all the events emitted by a user application will be synchronized with the kernel
   trace without any additional work needed."* This is the whole trick, and it is why they avoid
   the cost other approaches pay.
3. **Stay in user space.** Earlier synchronisation techniques rely on **vertical context
   propagation** and so **switch into kernel mode on every event**. They compare against a "fake
   syscall" technique and measure it costing **17-18% more** than their approach.

They also note a subtlety worth remembering: **timestamp precision changes the answer**. If a
span-start event lands just before or just after a `sched_switch`, the analysis attributes the
request to a different thread and computes a different critical path.

**Thread-to-request mapping.** Each sub-request is tied to the thread that started it, and that
thread's critical path is taken as the request's. A thread may only be associated with **one
request at a time**; where several are possible, the **most recently started** wins (their
Algorithm 1 keeps a stack). **Requests migrating between threads are not handled** — they call
this out as future work.

---

## 5. The critical path analysis

- Trace Compass already computes a **thread** critical path: the longest chain of waiting, built
  from context switches and mutex operations, output as intervals plus arrows showing blocking
  and wake-up links.
- Their contribution extends it to **requests**, and to **interactions between requests**.
- The key structure: **two threads can share a state** in their critical paths — e.g. two threads
  waiting on the same mutex held by a third. That shared state is how contention between
  arbitrary numbers of critical paths becomes visible in one graph.
- Result: you can see that two requests are slow **because of contention between their underlying
  threads**.

---

## 6. Measured overhead

Two applications, several scenarios. A = no tracing, B = Jaeger only (baseline), C = their
solution, D = the fake-syscall alternative.

**HotROD (Jaeger's demo app), 10,000 requests, 10 client threads, 100% sampled:**

| | Overhead vs Jaeger-only baseline |
|---|---|
| Their solution, **LTTng snapshot mode** | **below 4%** |
| Their solution, **standard mode** | **about 5%** |

They compare that to Borderpatrol's ~10-15% and X-Trace's ~15% throughput loss, and argue their
overhead is low enough for production.

**Cassandra, high throughput, only 10% of requests sampled:**

| Workload | Snapshot mode | Standard mode |
|---|---|---|
| Read | **below 18%** | **below 27%** |
| Write | **below 27%** | **about 29%** |

Their own explanation: **Cassandra's requests are much shorter**, so per-event kernel tracing cost
is a much bigger fraction. They are explicit that **10% sampling is fine for benchmarking but
unreasonable for production**, and that lower sampling is the trade-off.

**Analysis time.** Scales **linearly** with trace size. **About 15 s for a 500 MB trace**, which
is 20-30 s of tracing. Parallelisation in Trace Compass is near-perfect: the extended critical
path analysis alone takes almost as long as the full analysis including the kernel pass.

---

## 7. The use case — this is our blueprint 10

They inject a fault and diagnose it. **The fault is a CPU control-group limit.**

Setup: Cassandra under constant load, **all its threads in a cpu cgroup**, limit set to **1% of
available CPU**, then **waived a few seconds later**.

What they observed, in order:

1. **Identical requests take wildly different times** — about **2 s** during the fault versus
   about **5 ms** after. The slow ones spend most of their time waiting on CPU or on another
   request.
2. Threads show as **waiting-for-CPU or blocked**, with only small slices of running.
3. **The CPU becomes significantly underused** while the limit is in force, and returns to normal
   when it is waived.
4. Zooming into one 600 ms request: **a pattern of recurring preemption every 100 ms**.
5. The critical path summary shows **PREEMPTED dominating the time**.
6. The decisive evidence: **threads are preempted but not replaced**. Their Table 5 shows the
   raw event —

   ```
   sched_switch  prev_comm=java, prev_tid=7949, prev_prio=20, prev_state=0,
                 next_comm=swapper/2, next_tid=0, next_prio=20
   ```

   The java thread is replaced by **swapper**, i.e. **the CPU goes idle**, and `prev_state=0`
   means the thread **could still have run**. So nothing of higher priority took the CPU —
   the group was simply banned from running.

They also note the kernel events for the limit being applied and waived are themselves
identifiable in the trace.

**Why they chose this fault:** *"CPU contention is a frequent source of problems and is difficult
to diagnose without kernel tracing"*, and a cgroup limit is **more difficult to diagnose than
competing threads**, which makes it a better test.

---

## 8. What this means for our work

**This paper independently confirms blueprint 10's core discriminator.** Our
`cfs-throttling-quota` blueprint says: look for `sched_switch` with **`prev_state=0` and
`next_comm=swapper`** — runnable, yet the CPU goes idle — recurring on the **100 ms CFS period**.
Gelle et al. found exactly that, from a real injection, four years earlier, and published the raw
event. **This is the single strongest external validation in the pack of anything we claim.** The
blueprint should cite it as confirmation, not just as background.

**Their 100 ms is `cfs_period_us` and they do not say so.** They report "preempted every 100 ms"
as an observation. We know the mechanism: the default CFS bandwidth period is 100 ms, and quota
is refilled at that boundary. Naming it is a small thing we can add on top of their finding.

**It also tells us clearly what our contribution is not.** We are not the first to join kernel
traces with request context, and we are not the first to diagnose a cgroup CPU limit from
`sched_switch`. What is different:

| Gelle et al. 2021 | Us |
|---|---|
| **One fault**, injected to demonstrate the tool | **24 fault families**, 303 labelled runs |
| Requires **patching the Jaeger client** | **no application or tracer changes** — kernel trace only |
| Output is a **view for a human** in Trace Compass | output is a **decision** from an agent, scored |
| No ground truth, no scoring | pre-registered predictions, WHERE/window/label scoring |
| Cassandra and HotROD | Sock Shop and Train Ticket, 7 to 67 containers |

**Our actual claim is the harder one:** they had the request context and still needed a human to
read the views. We ask whether the kernel trace **alone** is enough to name the container. That
is a different question, and this paper is the right thing to position against.

**A method we should consider adopting.** Their critical path over threads, with **shared states
marking contention**, is a better structure than our per-signal aggregates for faults where two
containers fight. Trace Compass already implements the thread-level version. If blueprint 7
(`cpu-contention-co-tenant`) ever needs to show *which* container blocked *which*, this is the
published algorithm to follow.

**A number we should quote, carefully.** Their overhead is **4-5% on HotROD but 18-30% on
Cassandra**, and the reason is **request duration** — short requests pay more per event. Our own
overhead numbers come from Sock Shop, whose requests are short. **If we report a single overhead
percentage without saying what the workload was, we are making the mistake this paper shows you
cannot make.** Their honesty about 10% sampling being unacceptable in production is the right
tone for ours too.

**One limitation they share with us.** They cannot follow a request that **migrates between
threads**, and say so. We have the same blind spot in a stronger form: we never see request
identity at all.

---

## 9. Safe claims

- Distributed tracing gives correct request flow and duration but **cannot explain why a
  subrequest is slow** when the cause is OS-level contention on CPU, disk, network or mutexes.
- Their solution instruments **only the Jaeger client**, emitting an **LTTng-UST event on span
  start and finish** carrying the request ID. **No application patching.**
- **LTTng uses the same clock for kernel and user-space events**, so the two traces are
  synchronised with no extra work and no kernel-mode transition per span.
- Earlier approaches use vertical context propagation and enter kernel mode per event; their
  measured "fake syscall" comparison costs **17-18% more**.
- They extend Trace Compass's thread critical path to **requests**, and represent contention as
  **shared states between critical paths**.
- Overhead versus Jaeger-only: **below 4% (snapshot) / about 5% (standard) on HotROD** at 100%
  sampling; **18-27% read, 27-29% write on Cassandra** at 10% sampling. Shorter requests pay
  proportionally more.
- Analysis scales **linearly** with trace size: **~15 s for 500 MB**, about 20-30 s of tracing.
- Use case: Cassandra threads in a cpu cgroup limited to **1% of CPU**. Identical requests took
  **~2 s** during the fault versus **~5 ms** after; **PREEMPTED dominated the critical path**;
  **preemption recurred every 100 ms**; **the CPU became underused**; and `sched_switch` showed
  the java thread **replaced by swapper with `prev_state=0`** — preempted but not replaced.
- They state that **CPU contention is a frequent source of problems and is difficult to diagnose
  without kernel tracing**, and that a cgroup limit is harder to diagnose than competing threads.

## 10. Do NOT claim

- That it works without instrumentation. It needs a **patched Jaeger client**, though not a
  patched application.
- That overhead is "about 5%". That is **HotROD only**; Cassandra is 18-30% at 10% sampling.
- That it handles requests moving between threads. The authors say it does not.
- That it evaluates many faults. It demonstrates **one**, a cgroup CPU limit, in a controlled
  environment — and they call the contention "artificial rather than emerging from a natural
  scenario".
- That it scores or evaluates diagnosis accuracy. There is no ground truth and no metric; the
  output is a view a human reads.

## 11. Reusable ideas

- **Instrument the tracer, not the application.** One patch to Jaeger buys request context for
  every app that uses it.
- **Let one clock do the joining.** The reason this is cheap is that LTTng timestamps kernel and
  user-space events from the same source — the same property our `otel-to-lttng.py` relay depends
  on.
- **Preempted but not replaced is the signature.** `prev_state=0` plus `next_comm=swapper` is a
  two-field test that separates "banned from running" from "someone else took the CPU". Published
  evidence, and we should cite it.
- **Shared state = contention.** Representing two critical paths that touch the same resource as
  sharing a state is a clean way to make contention a graph property rather than a heuristic.
- **Report overhead per workload, not as one number.** Their 5% and 30% come from the same tool;
  what changed was request duration.
