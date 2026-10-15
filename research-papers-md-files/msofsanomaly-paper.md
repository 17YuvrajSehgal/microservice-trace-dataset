# Paper Context: MSoFSAnomaly (JSS 2025)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> It captures every key idea, method detail, number, and limitation of the paper so the
> agent can reason about it, cite it correctly, compare against it, and reuse its ideas
> without re-reading the PDF. All numbers are taken from the paper. Values read from
> figures (not stated in text) are marked "approx.". Internal inconsistencies are listed
> in Section 13.

---

## 1. Bibliographic info

- **Title:** A failure analysis framework to provide pure anomalous data using multi-source data of fault-sensitive microservices
- **Method name:** **MSoFSAnomaly** (Multi-Source data of Fault-Sensitive microservices for Anomaly detection)
- **Authors:** Nan Fu, Guang Cheng (corresponding, chengguang@seu.edu.cn), Guangye Dai, Hantao Mei, Xing Qiu, Yue Teng
- **Affiliation:** School of Cyber Science and Engineering, Southeast University, Nanjing, China; Jiangsu Province Engineering Research Center of Security for Ubiquitous Network
- **Venue:** The Journal of Systems and Software (JSS), Vol. 230 (2025), Article 112513. Editor: Jacopo Soldani.
- **DOI:** 10.1016/j.jss.2025.112513
- **Dates:** received 23 Dec 2024; revised 17 Apr 2025; accepted 22 May 2025; online 7 Jun 2025
- **Code:** https://github.com/FuN312/MSoFSAnomaly (the "Data availability" section says data available on request)
- **Funding:** National Natural Science Foundation of China, grant 62172093
- **Keywords:** microservice systems, multi-source data mining, feature analysis, failure detection

```bibtex
@article{fu2025msofsanomaly,
  title   = {A failure analysis framework to provide pure anomalous data using multi-source data of fault-sensitive microservices},
  author  = {Fu, Nan and Cheng, Guang and Dai, Guangye and Mei, Hantao and Qiu, Xing and Teng, Yue},
  journal = {Journal of Systems and Software},
  volume  = {230},
  pages   = {112513},
  year    = {2025},
  doi     = {10.1016/j.jss.2025.112513}
}
```

---

## 2. One-paragraph summary

MSoFSAnomaly is an **unsupervised, reconstruction-based failure detector** for microservice
systems whose goal is to hand **"pure" anomalous data** (only truly anomalous time points, no
normal data mixed in) to a downstream **root cause localizer**. It has three parts:
(1) **fault-sensitive microservice selection**: build a call tree from normal traces and keep
only **leaf microservices** (services that call no others) plus all services in **call cycles**,
because faults propagate down to leaves; (2) **fault-feature correlation analysis**: mutual
information on 11 K8s metrics shows metrics catch resource faults but not code/network faults,
so they add two trace features, **Span Duration** and a new **Span Offset** (child span timing
relative to parent span end); the final 5 features are MCUR, NCUR, MMUR, Span Duration, Span Offset;
(3) a **Transformer encoder–decoder** that reconstructs the **per-window maximum** of each
(microservice, feature) over a sliding window of W = 3 minutes; the reconstruction error
(MSE) is compared to a threshold `val_re·(1+μ)` with μ = 11; the per-feature squared error is
also used for **interpretation** (top-3 (microservice, feature) pairs). On Online Boutique (OB, 11
services) it gets **Precision 97.16%, Recall 97.85%, FPR 3.10%**; on Train Ticket (TT, 41 services)
**Precision 85.17%, Recall 80.54%, FPR 8.78%**, beating 8 baselines on balance (not on every
single metric). Test time ≈ 0.03 s.

---

## 3. Problem framing and motivation

### 3.1 The RCA workflow (Fig. 1)

`All microservices data → selected features → failure detection → failure time window → root cause localization`

The detector's output window becomes the localizer's input. If that window contains unexpected
normal data (impure), the localizer degrades.

### 3.2 Motivating evidence (Introduction)

- On public **Social Network (SN)** metrics from Eadro (Lee et al., ICSE 2023), existing detectors do poorly: **SPOT recall 23%**, **OmniAnomaly recall 35%**.
- Window choice differs wildly across methods: **MicroCause** uses a 4-hour window before the anomaly; **Dycause** uses 280 data points after it.
- As anomalous-data purity decreases: **Grace F1 drops from 90% to 60%**; **Dycause top-5 localization drops from 71% to 30%**. (How purity was varied is not described.)
- Too little true anomaly → localizer cannot find the cause. Too much normal data → higher cost and worse localization.

### 3.3 Three limitations of existing detectors (the paper's stated gaps)

