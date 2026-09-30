# Paper Context: Fault Analysis and Debugging of Microservice Systems — Industrial Survey, Benchmark System, and Empirical Study (IEEE TSE 2021)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> **This is the paper that created Train Ticket**, our second application. It is also the
> strongest published evidence we have for a specific claim we want to make: **the faults that
> defeat log and trace analysis are the environment/infrastructure ones — which are exactly the
> ones a kernel trace sees.** See §8. Note the citation year: **2021, not 2018.**

---

## 1. Bibliographic info

- **Title:** Fault Analysis and Debugging of Microservice Systems: Industrial Survey, Benchmark
  System, and Empirical Study
- **Authors:** Xiang Zhou, Xin Peng, Chao Ji, Wenhai Li, Dan Ding (Fudan University);
  Tao Xie (UIUC); Jun Sun (Singapore Management University)
- **Venue:** **IEEE Transactions on Software Engineering 47(2):243-260, February 2021**
- The PDF we hold is the SMU institutional repository copy, whose running header still reads
  "VOL. 14, NO. 8, AUGUST 2018" from an earlier draft. **Cite the TSE 2021 record.**
- Benchmark: **TrainTicket**, open source, with a replication package.

```bibtex
@article{zhou2021fault,
  title   = {Fault Analysis and Debugging of Microservice Systems: Industrial Survey, Benchmark System, and Empirical Study},
  author  = {Zhou, Xiang and Peng, Xin and Xie, Tao and Sun, Jun and Ji, Chao and Li, Wenhai and Ding, Dan},
  journal = {IEEE Transactions on Software Engineering},
  volume  = {47}, number = {2}, pages = {243--260}, year = {2021}
}
```

**Our slug says `zhou-2018-train-ticket`.** Keep the directory name, cite 2021.

---

## 2. One-paragraph summary

Three pieces in one paper. **(1) An industrial survey**: 16 developers from 12 companies describe
**22 real fault cases** from 13 microservice systems, with the time each took to debug.
**(2) A benchmark**: they build **TrainTicket** — **41 business microservices in Java, Python,
Node.js and Go** — and **replicate all 22 faults on it**, because no realistic open-source
microservice system existed to do research on. **(3) An empirical study**: they re-debug all 22
replicated faults at three levels of tooling — basic logs, visual logs, visual traces — and
measure how long each takes. Better tooling helps, especially for **interaction faults**. But
**two faults could not be debugged at any level**, and both were **non-functional environment
faults**.

---

## 3. The survey

- **16 participants from 12 companies**, covering **13 microservice systems**.
- Company mix: 6 leading traditional IT companies (**two are Fortune 500**), 4 leading Internet
  companies, 2 non-IT companies.
- Participants span junior developer to manager and architect.
- Method: each recalls the microservice system they know best, then reports fault cases with
  symptom, root cause, and debugging time. **Time estimates were cross-checked with colleagues
  and against issue-tracker records** (bug assignment to resolution).
- Scale context they give: Netflix runs **500+ microservices**; another system runs thousands
  across **20,000+ machines**.

**Their motivation for the benchmark, stated plainly:** research on microservices *"is usually
based on small systems with few microservices (e.g., 5 microservices or fewer)."*

---

## 4. The 22 faults and their taxonomy

Two axes: **symptom** (functional / non-functional) and **root cause** (internal / interaction /
environment).

| Root cause | Functional | Non-functional |
|---|---|---|
| **Internal** | F9, F14, F18, F19, F21, F22 | F17 |
| **Interaction** | F1, F2, F6, F7, F8, F10, F11, F12, F13 | F5 |
| **Environment** | F15, F16, F20 | **F3, F4** |

- **Most faults are functional.** Only 4 of 22 are non-functional — F3 and F5 (unreliable
  service), F4 and F17 (long response time).
- **Internal** = inside one microservice. **Interaction** = missing or wrong coordination between
  microservices. **Environment** = runtime infrastructure configuration, at service or cluster
  level.
- They asked each participant whether the fault could happen in a monolith. The answer:
  **interaction faults and cluster-level environment faults are particular to microservices**;
  internal and service-level configuration faults are not.

### The fault cases that overlap with our fault families

| | Symptom | Root cause | Days to locate |
|---|---|---|---|
| **F3** | periodic HTTP 500 | **JVM memory config conflicts with the Docker cluster's memory limit, so Docker sometimes kills the JVM** | **10** |
| **F4** | very long response time for some requests | SSL offloading at too fine a granularity, in almost every Docker instance | **7** |
| **F5** | service sometimes returns timeout exceptions | **a thread pool shared between two request types; high load of one exhausts it and the other times out** | 6 |
| **F6** | service slows down then errors | **endless recursive requests** caused by SQL errors in a dependency | 3 |
| **F7** | payment service fails | **overload of requests to a third-party service leads to denial of service** | 2 |
| **F17** | grid loading too slow | too many nested `select`/`from` clauses in the constructed SQL | 1 |

