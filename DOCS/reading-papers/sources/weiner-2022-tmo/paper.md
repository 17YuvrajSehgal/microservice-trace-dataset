# Paper Context: TMO — Transparent Memory Offloading in Datacenters (ASPLOS 2022)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> **This is the paper behind PSI**, which our pack cites via the kernel docs. It defines `some`
> and `full` precisely, says exactly which kernel events feed each resource, and — most useful for
> us — explains **what operators had to do before PSI existed**, which is almost exactly what our
> blueprints do. See §8.

---

## 1. Bibliographic info

- **Title:** TMO: Transparent Memory Offloading in Datacenters
- **Authors:** **Johannes Weiner**, Niket Agarwal, Dan Schatzberg, Leon Yang, Hao Wang,
  Blaise Sanouillet, Bikash Sharma, **Tejun Heo**, Mayank Jain, Chunqiang Tang (Meta)
- **Venue:** **ASPLOS 2022**, 28 February - 4 March, Lausanne
- **DOI:** 10.1145/3503222.3507731

```bibtex
@inproceedings{weiner2022tmo,
  title     = {{TMO}: Transparent Memory Offloading in Datacenters},
  author    = {Weiner, Johannes and Agarwal, Niket and Schatzberg, Dan and Yang, Leon and Wang, Hao and Sanouillet, Blaise and Sharma, Bikash and Heo, Tejun and Jain, Mayank and Tang, Chunqiang},
  booktitle = {ASPLOS 2022}, year = {2022},
  doi       = {10.1145/3503222.3507731}
}
```

Weiner and Heo are Linux memory-management and cgroup maintainers. **PSI was upstreamed into the
Linux kernel from this work**, and the kernel documentation our pack already cites is Weiner's.

---

## 2. One-paragraph summary

Memory is the biggest cost in Meta's fleet, so they move **cold memory to cheaper tiers** —
compressed memory (zswap) or NVMe SSD. The hard part is knowing **how much** to offload without
hurting the application, across wildly different workloads and offload devices. Their answer is
**PSI (Pressure Stall Information)**, a kernel mechanism that measures **lost work due to resource
shortage**, per process and per container, for CPU, memory and I/O. A userspace agent called
**Senpai** applies **mild, deliberate memory pressure** and watches PSI to find each workload's
true working set. **Deployed across millions of servers, TMO saves 20-32% of total memory** —
7-19% from application containers and about 13% from sidecars.

---

## 3. What PSI actually measures

This is the definitional section, and it is worth having exactly.

> **PSI exposes a metric that represents the amount of lost work due to the lack of a resource.**
> It can be measured for a single process, a container or machine-wide.

The mechanics:

- **Only non-idle processes count.** For each, PSI distinguishes time when the process is
  **runnable** from time when it is **stalled due to insufficient resources**.
- **Compute potential** = the number of non-idle processes, **capped at the number of CPUs**.
- **PSI is the proportion of compute potential that is unproductive due to resource stalls**,
  usually shown as a percentage.

### `some` versus `full`

| Metric | Meaning |
|---|---|
| **`some`** | the percentage of time in which **at least one** process in the domain is stalled waiting for the resource |
| **`full`** | the percentage of time in which **all** processes are delayed simultaneously |

Their framing: **`some` captures added latency to individual processes; `full` indicates
completely unproductive time** in the container or system.

### Which kernel events feed memory pressure

PSI records time spent on events that **occur exclusively when memory is short** — exactly three:

1. A process **triggers reclaim** when memory is full and it tries to allocate.
2. A process **waits on I/O for a refault** — a major fault against a page recently evicted from
   the file cache.
3. A process **blocks reading a page in from the swap device**.

### I/O and CPU

- **Block I/O:** they are candid that *"existing hardware provides little insight into device
  contention"*, so they **cannot separate oversubscription from expected device latency**. They
  therefore **treat any process waiting on block I/O completion as stalled**. *"This has worked
  well for us in production."*
- **CPU:** stalls are *"the periods of time when a process is **runnable but needs to wait for an
  idle CPU** to become available."* And a detail that matters to us:

  > **CPU `full` pressure is only possible within a container**, which occurs when **none of the
  > processes can execute either due to outside competition or due to configured limits on the
  > cgroup's CPU cycles.**

### Resolution and cost

- Aggregated in realtime, available at **microsecond resolution** plus **10 s, 1 m and 5 m running
  averages**.
- **Cost is scheduling latency** — logic runs on context switch. *"In real applications in our
  fleet the overhead is negligible."*
- **Enabled by default on all major Linux distributions, including Android.**

---

## 4. Why PSI rather than the alternatives

| Metric | Why it fails |
|---|---|
| **RSS** (resident set size) | *"by itself it does not capture the impact of memory, or a lack thereof, on application performance"* |
| **Promotion rate** (swap-ins/s) | ignores **the performance of the offload backend**, and cannot see the improvement as more memory becomes available |

