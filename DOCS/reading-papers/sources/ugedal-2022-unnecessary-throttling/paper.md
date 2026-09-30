# Paper Context: Mitigating Unnecessary Throttling in Linux CFS Bandwidth Control (SBAC-PAD 2022)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is the **mechanism source for blueprint 10** (`service-cpu-throttle`) and it explains a
> discriminator that would otherwise look wrong: **a container can be throttled while its
> average CPU use is below its quota**. Section 10 has the numbers we should cite.

---

## 1. Bibliographic info

- **Title:** Mitigating Unnecessary Throttling in Linux CFS Bandwidth Control
- **Authors:** Odin Ugedal (NTNU, Norway), Rakesh Kumar (NTNU, Norway)
- **Venue:** SBAC-PAD 2022 (IEEE International Symposium on Computer Architecture and High
  Performance Computing)
- **PDF:** https://rakeshk.folk.ntnu.no/pubs/SBACPAD22.pdf
- **Length:** 10 pages

```bibtex
@inproceedings{ugedal2022mitigating,
  title     = {Mitigating Unnecessary Throttling in Linux CFS Bandwidth Control},
  author    = {Ugedal, Odin and Kumar, Rakesh},
  booktitle = {SBAC-PAD 2022}, year = {2022}
}
```

---

## 2. One-paragraph summary

CFS Bandwidth Control caps how much CPU a cgroup can use. Containers everywhere depend on it -
Docker, Kubernetes, Borg. This paper shows it **throttles processes that have not used their
quota**. The cause is bookkeeping. CPU time is counted only at scheduler ticks, so a process
can overrun its remaining budget between two ticks and leave the per-CPU pool with a
**negative** balance. That debt is paid back on the next refill. If the refill happens in the
**next period**, the new period starts short, and the process gets throttled near the end of it
despite using less than its quota. They also find the **spinlock** guarding the shared quota
pool is a major overhead at scale. Their fixes remove nearly all throttling (up to **12%**
faster) and cut overhead by up to **24×**.

---

## 3. Background: how bandwidth control actually works

**Two knobs per cgroup:**

| Parameter | Meaning | Default |
|---|---|---|
| **Period** | the accounting interval | **100 ms** |
| **Quota** | total CPU time the cgroup may use per period | unlimited (off) |

Quota ÷ period = how many logical CPUs the group can use continuously. 100 ms period with
300 ms quota ≈ 3 CPUs. 100 ms period with 50 ms quota ≈ half a CPU. Non-integer ratios are
fine.

**Three statistics exposed per cgroup** - these are what a monitoring system sees:

- **Periods** - periods where the group was active.
- **Periods throttled** - periods where it was stopped for using too much CPU.
- **Time throttled** - total time stopped, summed across all logical CPUs.

**Two pools do the enforcement:**

- **Global pool** - one per cgroup. An integer **protected by a spinlock**. Refilled to the
  quota at the start of each period.
- **Local pool** - one per logical CPU per cgroup. Where runtime is actually spent.

**How time is deducted.** Only at two moments: when the process is **swapped out**, or on a
**scheduler tick** while it is running. When a local pool empties, it takes the spinlock and
refills from the global pool up to one **slice** - a system-wide value, default **5 ms**.

**Throttling is per-CPU.** If a local pool cannot refill, the scheduler marks everything under
that logical CPU as throttled. **One local pool being throttled does not throttle the others.**
At the next period the refill timer distributes new quota to the throttled pools and unthrottles
them.

---

## 4. The bug: unnecessary throttling

### Why balances go negative

Two parameters cause it:

1. **Scheduler tick interval (jiffy)** - Linux supports 1 ms, 3.33 ms, 4 ms, 10 ms. Accounting
   only happens at ticks. If a pool has less runtime left than one tick, the process keeps
   running past its budget until the next tick arrives.
   - Their example: 4 ms jiffy, 1 ms left in the pool. The process runs the full 4 ms before
     anyone checks. The pool ends at **−3 ms**.
2. **Slice length** (default 5 ms) - a trade-off. Bigger slices mean fewer refills, so less
   accounting overhead *and* less accumulated negative runtime. But bigger slices also make it
   more likely that one local pool grabs more than it can use, starving the others.

### Why the debt causes throttling

When a local pool refills, its negative balance is repaid **first**. If that repayment happens
**in the same period** the overrun occurred, everything is fine. If a new period has already
started, **the debt is paid from the new period's quota** - so the new period begins short and
the process is throttled at the end of it, having used **less than its quota**.

Their worked example (10 ms period, 10 ms quota, 5 ms slice, 4 ms jiffy) ends with the process
running **8 ms of a 10 ms quota and being throttled for 2 ms**, purely because 3 ms of debt
from the previous period was charged to this one.

### A second, separate cause

**Updating the bandwidth configuration from user space resets all local pools to zero and
refills the global pool - even if the new values are identical to the old ones.** They note
system daemons and container runtimes often rewrite these values regularly to make sure they
are correct. That alone can cause throttling.

### Why "just align the slice to the tick" does not work

They address the obvious fix and reject it: processes start and stop between ticks, each local
pool may have a hierarchy of processes rather than one, quota-to-period ratios can be
fractional, and tick frequency is chosen for other reasons too.

---

## 5. Measured throttling (Table II)