1. **Weak use of sensitivity differences among microservices.** Methods analyze all active services, ignoring that some services reflect others' faults much more strongly (determined by invocation structure).
2. **No fault-type ↔ data-source correlation analysis.** Multi-source methods (Eadro, Nezha, UAC-AD, ServiceAnomaly) use all data for all faults, causing redundancy. Example: CPU contention is visible in metrics alone; error returns are not.
3. **Ignoring data distribution.** Detector + window methods (MicroCause, MicroHECL, DejaVu) depend on distribution and produce many false positives when anomalies are **scarce and continuous** ("locally anomalous data").

### 3.4 Claimed novelty

Combining (a) fault-sensitive microservice selection via interaction patterns, (b) fault-type ↔ multi-source feature correlation, and (c) Transformer-based reconstruction that learns significant feature changes over adjacent time points.

### 3.5 Contributions

1. Quantitative correlation analysis between fault types and multi-source data; hierarchical (call-tree) representation of service calls and analysis of sensitivity differences.
2. MSoFSAnomaly framework: detects failures and outputs pure anomalous data; Transformer models feature representations of fault-sensitive services and their dependency with faults.
3. Evaluation on OB (11 services) and TT (41 services): P 97.16/85.17%, R 97.85/80.54%, FPR 3.1/8.78%. Code public.

---

## 4. Background definitions used