Their evaluation makes the backend point concrete: g-swap assumes offloading must stay **below a
preconfigured promotion rate** to protect the application. **With a faster offload device, a higher
promotion rate is fine** — so a fixed rate threshold is wrong in both directions.

**PSI instead measures the application's actual slowdown**, which folds in the device
characteristics and the application's own sensitivity.

---

## 5. The sentence that describes our blueprints

> **Before PSI, operators relied on correlating indirect metrics such as kernel time, variations
> in application throughput, event counters for reclaim activity, file re-reads, and swap-ins, in
> order to estimate the resource health of workloads. This required an intuitive understanding of
> the storage hardware device characteristics and kernel behavior.**

Their example of why that is fragile: **the file read-ahead algorithm shields the application from
recorded cache re-reads to varying degrees**, so the counter and the harm are only loosely
related.

PSI, by contrast, *"measures productivity losses from qualifying stall events directly at the
process level ... takes into account differences in underlying hardware, the effectiveness of the
kernel's memory management algorithms, and even the internal concurrency (`some` vs `full`) of the
workload."*

---

## 6. Senpai and the results

**Senpai** is a userspace agent that applies **mild memory pressure** and uses PSI as feedback:

- It drives offload by **writing to cgroup control files**, triggering kernel reclaim.
- Control law uses the cgroup's **`some`** PSI against a configurable `PSI_threshold` and a
  `reclaim_ratio`.
- **TMO relies exclusively on `some` metrics.** The goal is to keep the value *"low but non-zero"*
  — enough contention that no resource goes idle, not enough to disturb the workload. In that
  band, *"the workload is provisioned with the minimum amount of the resource it requires to
  function well."*
- Also monitors **I/O PSI**, because memory PSI alone is insufficient.
- **No offline application profiling required**; works with both **SSD and zswap** backends.

**Results:** deployed across **millions of servers**; **20-32% of total memory saved** — **7-19%
from application containers, ~13% from sidecars**. NVMe SSDs offer *"an order of magnitude cost and
power savings compared with compressed memory."*

PSI's other stated use: **large `full` pressure detects unacceptable productivity loss** — from
overlapping workload and maintenance peaks, application bugs, or configuration and scheduling
errors. Notably:

> **Long before the kernel's out-of-memory killer triggers, applications can be functionally out
> of memory** when the lack of it causes delays that prevent the application from meeting its SLO.

Userspace OOM killers can watch `full` and act on that.

---

## 7. What kind of paper this is

- A **deployed production system** at Meta scale, plus **a kernel mechanism that was upstreamed**.
- Its purpose is **resource provisioning**, not diagnosis — though §3.2.4 explicitly claims PSI
  *"provides the ability to root-cause performance problems or SLO violations."*
- Signal is **PSI counters**, not traces.

---

## 8. What this means for our work

**Our pack cites the PSI kernel docs and says: "PSI is not in your LTTng trace, but you can rebuild
it from the runnable-but-waiting time between `sched_wakeup` and `sched_switch`."** This paper
confirms that reading is right for the CPU component, in the authors' own words: CPU stalls are
*"the periods of time when a process is runnable but needs to wait for an idle CPU to become
available."* **That is exactly the quantity our blueprints call runnable-wait.**

**Three precise things we can take.**

**1. `some` versus `full` is a distinction our blueprints should make and currently do not.**
`some` = at least one process stalled. `full` = all of them. We compute aggregate waits per
container without separating these, and they mean different things — `some` is added latency,
`full` is total unproductivity. **It is computable from what we already collect**, and it would
sharpen `host-cpu-saturation` (expect high `some`, lower `full`) against `service-cpu-throttle`.

**2. Their definition of CPU `full` is a direct statement of blueprint 10's discriminator.**

> CPU `full` pressure is **only possible within a container**, which occurs when **none of the
> processes can execute either due to outside competition or due to configured limits on the
> cgroup's CPU cycles**

Those two causes are exactly our `cpu-contention-co-tenant` and `service-cpu-throttle`, named by
the kernel's own PSI author as the only two ways to reach CPU `full`. **We separate them with
`next_comm=swapper` versus a foreign task.** This is a clean mechanism-level citation for why
those are the only two candidates.

**3. The three memory-pressure events are a ready-made discriminator list for
`service-memory-cap`.** Reclaim on allocation, refault I/O, and swap-in blocking. Our
`service-memory-cap` blueprint looks for cgroup memory limits; **these three events are what the
kernel itself counts as evidence of memory shortage**, and they are visible in a kernel trace.
Worth checking which of the three our profile actually captures.

**And one warning aimed straight at us.** Their rejection of **promotion rate** is a rejection of
**fixed rate thresholds**:

> the promotion rate ... does not take into account the performance characteristics of the
> offloading backend ... **with a faster offloading device, a higher promotion rate can be
> tolerated**

Generalised: **a rate threshold tuned on one hardware configuration is wrong on another.** Our
blueprints carry ratio thresholds measured on one GCP VM shape. **This is the second independent
warning about rate-based features today** — REPLICAWATCHER measured syscall rate varying
substantially between identical replicas; TMO argues rate thresholds do not transfer across
hardware. Together they are a good reason to prefer **structural discriminators** (who was on the
CPU, was it swapper, was the process runnable) over **magnitude thresholds**, which is what our
better blueprints already do.

