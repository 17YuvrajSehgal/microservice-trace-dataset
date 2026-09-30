# Paper Summary: PPD — Performance Problem Diagnostics ("Supporting Swift Reaction: Automatically Uncovering Performance Problems by Systematic Experiments")

> Purpose of this file: full reference for an AI agent (Claude Code) so it understands this paper without reading the PDF.
> The user is writing their own research paper that builds on these ideas. Use this file for related work, method comparison, and numbers.
> Sections marked **[Reviewer note]** are NOT claims of the paper. They are observations (gaps, inconsistencies) found while reading.

---

## 1. Bibliographic info

- **Title:** Supporting Swift Reaction: Automatically Uncovering Performance Problems by Systematic Experiments
- **Authors:** Alexander Wert (Karlsruhe Institute of Technology, KIT), Jens Happe (SAP Research, Karlsruhe), Lucia Happe (KIT; email lucia.kapova@kit.edu)
- **Venue:** ICSE 2013 (35th International Conference on Software Engineering), San Francisco, CA, USA. IEEE. pp. 552–561
- **ISBN line:** 978-1-4673-3076-3/13/$31.00 © 2013 IEEE
- **Index terms:** performance; problem detection; measurement
- **Short name of method:** PPD (Performance Problem Diagnostics)
- **Funding:** German Research Foundation (DFG) grant RE 1674/6-1
- **Extended version of hierarchy and all 12 heuristics:** A. Wert, "Uncovering performance antipatterns by systematic experiments," Master's thesis, KIT, 2012 (ref [20])

---

## 2. One-paragraph summary

PPD is an automated approach that **searches for known performance antipatterns** in a Java three-tier enterprise application running in a **test environment**, and **isolates their root cause**. It organizes known antipatterns into a **Performance Problem Hierarchy** (symptoms → problems → root causes) and uses it as a **decision tree**. At each node, PPD runs a **detection strategy**: a goal-driven experiment that (i) varies the workload (e.g., number of users, stimulation time), (ii) dynamically instruments the code to collect specific metrics, and (iii) applies a statistical heuristic (mostly **t-tests** plus utilization thresholds) to decide if the problem is present. If yes, it goes deeper in the tree; if not, the whole branch is skipped. Detection strategies were chosen by measuring their false negative/false positive rates on **10 fault-injected reference scenarios** in an Online Banking test app. Applied to the **TPC-W** bookstore benchmark, PPD found **4 problems** (DB connection pool size, pool implementation, network bandwidth, MySQL storage engine). Fixing them (manually) raised max throughput from **~1800 to >3500 requests/s**. A full diagnosis run took **about 3 hours**.

---

## 3. Problem and motivation

- Performance problems cause lost customers, higher operating cost, damaged reputation.
- Performance is often handled at the end ("**fix-it-later**" approach, Smith [1]). Late problems are expensive.
- Cost escalation (Boehm [2,3]; NASA [4]) for a requirements-phase error:
  - found in design: **3–8×** cost
  - found in integration: **21–78×**
  - found in operation: **29–1500×**
- Slow performance can come from architecture, implementation, or deployment. Engineers need expertise to know typical problems, where to measure, and how to measure without distorting results. Often the needed metrics are not collected → incomplete, noisy data.
- Existing approaches and their weaknesses (as stated by authors):
  - **Architecture/model-based** [5,6]: early, but too abstract; miss implementation causes.
  - **Load tests** [7–10]: include implementation effects, but focus on specific scenarios (e.g., resource bottlenecks); no goal-driven search in the implementation logic.
  - **Runtime data / monitoring** [11,12]: real data, but "last resort"; problems found too late.

### Research / evaluation questions
- **Q1:** Which detection strategies can accurately identify performance problems (least false positives and false negatives)?
- **Q2:** Can PPD identify performance problems and their root cause in real applications?

### Stated contributions
1. PPD: automated approach for performance problem detection and root cause analysis in three-tier enterprise apps.
2. A **Performance Problem Hierarchy** that structures known antipatterns [13–18] from general symptoms to root causes, to guide and prune the search.
3. **Detection strategies for 12 performance problems**, based on goal-oriented experiments; heuristics compared and chosen to minimize false positives/negatives.
4. Two-step evaluation: (a) accuracy of strategies on **10 reference scenarios** with injected problems; (b) application to the **TPC-W** benchmark → 4 problems found.