**F3 is our `service-memory-cap` fault.** **F5 is our `connection-pool-exhaustion` fault, exactly
— shared pool, one workload starves another.** **F7 is a retry/overload storm. F17 is
`slow_query`.** These are not analogies; they are the same mechanisms, reported independently by
industrial developers.

**Median time to locate a root cause is measured in days.** F3 took 10.

---

## 5. Debugging practice and its three maturity levels

Seven steps: Initial Understanding → Environment Setup → Failure Reproduction → Failure
Identification → Fault Scoping → Fault Localization → Fault Fixing. Not strictly sequential; steps
repeat or are skipped.

**All 16 participants depend on log analysis.** Maturity split across the 13 systems:

| Level | Systems | Share |
|---|---|---|
| Basic log analysis | 3 | **23%** |
| Visual log analysis | 6 | **46%** |
| **Visual trace analysis** | 4 | **31%** |

**Time grows with the number of microservices involved:**

| Microservices in the fault | Average time to locate and fix |
|---|---|
| 1 | **9.5 hours** |
| 2 | **20 hours** |
| 3 | **40 hours** |
| more than 3 | **48 hours** |

And by tooling, for **interaction faults**: **20 hours with visual trace analysis, 35 with visual
logs, 45 with basic logs.** The biggest single gap is in **initial understanding: 3 hours with
visual traces versus 21 with basic logs** — a **7× difference**.

**11 of 13 participants** with visual log/trace experience call the tools very useful, but say
how much they help depends on fault type and the developer.

---

## 6. TrainTicket

- **41 business-logic microservices**, not counting databases and infrastructure.
- **Four languages: Java, Python, Node.js, Go.**
- Covers **synchronous invocations, asynchronous invocations, and message queues**.
- Functions: ticket enquiry, reservation, payment, change, user notification.
- **All 22 faults replicated** by transferring the mechanism from the original industrial system.

Replication examples: F3 is reproduced by making some ticket-search microservices more
resource-hungry and deploying them with conflicting JVM/Docker memory settings. F4 by applying
the bad SSL config to **every** microservice. F5 in the ticket-reservation service, which serves
both searching and booking — high search load exhausts the pool and booking requests time out.

---

## 7. The empirical study — including the two failures

They re-debugged all 22 replicated faults at each maturity level and timed every step.

**The general trend:** more tooling, less time. **Interaction faults benefit most.**

**The exceptions, and they matter:**

- **F9, F19, F21, F22 were easy with basic logs alone** — all **Internal** faults. Higher tooling
  added nothing.
- **F3 and F4 failed at all three levels.** Developers got through initial understanding,
  environment setup and failure reproduction, then **failed at failure identification and
  everything after it**. *"If a step of a debugging process fails, the whole process fails also."*

> **The developers fail in F3 and F4 with all the three levels of industrial practices. Both of
> them are non-functional Environment faults.**

They also note **F2 cannot be effectively analysed by existing visualisation** unless success and
failure traces are compared directly.

### Their stated findings

- Most faults **except those caused by environmental settings** benefit from trace visualisation.
- Scale is a problem: industrial systems have **hundreds to thousands of microservices and tens
  of thousands to millions of events in a trace**, which can make visual analysis infeasible.
  They call for clustering, zoom, and combination with spectrum-based fault localisation and delta
  debugging.
- They argue debugging must become **data-driven** — combining human expertise with machine
  intelligence to suggest suspicious scopes, recommend similar historical cases, and learn from
  developer actions.

### Their own stated threats

- **Limited participants and fault cases**; may not generalise.
- **Time estimates are recalled, not precisely recorded.**
- **TrainTicket is smaller and less heterogeneous than most of the surveyed industrial systems**,
  despite being the largest open-source one they know of.
- Fault replication depends on their understanding of the original and **may not capture the
  essential characteristics**.
- **Runtime environment (load, network traffic) is uncontrolled**, and some faults behave
  differently under different settings.

---

## 8. What this means for our work

**First, this is the provenance of our second application.** Any claim we make about Train Ticket
should cite it, and should carry the authors' own caveat that **it is smaller and less
heterogeneous than the industrial systems it was modelled on**. Its 41 services in 4 languages is
exactly why we chose it over Sock Shop's 7 — and exactly what makes cross-application comparison
hard.

**Second, and much more important: F3 and F4 are the best argument in the entire reference pack
for the kernel modality.** Sixteen industrial developers, three levels of tooling up to and
including distributed trace visualisation, and **two faults that nobody could debug at any
level**. Both are **non-functional environment faults**. Look at what they are:

| | Fault | Why logs and traces fail | What a kernel trace shows |
|---|---|---|---|
| **F3** | JVM memory config conflicts with the Docker cluster memory limit; **Docker kills the JVM** | the JVM dies without writing why; the trace just stops | the **OOM kill and the cgroup limit**, directly — this is our `service-memory-cap` fault |
| **F4** | SSL offloading at fine granularity in almost every container | no single span is slow; the cost is spread across every call | **CPU time in crypto work**, attributable per container |

