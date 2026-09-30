# Paper Context: Understanding the Issues, Their Causes and Solutions in Microservices Systems — An Empirical Study (JSS 2023)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> One of the two MSR-style GitHub-mining papers the supervisor asked for, and the larger of the
> pair with [[waseem-2021-issues-five-microservices]]. **It contains a measured gap that directly
> justifies our dataset**: practitioners say performance problems happen often, and almost nobody
> files them as issues. See §7.

---

## 1. Bibliographic info

- **Title:** Understanding the Issues, Their Causes and Solutions in Microservices Systems: An
  Empirical Study
- **Authors:** Muhammad Waseem (Tampere University), Peng Liang (Wuhan University, corresponding),
  Aakash Ahmad (Derby), Arif Ali Khan (Oulu), Mojtaba Shahin (RMIT), Ali Rezaei Nasab (Wuhan),
  Tommi Mikkonen (Jyväskylä), Pekka Abrahamsson (Tampere)
- **Venue:** *Journal of Systems and Software*, 2023
- **Preprint:** arXiv:2302.01894

```bibtex
@article{waseem2023understanding,
  title   = {Understanding the issues, their causes and solutions in microservices systems: An empirical study},
  author  = {Waseem, Muhammad and Liang, Peng and Ahmad, Aakash and Khan, Arif Ali and Shahin, Mojtaba and Nasab, Ali Rezaei and Mikkonen, Tommi and Abrahamsson, Pekka},
  journal = {Journal of Systems and Software}, year = {2023}
}
```

---

## 2. One-paragraph summary

A **mixed-methods** study of what actually goes wrong in microservice systems, from three
independent sources: **2,641 issues mined from the issue trackers of 15 open-source microservice
systems on GitHub**, **15 interviews**, and an **online survey of 150 practitioners from 42
countries across 6 continents**. They build taxonomies of **issues, causes and solutions** — the
issues resolve into **19 categories over 2,698 tagged instances**, and they identify **177 types
of solution**. Dominant issues: **Technical Debt, CI/CD, Exception Handling, Service Execution and
Communication, Security**. Dominant causes: **General Programming Errors, Missing Features and
Artifacts, Invalid Configuration and Communication**.

---

## 3. The issue taxonomy — all 19 categories

Counts are out of **2,698** tagged instances from 2,641 issues.

| # | Category | Count | Share |
|---|---|---|---|
| 1 | **Technical Debt** | 687 | **25.46%** |
| 2 | **CI/CD** | 313 | **11.60%** |
| 3 | **Exception Handling** | 228 | **8.45%** |
| 4 | **Service Execution and Communication** | 219 | **8.11%** |
| 5 | **Security** | 213 | **7.89%** |
| 6 | Build | 210 | 7.78% |
| 7 | Configuration | 121 | 4.48% |
| 8 | **Monitoring** | 89 | 3.29% |
| 9 | Compilation | 79 | 2.92% |
| 10 | Testing | 77 | 2.85% |
| 11 | Documentation | 75 | 2.77% |
| 12 | GUI | 70 | 2.59% |
| 13 | Update and Installation | 68 | 2.52% |
| 14 | **Database** | 65 | 2.40% |
| 15 | Storage | 54 | 2.00% |
| 16 | **Performance** | **45** | **1.67%** |
| 17 | **Networking** | 41 | 1.51% |
| 18 | Typecasting | 35 | 1.29% |
| 19 | Organizational | 7 | 0.25% |

**Performance is 16th of 19.** Networking is 17th.

### The Performance category, broken down (45 issues, 16 types)

| Subcategory | Count | Types named |
|---|---|---|
| **Service Response Delay** | 28 (1.03%) | long payloads, **SLOW QUERY** |
| **Resource Utilisation** | 13 (0.48%) | load balancer error, **HIGH CPU USAGE**, rate limiting error |
| **Lack of Scalability** | 4 (0.14%) | scale-to-cluster error, **circuit breaker issue** |

### The Monitoring category (89 issues, 17 types)

| Subcategory | Count | Types named |
|---|---|---|
| **Tracing and Logging Management** | 60 (2.22%) | **distributed tracing error**, logging management error, **observability issue** |
| Health Check | 17 (0.63%) | health check API error, health check fail, health check port error |
| Monitoring Tool | 12 (0.44%) | **Zipkin issue**, Jenkins issue, TCP/TT health check issue |

An interviewee (P14, Azure Technical Engineer) on why monitoring is hard:

> *"Monitoring highly distributed systems like microservices systems through traditional
> monitoring tools is a challenging experience because these tools only focus on a specific
> component or the overall operational health of the system."*

And on performance (P15, Software Architect):

> *"A microservices-based application has numerous independent services that may be deployed on
> different infrastructures and platforms. Such an aspect increases its performance overhead. I
> also think that microservices systems consume more resources, creating a heavy burden for
> servers."*

---

## 4. Causes

Top causes across the study: **General Programming Errors**, **Missing Features and Artifacts**,
**Invalid Configuration and Communication**.

Survey agreement (150 practitioners, 5-point scale):

| Cause | Strongly agree | Agree | Mean |
|---|---|---|---|
| **General Programming Error** | 41.33% | 38.67% | **4.11** |
| Missing Features and Artifacts | 12.67% | 55.33% | 3.70 |
| Invalid Configuration and Communication | 18.00% | 47.33% | 3.64 |

---

## 5. Solutions

**177 types of solution** identified. Relevant to us, the observability-adjacent ones are small and
specific: *Add Logs* (4), *Remove Logs* (5), *Add Monitoring Metrics* (3), *Add Dependencies and
Metrics* (7), *Upgrade Container Logging* (6), *Upgrade Development and Monitoring Tool Support*
(8), *Remove Transaction ID for Logging* (1).

---

## 6. The survey — how often practitioners say each issue occurs

150 practitioners, 42 countries. "Very often" / "Often" / Sometimes / Rarely / Never, and a mean.

| Category | Very often | Often | **VO+O** | Mean |
|---|---|---|---|---|
| Security | 18.67% | 64.00% | **82.67%** | 3.90 |
| Organizational | 18.67% | 64.00% | **82.67%** | 3.90 |
| Technical Debt | 46.67% | 24.00% | **70.67%** | **3.93** |
| CI/CD | 26.67% | 42.67% | 69.33% | 3.73 |
| **Performance** | **17.33%** | **46.00%** | **63.33%** | **3.51** |
| Service Execution and Communication | 15.33% | 44.67% | 60.00% | 3.51 |
| Testing | 26.67% | 32.67% | 59.33% | 3.51 |
| Database | 18.00% | 40.67% | 58.67% | 3.46 |
| Build | 15.33% | 43.33% | 58.67% | 3.48 |
| Monitoring | 12.00% | 40.67% | **52.67%** | 3.31 |
| Networking | 12.00% | 34.67% | 46.67% | 3.15 |
| GUI | 7.33% | 30.67% | 38.00% | 2.79 |

---

## 7. What this means for our work — the gap between what is filed and what is felt

**The pack cites this as "the MSR-style GitHub-mining paper at the microservice level", which it
is. But the most useful thing in it is a contradiction between its own two data sources.**

| Category | Share of **mined issues** | Practitioners saying **very often / often** |
|---|---|---|
| **Performance** | **1.67%** (16th of 19) | **63.33%** (5th of 19), mean **3.51** |
| **Monitoring** | 3.29% (8th) | 52.67%, mean 3.31 |
| Networking | 1.51% (17th) | 46.67%, mean 3.15 |
| Technical Debt | 25.46% (1st) | 70.67%, mean 3.93 |
| GUI | 2.59% (12th) | 38.00%, mean 2.79 |

**Nearly two thirds of practitioners say they hit performance problems often or very often. Fewer
than one issue in fifty in the trackers is about performance.** Technical debt is filed **15×
more often** than performance while being reported as only slightly more frequent in practice.

**That gap is the empirical justification for our dataset, and it comes from within a single
peer-reviewed study.** Performance faults are experienced constantly and recorded rarely. So:

- **A GitHub mining study cannot be the empirical base for performance faults** — the population
  is not there to mine. Waseem's own 45 performance issues, spread over 16 types, gives roughly
  **3 issues per fault type across 15 systems**.
- **This is why the fault families have to be injected and labelled.** There is no natural corpus.
- It also explains the "honest gaps" our reference pack already records — no paper on
  connection-pool exhaustion, none on message-queue backlog. **They are not oversights in the
  literature; they are a consequence of how this class of problem gets recorded.**

**Jin 2012 explains the mechanism.** Performance bugs in Mozilla took **935 days to discover**
versus 252 for functional bugs, and *"judging whether performance bugs have manifested is a unique
challenge."* Waseem measures the downstream effect: they are not in the tracker because nobody
notices them in time to file one. **Cite the two together** — one gives the cause, the other the
consequence.