### Requirements / scope
- Needs a **representative usage profile** (a load driver) and a **test system that resembles the real setup**.
- Current version tailored to **Java-based three-tier enterprise applications**.

---

## 4. Core idea

Two observations:
1. Particular performance problems **share common symptoms**.
2. Many antipatterns in the literature are **defined by a particular set of root causes**.

So: build a hierarchy (Section 5), then run systematic experiments that first test for symptoms and then for more specific problems/root causes (Section 6).

---

## 5. Performance Problem Hierarchy (Fig. 1 and Fig. 6)

Levels: **categories → symptoms → performance problems → root causes**.

Category **Occurrences of High Response Times** groups these symptoms:
- High Overhead
- Varying Response Times
- Unbalanced Processing [13]
- Dispensable Computations

Sub-tree for **Varying Response Times** (Fig. 1b, plus "Temp. High Demand" shown in Fig. 6):

```
Varying Response Times
├── The Ramp                      (response times grow during operation) [13]
│   ├── Dormant References        (memory grows over time) [21]
│   │   └── Specific Data Structure   (root cause: growing / not disposed structure)
│   └── Sisyphus DB Retrieval     [17]
│       └── Specific Methods      (root cause)
└── Traffic Jam                   (many threads wait for same shared resource) [16]
    ├── One Lane Bridge (OLB)     (passive resource limits concurrency) [14]
    │   ├── Synchronization Points    (semaphores, synchronized methods)
    │   ├── Database Locks
    │   └── Pools                 (e.g., DB connection pool)
    ├── Bottleneck Resource       (active/physical resource: CPU, disk, network)
    └── Temp. High Demand         (appears in Fig. 6 only)
```

Definitions:
- **The Ramp:** response times increase over operation time (example: 10 ms at start → >1 s after a few hours).
- **Dormant References:** memory consumption grows over time.
- **Sisyphus Database Retrieval:** retrieving whole tables when only a few rows are needed.
- **Traffic Jam:** many concurrent threads/processes wait for the same shared resource. Passive resource (mutex, semaphore, pool, lock) → One Lane Bridge. Active/physical resource (CPU, disk) → Bottleneck Resource.
- **One Lane Bridge:** a passive resource limits concurrency.

Properties:
- Not all-encompassing, but **extensible**. Hardest part of extending: defining new accurate heuristics.
- Used as a **decision tree**. Root nodes = symptoms, needing only top-level metrics (end-to-end response time, CPU utilization). Deeper nodes need **finer-grained instrumentation**.
- If a node is not detected, its whole sub-tree is skipped (e.g., Ramp not found → Dormant References not tested).

---

## 6. Detection strategies

Each detection strategy targets **one** problem or root cause and consists of:
1. **Workload variation:** independent workload parameters varied across experiments (e.g., number of users, data size, stimulation time).
2. **Observed metrics:** what to measure, defined by **instrumentation rules** (e.g., end-to-end response time, waiting times at a synchronization point).
3. **Analysis strategy:** a heuristic that decides if the problem is present.

- Strategies are defined **once** per class of applications (e.g., Java enterprise apps) and run **fully automatically** on any such app.
- Examples of the logic:
  - If response time **variance grows disproportionately** with number of users → Varying Response Times → possibly Traffic Jam or The Ramp.
  - If **waiting time at a synchronization point** grows significantly with users → that Synchronization Point is a potential root cause of an OLB.
- 12 strategies exist; only 3 are described in the paper (2 for The Ramp, 1 for OLB). All 12 are in [20].

---

## 7. How strategies are evaluated (accuracy metric)

### 7.1 Reference scenarios (fault injection [23])
- Test app: a simple **Online Banking** system (representative three-tier enterprise app).
- **10 reference scenarios**, each with **no, one, or a mix** of injected problems. They test false positives, false negatives, and interaction effects.
- Injection examples:
  - **The Ramp** injected by changing SQL queries to retrieve **complete tables** to show only a fixed, limited number of entries (= Sisyphus DB Retrieval). Tables grow → response times grow.
  - **One Lane Bridge** injected by **synchronizing transactions** so only one runs at a time (software bottleneck).

### 7.2 Accuracy definition (based on Swets [22])
- Accuracy = tuple **(1 − r_fn, 1 − r_fp)**
  - r_fn = probability a problem is falsely neglected (false negative)
  - r_fp = probability a problem is falsely identified (false positive)
