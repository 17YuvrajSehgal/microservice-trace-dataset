# Paper Context: CPI² — CPU performance isolation for shared compute clusters (EuroSys 2013)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited by blueprint 7 (`cpu-contention-co-tenant`) for the logic of "who preempted me". That
> is a fair reading, though the paper's actual mechanism is different from ours in an important
> way — see §8. It is also the source of the **victim / antagonist** vocabulary.

---

## 1. Bibliographic info

- **Title:** CPI²: CPU performance isolation for shared compute clusters
- **Authors:** Xiao Zhang, Eric Tune, Robert Hagmann, Rohit Jnagal, Vrigo Gokhale, John Wilkes
  (Google)
- **Venue:** EuroSys '13
- **DOI:** 10.1145/2465351.2465388
- **PDF:** https://research.google.com/pubs/archive/40737.pdf

```bibtex
@inproceedings{zhang2013cpi2,
  title     = {{CPI}$^2$: {CPU} performance isolation for shared compute clusters},
  author    = {Zhang, Xiao and Tune, Eric and Hagmann, Robert and Jnagal, Rohit and Gokhale, Vrigo and Wilkes, John},
  booktitle = {EuroSys '13}, year = {2013},
  doi       = {10.1145/2465351.2465388}
}
```

---

## 2. One-paragraph summary

When jobs share a machine they fight over things Linux cannot partition — **processor caches
and memory buses**. The result is that a job's performance depends on what else happens to be
running, which is unpredictable. CPI² watches **cycles per instruction**, read from hardware
performance counters, and uses it as a health signal. It learns what normal CPI looks like for
each job **by pooling data across all tasks of that job**, flags outliers, then correlates the
victim's bad CPI against the **CPU usage of co-located suspects** to name the **antagonist**.
Optionally it throttles the antagonist so the victim recovers. **Deployed across all of
Google's shared compute clusters.**

---

## 3. The problem

- Performance isolation is a key challenge in cloud computing.
- **Linux has few defences against interference in shared caches and memory buses.**
- So applications experience unpredictable performance caused by other programs' behaviour.
- Scale context they give: in one cluster, **7% of jobs run at production priority and use
  about 30% of available CPUs**, while non-production jobs consume roughly another 10%.

---

## 4. Why CPI is the signal

They argue CPI correlates with application-level performance, and they measure it rather than
assert it:

- For one job, CPI against reported latency has a **correlation coefficient of 0.97**. A second
  job, same result — **0.97**. A third with similar results.
- Across three other jobs: **0.68-0.75**, and a fourth with **poor correlation** because *"CPI
  does not capture"* what that job is doing.
- Baseline CPI has a **diurnal pattern** with about a **4% coefficient of variation**.

They state the limitation openly: **CPI might not be well correlated with application-level
performance** for every job, and they show a case where it is not.

---

## 5. How it works

### 5.1 Learning normal

CPI values are measured and analysed **locally by an agent on every machine**, to avoid a
central bottleneck. Each agent is given a **predicted CPI distribution** for the jobs it runs
tasks for, updated as needed.

The distribution matters. From a web-search job across thousands of machines over two days,
**more than 450,000 CPI samples**, mean **1.8**, standard deviation **0.16**. The shape is
**skewed — the right tail is longer**, because bad performance is more common than exceptionally
good performance. They fitted normal, log-normal, Gamma and **generalized extreme value (GEV)**
distributions; **GEV fit best**.

**A sample is flagged as an outlier if it exceeds the 2σ point** of the predicted distribution —
about 5% of samples.

**The key design choice: normal behaviour is learned by aggregating across the many tasks of the
same job**, not from a shipped constant and not from one task's history.

### 5.2 Finding the antagonist

1. Suspects are pre-filtered **by heuristics like CPU usage and cache miss rate**.
2. Then correlate **the victim's CPI values against the CPU usage of each suspect**, over the
   same time window.
3. The correlation lands in **[-1, 1]**. It **increases when a spike in the antagonist's CPU
   usage coincides with high victim CPI**, and decreases when high antagonist usage coincides
   with *low* victim CPI.
4. **At most one correlation analysis is performed at a time**, so the diagnosis itself does not
   disturb the machine. A single analysis takes about a second.

### 5.3 Handling it

Optionally **throttle the antagonist** (hard-cap its CPU) so the victim returns to expected
behaviour.

