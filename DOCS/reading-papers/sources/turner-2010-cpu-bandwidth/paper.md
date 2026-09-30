# Paper Context: CPU bandwidth control for CFS (Linux Symposium 2010)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> **The PDF on disk is the whole 272-page OLS 2010 proceedings.** This paper is
> **pages 245-254**. Everything below comes from those ten pages.
> This is the **original design paper** for the mechanism blueprint 10 detects. Read §9 - the
> paper predicts the throttling bug that Ugedal et al. measured twelve years later.

---

## 1. Bibliographic info

- **Title:** CPU bandwidth control for CFS
- **Authors:** Paul Turner (Google), Bharata B Rao (IBM India Software Labs, Bangalore),
  Nikhil Rao (Google)
- **Venue:** Proceedings of the Linux Symposium 2010, Ottawa, **pp. 245-254**
- **PDF:** https://www.kernel.org/doc/mirror/ols2010.pdf (the full proceedings)
- **Status at the time:** patchset v2, **not yet merged**; kernel base was **v2.6.34**

```bibtex
@inproceedings{turner2010cpu,
  title     = {CPU bandwidth control for {CFS}},
  author    = {Turner, Paul and Rao, Bharata B and Rao, Nikhil},
  booktitle = {Proceedings of the Linux Symposium}, pages = {245--254}, year = {2010}
}
```

---

## 2. One-paragraph summary

CFS gives each group a **share** - a lower bound on CPU when the machine is busy. But CFS is
**work-conserving**: if the machine is otherwise idle, a group can use far more than its share.
That makes two things unpredictable: how much CPU a group actually gets, and the **maximum** it
could get. For pay-per-use hosting and latency-sensitive workloads, both matter. This paper
adds an **upper bound** - a quota per period. The interesting part is the implementation. A
purely per-CPU scheme does not converge; a purely global one does not scale. They build a
**hybrid**: a global pool per group, handed out in **slices** to per-CPU local pools, consumed
locally without extra locking. When a local pool runs dry and the global pool is empty, that
run-queue is **throttled** until the next period.

---

## 3. Background — shares are not guarantees

- Before v2.6.24 the scheduler had no entity bigger than a single task; `nice(2)` was the only
  bandwidth control.
- **v2.6.24** merged CFS, giving weight-based scheduling and enabling group scheduling via
  cgroups. Groups nest; each has a `shares` attribute. `nice(2)` became the per-task weight.
- **Shares are a lower bound, and they are relative.** Their worked example: three groups of
  1024 shares each get 33.3% when all are runnable. Add a fourth group with 2048 shares and the
  original three drop to **20%**.
- A key clarification they make: *"the concept of proportional shares is different from a
  guarantee."*
- Note also: these ratios apply only to time available to `SCHED_NORMAL`. Time in `SCHED_RT` is
  outside the model.

---

## 4. Why an upper bound was needed

The scheduler is work-conserving, so idle cycles get used. Two consequences:

1. **The actual CPU a group receives is highly variable**, depending on what else is running.
   You cannot partition a machine predictably without understanding every co-scheduled
   application.
2. **The maximum a group can get is unpredictable**, which breaks capacity planning.

Four stated use cases: **pay-per-use** (a customer objects if they get less, and the provider
does not want to give more), **virtual machines** (KVM CPU entitlements), **latency
provisioning** (non-homogeneous latency-sensitive tasks that are hard to keep apart), and
**guarantees** (derive a soft minimum from other groups' hard limits - they point to the
OpenVZ wiki for how).

---

## 5. Interfaces

| Control | Meaning |
|---|---|
| `cpu.cfs_period_us` | enforcement interval |
| `cpu.cfs_quota_us` | allowed CPU time in that interval |
| `/proc/sys/kernel/sched_cfs_bandwidth_slice_us` | how much is transferred from global to local pool per request. **Default 10 ms** at the time |

Two design notes worth keeping:

- **Limits are hierarchical, and there is no feasibility check.** If a child has a more
  permissive limit than its parent, it is **indirectly throttled** when the parent's quota runs
  out.
- They moved away from the `SCHED_RT` model (per-CPU runtime plus borrowing between CPUs) to
  **global** specification of period and quota.

---

## 6. Why the obvious designs fail

### 6.1 Local pools with borrowing (the first attempt, modelled on SCHED_RT)

Each CPU gets `cfs_runtime_us`; CPUs borrow from neighbours in the `root_domain`. Redistribution
visits every neighbour and takes 1/n of their remaining runtime.