- **Expectation vector** for problem p over scenarios s1..sn (Eq. 1): v_p,i = 1 if scenario s_i contains p, else 0.
- Detection strategies for p: t_p = {t_p,1, ..., t_p,m}.
- **Detection vector** (Eq. 2): d_p,k,i = 1 if strategy t_p,k detected p in s_i, else 0.
- **Error vector** (Eq. 3): e_p,k = d_p,k − v_p; value −1 = false negative, +1 = false positive, 0 = correct.
- **Error rates** (Eq. 4):
  - r_fn,p,k = (−1) · (v_p · e_p,k) / (v_p · **1**)
  - r_fp,p,k = ((**1** − v_p) · e_p,k) / ((**1** − v_p) · **1**)
  - i.e., false negatives normalized by number of scenarios with the problem; false positives normalized by number without it.
- **Comparison rule** (Eq. 5): strategy 1 is more accurate than strategy 2 if r_fn,1 < r_fn,2 (when they differ); if r_fn are equal, compare r_fp. **Missing a problem is worse than a false alarm**, so false negatives have priority.

---

## 8. Example 1 — "Direct Growth" (DG) strategy for The Ramp (rejected)

- **Setup:** one experiment of fixed duration D; load driver runs the usage profile with fixed workload intensity w; record end-to-end response times R = (r1..rn) with timestamps T = (t1..tn).
- **Analysis:** split R into R1 = (r1..rk) and R2 = (rk+1..rn) covering about equal time spans (t_k − t_1 ≈ t_n − t_k+1). **t-test** with H0: E[R1] = E[R2]. If H0 rejected and mean(R1) < mean(R2) → The Ramp detected.
- **Evaluation** with w1, w10, w50 (1, 10, 50 concurrent users). Ramp present in scenarios **1, 2, 10**.

**Table I** (d = detected, n = not detected)

| | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | r_fn | r_fp |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v_ramp (truth) | d | d | n | n | n | n | n | n | n | d | — | — |
| DG w1 | n | n | n | n | n | n | n | n | n | n | 3/3 | 0/7 |
| DG w10 | d | n | n | d | n | n | n | n | n | d | 1/3 | 1/7 |
| DG w50 | d | d | n | d | n | d | n | d | n | d | 0/3 | 3/7 |

- Low load: Ramp grows too slowly → all missed.
- High load: many false positives. Scenarios **6 and 8 contain software bottlenecks**, which under constant high load also cause growing response times → confused with the Ramp.
- Conclusion: DG not satisfactory at any load. Core conflict: need high load to trigger the Ramp, but high load also triggers bottleneck effects.

## 9. Example 2 — "Time Windows" (TW) strategy for The Ramp (chosen)

- Observations: (i) high load pushes Ramp behaviour faster; (ii) bottleneck effects must be excluded.
- **Setup:** each experiment has two phases:
  - **Stimulation phase:** high workload to push a potential Ramp. **No measurements.**
  - **Observation phase:** **closed workload with 1 user** and short think time (no concurrency → no synchronization effects). Capture a **fixed number** of end-to-end response times.
- Repeat the experiment with **increasing stimulation duration** → n chronologically ordered sets R1..Rn ("time windows").
- **Analysis:** n − 1 pairwise t-tests on neighbouring windows, H0^i: E[R_i] = E[R_i+1]. If **every** test rejects H0 and mean(R_i) < mean(R_i+1) → response times grow with operation time → The Ramp.
- **Fig. 2:** scenario 1 (Ramp) mean response time rises roughly linearly from ~50 ms to ~350 ms as stimulation time goes 5 → 65 s; scenario 3 (no Ramp) stays flat ~50 ms.
- **Result:** on the same 10 scenarios, **r_fn = 0 and r_fp = 0**. TW is used in PPD.

## 10. Example 3 — Detection strategy for One Lane Bridge (OLB)