- **Microservice system:** app split into lightweight, loosely coupled, independent services (e.g., Train Ticket = 41 services such as order, price, seat).
- **Failure vs fault:** failure = unexpected deviation in service delivery; fault = its cause (Notaro et al. 2021).
- **Failure detection:** rapidly identify anomalous states from resource consumption, network delay, or code errors. **Failure analysis:** also report anomalous features and services.
- **RCA workflow:** data collection → feature extraction → failure detection → root cause localization.
- **Trace / span:** a trace is a request's end-to-end journey; a span is one operation in it.
- **Transformer rationale:** self-attention computes dependencies between all positions in parallel; models long-range and cross-service dependencies; test time nearly agnostic to sequence length; attention gives explicit dependency representation for interpretation; LSTM is sequential, slower, weaker at long dependencies. Precedent: TADL (Li et al., SANER 2023).
- **Locally anomalous data (paper's term):** real-world data where normal and anomalous data occur in chronological order and anomalies are much rarer than normal data. This is the paper's primary target setting.
- **Pseudo-normal data (paper's term):** data labeled normal (after a fault's injection window ends) that still shows anomalous characteristics due to lingering effects, recovery, or gradual resource state transitions.

---

## 5. Related work taxonomy (Section 3)

### 5.1 Detector types in RCA pipelines (Table 1)

Type M = detects anomalous **moments**; Type P = detects anomalous **periods** (moment detection + window selection).

| Type | RCA method | Detection data | Detection algorithm | Input to localizer |
|---|---|---|---|---|
| P | MicroCause (Meng 2020) | Metrics | SPOT | Metrics in preceding 4 h |
| P | MicroHECL (Liu 2021) | Metrics | OC-SVM, Random Forest, 3-sigma | Service calls + metrics in current window (e.g., 10 min) |
| P | DejaVu (Li 2022) | Metrics | / | Metrics + failure dependency graphs around anomaly |
| M | Grace (Ren 2023) | Metrics, Traces | / | Anomalous metrics + service traces |
| M | Nezha (Yu 2023) | Metrics, Traces | N-sigma | Anomalous metrics + call latency at exact moment |
| P | Dycause (Pan 2023) | Metrics | SPOT | Metrics in current window (e.g., 280 points) |
| P | CloudRanger (Wang 2018) | Metrics | Polynomial regression | Metrics in a window (e.g., 5 s) |
| P | MonitorRank (Kim 2013) | Metrics | / | Metrics in approximate period |
| P | MicroRank (Yu 2021) | Traces | N-sigma | Traces in last window (e.g., 30 s) |
| M | Microscope (Lin 2018) | Metrics | N-sigma | Metrics + service connections at exact moment |
| P | TraceRCA (Li 2021) | Metrics, Traces | N-sigma | Anomalous traces in last window |

### 5.2 Detector families

- **Statistical:** N-sigma (per-feature mean/std baseline per service), SPOT (extreme value theory, per-time-point thresholds), JumpStarter (multivariate metrics; clustering + outlier-resistant sampling; compressed sensing). Lightweight, but distribution-dependent, no fault–feature correlation, per-service baselines scale badly.
- **Model-based:** ADSketch (metric subsequence pattern sketching, Euclidean distance), ServiceAnomaly (traces → call propagation graph with edges labeled by 6 metrics; subgraph + metric matching). Rely on predefined patterns; ServiceAnomaly compares full call graphs, no sensitivity analysis.
- **Learning-based:** LSTM-AD (trace feature sequences into LSTM), TraceAnomaly (service trace vectors into deep Bayesian network with posterior flow). Usually ignore feature changes between neighboring time points (TraceAnomaly looks at a single time point); use all services without sensitivity selection. Work well on balanced data, worse on scarce continuous anomalies.

### 5.3 Features in prior work

- Metrics: CPU/memory, response time, error/success rates, QPS, throughput.
- Traces: trace/span latency.
- Eadro and Nezha found metrics and traces give different insights per fault type: system metrics catch CPU contention/consumption; trace latency catches error returns.
- Logs rarely used for detection (parsing complexity, cost).

---

## 6. Method overview (Fig. 2)

Unsupervised. **Training:** learn normal data by minimizing distance between normal data and its reconstruction. **Testing:** compute reconstruction error; if above threshold derived from normal (validation) data → anomalous.

Three phases:
1. **Fault-sensitive microservices selection** (traces → call dependencies → call tree → selected services).
2. **Feature exploration with multi-source data** (metrics + traces → correlation with fault types → feature extraction, serialization, time alignment → tensor D(T, M, F)).
3. **Failure detection and interpretation** (sliding window → linear projection → position embedding → Transformer reconstruction → reconstruction distance → alarm + top-3 interpretation).

---

## 7. Phase 1: Fault-sensitive microservice selection

### 7.1 Call graph → call tree

- Use **traces from normal runs** to get call relationships.
- Without cycles: build call graph, convert to **call tree** to analyze depth.
- Transitive-edge removal example (Online Boutique, Fig. 3): frontend calls checkout and shipping; checkout also calls shipping. Place frontend at level i, checkout at i+1, shipping at i+2, and **remove the frontend→shipping edge** to highlight hierarchy.
- OB call tree (Fig. 3b): frontend → recommendation, checkout, ad, currency; recommendation → productcatalog; checkout → productcatalog, cart, email, payment, shipping, currency (dashed cross-layer edges exist). Leaves: productcatalog, cart, email, payment, shipping, ad, currency.
- Node types: **root** (not called by anyone), **leaves** (call no one), **intermediate**.

### 7.2 Four fault propagation patterns (Fig. 4)

- (a) Fault at a leaf, no callers → stays at that node.
- (b) Fault at a leaf with callers → may affect some ancestors and their descendants.
- (c) Fault at an intermediate node with no callers → propagates down, affecting some children.
- (d) Fault at an intermediate node that is called → pattern (c) plus affects ancestors and their descendants.
- Root faults are not a separate category (same as (c)).
- Conclusion: faults quickly spread **down to leaf nodes** along the call chain → **fault-sensitive microservices = microservices that do not call other microservices (leaves).**

### 7.3 Cycles

Services in circular dependencies can trigger and amplify failures via feedback → **select all services in each cycle**, merged with leaves.

### 7.4 Algorithm 1 (Fault-sensitive microservices selection)

```
Input: normal traces Tras
Output: fault-sensitive microservices M
for each trace t:
    TraceID, SpanID, ParentID, PodName, OpName ← aggre(Tras)
    call_list ← invk(TraceID, SpanID, ParentID, PodName, OpName)
check for cycles (DFS)
if no cycles: M ← ExtractLeafMicroservices(call_list)
else:         m1 ← IdentifyServicesInCycle(call_list)
              m2 ← ExtractLeafMicroservices(call_list)
              M  ← Merge(m1, m2)
return M
```

- Complexity **O(n + m)** (n services, m call pairs). Worst case (everyone calls everyone) m → O(N²), so **O(N²)**.

### 7.5 Indirect interactions via shared storage

- Tracing tools propagate context along request chains; shared storage (e.g., an S3 data warehouse or file) breaks the TraceID.
- Example chain C → A → s3 → B → D. Ideal: pairs [[C,A],[A,s3],[s3,B],[B,D]] → select D. Real: two traces [[C,A],[A,s3]] and [[s3,B],[B,D]] → select s3 and D. Superset of the ideal choice, so the authors argue precision is not hurt.

### 7.6 Empirical sanity check (Fig. 5)

- Used a public dataset from Eadro: 27 business-related microservices, 7 h normal + 1 h anomalous at 1-s intervals; faults injected randomly into all services every 2 min, each lasting 600 s (as stated; see Section 13).
- Threshold per service = average feature value of normal data; count anomalies reflected by feature changes over the 3,600 s anomalous stage.
- Algorithm 1 selected **17 of 27** services; the selected ones show strong fault-sensing ability. (Bar chart: top services travel ~950, food ~840; most others ~260–460; selected in orange.)

---

## 8. Phase 2: Feature exploration with multi-source data

### 8.1 Fault categories

Three categories (from Nezha, Dycause, TraceRCA): **resource faults**, **program code faults**, **network faults**.
Five concrete faults evaluated: **CPU contention**, **CPU consumed** (resource); **network delay** (network); **error return**, **exception code defect** (program code).

### 8.2 Metrics analysis via mutual information

- 11 system- and application-level K8s metrics analyzed (only the 4 selected are named).
- MI (Kraskov et al. 2004):
  ```
  I(X;Y) = Σ_{x,y} p(x,y) · log( p(x,y) / (p(x)p(y)) )
  ```
  X = metric, Y = normal/anomalous label. Stated range 0–1.
- Procedure: split data chronologically into blocks around each fault (each block has normal + anomalous); compute MI per fault per (selected service, feature); average MI of a feature across selected services under that fault; keep features whose average exceeds the **90th percentile** for all faults.

**Table 2: effective metrics**

| Fault type | OB | TT |
|---|---|---|
| Resource faults | MCUR, NCUR, NRB | MCUR, NCUR |
| Network faults | / | MMUR |
| Program code faults | / | / |

- **MCUR** = CPU usage rate of each microservice; **NCUR** = CPU usage rate of each node; **NRB** = network bytes received by each node; **MMUR** = memory usage rate of each microservice.
- Finding: **no metric significantly reflects program code faults** on either dataset.

### 8.3 Trace analysis: Span Duration and the new Span Offset

- **Span Duration:** duration of each span (used in prior work); captures single operations only.
- **Span Offset (proposed):** relative timing of each **child span with respect to the end of its parent span**; captures dependencies/bottlenecks across operations in the chain.
  - Positive offset: parent span ends after the child span ends.
  - Negative offset: two types, distinguished by comparing |offset| with the child span's duration (i.e., whether the child ends after the parent by less or more than its own duration). Exact formula not given.
  - Same relations also apply among multiple child spans.
- Validation: extract both per microservice and apply an N-sigma variant; measure recall (precision on normal data deliberately sacrificed in this experiment).

**Table 3: Recall of trace features**

| Fault | OB Offset | OB Duration | OB Both | TT Offset | TT Duration | TT Both |
|---|---|---|---|---|---|---|
| Network delay | 100% | 42.9% | 100% | 100% | 100% | 100% |
| Error return | 0% | 33.3% | 33.3% | 72.7% | 100% | 100% |
| Exception code | 33.3% | 33.3% | 66.7% | 100% | 84.6% | 100% |

Conclusion: trace features reveal faults metrics miss → combine sources.

### 8.4 Final feature set (F = 5)

- **Resource faults:** MCUR, NCUR, MMUR.
- **Program code + network faults:** Span Duration, Span Offset.
- (NRB, though effective in OB, is not in the final set.)

Algorithm 2 (feature extraction):
```
for t = 1..T:
    MCUR, NCUR, MMUR = metrics_extra(Mets, M)
    Sp_Dur, Sp_Off   = traces_extra(Tras, M)
    F = aggre2(MCUR, NCUR, MMUR, Sp_Dur, Sp_Off, M)
```

### 8.5 Serialization and preprocessing

- **Z-score using training statistics only**, applied to both train and test: `M'_d = (M_d − mean(M_train)) / std(M_train)`. Reason: separate normalization would shift the normal-data distribution between splits.
- Traces depend on user behavior; a selected service may have no calls in some interval → **missing value imputation** (method not specified), then the same Z-score.

### 8.6 Clock sync and time alignment

- Keep only features sharing the same Unix timestamps across metrics and traces.
- Metrics collected **every 1 minute**; traces recorded per request and **aggregated every minute**.
- Result: 3-D tensor **D(T, M, F)** (time × microservice instance × feature).

---

## 9. Phase 3: Transformer-based detection and interpretation (Fig. 7)

### 9.1 Window embedding

- Sliding window of **W time points** → data blocks. Token = **D_t**, all selected services' features at time t.
- Flatten D_t along microservice and feature dims, linear mapping → D'_t ∈ R^{W×(M·F)}. Positions of (service, feature) in the vector are fixed → aids interpretation.
- Learnable 1-D position embedding (Eq. 2):
  ```
  z_0^t = [D'_{t−w+1}; …; D'_{t−1}; D'_t] + E_pos,   E_pos ∈ R^{W×(M·F)}
  ```
  Fig. 2 also shows an E[CLS]/P[*] token, not discussed in text.

### 9.2 Reconstruction network

- **Encoder** (Eq. 3–4), pre-norm style, L layers (Fig. 7 shows 2 encoder blocks):
  ```
  z'_ℓ = Drop(MHA(Norm(z_{ℓ−1}))) + z_{ℓ−1}
  z_ℓ  = Norm(MLP(Norm(z'_ℓ))) + z'_ℓ          # MLP: linear → GELU → LayerNorm
  ```
- **MHA:** H heads, where **H = number of features = 5**; scaled dot-product attention.
- **Decoder:** five-head self-attention + feed-forward (Fig. 7 shows 2 decoder blocks), produces z_d.
- **Maximum output block (Eq. 5):** since features rise sharply during faults, the output is the **max over the window (time) for each of the M·F columns**:
  ```
  Output = Max(z_d[:, i]),  i = 1..M·F
  ```

### 9.3 Failure alarm

- Rec^t_w = reconstruction for window at time t. **Max^t_w** = per-(service, feature) maximum of the raw window.
- Assumption: under a fault, distance between Max and Rec is much larger than the normal baseline.
- **Loss / anomaly score (Eq. 6):**
  ```
  Loss = Σ_i^M Σ_j^F (Rec^t_w[i,j] − Max^t_w[i,j])² / (M·F)
  ```
- **val_re** = maximum loss on the validation set at the end of training (idea from TADL).
- Observation (Fig. 8, 2 h random test data): normal reconstruction outputs cluster in a narrow range; anomalous ones spread wider; in TT some anomalous points overlap normal ones (model misses those faults). A simple linear threshold suffices.
- Test normal data differ from training normal data (anomalies influence neighboring normal data), so raw val_re would cause false positives → **threshold (Eq. 7):**
  ```
  test_th = val_re + μ·val_re        # μ = 11 → threshold = 12 × val_re
  ```
- Flag window as anomalous if its error exceeds test_th.

### 9.4 Failure interpretation

- Linear projection along time of Rec^t_w and Max^t_w → R^t_w, M^t_w ∈ R^{1×(M·F)}.
- **Distance vector (Eq. 8):** `Dis^t_W[i] = (R^t_w[i] − M^t_w[i])²`, i = 1..M·F. Each entry = contribution of one (service, feature).
- **Top-K with K = 3** → report the top 3 (microservice, feature) pairs per detected fault.
- Aggregated over correctly detected faults into heat maps (Fig. 11).

---

## 10. Evaluation setup

### 10.1 Systems and datasets (Table 4)

| Dataset | #Microservices | Collection interval | Fault duration | #Fault injections | Anomaly ratio |
|---|---|---|---|---|---|
| OB (Online Boutique, e-commerce) | 11 | 1 min | 3 min | 56 | 31.11% |
| TT (Train Ticket, ticket booking) | 41 | 1 min | 3 min | 45 | 23.44% |
| SN (Social Network, DeathStarBench; public, from Eadro) | 21 | 1 s | 2 min | 72 | 21.88% |

- SN is used only for the Introduction's motivating detector results.
- **Platform:** Kubernetes cluster of 4 cloud servers (4-core 2.50 GHz CPU, 16 GB RAM, CentOS 7.6). **Jaeger** for traces; **cAdvisor** and **Istio** for metrics (CPU, request latency).
- **Fault injection:** Chaos Mesh StressChaos (resource), Chaos Mesh Request/Response Delay (network), and for code faults Chaos Mesh, **Hypno** (Python), **Failpoint** (Go), following Nezha and DeepTraLog; services in Java, Python, Go.
- **Injected services:** TT, 12 randomly chosen: preserve, security, contacts, verification-code, food, train-food, travel, travel2, basic, price, route, seat. OB, 10 of 11 (all except loadgenerator, a Python/Locust traffic generator).
- **Training machine:** Python 3.10; Linux, 3.20 GHz CPU, 132 GB RAM, Ubuntu 20.04.
- **Split:** train/val/test = **7:1:2** (ordering not stated).
- **Hyperparameters:** 5-head attention; Adam, lr 0.001, StepLR; batch 32; 100 epochs; **W = 3**; **μ = 11**; top-K = 3.
- **Metrics:** Precision, Recall (TPR), FPR, on test sets, framed as quality of data fed to the localizer.

### 10.2 Baselines (8, all unsupervised)

N-Sigma (statistical), SPOT (EVT), JumpStarter (compressed sensing), ADSketch (pattern sketching), ServiceAnomaly (traces + 6 metrics, graph matching), MicroHECL-SVM (OC-SVM on response time), TraceAnomaly (deep Bayesian net with posterior flow; VAE + modified Glow), LSTM-AD (single-modality LSTM on traces). Instance-based baselines (N-Sigma, SPOT, JumpStarter) were given one model per feature per fault-sensitive service.

### 10.3 Research questions

- RQ1: performance across faults, features, data.
- RQ2: beats baselines by reducing false positives while keeping recall?
- RQ3: efficiency and scalability.
- RQ4: influence of selected fault-sensitive services.
- RQ5: hyperparameter influence.

---

## 11. Results

### 11.1 RQ1: detection capability

| Dataset | Precision | Recall | FPR |
|---|---|---|---|
| OB | 97.16% | 97.85% | 3.10% |
| TT | 85.17% | 80.54% | 8.78% |

- Why TT is worse: TT's normal training data is less densely clustered; some normal and anomalous TT points are very close, so the linear threshold misclassifies them.

**Per-fault recall (Fig. 10)**

| Fault | OB | TT |
|---|---|---|
| Exception code defect | 97.14% | 76.69% |
| Error return | 91.43% | 72.22% |
| Network delay | 98.75% | 80.88% |
| CPU contention | 97.5% | 97.14% |
| CPU consumed | 100% | not reported |

- Best on CPU faults (they raise MCUR and MMUR). Network delay raises Span Duration/Offset. Code faults are hardest via metrics; trace features help.

**Interpretation heat maps (Fig. 11): count of appearances in top-3, columns Offset / Duration / NCUR / MCUR / MMUR**

OB (7 fault-sensitive services):

| Service | Offset | Duration | NCUR | MCUR | MMUR |
|---|---|---|---|---|---|
| ad | 156 | 152 | 158 | 0 | 0 |
| cart | 39 | 36 | 33 | 0 | 0 |
| currency | 13 | 15 | 11 | 0 | 0 |
| email | 16 | 13 | 10 | 0 | 0 |
| payment | 0 | 0 | 0 | 0 | 0 |
| productcatalog | 58 | 58 | 57 | 0 | 0 |
| shipping | 4 | 2 | 3 | 0 | 0 |

TT (15 fault-sensitive services):

| Service | Offset | Duration | NCUR | MCUR | MMUR |
|---|---|---|---|---|---|
| assurance | 1 | 16 | 1 | 14 | 15 |
| config | 9 | 9 | 13 | 2 | 2 |
| contacts | 3 | 7 | 8 | 10 | 8 |
| delivery | 5 | 67 | 9 | 67 | 60 |
| order-other | 2 | 1 | 1 | 1 | 3 |
| order | 14 | 25 | 14 | 2 | 5 |
| payment | 0 | 5 | 0 | 1 | 2 |
| price | 0 | 2 | 1 | 2 | 2 |
| route | 0 | 6 | 0 | 5 | 5 |
| station-food | 1 | 12 | 3 | 7 | 10 |
| station | 2 | 9 | 6 | 7 | 5 |
| train-food | 0 | 16 | 1 | 14 | 19 |
| train | 1 | 1 | 8 | 4 | 8 |
| user | 1 | 3 | 1 | 2 | 2 |
| verification-code | 7 | 11 | 12 | 14 | 15 |

- Text findings: OB top features = Span Offset, Span Duration, NCUR; most fault-prone services = ad, productcatalog, cart; NCUR dominates resource faults; Offset/Duration dominate network and code faults. TT: delivery and train-food tied to Span Duration, MCUR, MMUR; order tied to Duration, Offset, NCUR; MCUR/MMUR dominate resource faults; Span Duration dominates network/code faults.
- Practical claim: operators can focus monitoring on a few (service, feature) pairs, e.g., Offset/Duration/NCUR of ad, productcatalog, cart in OB.

**Locally anomalous data and pseudo-normal (Fig. 12)**

- Visualized averages of the 5 features per service over a random continuous 4-h window: OB (ad, productcatalog, cart) aligns well; TT (delivery, order, train-food) shows FNs and FPs.
- TT false negative rate ≈ **19.46%** (= 1 − recall), FPR ≈ 8.78%. FNs: some faults change features too little.
- Many FPs are **pseudo-normal**: e.g., fault injected for 3 min → points A, B, C labeled anomalous; following D, E, F labeled normal but still anomalous (recovery). The authors argue detecting them is correct behavior, not misclassification, yet these are counted as FPs in the metrics.

### 11.2 RQ2: comparison with baselines (Table 5)

| Approach | Technique | Metric | Trace | OB P | OB FPR | OB R | TT P | TT FPR | TT R |
|---|---|---|---|---|---|---|---|---|---|
| N-Sigma | Statistical | ✓ | | 34.10 | 31.58 | 34.71 | 23.73 | 88.21 | 89.63 |
| SPOT | EVT | ✓ | | 33.80 | 39.66 | 42.35 | 21.87 | 51.02 | 46.67 |
| JumpStarter | Compressed sensing | ✓ | | 40.54 | 34.92 | 46.88 | 33.83 | 87.13 | 88.24 |
| ServiceAnomaly | Graph matching | ✓ | ✓ | 61.22 | 33.93 | 53.57 | 53.25 | 80.00 | 91.11 |
| ADSketch | Pattern matching | ✓ | ✓ | 82.81 | 10.65 | 80.95 | 42.68 | 35.05 | 73.02 |
| MicroHECL-SVM | ML | ✓ | ✓ | 45.61 | 49.87 | 92.86 | 35.11 | 49.89 | 88.15 |
| TraceAnomaly | DL | | ✓ | 79.93 | 24.81 | 91.07 | 80.70 | 12.45 | 83.19 |
| LSTM-AD | DL | | ✓ | 81.44 | 9.68 | 94.05 | 63.83 | 15.42 | 88.89 |
| **Ours** | DL (Transformer) | ✓ | ✓ | **97.16** | **3.10** | **97.85** | **85.17** | **8.78** | 80.54 |

(All values in %. Table marks ADSketch and MicroHECL-SVM as using both sources even though text describes them as metric/response-time based.)

- Ours is best on all OB metrics and best on TT precision and FPR. **On TT, recall is lower than 7 of 8 baselines** (only SPOT and ADSketch are lower); authors frame it as trading recall for much higher precision and lower FPR.

**Ablation by data source (Table 6)**

| Variant | OB P | OB FPR | OB R | TT P | TT FPR | TT R |
|---|---|---|---|---|---|---|
| w/o traces (metrics only) | 50.50 | 76.37 | 71.79 | 37.67 | 65.16 | 62.90 |
| w/o metrics (traces only) | 85.32 | 18.60 | 95.71 | 57.64 | 34.56 | 75.11 |
| Full | 97.16 | 3.10 | 97.85 | 85.17 | 8.78 | 80.54 |

- Metrics-only is worst; traces-only is much better; both is best.

**Authors' analysis:** instance-based detectors (N-Sigma, SPOT, JumpStarter) treat services independently and use only metrics, so they miss network/code faults and need many models. System-based methods need one model and capture inter-service relations. OC-SVM boundaries create FPs when normal/anomalous features are similar. TraceAnomaly suits balanced data, looks at one time point, so it underperforms on locally anomalous data. MSoFSAnomaly focuses on contextual changes over time with attention.

### 11.3 RQ3: efficiency and scalability

**Table 7: test time (same test data size)**

| Approach | OB (s) | TT (s) |
|---|---|---|
| MicroHECL-SVM | 0.007 | 0.007 |
| TraceAnomaly | 0.516 | 0.8912 |
| LSTM-AD | 0.499 | 0.884 |
| **Ours** | **0.030** | **0.031** |

- Fastest of the three DL methods; OC-SVM is faster (linear ops). TraceAnomaly slow due to VAE + Glow flow; LSTM-AD slow due to step-by-step processing.
- **Fig. 13 (TT):** detection improves as number of input services grows from 1 to 15, then stays stable up to 28 (x-axis points 1, 2, 5, 10, 15, 20, 25, 26, 27, 28). Approx.: precision ~32% → ~87%, recall ~45% → ~84%, FPR ~61% → ~8%.

### 11.4 RQ4: value of fault-sensitive selection

- Feeding only the **15 selected TT services** gives performance comparable to all services (Fig. 13 gray region).
- **Fig. 14 (approx.):** selected services P ≈ 85%, R ≈ 80%, FPR ≈ 9% vs other services P ≈ 49%, R ≈ 62%, FPR ≈ 40%.

### 11.5 RQ5: hyperparameters (OB data, Fig. 15)

- **μ from 1 to 13:** too large → anomalies missed; too small → normal flagged. Good range **10–12**; chosen **μ = 11**. Approx.: μ=1 precision ~90%, FPR ~12%; μ=11 precision ~99.6%, FPR ~0.3%; recall ~99% throughout.
- **W from 1 to 4** (1-min interval, 3-min faults): **W = 3 best**. Too small misses complete fault info; too large dilutes local changes. Approx. at W=3: precision ~99.6%, recall ~99.3%, FPR ~0.4%.

---

## 12. Threats, limitations, future work (as stated)

- **Internal:** normal training data may contain noise or lack some fault types; mitigations include workload replay (Nezha); normal data is easy to collect since production is mostly normal.
- **Conclusion validity:** threshold depends on max validation loss and μ.
- **External:** only 2 benchmark systems (11 and 41 services); generalization to larger real systems unclear; faults follow prior work (Nezha, DejaVu).
- **Future work:** architecture-specific/adaptive feature selection (service mesh, serverless, edge); efficiency at large scale; a **theoretical/probabilistic model justifying fault-sensitive selection** (currently based on four propagation patterns + experiments only).

---

## 13. Ambiguities and inconsistencies (observations, not author claims)

1. **Fig. 5 dataset mismatch:** described as Eadro's public dataset with 27 business services, but Eadro's SN system has 21 services (Table 4), and Fig. 5 service names (travel, food, price, config, route, seat, …) are Train Ticket services. Also "faults every 2 min, each lasting 600 s" is self-contradictory.
2. **Fig. 15 vs Table 5:** at the chosen μ = 11 and W = 3, Fig. 15 shows OB precision ~99.6% and FPR ~0.3–0.4%, higher than the reported 97.16% / 3.10%.
3. **Possible tuning on test data:** μ and W were chosen by sensitivity analysis on OB performance; no separate tuning split is described. μ tuned on OB only but used for TT.
4. **Effective threshold is 12× the maximum validation loss**, a very large margin that is empirically, not theoretically, motivated.
5. **Pseudo-normal handling:** authors argue post-fault detections are correct, but they are counted as FPs; labels are not corrected, so reported FPR mixes true FPs with recovery effects.
6. **Reconstruction target is the per-window max,** not the raw sequence; the loss compares reconstruction to raw window max. This is a design choice to amplify spikes but biases toward upward anomalies (drops may be missed).
7. **Heads = features:** H is set to the number of features (5); why feature count should set head count is not justified.
8. **Table 2 vs final features:** MMUR is listed as effective for network faults in TT but used as a resource-fault feature; NRB is effective in OB but dropped. OB heat map shows MCUR and MMUR never in top-3 (all zeros).
9. **TT per-fault recall covers only 4 faults** (CPU consumed not reported for TT), while Table 2 still discusses resource faults on TT.
10. **Only 4 of 11 metrics are named**; the MI selection rule ("greater than the 90th percentile for all faults") is ambiguous.
11. **Span Offset** has no formal equation; the two negative-offset types are only described in words.
12. **Imputation method** for missing trace features is not specified.
13. **Z-score formula typo** ("M_d taking values from both M_train and M_train", meant train and test).
14. **Split ordering** (chronological vs random) for 7:1:2 is not stated; a random split would leak temporal context.
15. **Coarse granularity:** 1-min metrics with 3-min faults means each fault is ~3 data points; W = 3 equals the fault length, which suits these benchmarks but may not transfer.
16. **Leaf selection assumption:** leaves are chosen as sensitive, yet propagation pattern (a) (leaf fault, no callers) and upward effects on callers (latency) suggest callers can be more sensitive for some faults; no theory given (authors admit this).
17. Data availability says "on request" while code is on GitHub.
18. MI range stated as 0–1; only true for binary Y with log base 2.
19. Baseline FPRs on TT for N-Sigma (88.21%) and JumpStarter (87.13%) are extremely high, suggesting baseline configuration choices strongly affect the comparison.
20. The E[CLS] token in Fig. 2 is not explained in the text.

---

## 14. Claims safe to cite (exact figures)

- OB: **P 97.16%, R 97.85%, FPR 3.10%**; TT: **P 85.17%, R 80.54%, FPR 8.78%**.
- Metrics-only variant falls to P 50.50% / 37.67% (OB/TT); traces-only 85.32% / 57.64%.
- Test time **0.030 s (OB), 0.031 s (TT)**, vs 0.5–0.9 s for TraceAnomaly and LSTM-AD.
- Existing detectors on SN: **SPOT recall 23%, OmniAnomaly recall 35%**.
- Lower anomalous-data purity: **Grace F1 90% → 60%; Dycause top-5 71% → 30%**.
- Selection algorithm complexity **O(n + m)**, worst case O(N²).
- Using the 15 selected TT services matches using all services.
- No K8s metric among the 11 significantly reflects program code faults (MI analysis).

---

## 15. Reusable ideas

- **Structure-based sensor selection:** pick leaf services (+ cycle members) from a call tree built from normal traces to cut monitoring cost.
- **Transitive edge removal** to get a hierarchical call tree from a call graph.
- **Fault-type ↔ feature MI analysis** to choose which data source to use per fault category.
- **Span Offset** feature: child-span timing relative to parent-span end, capturing cross-operation dependency and waiting.
- **Train-statistics-only Z-scoring** for train and test.
- **Window-max reconstruction** to emphasize spikes; threshold = validation max loss scaled by (1+μ).
- **Per-(service, feature) squared-error vector + top-K** as a lightweight interpretation and a hand-off to localization.
- **"Purity of anomalous data"** as an explicit objective for detectors feeding RCA.
- **Pseudo-normal** concept for post-fault recovery periods.

## 16. Open gaps a follow-up could target

- No end-to-end evaluation of localization accuracy with MSoFSAnomaly's output (purity benefit is argued via Grace/Dycause but not measured with this detector's output).
- Pseudo-normal labels are not corrected; a recovery-aware labeling or evaluation protocol is missing.
- No theoretical justification for leaf-based sensitivity; no comparison with other selection strategies (e.g., centrality, random subsets of equal size).
- No logs, no events, no kernel-level signals.
- Only small benchmarks, synthetic injected faults, 1-min granularity; no production data, no multiple simultaneous faults, no concept drift or deployment changes.
- Hyperparameters tuned on test-like data; no cross-validation or variance reporting.
- Indirect dependencies through shared storage handled only heuristically.
- Downward-only anomaly bias from max-based reconstruction.