**Why it works for RT and not for CFS:** `SCHED_RT` is provisioned with 95% of system time by
default, so one partial borrowing pass converges. When a reservation is a **small-to-medium**
fraction of the machine, convergence breaks down - each iteration gains at most (n−1)/n more
time, **at the cost of taking every `rq->lock`**, and there is "an extremely long tail of
redistribution".

### 6.2 Purely global tracking

Does not scale - the global store becomes contended. The local model's advantage is that
in-quota consumption can be accounted **locklessly** with no remote queries.

### 6.3 The hybrid (what shipped)

A `cfs_bandwidth` structure per `task_group` tracks quota globally, but **consumption happens
against a local per-`cfs_rq` store**, refilled from the global pool in configurable **batch
slices**. Refresh is periodic, once per quota period, driven by an **hrtimer**; all throttled
run-queues are unthrottled and the global pool is replenished.

---

## 7. How throttling actually works

- `update_curr()` runs on scheduler ticks and on enqueue/dequeue, charging elapsed time to the
  running entity. It now also calls **`account_cfs_rq_quota()`**, so **quota accounting happens
  at the same instant execution time is charged**.
- A `cfs_rq` is **throttled** when `local_quota_used >= local_quota_assigned` **and** the global
  pool had nothing to top it up with.
- `throttle_cfs_rq()` dequeues the `sched_entity` from its parent and sets a `throttled` flag.
  Re-entry is prevented two ways: the `entity->on_rq` flag stops a `put` returning it, and
  `enqueue_task_fair()` stops enqueueing past a throttled entity on wake-up.
- **Dequeuing continues up the tree** past the throttled entity until an ancestor still has load
  weight, because a parent with no runnable children need not stay on the RB tree.
- **A task entity is never throttled - only its parent group.** (Their footnote 5.)
- Local quota tracking needs **no extra locking** because it nests under the existing
  `rq->lock`. Only global-pool modification needs explicit locking.

---

## 8. Results

**Setup:** 16-core AMD, no affinity restrictions, kernel v2.6.34 plus their patches,
`CONFIG_FAIR_GROUP_SCHED` and `CONFIG_CFS_BANDWIDTH_CONTROL` enabled. Two cgroups: `system`
(1024 shares) and `protag` (65536 shares, big enough to mitigate interference). A monitor
thread read `/proc/stat` once a second.

**Benchmarks:** `while(1)` soakers and **sysbench** (16 threads, primes below 100,000). Both
saturate the machine without bandwidth control. Baseline for comparison was the **same limits
achieved with cpusets and CPU affinity**.

**Periods tested: 100 ms, 250 ms, 500 ms**, with quota from 1 to 16 cores' worth.

**Finding:** deviation from the affinity baseline is small, and **the deviation decreases as the
enforcement period increases**.

**Overhead** (tbench, 10 procs, ~450K enqueue/dequeue per second, 100 ms period):

| CPUs | baseline | with bandwidth control |
|---|---|---|
| 1 | 219.022 | 213.415 |
| 8 | 1668.12 | 1653.7 |
| 16 | 2451.82 | 2421.36 |

They also note that **reducing the batch slice had no measurable performance impact**.

---

## 9. The challenges they name — and one that came true

Section 6.3 lists three known problems. The first two are what Ugedal & Kumar measured in 2022.

**Slack time / local over-commit.** Time assigned locally may have come from a *previous*
period. Maximum outstanding over-subscription is **`num_cpus × batch_slice`**, constant across
any number of consecutive intervals. Their proposed mitigation: **generation counters** on
quota.

**Fairness.** Batch-sized allocation can **reduce parallelism** for a multi-threaded
application, and quota can be **"stranded"** when load-balancing leaves a local pool with no
runnable entity to spend it. Suggested fixes: smaller batch slices short-term; graduated batch
sizing or subdividing the global pool per `sched_domain` long-term.

**Load-balancer interaction** - they call their model "very primitive". Throttled run-queues are
excluded from load balancing. They explain why the obvious improvements fail:
- Migrating threads *from* a throttled run-queue to an unthrottled one breaks down under
  insufficient quota - the last run-queue with quota becomes **"that last seat in the game
  'musical chairs'"**, creating a **herd** of executing threads.
- Migrating *to* an already-throttled run-queue makes no sense either.
- Also, a throttled run-queue stops participating in group share distribution, causing
  **weight fluctuations** on re-wake.

---

## 10. What this means for our work