- OLB = a **passive resource** (mutex, connection pool, DB lock) limits concurrency. It is a scalability problem, so study behaviour as concurrency grows.
- **Setup:** series of experiments, increasing number of users u1 < u2 < ... < un. Stop when (i) a resource is fully utilized (**> 90%**), (ii) response times increase **more than 10×**, or (iii) the maximum number of potential concurrent users is reached. Also measure **resource utilization** in every experiment (to separate OLB from Bottleneck Resource).
- **Fig. 3** (users 1–31): OLB → response times rise strongly (to ~25 s) while CPU stays low (~15%). Bottleneck Resource (CPU) → response times rise (~20 s) and CPU goes to ~90–95%. No problem → both rise only moderately.
- **Analysis:**
  1. n − 1 pairwise t-tests on neighbouring R_i, R_i+1.
  2. Find j such that all tests from R_j to R_n reject H0 (response times grow for every experiment after j).
  3. If **mean utilization of all resources < 90%** for all i ≥ j → **OLB** (no hardware explains it, so it must be a software resource).
  4. If at least one resource > 90% → no OLB conclusion; that resource is reported as a **Bottleneck Resource**.
- **Evaluation:** paper states it "successfully" identifies bottleneck resources in all reference scenarios; chosen for its low error rate. No numbers given.

---

## 11. Case study: TPC-W benchmark (answers Q2)

### 11.1 System under test (Fig. 4)
- **TPC-W** [24]: official web e-commerce benchmark emulating an online bookstore. **12 request types** for browsing/ordering + **2 admin** request types.
- Implementation: Java-Servlet TPC-W from ObjectWeb [19], on **Apache Tomcat 6 (6.0.35)**; **MySQL 5.0.95** database on a separate machine via **JDBC**.
- Nodes:
  | Node | OS | CPU | RAM |
  |---|---|---|---|
  | Measurement Control Node (PPD + usage profile) | Windows 7 x64 | 2 × 3 GHz | 4 GB |
  | Web/Application server (Tomcat + TPC-W + Satellite) | SUSE Linux | 4 × 2.3 GHz | 4 GB |
  | Database server (MySQL + Satellite) | SUSE Linux | 16 × 2.13 GHz | 16 GB |
- Network: **Setup A = 100 Mbit/s Ethernet**, **Setup B = 1 Gbit/s Ethernet**.
- Lightweight **Satellites** on SUT nodes collect data and **instrument automatically with Javassist** [25]. Communication with PPD via RMI.
- Instrumentation is **rule-based pattern matching**, independent of the app. Example rule: "Measure the response time of all calls to JDBC".
- Usage profile: a **fixed sequence of TPC-W requests**.

### 11.2 Sequence of problems found and fixes (Fig. 5, Table II)

| Step | Config | PPD finding | Fix (manual) | Max throughput |
|---|---|---|---|---|
| 1 | Setup A, Apache Tomcat pool (ApacheCP), pool size 15 | **OLB: DB connection pool** limits concurrency (CPU max ~75%, network ~82%) | Pool size → 60 | ~1800 req/s |
| 2 | Setup A, ApacheCP, pool size 60 | **Resource Bottleneck: network bandwidth** (99% utilization); collisions → throughput *declines* at high load; long response times | Move to 1 Gbit/s (Setup B) | declining |
| 3 | Setup B, ApacheCP, pool size 60 | **OLB: DB connection pool** again; larger size does not help | Replace pool implementation with **BoneCP** [26] | ~2200 req/s |
| 4 | Setup B, BoneCP, pool size 60 | **OLB in the database**: DB call response times grow disproportionately; no DB resource (CPU, network, disk) at capacity; PPD **cannot pinpoint** further | Authors reasoned: MyISAM (MySQL 5.0 default) only has **table locking** → switch to **InnoDB** (row locking) | ~2700 req/s |
| 5 | Setup B, BoneCP, InnoDB | Web server CPU at **100%** → all problems solved | — | **~3500 req/s** |

The "four problems": (1) connection pool size, (2) connection pool default implementation, (3) network bandwidth, (4) DB storage engine. Located in benchmark, web server, database, infrastructure.

**Fig. 5(b): mean response time for the complete usage profile, 50 users:**
config 1 = **378 ms**, config 2 = **868 ms**, config 3 = **267 ms**, config 4 = **215 ms**.

**Table II: utilization (%) by users.** Configs: 1 = Setup A, ApacheCP, PS 15; 2 = Setup A, ApacheCP, PS 60; 3 = Setup B, ApacheCP, PS 60; 4 = Setup B, BoneCP, PS 60.