**Their performance subcategories map onto fault families we already have:**

| Their type | Our family |
|---|---|
| **SLOW QUERY** | `slow_query` / `db-latency-dependency-wait` |
| **HIGH CPU USAGE** | `noisy_neighbor` / `host-cpu-saturation` |
| Load balancer error, rate limiting error | — (no family) |
| **Circuit breaker issue** | `dependency-outage-retry-storm` |
| Scale-to-cluster error | — (no family) |

**Three of our families are named in their taxonomy.** That is a real, if thin, "it happens in the
wild" anchor for those three, and it is honest to say the counts behind it are small.

**The Monitoring category is worth citing for a different reason.** *Distributed tracing error*,
*observability issue*, and a *Zipkin issue* subcategory say that **the observability stack itself
fails** — 60 issues on tracing and logging management, more than the entire Performance category.
Any claim that "distributed tracing already solves this" has to contend with the fact that tracing
is itself one of the reported problems. **This pairs with Zhou's two undebuggable faults.**

**A caution on their own numbers.** The abstract says **2,641 issues**; the category table sums
over **2,698** instances. Issues carry **more than one tag**. Quote either "2,641 issues" or
"2,698 tagged instances", not both as the same thing.

**Scope caution.** These are **open-source GitHub projects**, and issue trackers record what
developers choose to write down. The survey is self-reported recall. Neither is telemetry. **Cite
for prevalence and for the filing gap; never for a signature.**

---

## 8. Safe claims

- Mixed-methods: **2,641 issues from 15 open-source microservice systems on GitHub**, **15
  interviews**, and a **survey of 150 practitioners from 42 countries across 6 continents**.
- Issue taxonomy of **19 categories over 2,698 tagged instances**, plus taxonomies of causes and
  **177 types of solution**.
- Dominant issues by count: **Technical Debt 25.46%, CI/CD 11.60%, Exception Handling 8.45%,
  Service Execution and Communication 8.11%, Security 7.89%**.
- **Performance is 45 of 2,698 (1.67%), ranked 16th of 19**, in three subcategories: **Service
  Response Delay 28** (long payloads, slow query), **Resource Utilisation 13** (load balancer
  error, high CPU usage, rate limiting error), **Lack of Scalability 4** (scale-to-cluster error,
  circuit breaker issue).
- **Monitoring is 89 (3.29%)**, of which **Tracing and Logging Management is 60 (2.22%)** —
  distributed tracing error, logging management error, observability issue — plus Health Check 17
  and Monitoring Tool 12 (Zipkin, Jenkins, TCP/TT health check).
- Networking is 41 (1.51%); Database 65 (2.40%); Storage 54 (2.00%).
- Dominant causes: **General Programming Errors, Missing Features and Artifacts, Invalid
  Configuration and Communication**; survey agreement means **4.11 / 3.70 / 3.64**.
- Survey frequency: **63.33% of practitioners report performance issues "very often" or "often"
  (mean 3.51)**; Technical Debt 70.67% (mean 3.93); Security 82.67% (mean 3.90); Monitoring
  52.67% (mean 3.31).
- An interviewed Azure engineer: traditional monitoring tools *"only focus on a specific component
  or the overall operational health of the system"*.

## 9. Do NOT claim

- That performance problems are rare in microservices. **The paper's own survey says the
  opposite** — they are rare *in issue trackers*, which is a different statement.
- That 2,641 and 2,698 are the same count. Issues carry multiple tags.
- That the study uses any runtime data. It is **issue text, interviews and a survey**.
- That the findings represent industrial closed-source systems. The mined systems are
  **open-source GitHub projects**; only the interviews and survey reach practitioners elsewhere.
- Any signature, mechanism or discriminator. There is none in this paper.

## 10. Reusable ideas

- **Triangulate with sources that can disagree.** Mining says performance is 1.67%; the survey
  says 63% hit it often. **The disagreement is the finding**, and it only exists because they ran
  both.
- **Report the long tail of the taxonomy.** Categories 16-19 are where the interesting mismatch
  lives; a paper that only discussed the top five would have hidden it.
- **Name the types, not just the categories.** "SLOW QUERY" and "HIGH CPU USAGE" as named types is
  what lets us map their taxonomy onto our fault families at all.
- **Ask practitioners how often, not just what.** Frequency-of-occurrence turns a taxonomy into a
  priority ordering.