Sysbench CPU, 300,000 events, three processes on three exclusive logical CPUs. Mean of 10 runs.
**The quota-to-period ratio is held constant at 3.0 throughout** - only the period changes.

| Period | Quota | Periods | Periods throttled | Throttled ratio | Throttled time |
|---|---|---|---|---|---|
| — | unlimited | 734 | 0 | **0%** | 0 ms |
| 100 ms | 300 ms | 735 | 50 | **6.8%** | 94 ms |
| 50 ms | 150 ms | 1486 | 661 | **45%** | 2,457 ms |
| 10 ms | 30 ms | 7840 | 3835 | **49%** | 14,608 ms |

**The same workload, the same CPU allowance, and throttling goes from 0% to 49% purely by
shortening the period.** At 10 ms, **18.6% of execution time is spent throttled**.

---

## 6. The overhead problem

The global pool is guarded by a **spinlock**, taken every time the pool is touched - at each
period refill and at every local-pool refill. With few waiters the cost is negligible. With
many logical CPUs under the same cgroup it is taken **thousands of times per second**, and
waiting time grows with the number of threads.

---

## 7. Their fixes

1. **Slush fund.** On refill, save the previous period's leftover runtime into a `slush_fund`
   before overwriting `runtime` with the quota, and track a period number. Negative runtime can
   then be repaid from the period in which it was actually incurred. The information was
   previously just discarded - they call it "runtime lost on quota refilling".
2. **Atomic variables instead of the spinlock** for the global pool.

**Results: nearly all throttling eliminated, up to 12% performance gain, overhead down by up
to 24×.**

---

## 8. What this means for our work

**This is the citation for blueprint 10's most counter-intuitive claim.** Our blueprint tells
the agent that a throttled container's threads all stop together while CPUs sit idle. The
obvious objection is "then its CPU usage must be at the cap". This paper shows that is **not**
required: throttling happens with average use **below** quota, because of debt carried across
period boundaries.

**The numbers we should cite, and why they matter more than the fix.** The fix is a kernel
patch we do not run. The **measurement** is what transfers:

- **0% throttling with unlimited quota**, versus **6.8% of periods at the default 100 ms**, on
  identical work.
- **Shorter periods make it dramatically worse** - 49% of periods at 10 ms.
- Throttling is **per logical CPU**, not per container. That is directly relevant to what we
  see in a trace: *some* of a container's threads stop, not necessarily all of them at once.

**The per-CPU detail is the one to be careful about.** Blueprint 10's discriminator says "all
its threads stop at the same time". This paper says throttling is applied **per local pool**,
i.e. per logical CPU, and one pool being throttled does **not** throttle the others. So the
honest signature is: *the threads on a throttled CPU stop together, while CPUs are idle* - not
necessarily every thread in the container. Worth checking against our own measurements before
the next campaign.

**A second thing worth knowing for our data.** Their §III-A2: writing the same bandwidth values
back from user space resets the pools and can itself cause throttling. Container runtimes do
this routinely. If we ever see throttling in a *baseline* run, this is a candidate explanation
rather than a collection bug.

**What we cannot see from our traces.** `nr_throttled` and `throttled_time` come from
`cpu.stat` in the cgroup filesystem, not from the kernel trace. We do not collect them. So we
infer throttling from scheduler behaviour, and this paper is the mechanism that justifies the
inference - not evidence that we measured throttling directly.

---

## 9. Safe claims

- CFS Bandwidth Control sets a **maximum**, unlike earlier mechanisms which set minimums. It
  was designed at Google to cap badly behaving applications.
- It underpins CPU limits in Docker, Kubernetes and Borg.
- Default period is **100 ms**; default slice is **5 ms**; Linux tick intervals are 1, 3.33, 4
  or 10 ms.
- Runtime is accounted **only** on scheduler ticks and on process swap-out, so a pool can go
  negative between ticks.
- **Negative runtime repaid from the next period's quota causes throttling before the quota is
  reached.**
- Measured: 0% throttled periods with unlimited quota, **6.8% at a 100 ms period**, 45% at
  50 ms, **49% at 10 ms** - same workload and same quota ratio. At 10 ms, 18.6% of execution
  time is throttled.
- Throttling is enforced **per logical CPU**; one throttled local pool does not throttle others.
- Rewriting the bandwidth configuration from user space resets local pools and can cause
  throttling even when the values are unchanged.
- Their fixes remove nearly all throttling, give up to 12% performance gain, and cut overhead
  up to 24×.

## 10. Do NOT claim

- That throttling always means the container hit its CPU limit. That is the point of the paper.
- That all of a container's threads stop together. Throttling is per logical CPU.
- That we measured `nr_throttled` or `throttled_time`. Those come from `cpu.stat`, which we do
  not collect.
- That the slush-fund fix is in mainline Linux. The paper proposes it; we run stock kernels.

## 11. Reusable ideas

- **Hold the ratio constant and vary the period** - their Table II isolates one variable
  cleanly and produces a result nobody would guess. Good experiment design to copy.
- **Look for accounting artifacts, not just resource limits.** The fault here is bookkeeping
  across a boundary, not shortage.
- **A statistic that exists is not a statistic you collect.** `nr_throttled` is right there in
  `cpu.stat` and invisible in a kernel trace. Worth knowing which of our claims depend on data
  we do not have.
