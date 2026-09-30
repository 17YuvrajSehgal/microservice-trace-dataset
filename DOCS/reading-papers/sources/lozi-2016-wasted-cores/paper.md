# Paper Context: The Linux Scheduler — a Decade of Wasted Cores (EuroSys 2016)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited by blueprint 1 as a **refinement**, and it is the right use. Its point is that a long
> runqueue wait does **not** prove every CPU is busy — Linux can leave cores idle for seconds
> while threads wait. §8 explains why that is a rule-out our blueprint needs.

---

## 1. Bibliographic info

- **Title:** The Linux Scheduler: a Decade of Wasted Cores
- **Authors:** Jean-Pierre Lozi, Baptiste Lepers, Justin Funston, Fabien Gaud, Vivien Quéma,
  Alexandra Fedorova (University of British Columbia and collaborators)
- **Venue:** EuroSys '16, 18-21 April 2016, London
- **DOI:** 10.1145/2901318.2901326
- **PDF:** https://people.ece.ubc.ca/sasha/papers/eurosys16-final29.pdf

```bibtex
@inproceedings{lozi2016linux,
  title     = {The Linux Scheduler: a Decade of Wasted Cores},
  author    = {Lozi, Jean-Pierre and Lepers, Baptiste and Funston, Justin and Gaud, Fabien and Qu{\'e}ma, Vivien and Fedorova, Alexandra},
  booktitle = {EuroSys '16}, year = {2016},
  doi       = {10.1145/2901318.2901326}
}
```

---

## 2. One-paragraph summary

A thread scheduler has one simple job: **if a thread is ready and a core is free, put them
together.** The authors found Linux breaks that invariant routinely. **Cores sit idle for
seconds while runnable threads wait in runqueues.** They identify four distinct bugs with
different root causes and the same symptom, measure the damage — 13-24% on ordinary workloads,
**138× in a corner case** — and fix them. They also make a methodological point that matters
more than the bugs: these failures **evade conventional testing and debugging** because they
never crash anything and never show up as a wrong answer. So they built two tools: an online
**sanity checker** for the invariant, and a **scheduling visualiser**.

---

## 3. The invariant, and why breaking it is always a bug

> "the OS thread scheduler must maintain the following, simple, invariant: make sure that ready
> threads are scheduled on available cores."

Their argument for why a violation is never intentional: a core should not be idle if there is
work to do. **Long-term presence of that symptom is therefore a bug**, not a policy decision.

The paper opens with a Torvalds quote from 2001 — *"there are not very many things that have
aged as well as the scheduler. Which is just another proof that scheduling is easy."* — which
is the joke the title is built on.

---

## 4. The four bugs

All four leave cores idle while threads wait. Different root causes, same symptom.

| Bug | Section |
|---|---|
| **Group Imbalance** | 3.1 |
| **Scheduling Group Construction** | 3.2 |
| **Overload-on-Wakeup** | 3.3 |
| **Missing Scheduling Domains** | 3.4 |

They note these interact: one application triggered **both** Group Imbalance and
Overload-on-Wakeup.

---

## 5. Measured impact

| Workload | Effect |
|---|---|
| Synchronisation-heavy scientific applications | **many-fold** degradation |
| One barrier-heavy scientific application | **138× faster** after the fix |
| `lu` with four single-threaded R processes | **13× faster** after fixing Group Imbalance — a *super-linear* speedup |
| Kernel `make` | **13%** higher latency |
| Widely used commercial DBMS, TPC-H throughput | **14-23% decrease** |
| Most-affected TPC-H query | slowed by **23%** |

Typical range quoted in the introduction: **13-24% for ordinary Linux workloads, up to 138× in
corner cases.** Energy waste is proportional.

---

## 6. Why these bugs are hard to find — the methodological point

- They **do not crash, hang, or produce wrong results.** Nothing fails; things are just slower.
- Symptoms are described as **"evasive"**.
- Conventional testing and debugging tools are **ineffective at confirming or understanding**
  them.
- The authors themselves only *suspected* scheduler bugs after observing anomalous behaviour —
  they had to build tools to confirm it.

**Their two tools:**
1. A **sanity checker** that periodically tests the invariant on a live system and catches
   violations as they happen.
2. A **scheduling visualiser** to expedite debugging.

Both were **easy to port across kernel versions** (Linux 3.17 through 4.3) and run with
**negligible overhead**. Their closing recommendation is that these belong in every kernel
developer's toolbox.