---

## 6. Status

**Rolled out to all of Google's shared compute clusters.** The paper presents the analysis that
led to that decision, including case studies and a large-scale evaluation against real
production issues.

---

## 7. What kind of paper this is

- A **deployed production system** at Google scale, not a prototype.
- Signal is **hardware performance counters** (CPI), not kernel traces.
- The contribution is detection **and** mitigation — it acts, not just reports.

---

## 8. What this means for our work

**Blueprint 7 cites it for: "co-located antagonists hurt victims; Google finds them by
correlating victim slowdown with antagonist CPU use. That is the same logic as 'who preempted
me' in sched_switch."**

The first two clauses are exactly right. **The third is a looser analogy than it reads.**

| CPI² | Our blueprint 7 |
|---|---|
| Signal is **CPI from hardware counters** | signal is **scheduler events** |
| Interference is in **caches and memory buses** — invisible resources | interference is **CPU time** — a visible one |
| Antagonist found by **statistical correlation** between victim CPI and suspect CPU usage over a window | culprit found by reading **who was actually on the CPU** in `sched_switch` |
| Learns normal from **many tasks of the same job** | compares a window against the run's own baseline |

CPI² correlates because it **cannot see the mechanism** — nothing in Linux tells you which job
evicted your cache lines. We *can* see our mechanism: `sched_switch` says precisely which task
took the CPU. So ours is direct attribution and theirs is statistical inference. **That makes
our claim stronger, not weaker, and the blueprint should say so rather than claiming sameness.**

**The genuinely transferable idea is how they learn "normal".** Pooling across many tasks of the
same job, fitting a **GEV** rather than assuming a normal distribution, and flagging at **2σ**.
Our blueprints mostly use ratios against a per-run baseline; the observation that **the CPI
distribution is right-skewed because bad performance is more common than exceptionally good**
is a good argument for not assuming symmetry in any of our thresholds.

**One caution their paper supplies for free.** They found a job where **CPI simply does not
correlate** with its performance and they say so. That is the same honesty our blueprints need
in their applicability fields — and `connection-pool-exhaustion` already does it.

**A limitation worth noting for our setting.** CPI² addresses cache and memory-bus interference.
Our `noisy_neighbor` fault is a **CPU hog**, which is the *visible* kind of contention. So CPI²
is evidence that co-tenant interference matters in production, but it is **not** evidence about
the specific fault we inject.

---

## 9. Safe claims

- Performance isolation is a key challenge in cloud computing, and **Linux has few defences
  against interference in shared processor caches and memory buses**.
- CPI² uses cycles-per-instruction from hardware performance counters to detect interference,
  identify the antagonist, and optionally throttle it.
- Normal behaviour is learned **by aggregating data across multiple tasks of the same job**.
- The CPI distribution is **right-skewed**; a **generalized extreme value** distribution fit
  best out of normal, log-normal, Gamma and GEV. Outliers are flagged beyond **2σ**, about 5%
  of samples.
- CPI correlated with reported latency at **0.97** for two jobs, 0.68-0.75 for three more, and
  **poorly for one**, which the authors report.
- Antagonists are found by correlating the **victim's CPI** against the **CPU usage of
  suspects**, pre-filtered by CPU usage and cache miss rate. One analysis takes about a second,
  and only one runs at a time to avoid disturbing the machine.
- **Deployed to all of Google's shared compute clusters.**

## 10. Do NOT claim

- That CPI² reads scheduler events or kernel traces. It uses hardware performance counters.
- That its mechanism is the same as reading `sched_switch`. It correlates statistically because
  cache interference is not directly attributable; we read the culprit directly.
- That it addresses CPU-time contention. It addresses cache and memory-bus interference.
- That CPI works as a health signal for every job — the paper shows one where it does not.

## 11. Reusable ideas

- **Learn normal from the population, not the individual.** Aggregating across tasks of the same
  job gives a distribution a single task's history cannot.
- **Do not assume a normal distribution.** They tested four and GEV won, because performance
  data is right-skewed by nature.
- **Bound the cost of diagnosis.** At most one correlation analysis at a time, about a second
  each, so the investigation does not become the problem.
- **Publish the case where your signal fails.** One job where CPI did not correlate, reported
  plainly, makes the other numbers more credible.
- **victim / antagonist** is good vocabulary and we already borrow it.