---

## 17. Links to the Performance Archetypes paper (Shahedi et al., ASE '26)

If both papers are in context, these are the main parallels and differences:

| Aspect | MSoFSAnomaly (JSS 2025) | Performance Archetypes (ASE '26) |
|---|---|---|
| Setting | Microservices (OB, TT) | Single-process C/C++ apps |
| Signals | Metrics + distributed traces | Static code + function traces + kernel events |
| Structure used | Call tree over services; keep leaves + cycles | Call tree over functions; keep top-k critical paths |
| Idea of "where to look" | Fault-sensitive services | Critical paths (time-dominant call chains) |
| Detector | Transformer reconstruction, threshold on MSE | Weighted sum of 4 anomaly scores, threshold 0.65 |
| Multi-source ablation | Metrics-only much worse than both | Resource-only much worse than CP-aware (+60.4% F1) |
| Faults | Injected via Chaos Mesh etc. (resource, network, code) | Injected CPU / memory / I/O code into one function |
| Interpretation | Top-3 (service, feature) by squared error | Bottleneck function, archetype, root-cause attribution |
| Headline numbers | P 97.16 / R 97.85 (OB) | F1 0.867, P 0.910, R 0.827 |

Shared message: the right structural subset (leaf services or critical paths) plus fused signals beats single-source detection. Neither paper evaluates a full detection → localization pipeline end to end with its own output.