**This is the design document for the mechanism blueprint 10 detects.** Six things in it
directly shape what we should expect in a trace:

1. **Throttling is per `cfs_rq`, i.e. per CPU per group.** Stated here in 2010 and confirmed by
   Ugedal 2022. Blueprint 10's "all its threads stop at the same time" is **too strong** - it
   should be "the threads on a throttled run-queue stop together".
2. **Individual tasks are never throttled - groups are.** The container is the unit.
3. **Accounting happens inside `update_curr()`**, which fires on scheduler ticks and on
   enqueue/dequeue. That is why throttling is quantised to tick boundaries, and why Ugedal's
   negative-runtime problem exists at all.
4. **Throttled entities are dequeued and blocked from re-entering on wake-up.** In a kernel
   trace this looks like the threads simply stopping - no `sched_switch` to them, no run-queue
   presence - which is exactly the signature we look for.
5. **Unthrottling is hrtimer-driven, once per period.** The 100 ms default period is the
   rhythm blueprint 10 expects.
6. **Hierarchical limits with no feasibility check** means a container can be throttled by its
   *parent's* quota even when its own is generous. Worth knowing before concluding a container
   hit its own cap.

**The slack-time paragraph is the one to cite alongside Ugedal.** The original authors wrote
down the over-commit bound (`num_cpus × batch_slice`) and proposed generation counters as the
fix. Ugedal 2022 measured the resulting throttling and implemented essentially that fix (the
"slush fund"). **The bug was documented as a known caveat in the design paper and left
unresolved for over a decade.** That is a good line for the thesis: the mechanism our blueprint
detects has a well-known, long-standing accounting artifact.

**A caution on the numbers.** Everything here is from **2010 on kernel 2.6.34 with an unmerged
patchset**. The default batch slice is stated as **10 ms**; by the time of Ugedal 2022 it is
**5 ms**. Do not quote this paper's defaults as current - quote it for the design and the
stated caveats.

---

## 11. Safe claims

- CFS is **work-conserving**, so a group can exceed its share when the machine is otherwise
  idle. Shares are a lower bound and are **relative**, not a guarantee.
- Bandwidth control adds an **upper** bound: `cpu.cfs_quota_us` within `cpu.cfs_period_us`.
- Motivating use cases: pay-per-use hosting, KVM VM entitlements, latency provisioning,
  deriving soft guarantees.
- The implementation is a **hybrid**: a global per-group pool distributed in **slices** to
  per-CPU local pools. Local consumption needs no additional locking; only global-pool changes
  do.
- **A `cfs_rq` is throttled when its local quota is exhausted and the global pool cannot refill
  it.** Throttling is per run-queue; individual tasks are never throttled, only groups.
- Quota accounting happens in `update_curr()`, at the same moment execution time is charged.
- Refresh is hrtimer-driven, once per period, unthrottling all throttled run-queues.
- Limits are hierarchical with **no feasibility check** - a child is indirectly throttled when
  its parent's quota runs out.
- Known caveats stated by the authors: **local over-commit bounded by `num_cpus × batch_slice`**,
  reduced parallelism and **stranded quota** from batch allocation, and a primitive
  load-balancer model that excludes throttled run-queues.
- Measured overhead on tbench was small (e.g. 2451.82 → 2421.36 at 16 CPUs), and deviation from
  an affinity-based baseline shrinks as the enforcement period grows.

## 12. Do NOT claim

- That the defaults here are current. Batch slice is stated as **10 ms** in 2010; it is **5 ms**
  in later kernels.
- That this describes merged mainline code. It is patchset **v2**, pre-merge, on **2.6.34**.
- That throttling stops every thread in a container simultaneously. It is per run-queue.
- That the paper measured the unnecessary-throttling bug. It **predicts** the cause (slack time
  across periods) as a caveat; Ugedal 2022 measured it.

## 13. Reusable ideas

- **Name the caveats you could not fix.** Their §6.3 is the honest part of the paper and it is
  what makes it still useful fifteen years later.
- **Explain why the simple designs fail before presenting the hybrid.** Per-CPU does not
  converge, global does not scale - the reader then understands why the implementation is
  complicated.
- **Use an independent mechanism as the baseline.** Comparing bandwidth control against cpusets
  and CPU affinity achieving the same limit is a much stronger check than comparing against
  unlimited.
- **"Musical chairs"** is a good name for the herd effect of migrating toward whichever
  resource still has budget. Worth remembering as a failure mode in any quota system.
