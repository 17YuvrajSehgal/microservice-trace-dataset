# Paper Context: RCAEval — A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data (WWW Companion 2025)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is a **4-page benchmark/resource paper**. It is our closest comparison point as a
> *dataset*: same two applications (Sock Shop, Train Ticket), same style of fault injection,
> published root-cause labels. Section 11 lists the differences that matter for us - the
> biggest is that **RCAEval has no kernel traces**.

---

## 1. Bibliographic info

- **Title:** RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems with
  Telemetry Data
- **Authors:** Luan Pham (RMIT / UNSW), Hongyu Zhang (Newcastle), Huong Ha (RMIT),
  Flora Salim (UNSW), Xiuzhen Zhang (RMIT)
- **Venue:** Companion Proceedings of the ACM Web Conference 2025 (WWW Companion '25),
  Sydney, 28 Apr - 2 May 2025. 4 pages
- **DOI:** 10.1145/3701716.3715290
- **arXiv:** 2412.17015v5, 3 Feb 2025
- **Licence:** CC BY 4.0
- **Code + data:** https://github.com/phamquiluan/RCAEval (also on PyPI)
- **Funding:** Australian Research Council DP220103044

```bibtex
@inproceedings{pham2025rcaeval,
  title     = {RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data},
  author    = {Pham, Luan and Zhang, Hongyu and Ha, Huong and Salim, Flora and Zhang, Xiuzhen},
  booktitle = {Companion Proceedings of the ACM Web Conference 2025},
  year      = {2025},
  doi       = {10.1145/3701716.3715290}
}
```

---

## 2. One-paragraph summary

There is no standard benchmark for root cause analysis in microservices, so every paper
evaluates on its own small setup and the results cannot be compared. RCAEval fixes that. It
publishes **three datasets with 735 failure cases** from **three systems** (Online Boutique,
Sock Shop, Train Ticket), covering **11 fault types**, with **metrics, logs and traces**. It
also publishes an evaluation framework with **15 reproducible baselines** and two standard
metrics. Their own preliminary run shows the field is not solved: the best average Avg@5 on
Train Ticket is around 0.8, and methods that do well on resource faults do badly on network
faults.

---

## 3. Problem and motivation

The paper's complaint is about evaluation, not about methods.

- Most RCA studies use **1-2 systems and 2-3 fault types**.
- Some use **private data** (they name AWS and Oracle), so nobody can reproduce it.
- One prior dataset (Eadro) used an **unrealistic load of 2-3 requests per second**.
- Existing open resources each miss something (Table 1):

| Resource | Fault types | Metrics | Logs | Traces |
|---|---|---|---|---|
| PyRCA (Salesforce) | synthetic | yes | - | - |
| AIOps 2020 | resource, network | yes | - | yes |
| Pham et al. 2024 | resource, network | yes | - | - |
| **RCAEval** | **resource, network, code-level** | **yes** | **yes** | **yes** |

They also state a finding from their own prior work that is worth keeping: **performance on
synthetic datasets does not predict performance on real systems.**

---

## 4. Definitions the paper uses

- **Failure** = a service cannot do its job.
- **Fault** = the underlying cause (e.g. a memory leak).
- **RCA** = find the root cause from telemetry.
- They score two levels:
  - **coarse-grained** = the root cause *service*
  - **fine-grained** = the root cause *indicator* (which metric or log points at it)

---

## 5. The three datasets

| Dataset | Cases | Systems | Fault types | Data |
|---|---|---|---|---|
| **RE1** (from prior work) | 375 (125/system) | 3 | 5: CPU, MEM, DISK, DELAY, LOSS | metrics only, 49-212 per case |
| **RE2** (new) | 270 (90/system) | 3 | 6: RE1 + SOCKET | metrics 77-376, logs 8.6-26.9 M lines, traces 39.6-76.7 M |
| **RE3** (new) | 90 (30/system) | 3 | 5 code-level: F1-F5 | metrics 68-322, logs 1.7-2.7 M, traces 4.5-4.7 M |

**735 cases total.** Every case is annotated with the root cause service **and** the root cause
indicator.

Design: RE1 is 5 faults × 5 services × 5 repeats. RE2 is 6 faults × 5 services × 3 repeats.

---

## 6. The three systems

| System | Services | Notes |
|---|---|---|
| Online Boutique (Google) | 12 | e-commerce, gRPC |
| **Sock Shop** (Weaveworks) | 15 | e-commerce, HTTP |
| **Train Ticket** (Fudan) | 64 | sync + async, most complex call chains. They call it the largest benchmark microservice system |

They note the systems deliberately mix languages (Java, Go, Python, C#) and protocols
(HTTP, gRPC).

---

## 7. The 11 fault types

**Resource faults (4)** - injected with `stress-ng` into the container: CPU hog, Memory leak,
Disk stress, Socket stress. Root cause indicator = the matching resource usage metric.

**Network faults (2)** - injected with `tc`: DELAY (added latency), LOSS/DROP (random packet
drops). Indicator = latency metric for DELAY; failed-request metric or error response codes in
traces for LOSS.

**Code-level faults (5)** - actual source edits to random services, taken from a study of
OpenStack failures: F1 incorrect parameter values, F2 missing parameters, F3 missing function
call, F4 incorrect return values, F5 missing exception handlers. Indicator = the stack trace in
logs; failing that, error logs or response codes.

**They claim RE3 is the first RCA dataset to cover code-level faults for microservices.**

---

## 8. How the data was collected

- Deployed on **Kubernetes** clusters.
- Random load of **10-200 requests per second** across all services.
- Metrics: **Prometheus, cAdvisor, Istio** (application-level and resource-level).
- Logs: **Vector + Loki**, stored in Elasticsearch.
- Traces: **Jaeger**, stored in Elasticsearch.
- Procedure: run normally to collect normal data, then inject a fault into a **randomly
  selected** running service and collect abnormal data.
- A DevOps engineer with 5 years of microservice experience helped with deployment and
  verification.
- Everything stored as **CSV**.

---

## 9. Evaluation framework

**15 baselines**, grouped by data source:

| Group | Methods |
|---|---|
| Metric-based, causal | RUN, CausalRCA, CIRCA, RCD, MicroCause, EasyRCA, MSCRED |
| Metric-based, non-causal | BARO, ε-Diagnosis |
| Trace-based | TraceRCA, MicroRank |
| Multi-source | PDiagnose, multi-source BARO, multi-source RCD, multi-source CIRCA |

They reused published implementations with default hyperparameters and **verified correctness
by reproducing the original papers' results**. PDiagnose they reimplemented, since no source
was available.

**Two metrics:**
- **AC@k** - probability that the true root cause is in the top k results.
- **Avg@k** = mean of AC@1..AC@k. An overall score.

---

## 10. Preliminary results (Table 6, Train Ticket, RE2)

Average across six fault types:

| Source | Method | AC@1 | AC@3 | Avg@5 |
|---|---|---|---|---|
| Metric | **BARO** | 0.67 | 0.82 | **0.80** |
| Metric | CausalRCA | 0.22 | 0.47 | 0.43 |
| Metric | CIRCA | 0.32 | 0.47 | 0.46 |
| Metric | MicroCause | 0.10 | 0.22 | 0.20 |
| Metric | RCD | 0.09 | 0.13 | 0.13 |
| Trace | MicroRank | 0.16 | 0.37 | 0.31 |
| Trace | **TraceRCA** | 0.66 | 0.79 | **0.77** |
| Multi | BARO | 0.69 | 0.82 | 0.81 |
| Multi | CIRCA | 0.06 | 0.11 | 0.13 |
| Multi | PDiagnose | 0.48 | 0.70 | 0.67 |
| Multi | RCD | 0.10 | 0.64 | 0.54 |

**The pattern that matters:** BARO gets **1.00 on DISK** but only **0.47 AC@1 on DELAY** and
**0.53 on LOSS**. Resource faults are easy; network faults are not.

The paper's own conclusion: "existing methods mostly obtain moderate results" and "further
research is needed to develop a holistic RCA solution".

> Note: the paper's text says CIRCA and RCD get "the best average Avg@5 score of 0.46 and
> 0.54" - but Table 6 shows BARO at 0.80/0.81, clearly higher. The sentence appears to be an
> error. **Cite the table, not the sentence.**

---

## 11. What this means for our work

**This is our nearest dataset neighbour, and the comparison is favourable in one specific way.**

| | RCAEval | StrataTrace (ours) |
|---|---|---|
| Applications | Online Boutique, **Sock Shop**, **Train Ticket** | **Sock Shop**, **Train Ticket** |
| Cases | 735 | 303 runs (v2) |
| Fault types | 11 | ~24 families |
| Metrics | yes | yes |
| Logs | yes | yes |
| Distributed traces | yes | yes |
| **Kernel traces** | **no** | **yes** |
| Deployment | Kubernetes | Docker Compose on one VM |
| Load | 10-200 req/s | load generator, recorded per run |
| Labels | root cause service + indicator | service + container pid_ns + injection window |

**The gap is the kernel modality.** RCAEval covers metrics, logs and traces. It does not
collect kernel data at all. That is exactly the modality our dataset adds, and this paper is
the citation that shows the gap is real in the most complete public benchmark available.

**Their network-fault result is directly useful to us.** On Train Ticket, the best metric
method drops to 0.47 AC@1 on DELAY and 0.53 on LOSS, while scoring 1.00 on DISK. **Network
faults are the hard case for metric-based RCA.** Our own network blueprints target the same
faults from the kernel side, so this is the number to compare against - not as a claim that we
beat them, but as evidence that the problem is unsolved with metrics alone.

**Two methodology points we should copy or cite.**

- **AC@k and Avg@k** are the standard metrics in this field. Our WHERE score is a different
  thing (a verified container match, not a ranked list), and we should say so rather than
  imply comparability.
- **Synthetic data does not predict real performance** - their prior finding. Good support for
  why we collect from a running system rather than simulate.

**A caution about comparing scores.** Their task is "rank the root cause service from
telemetry, given the failure window". Ours is "find the container *and* the window from a raw
kernel trace, without being told a fault happened". Ours is harder in scope and narrower in
data. **The numbers are not comparable** and we should never place them in the same table.

---

## 12. Safe claims

- There is no standard RCA benchmark for microservices; studies typically use 1-2 systems and
  2-3 fault types, and some use private data.
- RCAEval publishes 735 failure cases from 3 systems with 11 fault types, including metrics,
  logs and traces, plus 15 reproducible baselines.
- It is the first RCA dataset for microservices to include **code-level** faults.
- It contains **no kernel-level data**.
- On Train Ticket, the best baselines reach around Avg@5 0.80, and accuracy on network faults
  (DELAY, LOSS) is much lower than on resource faults.
- Performance on synthetic datasets does not reflect performance on real systems (their prior
  finding, cited in this paper).

## 13. Do NOT claim

- That RCAEval includes kernel traces, eBPF or LTTng data. It does not.
- That our scores can be compared with theirs. Different task, different inputs, different
  metric.
- That CIRCA and RCD are the best methods - the paper's own text says this but its table
  contradicts it.
- That 735 cases means 735 distinct faults; it is 11 fault types with repeats across services.

## 14. Reusable ideas

- **Publish the evaluation harness with the data.** A dataset without baselines does not stop
  people evaluating inconsistently.
- **Label two levels**: the root cause *service* and the root cause *indicator*. We do the
  equivalent with service plus container namespace.
- **Repeats per fault-service pair** (5 in RE1, 3 in RE2) - the same reason we run 5 repeats.
- **Report per-fault-type, not just an average.** Their DISK-vs-DELAY split is the most
  informative thing in the paper and an average would have hidden it.