| Users | CPU 1 | CPU 2 | CPU 3 | CPU 4 | Net 1 | Net 2 | Net 3 | Net 4 |
|---|---|---|---|---|---|---|---|---|
| 1 | 6.3 | 7.1 | 8.8 | 10.0 | 6.8 | 7.1 | 1.1 | 1.3 |
| 10 | 33.6 | 34.2 | 62.5 | 48.58 | 53.2 | 59.4 | 11.2 | 12.1 |
| 20 | 56.1 | 51.1 | 83.3 | 65.48 | 76.6 | 81.2 | 31.4 | 31.2 |
| 30 | 65.8 | 74.3 | 86.9 | 74.05 | 80.4 | 96.5 | 35.6 | 36.1 |
| 40 | 75.5 | 79.7 | 89.1 | 79.82 | 81.6 | 98.7 | 36.2 | 37.2 |
| 50 | 71.2 | 81.2 | 89.7 | 81.45 | 82.3 | 99.4 | 36.0 | 39.5 |

- Fixing was manual; **identification and root cause diagnosis were fully automated**.
- One full diagnosis run with the Fig. 6 hierarchy took **about 3 hours** (experiments + analysis).

### 11.3 Diagnosis in action (Fig. 6, initial setup)

| Node | Result |
|---|---|
| Varying Response Times | detected ✓ |
| The Ramp | excluded ✗ (so Dormant References etc. not tested) |
| Traffic Jam | detected ✓ |
| One Lane Bridge | detected ✓ |
| Synchronization Points | excluded ✗ |
| Database Locks | excluded ✗ |
| Pools | detected ✓ (root cause) |
| Bottleneck Resource | excluded ✗ |
| Temp. High Demand | excluded ✗ |

How root cause instrumentation works:
- PPD inspects **implemented interfaces of all Java classes on the classpath** and matches methods to searched signatures.
- **Javassist** inserts measurement snippets at runtime (dynamic instrumentation).
- Example: all classes implementing **JDBC** are instrumented to test for Database Locks. Then the workload is varied. If JDBC call response time grows disproportionately while no physical resource is saturated → DB locks are a candidate.
- In TPC-W: the **operation that gets a connection from the pool** showed an increase in response time similar to the overall response times → pool is the root cause.

---

## 12. Assumptions and limitations (as stated)

- **Usage profile:** must be provided and representative. A bad profile can hide even simple problems [8]. Could be combined with usage-profile optimization (e.g., Grechanik [8]). Tools like LoadRunner [27].
- **Nature of problems:** works for problems traceable to one code location or resource. Problems spread across many code places (from size/complexity) may be detected but **not isolated**.
- **Threats to validity:** strategies built for typical three-tier enterprise apps; results **not generalizable** without more studies.
- **Heuristics:** best effort; can only be falsified by counterexamples. Defining new heuristics needs **a lot of manual effort and expertise** (shown by the DG → TW story). Each must be evaluated in different scenarios.

---

## 13. Related work (as positioned by the paper)

Categorized by lifecycle phase:
- **Design (model-based):** performance models [28] (Xu, rule-based diagnosis), annotated architecture models [5] (Cortellessa et al., UML antipatterns), [6] (Trubiani & Koziolek, Palladio). Early but too abstract; miss implementation details.
- **Implementation & test:** test case/input selection [8–10, 29, 30] (Grechanik et al. feedback-directed learning; Avritzer & Weyuker; Garousi et al. UML stress tests), regression detection [31, 32] (Bulej et al.; Foo et al.), bottleneck detection [7, 8] (Jiang et al.; Grechanik et al.). Grechanik et al. find bottleneck methods but only **one** problem type.
- **Operation (monitoring):** [11] Parsons & Murphy (reconstruct runtime design model, check antipatterns), [33] Yan et al. (reference propagation profiling), [34] Pinpoint (Chen et al.), [35] Ehlers et al. (self-adaptive monitoring), [36] Miller & Mirgorodskiy (self-propelled instrumentation). Drawback: diagnosis comes **too late**; monitoring overhead.
- **Closest work: Paradyn** [12] (Miller et al.): dynamic instrumentation + **hierarchical search model** narrowing problems to place and time. PPD extends this with **systematic experimentation** (controlled workload variation).

---

## 14. Conclusion and future work (as stated)

- PPD = systematic search via decision tree + goal-oriented experiments; hierarchy of known problems; 12 heuristic strategies; each evaluated on 10 scenarios.
- Applied to a 3rd-party TPC-W implementation in 2 environments; 4 problems; 1800 → >3500 req/s.
- Lowers the effort of performance validation → can run early and regularly, e.g., **with continuous integration tests**.
- Future: integrate with **SAP's development infrastructure**, refine the approach, extend the range of detectable problems.

---