---

## 7. What kind of paper this is

- **Bug discovery, analysis, and fixes**, plus two tools.
- Real measurements on real workloads (NAS benchmarks, kernel make, TPC-H on a commercial DBMS).
- **Not** a diagnosis method for production systems, and not about containers or microservices.
- Linux 3.17-4.3 era. CFS, pre-EEVDF.

---

## 8. What this means for our work

**Blueprint 1 cites it as a refinement and the citation is sound.** The pack's wording:

> Cores "may stay idle for seconds while ready threads are waiting in runqueues." So a long
> runqueue wait does *not* always mean every CPU is busy. Your rule-out should check per-CPU
> idle time as well as runqueue wait.

That is exactly what the paper shows, and it is the correct lesson for us. Blueprint 1
(`host-cpu-saturation`) concludes saturation from **long runnable-wait across all containers**.
This paper says that inference can be wrong: the scheduler itself can produce long runnable-wait
with idle cores. So **per-CPU idle time is a necessary rule-out**, not an optional extra.

**It also sharpens the distinction between our blueprints 1, 7 and 10.** Three different reasons
a thread is runnable but not running:

| Reason | What is true of the CPUs |
|---|---|
| **Host saturation** (blueprint 1) | every CPU busy |
| **Noisy neighbour** (blueprint 7) | a *foreign* task is on the CPU |
| **CFS throttling** (blueprint 10) | CPUs **idle**, the group is banned from running |
| **Scheduler bug** (this paper) | CPUs **idle**, nothing is banning anything |

Throttling and a scheduler bug look alike from runnable-wait alone: both leave cores idle. The
separator is that throttling is periodic and quota-shaped, and a scheduler bug is not. Worth
naming in blueprint 10's rule-out list — we currently do not mention it.

**A caution about kernel version.** Their bugs were found and fixed in Linux 3.17-4.3. Our VM
runs **7.0.0-1011-gcp**, long after those fixes and after **EEVDF replaced CFS in 6.6**. So we
should cite this for the *principle* — idle cores with waiting threads is possible and is a
known class of failure — not as a claim that our traces contain these specific bugs.

**One idea directly applicable to us.** Their sanity checker tests an invariant continuously
and cheaply, rather than analysing after the fact. Our equivalent would be a collection-time
check: *were there idle CPUs while containers had runnable threads?* That is computable from
`sched_switch` and would make blueprint 1's rule-out mechanical instead of a judgement call.

---

## 9. Safe claims

- The scheduler invariant is that ready threads should run on available cores; Linux breaks it.
- **Cores can stay idle for seconds while runnable threads wait in runqueues.**
- Four distinct bugs with different root causes produce this symptom: Group Imbalance,
  Scheduling Group Construction, Overload-on-Wakeup, Missing Scheduling Domains.
- Impact: 13-24% on typical Linux workloads, **138×** in a corner case; kernel make 13% higher
  latency; TPC-H throughput down 14-23% on a commercial DBMS; one query 23% slower.
- Fixing Group Imbalance made `lu` with four R processes **13× faster** — a super-linear
  speedup.
- These bugs **do not crash or corrupt anything**, so conventional testing and debugging tools
  are ineffective at finding them.
- An online sanity checker plus a scheduling visualiser found them, ported easily across Linux
  3.17-4.3, and ran with negligible overhead.

## 10. Do NOT claim

- That these bugs are present in current kernels. They were fixed; our VM runs 7.0.0, and CFS
  itself was replaced by EEVDF in 6.6.
- That the paper is about containers, cgroups, or microservices. It is not.
- That idle cores always mean a scheduler bug. Throttling produces the same picture for an
  entirely different reason.
- Any claim that we detect these. We cite the possibility as a rule-out, not a finding.

## 11. Reusable ideas

- **State the invariant, then check it continuously.** A cheap always-on check beats a clever
  after-the-fact analysis for a symptom that never crashes anything.
- **A symptom with no failure is the hardest kind.** Nothing breaks, so nothing alerts. That is
  the same reason performance faults need a dataset like ours rather than a bug tracker.
- **Report the corner case and the typical case separately.** 13-24% and 138× tell different
  stories and both are true.
- **Check the negative condition.** "Were cores idle at the time?" turns an ambiguous signal
  (long runnable-wait) into a decisive one.