**Their own conclusion is our thesis statement, written by someone else:** *"most fault cases
**except those caused by environmental settings** can benefit from trace visualisation."* The
environment is the kernel's layer. **That is the gap, stated by the authors of the most-cited
microservice debugging study, from industrial data, seven years before us.** It belongs in our
introduction.

**Third, F5 validates a fault family we had trouble sourcing.** Our reference pack records an
*"honest gap: no peer-reviewed MSR paper focused only on connection-pool exhaustion."* **F5 is a
real industrial case of exactly that** — a shared thread pool, one request type exhausting it,
another type timing out, 6 days to find. It is not a paper *about* pool exhaustion, but it is a
**verified industrial instance in a peer-reviewed venue, with a replication in TrainTicket we can
run**. That narrows the gap and should be added to blueprint 3's evidence.

**Fourth, their time numbers are the motivation numbers we should use.** **9.5 → 20 → 40 → 48
hours as the fault spans 1 → 2 → 3 → 3+ microservices.** That is a measured statement that
localisation cost grows with scope, from industrial issue trackers. It is a better argument for
automated WHERE than anything we have written.

**A caution about comparing to their timings.** Their study measures **humans debugging with
tools**. Ours measures an **agent scoring against ground truth**. **The numbers are not
comparable in either direction**, and we should never present a runtime next to their 20 hours.

**One thing to check against our own data.** They report industrial traces with **tens of
thousands to millions of events**, making visualisation infeasible. Our kernel traces run at
**1.56M events per second**. Their scale problem is our scale problem, several orders worse — and
it is the reason our `ctf_lines` tool needed a truncation flag. Worth citing when we justify
sampling and indexing decisions.

---

## 9. Safe claims

- Industrial survey: **16 participants, 12 companies, 13 microservice systems, 22 fault cases**.
  Two companies are Fortune 500. Times were cross-checked against issue-tracker records.
- Faults classify by symptom (**functional / non-functional**) and root cause (**internal /
  interaction / environment**). **Only 4 of 22 are non-functional.**
- **Interaction faults and cluster-level environment faults are particular to microservices**;
  internal and service-level configuration faults also occur in monoliths.
- **Developers take several days to locate the root cause in most cases** — F3 took 10 days.
- Debugging maturity across the 13 systems: **basic log analysis 23%, visual log analysis 46%,
  visual trace analysis 31%**. **All participants depend on log analysis.**
- Time to locate and fix grows with scope: **9.5 h (1 microservice), 20 h (2), 40 h (3), 48 h
  (>3)**.
- For interaction faults: **20 h with visual traces, 35 h with visual logs, 45 h with basic
  logs**. Initial understanding alone: **3 h vs 7 h vs 21 h**.
- **TrainTicket has 41 business microservices in Java, Python, Node.js and Go**, covering
  synchronous, asynchronous and message-queue interactions; **all 22 faults are replicated on
  it**.
- In the empirical study, **F3 and F4 could not be debugged at any of the three maturity levels.
  Both are non-functional environment faults.** F9, F19, F21 and F22 needed only basic logs; all
  four are internal faults.
- **F5 is an industrial case of connection/thread-pool exhaustion**: a shared pool, high load of
  one request type, timeout failures of another. 6 days to locate.
- Their finding: *"most fault cases except those caused by environmental settings can benefit
  from trace visualisation."*
- Industrial traces have **hundreds to thousands of microservices and tens of thousands to
  millions of events**, which can make visual analysis infeasible.
- Their own threats: small sample, recalled timings, and **TrainTicket being smaller and less
  heterogeneous than the industrial systems surveyed**.

## 10. Do NOT claim

- **That it is a 2018 paper.** It is **IEEE TSE 47(2):243-260, 2021**. The 2018 header in the
  repository PDF is a stale draft template.
- That the 22 faults are a representative sample. 16 developers recalling cases is a convenience
  sample, and the authors say so.
- That the debugging times are precise. They are **participant estimates**, validated against
  issue trackers but not directly measured.
- That TrainTicket is representative of industrial systems. The authors state it is **smaller and
  less heterogeneous** than most systems they surveyed.
- That our agent's runtime is comparable to their hours. Different task, different actor.
- That kernel tracing was evaluated. It was not — the three levels are logs, visual logs, and
  distributed traces.

## 11. Reusable ideas

- **Report the cases where every method failed.** F3 and F4 are the most valuable two rows in the
  paper, and they are failures. Our own results tables should be as willing to publish the faults
  nobody could localise.
- **Survey first, then build the benchmark from what the survey found.** The 22 faults are real
  before they are replicated, which is why TrainTicket is worth using at all.
- **Cross-check self-reported times against the issue tracker.** Cheap validation of soft data.
- **Cost scales with scope, and you can measure it.** 9.5 → 48 hours across 1 → 3+ services turns
  "distributed debugging is hard" into a number.
- **Classify by symptom *and* root cause.** The 2×3 table is what makes "environment faults defeat
  trace analysis" visible; either axis alone would have hidden it.
