# Paper Context: On the Nature of Issues in Five Open Source Microservices Systems — An Empirical Study (EASE 2021)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> The **earlier and smaller** of the Waseem pair; [[waseem-2023-issues-causes-solutions]] is the
> extended version and supersedes it for most purposes. **Two reasons to keep this one anyway:**
> one of its five subject systems **is Sock Shop**, and its performance numbers are even starker
> than the 2023 paper's. See §6.

---

## 1. Bibliographic info

- **Title:** On the Nature of Issues in Five Open Source Microservices Systems: An Empirical Study
- **Authors:** Muhammad Waseem, Peng Liang (Wuhan University, corresponding);
  Mojtaba Shahin (Monash); Aakash Ahmad (University of Ha'il); Ali Rezaei Nasab (Shiraz)
- **Venue:** EASE 2021, 21-23 June, Trondheim
- **DOI:** 10.1145/3463274.3463337
- **Preprint:** arXiv:2104.12192

```bibtex
@inproceedings{waseem2021nature,
  title     = {On the Nature of Issues in Five Open Source Microservices Systems: An Empirical Study},
  author    = {Waseem, Muhammad and Liang, Peng and Shahin, Mojtaba and Ahmad, Aakash and Nasab, Ali Rezaei},
  booktitle = {EASE 2021}, year = {2021},
  doi       = {10.1145/3463274.3463337}
}
```

**Relationship to the 2023 JSS paper:** same first two authors, same method, scaled up from 5
systems and 1,345 issues to 15 systems and 2,641 issues, plus 15 interviews and a 150-person
survey. **Cite the 2023 paper unless you specifically need this one's per-system detail.**

---

## 2. One-paragraph summary

**1,345 closed issue discussions from five open-source microservice systems on GitHub**, manually
classified into the first taxonomy of its kind: **17 categories, 46 subcategories, 138 types**.
The prominent categories are **Technical Debt (321, 23.86%)**, **Build (145, 10.78%)**,
**Security (137, 10.18%)** and **Service Execution and Communication (119, 8.84%)**. For those top
four they also derive causes — **94 types in 7 categories and 21 subcategories** — led by *General
programming errors*, *Poor security management*, *Invalid configuration and communication*, and
*Legacy versions, compatibility and dependency*.

---

## 3. The five systems — one of them is ours

| Project | Closed issues | Contributors | Forks | Stars |
|---|---|---|---|---|
| `goadesign/goa` | 799 | 82 | 447 | 4K |
| `dotnet-architecture/eShopOnContainers` | 904 | 119 | 6.7K | 16K |
| `networknt/light-4j` | 523 | 28 | 492 | 2.9K |
| `moleculerjs/moleculer` | 436 | 76 | 377 | 3.9K |
| **`microservices-demo/microservices-demo`** | **280** | **45** | **1.5K** | **2.5K** |

**`microservices-demo/microservices-demo` is Sock Shop** — the application our dataset is built
on. Its 280 closed issues are in this study's 1,345.

Only closed issues were used, on the grounds that only they answer "what was the cause".

---

## 4. The taxonomy

**17 categories, 46 subcategories, 138 types.** Top four by count:

| Category | Count | Share |
|---|---|---|
| **Technical Debt** | 321 | **23.86%** |
| **Build** | 145 | **10.78%** |
| **Security** | 137 | **10.18%** |
| **Service Execution and Communication** | 119 | **8.84%** |

**Technical Debt** splits into *code debt* (code smells, refactoring, formatting, derived-class
errors, cyclomatic complexity, wrong headers) and *service design debt*.

**Service Execution and Communication** splits into:

- **Service communication** — connection strings, protocols (gRPC, HTTP, WebSocket, RPC),
  centralised transporters (MQTT, NATS, Kafka, Moleculer), **server connection**, **service
  discovery**, broken URLs. Most common: **service discovery failure**, HTTP protocol
  implementation, and transporter issues.
- **Service execution** — asynchronous communication, **dynamic port binding**, RabbitMQ
  messaging, **service broker**. Examples given include a dependency failure because *"integration
  commands were sent asynchronously"* and a service broker that *"could not properly destroy the
  old services"*.

### The Performance category — the number that matters for us

Performance is **not** in the top four. From their taxonomy figure, the whole Performance category
is three types:

| Type | Count |
|---|---|
| **Service Delay** | 6 |
| **High CPU Usage** | 2 |
| **Front-end Service Hangs** | 1 |
| **Total** | **9** |

**9 issues out of 1,345 — 0.67%.**

For comparison, the **Networking** category alone lists service accessibility (5), hosting and
protocols (4), DNS and URL errors, firewall and proxy settings, and localhost exception; and a
single **Compilation** subcategory, *syntax error*, has **69** on its own — **more than seven
times the entire Performance category**.

---

## 5. Causes (RQ2)

For the top four issue categories they identified **94 types of cause in 7 categories and 21
subcategories**. The predominant ones:

| Issue category | Predominant cause |
|---|---|
| Technical Debt | **General programming errors** |
| Security | **Poor security management** |
| Service Execution and Communication | **Invalid configuration and communication** |
| Build | **Legacy versions, compatibility and dependency** |

*Invalid configuration and communication* is named as the source for issues in **service
communication, service execution, access control and build error** subcategories — i.e. it spans
categories.

---

## 6. What this means for our work

**Reason one to keep this paper: Sock Shop is in it.** `microservices-demo/microservices-demo`
contributed **280 closed issues**. When we describe Sock Shop as a research subject, this is a
peer-reviewed study that mined its issue tracker. It also means the 0.67% performance figure
below is partly *about the application we collect from*.

**Reason two: its performance number is starker than the 2023 paper's, and points the same way.**

| Study | Systems | Issues | Performance issues | Share |
|---|---|---|---|---|
| **Waseem 2021** (this) | 5 | 1,345 | **9** | **0.67%** |
| **Waseem 2023** | 15 | 2,641 (2,698 tags) | **45** | **1.67%** |

Two independent samples, both well under 2%. And the 2023 paper's survey of **150 practitioners
says 63.33% hit performance issues "very often" or "often"**.

**Nine issues across five systems is not a population you can mine.** Our three named types here —
*Service Delay*, *High CPU Usage*, *Front-end Service Hangs* — total 9 instances, against 11 fault
families in our campaign and 24 in the dataset. **This is the concrete measurement behind the
"honest gaps" our reference pack records** for connection-pool exhaustion, fork storms and queue
backlog: the literature is thin because the issue trackers are thin, not because the faults are
rare.

**One of their three types is interesting on its own.** *Front-end Service Hangs* is a single
issue, but it is the shape of `code_event_loop_block` — a front end that stops serving everything.
One instance is not evidence; it is a hint that the family is real outside our injection.

**What their Service Execution and Communication category tells us.** At 119 issues it is **13×
the size of Performance**, and its named problems are **service discovery failure**, **server
connection**, **dynamic port binding**, **asynchronous communication** and **service broker**
failures. These are *connectivity* faults, and they are what developers actually file. Our
`dependency-outage-retry-storm`, `dns-delay` and `network-path-degradation` families sit next to
this category, and it is a fairer "happens in the wild" anchor for them than the Performance
category is for the rest.

**A caution.** Closed GitHub issues on open-source projects, manually classified, single study,
no runtime data. **Cite for prevalence and for the filing gap; never for a mechanism.** And
prefer the 2023 paper when either will do — it has three data sources where this has one.

---

## 7. Safe claims

- **1,345 closed issue discussions from five open-source microservice systems on GitHub**,
  manually classified. Only closed issues were used.
- The five systems are **goa, eShopOnContainers, light-4j, Moleculer, and
  `microservices-demo/microservices-demo` (Sock Shop)**; Sock Shop contributed **280** closed
  issues.
- First taxonomy of its kind: **17 categories, 46 subcategories, 138 types**.
- Prominent categories: **Technical Debt 321 (23.86%), Build 145 (10.78%), Security 137 (10.18%),
  Service Execution and Communication 119 (8.84%)**.
- Predominant causes for those four: **General programming errors**, **Poor security management**,
  **Invalid configuration and communication**, **Legacy versions, compatibility and dependency** —
  **94 types of cause in 7 categories and 21 subcategories**.
- **Service Execution and Communication** covers service discovery failure, HTTP protocol
  implementation, centralised transporters (MQTT, NATS, Kafka), connection strings, broken URLs,
  asynchronous communication, dynamic port binding, RabbitMQ messaging and service broker
  problems.
- The **Performance** category totals **9 issues (0.67%)**: *Service Delay* 6, *High CPU Usage* 2,
  *Front-end Service Hangs* 1.
- A single Compilation subcategory, *syntax error*, has **69** issues on its own.

## 8. Do NOT claim

- That this and the 2023 JSS paper are independent studies. **Same first two authors, same method;
  the 2023 paper is the extension.** Do not add their issue counts together.
- That performance problems are rare in practice. This measures **what is filed**, and the 2023
  survey by the same authors says 63% of practitioners hit them often.
- That it contains any runtime, telemetry or mechanism data. It is issue-text classification only.
- That the taxonomy is validated beyond these five systems. The 2023 paper is the one with
  interviews and a practitioner survey.

## 9. Reusable ideas

- **Mine the application you are going to study.** Sock Shop's own issue tracker has been
  classified by someone else, which is free context for describing our subject system.
- **A tiny category can be the most informative one.** Nine performance issues out of 1,345 says
  more about why this research is needed than the 321 technical-debt issues do.
- **Use only closed issues when asking about causes.** Open issues do not have an answer yet.
- **Publish the per-system table.** It is what makes the study reusable by anyone who happens to
  work on one of those systems.