**The "before PSI" paragraph is worth quoting in the thesis.** Correlating kernel time, throughput
variation, reclaim counters, file re-reads and swap-ins, needing *"an intuitive understanding of
the storage hardware device characteristics and kernel behavior"* — **that is a description of
what a kernel-trace blueprint does.** Meta's response was to add a kernel mechanism that measures
the thing directly. Ours is to encode the expert intuition so an agent can apply it. **Both are
answers to the same problem**, and saying so is more honest than implying nobody noticed.

**A limit to state.** PSI is a **counter interface** (`cpu.pressure`, `memory.pressure`,
`io.pressure` per cgroup), not a trace. It tells you **how much** productivity was lost, never
**which other container took the resource**. Our WHERE axis is the thing PSI cannot do, and that
is the cleanest statement of our contribution relative to it.

**One number for the dataset motivation.** *"Long before the kernel's OOM killer triggers,
applications can be functionally out of memory."* That is Meta saying the standard failure signal
arrives **after** the user-visible failure — the same shape as Dai's 60% with no error message.

---

## 9. Safe claims

- **PSI measures the amount of lost work due to lack of a resource**, per process, per container,
  or machine-wide, for **CPU, memory and I/O**. It was **upstreamed into Linux** and is **enabled
  by default on all major distributions, including Android**.
- PSI counts only **non-idle** processes, separates **runnable** from **stalled**, defines
  **compute potential as non-idle processes capped at the CPU count**, and reports the proportion
  of that potential lost to stalls.
- **`some`** = at least one process in the domain stalled; **`full`** = all processes stalled
  simultaneously. `some` captures added latency; `full` captures completely unproductive time.
- **Memory pressure is recorded from exactly three events**: reclaim triggered on allocation,
  waiting on I/O for a **refault** (major fault on a recently evicted file page), and **blocking
  on a swap-in**.
- **Block I/O stalls cannot be attributed to contention versus normal device latency**, so **any
  process waiting on block I/O completion is treated as stalled**.
- **CPU stalls are time when a process is runnable but waiting for an idle CPU.** **CPU `full` is
  only possible within a container**, caused by **outside competition** or **configured cgroup CPU
  limits**.
- PSI is available at **microsecond resolution** plus **10 s / 1 m / 5 m averages**; its cost is
  **scheduling latency on context switch**, described as negligible in production.
- **RSS does not capture performance impact**; **promotion rate ignores the offload backend's
  performance** and cannot see gains from added memory. A faster device tolerates a higher
  promotion rate, so a fixed rate threshold is wrong.
- **Senpai** applies mild memory pressure driven by the cgroup's **`some`** metric plus a
  threshold and reclaim ratio, monitors **I/O PSI** as well, requires **no offline profiling**,
  and supports **SSD and zswap**. TMO relies **exclusively on `some`**, kept **low but non-zero**.
- **TMO runs across millions of Meta servers and saves 20-32% of total memory** — 7-19% from
  application containers, ~13% from sidecars. NVMe SSDs give an order of magnitude cost and power
  saving over compressed memory.
- **Before PSI, operators correlated kernel time, throughput variation, reclaim counters, file
  re-reads and swap-ins**, which *"required an intuitive understanding of the storage hardware
  device characteristics and kernel behavior"*.
- **Applications can be functionally out of memory long before the kernel OOM killer triggers.**

## 10. Do NOT claim

- That PSI localises anything. It reports **how much productivity was lost** per cgroup; it never
  says **which other container** caused it.
- That PSI is in our trace. It is a **counter interface** (`cpu.pressure` etc.); we would have to
  reconstruct the CPU component from `sched_wakeup` / `sched_switch`.
- That the I/O pressure metric distinguishes contention from slow hardware. **The authors say it
  cannot**, and treat all block-I/O waiting as stalled.
- That TMO diagnoses faults. It is a **memory provisioning system**; the RCA claim in §3.2.4 is a
  stated capability of PSI, not an evaluated result.
- That 20-32% is a general offloading figure. It is **Meta's fleet, their workloads, their
  hardware**.

## 11. Reusable ideas

- **Measure the harm, not a proxy for it.** RSS and promotion rate are counts; PSI is lost work.
  Every rate threshold in our blueprints is a proxy, and this paper is the argument for preferring
  the thing itself.
- **`some` versus `full` is a cheap, meaningful split** — one process hurting versus all of them —
  and it is computable from data we already have.
- **A threshold tuned to one device is wrong on another.** Their promotion-rate critique
  generalises to every magnitude threshold we carry from one VM shape.
- **Say when you cannot attribute.** Treating all block-I/O waiting as stalled, and explaining
  why, is exactly the honesty our blueprints need about futex and lock waits.
- **Keep pressure low but non-zero.** A resource with *zero* contention is over-provisioned. A
  useful reframing: the absence of a signal is itself information.