## 15. [Reviewer note] Gaps, weaknesses, inconsistencies

**Evaluation depth**
- Only **3 of 12** strategies are described; the other 9 and their accuracy are only in the master's thesis [20].
- Accuracy tested on only **10 scenarios in one synthetic app**. Rates like 0/3 and 0/7 come from very few cases.
- OLB strategy: **no error rates reported**, only "successfully".
- The t-test **significance level, sample sizes, number of windows, stimulation durations, think time** are not given.
- Thresholds (**90%** utilization, **10×** response time) are fixed and not justified or tested for sensitivity.
- **No comparison against any baseline tool** (e.g., a profiler, Paradyn, or an expert) in the TPC-W case.
- Only one case study (TPC-W); no repeated runs or variance reported for throughput.

**Automation claims**
- Fixing was manual. For the database problem PPD **could not pinpoint** the root cause; the authors inferred MyISAM table locking themselves.
- ~3 hours per run is long for the stated goal of use in continuous integration.
- Needs a **dedicated test environment** that matches production, and a representative usage profile.

**Inconsistencies / typos in the paper**
- The final 3500 req/s (InnoDB) configuration is **not shown** in Fig. 5 or Table II (they only show configs 1–4, max ~2700 req/s).
- Eq. 5 as printed has "if r_fn,1 = r_fn,2" on both lines; the first should be "≠".
- Text says 1800 req/s is a CPU of ~75% "for the CPU of the web server's CPU" (wording); Table II config 1 peaks at 75.5% (40 users), 71.2% at 50 users.
- Fig. 4 labels MySQL 5.0; text says 5.0.95. Tomcat "6" in text, "6.0.35" in figure.
- Typos: "form 1800" (from), "PDD" (PPD).
- Table I: scenario 4 is a false positive for DG at w10 and w50; the text only discusses scenarios 6 and 8.

**Scope limits**
- Designed for **monolithic Java three-tier** apps, not microservices or distributed tracing.
- Depends on a **predefined catalogue** of antipatterns; unknown problem types cannot be found.
- Single-problem focus per strategy; interaction of multiple problems only tested in the synthetic scenarios.

---

## 16. [Reviewer note] How this paper relates to the ASFC paper (Song et al., FGCS 2024)

Useful if the user's paper cites both.

| Aspect | PPD (Wert et al., ICSE 2013) | ASFC (Song et al., FGCS 2024) |
|---|---|---|
| System type | Java three-tier monolith | Microservices on Kubernetes |
| When | Test time (before production) | Operation-time monitoring data |
| Main technique | Controlled experiments + statistical tests + decision tree of antipatterns | Auto-selected cascade of unsupervised deep anomaly detectors + causal graph (PC + PageRank) |
| Knowledge source | Expert-defined antipattern hierarchy and heuristics | Learned from normal data; candidate model pool |
| Output | Antipattern + root cause (e.g., DB connection pool) | Fault type (CPU hog, memory leak, network) + root cause service |
| Data needed | Usage profile, test system, dynamic instrumentation | Metrics (latency, CPU, memory, network); some labeled faults for selection/threshold |
| Evaluation | 10 injected scenarios + TPC-W case study | Sock-Shop and Train-Ticket with injected faults |
| Shared idea | **Hierarchical narrowing**: first a symptom/fault type, then the root cause | Same: diagnose fault type, then localize |

Possible bridge for new work: combine PPD's **active, controlled experiments** (vary load, targeted instrumentation) with ASFC-style **learned detectors and causal graphs** for microservices; or turn PPD's antipattern hierarchy into fault classes for a cascade.

---

## 17. Glossary (quick)
- **Performance antipattern:** a known bad design/implementation habit that causes slow performance.
- **SUT:** system under test.
- **Usage profile / load driver:** script that simulates typical users sending requests.
- **Throughput:** requests handled per second.
- **Passive resource:** software resource that must be acquired (lock, mutex, pool).
- **Active resource:** hardware resource (CPU, disk, network).
- **One Lane Bridge:** a passive resource that lets too few requests through at once.
- **The Ramp:** response time keeps growing the longer the system runs.
- **t-test:** statistical test for whether two groups have different means.
- **Closed workload:** fixed number of users; each sends a new request after the previous one finishes (plus think time).
- **Dynamic instrumentation:** adding measurement code at runtime (here with Javassist).
- **False negative / false positive:** missed problem / false alarm.
