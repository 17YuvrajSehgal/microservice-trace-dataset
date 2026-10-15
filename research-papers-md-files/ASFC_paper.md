# Paper Summary: ASFC — Autonomous Selection of Fault Classification Models for Diagnosing Microservice Applications

> Purpose of this file: full reference for an AI agent (Claude Code) so it understands this paper without reading the PDF.
> The user is writing their own research paper that builds on these ideas. Use this file for related work, method comparison, baselines, and numbers.
> Sections marked **[Reviewer note]** are NOT claims of the paper. They are observations (inconsistencies, weaknesses) found while reading. Useful for positioning the user's own work.

---

## 1. Bibliographic info

- **Title:** Autonomous selection of the fault classification models for diagnosing microservice applications
- **Authors:** Yujia Song (co-first), Ruyue Xin (co-first), Peng Chen (corresponding), Rui Zhang, Juan Chen, Zhiming Zhao (corresponding)
- **Affiliations:** School of Computer and Software Engineering, Xihua University, Chengdu, China; Multiscale Networked Systems (MNS), University of Amsterdam, Netherlands
- **Venue:** Future Generation Computer Systems (FGCS), Vol. 153 (2024), pp. 326–339, Elsevier
- **DOI:** https://doi.org/10.1016/j.future.2023.12.005
- **Dates:** Received 24 Jul 2023; revised 3 Dec 2023; accepted 9 Dec 2023; online 12 Dec 2023
- **Keywords:** Microservice architecture, Fault diagnosis, Cascade network, Root cause localization, Monitoring data, Unsupervised learning
- **Short name of method:** ASFC
- **Sock-Shop data link (from paper):** https://surfdrive.surf.nl/files/index.php/s/FjmBjVQnDRWqDmV
- **Train-Ticket data:** reused from Eadro (Lee et al., 2023, arXiv:2302.05092)

---

## 2. One-paragraph summary

ASFC is a pipeline that (1) tells **what type of fault** happened in a microservice (e.g., CPU hog, memory leak, network delay) and (2) tells **which service is the root cause**. For fault type, it does not use one fixed deep model. Instead it tests 8 unsupervised anomaly-detection models and **automatically picks the best model for each fault type**. The chosen models are trained only on normal data and chained in a **cascade**: model 1 catches fault 1, passes everything else to model 2, and so on; whatever passes all models is "normal". For root cause, it builds a **causal graph** of service latencies with the **PC algorithm**, scores services with **PageRank**, and then mixes this score 50/50 with a **"fault degree"** score (how far each service's metric is from the fault threshold found during diagnosis). The service with the highest combined score is the predicted root cause. It is tested on **Sock-Shop** (7 services) and **Train-Ticket** (6 services).

---

## 3. Problem and motivation

- Microservice apps can have hundreds or thousands of services. Faults propagate along dependencies and degrade the whole system.
- Most prior anomaly detection methods only say "there is an anomaly". They do not say the **fault type**. Operators still spend time finding the cause.
- Supervised fault diagnosis needs labeled data, which costs time and labor. So unsupervised methods are wanted.
- Microservice environments are dynamic. Data distributions change. **One single deep model is not robust** across services and faults.
- Root cause methods based on causal graphs usually use only topology/causality. They **ignore fault patterns** in the metric data.
- Most works do **only one task** (diagnosis OR localization). Operators need both.

### Three stated limitations of existing work
1. A single deep learning model depends on its training data and is not robust enough for continuous accuracy in dynamic cloud microservices.
2. Most causal analysis methods ignore characteristics of service failures, so root cause location is inaccurate.
3. Most methods do only one task (diagnosis or root cause), which slows troubleshooting.

### Research questions
- **RQ1:** How to keep accuracy robust when diagnosing faults in complex, dynamic microservice systems? → Answer: auto-select models per fault and cascade them.
- **RQ2:** How to improve root cause accuracy by using characteristics of service failures? → Answer: add a "fault degree" (fault pattern) score to the causal PageRank score.
- **RQ3:** How to improve operator troubleshooting efficiency? → Answer: one pipeline that gives both fault type and root cause service, fast (seconds).

### Stated contributions
1. Model auto-selection module that picks the best unsupervised model per fault from a candidate pool, then cascades and trains them.
2. Fault pattern capture combined with causal-inference-based root cause localization.
3. Experiments on 7 (Sock-Shop) + 6 (Train-Ticket) microservice datasets showing better diagnosis and localization than baselines.

---

## 4. Related work covered by the paper

### 4.1 Supervised fault diagnosis (criticized: need labels)
- **1D-GAPCNN-SVM** [21]: CNN with 1-D global average pooling instead of fully connected layer; SVM instead of softmax.
- **PreMise** [22]: lightweight diagnosis/localization in multi-tier distributed systems; combines exception-based and signature-based techniques.
- SVM-bat algorithm + Gaussian classifier [14]; semi-supervised adversarial learning framework [15].

### 4.2 Unsupervised fault diagnosis
- **BIRCH** [23], **K-means** [24]: cluster monitoring data; centroids/radii define "normal" region; points outside = fault.
- **ST-CatGAN** [25]: STFT to time-frequency maps + CatGAN (adversarial training).
- **MRC** (Wu et al.) [26]: multiscale reduction clustering with convolutional encoder.
- Paper claims accuracy of existing methods is not satisfactory in complex, large, dynamic microservice systems.

### 4.3 Causal root cause localization
- **AutoMAP** [28]: PC algorithm to build fault propagation graph + random walk.
- **CauseInfer** [29]: PC algorithm + Breadth First Search.
- **MicroDiag** [30]: LiNGAM + PageRank.
- **FRL-MFPG** [18]: uses relations between microservices to find faulty service.
- Criticism: these ignore fault patterns in entity measurement data [19].

---

## 5. Method (ASFC) — full details

### 5.1 Overall architecture (Fig. 3): 5 modules
1. Model auto-selection
2. Model training
3. Fault diagnosis (cascade)
4. Root cause inference (PC + PageRank)
5. Root cause localization (combine causal score + fault degree)

Input data: continuous monitoring data with
- **service-level metrics** (e.g., service latency)
- **resource-level metrics** (e.g., CPU, memory usage)

Train/test split of monitoring data: **7:3**.

### 5.2 Candidate model pool (8 unsupervised multivariate time-series anomaly detectors)
| Model | Type |
|---|---|
| OmniAnomaly [44] | Reconstruction-based |
| CAE_M [38] | Reconstruction-based |
| DAGMM [42] | Reconstruction-based |
| CGNN-MHSA-AR [39] | Prediction-based (by same authors' group) |
| MTAD-GAT [43] | Hybrid (reconstruction + prediction) |
| MAD-GAN [40] | GAN-based |
| WPS [37] | GAN-based (WGAN-based, same group) |
| USAD [41] | GAN-based (adversarially trained autoencoders) |

### 5.3 Module 1 — Model auto-selection
- Motivation: the same fault looks different in different services (e.g., CPU hog in front-end vs in user). No single model is best for all.
- Sampling from the training set:
  - **Training subset:** randomly sample **500 consecutive normal instances**.
  - **Testing subset:** extract **100 instances of each fault type** and concatenate them.
- Every candidate model is trained on the training subset and evaluated on the testing subset.
- Repeat for **5 random sampling rounds**.
- For each fault type, pick the model with the **best average detection accuracy (average F1)** across the 5 rounds.
- Result: m models M1..Mm for m fault types. Selection is done **per service dataset** (so different services can get different models).

### 5.4 Module 2 — Model training
- Rank the selected models by their average F1 in descending order: a1 > a2 > ... > am.
- Train each selected model on **normal (fault-free) data of the related component/metric**. Example on the `user` service:
  - M1 (best for CPU hog) trained on **CPU usage** in fault-free periods
  - M2 (best for memory leak) trained on **memory usage** in fault-free periods
  - M3 (best for network delay) trained on **transmit bytes** in fault-free periods
- Training data needs no labels (only normal data). The paper calls diagnosis "unsupervised" for this reason.

### 5.5 Module 3 — Fault diagnosis (cascade, Fig. 2 and Fig. 4)
- Each trained model predicts/reconstructs the data. If **error between predicted and actual > threshold**, the instance is a fault for that level.
- Threshold for each model is chosen with **best-F1** (search the threshold that gives the best F1).
- Cascade order = descending average F1 from auto-selection (most reliable detector first). Reason: so that data passed to the next level matches the current fault as little as possible.
- Flow:
  - All data → M1. M1 outputs "fault 1" or passes the rest down.
  - Rest → M2. M2 outputs "fault 2" or passes the rest down.
  - ... → Mm. Mm outputs "fault m"; what is left is **normal**.
- Each level also **records its fault threshold** (thred_γ). This is reused in root cause localization.

### 5.6 Module 4 — Root cause inference (causal graph + PageRank)
- Input KPIs: **service latency** of each microservice during the fault: S = {s0, s1, ..., sk}, k = number of services.
- **PC algorithm** [31] (constraint-based causal discovery):
  1. Start with a fully connected undirected graph G over all variables.
  2. Run conditional independence tests between adjacent nodes, significance level **α = 0.05**.
  3. Remove the edge if conditional independence holds.
  4. Orient edges using v-structure ("v separation") rules. Expand skeleton into a **DAG**.
- DAG is unweighted, so set **w_ij = 1 if i → j**, else 0.
- Transition probability (Eq. 1):
  `P_ij = w_ij / Σ_j w_ij` if w_ij ≠ 0, else 0 (based on out-degree of node i)
- PageRank score (Eq. 2):
  `v_i = a · P_ij · v_j + (1 − a) / k`, with **a = 0.85** (damping)
- Output: causal root cause score v for each service.

### 5.7 Module 5 — Root cause localization (fault pattern + causal score)
- Idea: topology is not the only thing that matters. The **fault pattern** (how strongly a service's metric deviates) also indicates root cause.
- **Fault degree** of service i for fault γ (Eq. 3):
  `η_γ^i = max over t ∈ (1, T) of ( |s_i^t − thred_γ| / mean(s_i) )`
  - T = duration of fault γ
  - s_i^t = value of service i at time step t during the fault
  - thred_γ = best-F1 threshold found by ASFC for fault γ in the diagnosis step
  - γ ∈ {fault1, ..., faultm}
- **Final score** (Eq. 4):
  `score_γ = β · v + (1 − β) · η_γ`, with **β = 0.5**
  - η_γ = [η_γ^1, ..., η_γ^k] for k services
- Rank services by score (descending). Top = most likely root cause.

### 5.8 Implementation settings
- Python 3.7, PyTorch 1.11.0 (GPU)
- Sliding window size = **6**
- **20 epochs**, batch size **32**, learning rate **0.0001**, **Adam** optimizer
- Hyperparameters: α = 0.05 (PC), a = 0.85 (PageRank), β = 0.5 (score mix)

---

## 6. Datasets and fault injection

### 6.1 Sock-Shop (collected by the authors)
- E-commerce benchmark, **13 services** (front-end, catalogue, carts, user, orders, payment, shipping + communication services).
- Deployed on **Kubernetes**: 1 master + 3 worker nodes, each **Ubuntu 18.04, 4 vCPU, 16 GB RAM, 80 GB disk**.
- Monitoring: **Prometheus** + **Grafana** on master. Load: **Locust** on master.
- Fault injection with **Pumba** (Docker containers):
  - **CPU hog** (use up CPU)
  - **Memory leak** (continuously allocate memory)
  - **Network delay** (traffic control delays packets)
- Each fault lasts **1–5 min**; normal run **10–30 min** between faults; repeated **at least 5 times per fault**.
- Sampling interval: **every 5 s**.
- Metrics: service latency (service level); CPU usage, memory usage, disk read/write, network receive/transmit bytes (container resource level).
- **7 service datasets evaluated:** shipping, user, carts, catalogue, orders, payment, front-end.

### 6.2 Train-Ticket (reused from Eadro [36])
- KPIs: **CPU total usage, rx bytes, tx bytes**.
- Faults: **CPU hog, Network delay, Network loss**.
- Rare-fault scenario: only **50 instances of each fault** in test sets.
- **6 service datasets:** food, food_map, assurance, order_other, train, inside_payment (chosen because their faults look more varied — Fig. 5 shows different shapes for the 3 faults in `assurance`).

---

## 7. Evaluation metrics

### Fault diagnosis (imbalanced classes → macro metrics)
- macro-precision = (1/n) Σ p_i ; macro-recall = (1/n) Σ r_i ; macro-F1 = (1/n) Σ f_i  (n = number of fault types)
- Also an average **Rank** of each method across datasets (lower = better; ASFC = 0.000, i.e., best).

### Root cause localization
- `R_a = sorted(score_γ)`
- **PR@k** = (1/|A|) Σ_{a∈A} [ Σ_{i<k} 1(R_a(i) ∈ V_a) / min(k, |V_a|) ]  → probability that the true root cause is in the top-k.
  - A = set of faults = {cpu hog, memory leak, network delay}; V_a = true root cause; R_a = predicted ranking.
- **Avg@k** = (1/k) Σ_{j=1..k} PR@j. Paper uses k = 1..5 and reports **Avg@5**.

---

## 8. Baselines

### Fault diagnosis (11 baselines)
- Clustering: **K-means, GaussianMixture, Birch**
- Cascade variants using ONE model type at every cascade level (no auto-selection): **CAS_WPS, CAS_CGNN-MHSA-AR, CAS_MAD_GAN, CAS_USAD, CAS_DAGMM, CAS_MTAD-GAT, CAS_OmniAnomaly, CAS_CAE_M**
- Note: the CAS_ variants act like an ablation of the auto-selection module.

### Root cause localization (3 baselines, all + PageRank)
- **PC-based** (PC + PageRank) → this is ASFC without the fault-degree term, so it works as an ablation.
- **GES-based** (GES [45], score-based greedy search + PageRank)
- **LiNGAM-based** (LiNGAM [46], linear non-Gaussian model + PageRank)

---

## 9. Results

### 9.1 Headline numbers (abstract)
- Average macro-F1: **82.9% (Sock-Shop)** and **88.6% (Train-Ticket)**.
- Average improvement over baselines: **34.4%** and **24.7%**.
- Root cause **Avg@5: 0.857 (Sock-Shop)** and **0.525 (Train-Ticket)**.

### 9.2 Fault diagnosis — Sock-Shop (Table 1, macro-F1)

| Method | shipping | user | carts | catalogue | orders | payment | front-end |
|---|---|---|---|---|---|---|---|
| Kmeans | 0.190 | 0.132 | 0.226 | 0.122 | 0.251 | 0.238 | 0.115 |
| GaussianMixture | 0.219 | 0.148 | 0.116 | 0.193 | 0.107 | 0.172 | 0.027 |
| Birch | 0.231 | 0.036 | 0.045 | 0.240 | 0.221 | 0.188 | 0.410 |
| CAS_WPS | 0.219 | 0.503 | 0.236 | 0.891 | 0.904 | 0.872 | 0.652 |
| CAS_CGNN-MHSA-AR | 0.859 | 0.197 | 0.233 | 0.901 | 0.939 | **0.937** | 0.548 |
| CAS_MAD_GAN | 0.851 | 0.439 | 0.485 | 0.691 | 0.960 | 0.887 | 0.710 |
| CAS_USAD | 0.550 | 0.304 | 0.347 | 0.916 | 0.666 | 0.722 | 0.583 |
| CAS_DAGMM | 0.697 | 0.264 | 0.438 | 0.620 | 0.948 | 0.856 | 0.572 |
| CAS_MTAD-GAT | 0.825 | 0.464 | 0.238 | **0.930** | 0.565 | 0.933 | 0.622 |
| CAS_OmniAnomaly | 0.218 | 0.200 | 0.197 | 0.851 | **0.979** | 0.946* | 0.400 |
| CAS_CAE_M | 0.123 | 0.373 | 0.182 | 0.499 | 0.838 | 0.860 | 0.119 |
| **ASFC** | **0.862** | **0.760** | **0.640** | 0.921 | 0.941 | 0.930 | **0.756** |

*Table prints CAS_OmniAnomaly payment F1 = 0.946, which is higher than the bolded 0.937. See reviewer notes.

ASFC precision / recall per dataset (shipping, user, carts, catalogue, orders, payment, front-end):
- macro-Pre: 0.778, 0.690, 0.679, 0.876, 0.904, 0.888, 0.739
- macro-Rec: 0.987, 0.950, 0.878, 0.985, 0.990, 0.993, 0.928

Key Sock-Shop claims:
- ASFC averages: **macro-F1 0.829, macro-recall 0.958, macro-precision 0.793**.
- Beats best clustering method (Birch) by **64.7%** macro-F1.
- ASFC loses on 3 datasets: catalogue (CAS_MTAD-GAT 0.930), orders (CAS_OmniAnomaly 0.979), payment (CAS_CGNN-MHSA-AR 0.937). Paper explains: those models extract CPU features in more detail; ASFC's CPU hog accuracy is 0.81 (catalogue) and 0.70 (orders).
- Error rates: shipping 0.04 (63 of 1329 misclassified), catalogue 0.03, orders 0.02, payment 0.02; but user 0.16, carts 0.4, front-end 0.2.
- Reason for bad cases: **memory leak** in carts, front-end, user has small impact, so it looks like normal data.
- Average **false alarm rate 0.124**.
- Robustness (spread across 7 datasets): precision 0.67–0.90, recall 0.87–0.99, F1 0.64–0.94. All baselines have wider ranges (Fig. 8).
- Average rank (Fig. 6): ASFC ranked 1st on macro-P, macro-R, macro-F1.

Confusion matrices (Fig. 7). Rows = true [Normal, CPU hog, Memory leak, Network delay]; columns = predicted in the same order:
- shipping: [1121, 29, 12, 22], [0, 48, 0, 0], [0, 0, 37, 0], [0, 0, 0, 60]
- user: [939, 31, 186, 13], [0, 60, 0, 0], [0, 0, 85, 0], [0, 0, 0, 48]
- carts: [643, 35, 582, 0], [0, 73, 0, 0], [0, 0, 24, 0], [0, 0, 0, 49]
- catalogue: [1188, 16, 0, 25], [0, 70, 0, 2], [0, 0, 24, 0], [0, 0, 0, 60]
- orders: [1191, 30, 2, 0], [0, 72, 0, 1], [0, 0, 24, 0], [0, 0, 0, 84]
- payment: [1146, 28, 3, 1], [0, 48, 0, 0], [0, 0, 72, 0], [0, 0, 0, 24]
- front-end: [897, 31, 336, 0], [0, 96, 0, 0], [0, 0, 84, 0], [0, 0, 0, 36]

**[Reviewer note]** From the matrices, almost every true fault is detected and classified correctly. Nearly all errors are **normal data wrongly flagged as a fault** (mostly as memory leak: 186 in user, 582 in carts, 336 in front-end). So the weak point is false positives, not missed faults. The paper's text words this as "memory leak looks like normal", but the matrices show the reverse direction of error (normal → memory leak).

### 9.3 Fault diagnosis — Train-Ticket (Table 2, macro-F1)

| Method | food | assurance | train | order_other | food_map | inside_payment |
|---|---|---|---|---|---|---|
| KMeans | 0.241 | 0.242 | 0.241 | 0.102 | 0.095 | 0.231 |
| GaussianMixture | 0.197 | 0.126 | 0.229 | 0.227 | 0.184 | 0.189 |
| Birch | 0.020 | 0.024 | 0.028 | 0.238 | 0.024 | 0.019 |
| CAS_WPS | 0.769 | 0.855 | 0.877 | 0.859 | **0.967** | 0.777 |
| CAS_CGNN-MHSA-AR | 0.864 | 0.855 | 0.987 | 0.880 | 0.629 | 0.854 |
| CAS_MAD_GAN | 0.723 | 0.877 | 0.801 | **0.921** | 0.574 | 0.751 |
| CAS_USAD | 0.749 | 0.704 | 0.970 | 0.847 | 0.529 | 0.683 |
| CAS_DAGMM | 0.834 | 0.871 | 0.971 | 0.879 | 0.718 | 0.904 |
| CAS_MTAD-GAT | 0.855 | 0.881 | **0.987** | 0.889 | 0.596 | **0.907** |
| CAS_OmniAnomaly | 0.870 | 0.834 | 0.971 | 0.912 | 0.687 | 0.814 |
| CAS_CAE_M | 0.677 | 0.837 | 0.800 | 0.920 | 0.810 | 0.819 |
| **ASFC** | **0.896** | **0.894** | 0.971 | 0.911 | 0.832 | 0.817 |

ASFC precision / recall (food, assurance, train, order_other, food_map, inside_payment):
- macro-Pre: 0.838, 0.830, 0.954, 0.873, 0.779, 0.752
- macro-Rec: 0.988, 0.993, 0.989, 0.989, 0.975, 0.971

Key Train-Ticket claims:
- ASFC averages: **macro-precision 83.7%, macro-recall 98.4%, macro-F1 88.6%**.
- F1 improvement: **69.4%–82.7%** vs clustering; **3.4%–13.9%** vs CAS_ variants.
- ASFC is the only method with precision > 0.7, recall > 0.9, F1 > 0.8 on **all six** datasets (Fig. 9).
- ASFC is best on only 2 of 6 datasets (food, assurance). Its main claim is **stability**, not always winning.
- CAS_MTAD-GAT: best on train (0.987) but ranges 0.5–0.9 overall. CAS_MAD_GAN: 0.921 on order_other but 0.574 on food_map. CAS_WPS: best on food_map but less stable.
- Average rank: ASFC 1st.

### 9.4 Root cause localization — Sock-Shop (Table 3)

| Fault | Metric | ASFC | PC-based | GES-based | LiNGAM-based |
|---|---|---|---|---|---|
| CPU hog | PR@1 | 0.714 | 0.000 | 0.143 | 0.000 |
| | PR@2 | 0.857 | 0.000 | 0.429 | 0.143 |
| | PR@3 | 0.857 | 0.143 | 0.571 | 0.286 |
| | PR@4 | 1.000 | 0.286 | 0.857 | 0.429 |
| | PR@5 | 1.000 | 0.714 | 0.857 | 0.571 |
| | **Avg@5** | **0.886** | 0.229 | 0.571 | 0.286 |
| Memory leak | PR@1 | 0.571 | 0.143 | 0.286 | 0.143 |
| | PR@2 | 0.857 | 0.571 | 0.429 | 0.143 |
| | PR@3 | 1.000 | 0.571 | 0.429 | 0.429 |
| | PR@4 | 1.000 | 0.714 | 0.429 | 0.571 |
| | PR@5 | 1.000 | 1.000 | 0.571 | 0.714 |
| | **Avg@5** | **0.886** | 0.600 | 0.429 | 0.400 |
| Network delay | PR@1 | 0.429 | 0.286 | 0.000 | 0.143 |
| | PR@2 | 0.714 | 0.286 | 0.143 | 0.286 |
| | PR@3 | 0.857 | 0.286 | 0.143 | 0.429 |
| | PR@4 | 1.000 | 0.571 | 0.143 | 0.571 |
| | PR@5 | 1.000 | 0.714 | 0.571 | 0.714 |
| | **Avg@5** | **0.800** | 0.429 | 0.200 | 0.429 |

Claims:
- PR@1: 71% (CPU hog), 57% (memory leak), 43% (network delay) chance the top-1 is correct.
- Avg@5 gains over best baseline: CPU hog +31.4% (vs GES), memory leak +28.5% (vs PC), network delay +37.1% (vs PC and LiNGAM).
- Per service (Fig. 10): ASFC weak on **orders for CPU hog** and **shipping for memory leak** (high correlation with other metrics). Strong on **shipping for network delay** even though shipping depends heavily on the network.

### 9.5 Root cause localization — Train-Ticket (Table 4)

| Fault | Metric | ASFC | PC-based | GES-based | LiNGAM-based |
|---|---|---|---|---|---|
| CPU hog | PR@1 | 0.167 | 0.000 | 0.000 | 0.000 |
| | PR@2 | 0.167 | 0.000 | 0.000 | 0.167 |
| | PR@3 | 0.167 | 0.000 | 0.000 | 0.500 |
| | PR@4 | 0.167 | 0.000 | 0.000 | 0.667 |
| | PR@5 | 0.333 | 0.000 | 0.000 | 0.833 |
| | **Avg@5** | 0.200 | 0.000 | 0.000 | **0.433** |
| Network loss | PR@1 | 0.333 | 0.333 | 0.000 | 0.167 |
| | PR@2 | 0.667 | 0.333 | 0.167 | 0.500 |
| | PR@3 | 0.667 | 0.500 | 0.167 | 0.500 |
| | PR@4 | 0.833 | 0.500 | 0.333 | 0.667 |
| | PR@5 | 0.833 | 0.500 | 0.667 | 0.833 |
| | **Avg@5** | **0.667** | 0.433 | 0.267 | 0.533 |
| Network delay | PR@1 | 0.333 | 0.000 | 0.000 | 0.167 |
| | PR@2 | 0.667 | 0.333 | 0.667 | 0.500 |
| | PR@3 | 0.833 | 0.333 | 0.833 | 0.500 |
| | PR@4 | 0.833 | 0.333 | 0.833 | 0.833 |
| | PR@5 | 0.833 | 0.333 | 0.833 | 0.833 |
| | **Avg@5** | **0.700** | 0.267 | 0.633 | 0.567 |

Claims:
- ASFC best for network loss (+13.3% vs LiNGAM) and network delay (+13.3% vs LiNGAM, as the paper states).
- ASFC **worse than LiNGAM for CPU hog** (0.200 vs 0.433). Reason given: PC itself is poor for CPU hog; fault pattern helps but not enough.
- **Effect of adding fault pattern (ASFC vs PC-based):** +20% (CPU hog), +23.3% (network loss), +43.3% (network delay) in Avg@5. This is the main evidence for the fault-degree idea.
- Per service (Fig. 11): CPU hog: ASFC best only on food_map. Network delay: best except order_other and assurance (assurance only 0.2 below best). Network loss: best except inside_payment.

### 9.6 Efficiency (Table 5, seconds)

| Sock-Shop | shipping | user | carts | catalogue | orders | payment | front-end |
|---|---|---|---|---|---|---|---|
| Fault diagnosis | 3.446 | 3.426 | 3.833 | 3.628 | 3.624 | 3.796 | 3.984 |
| Root cause loc. | 0.078 | 0.128 | 0.142 | 0.128 | 0.221 | 0.133 | 0.125 |

| Train-Ticket | food | assurance | train | order_other | food_map | inside_payment |
|---|---|---|---|---|---|---|
| Fault diagnosis | 5.177 | 4.518 | 4.718 | 5.039 | 4.161 | 4.086 |
| Root cause loc. | 0.042 | 0.040 | 0.045 | 0.043 | 0.043 | 0.072 |

- Sock-Shop averages: diagnosis **3.677 s**, root cause **0.137 s**.
- Train-Ticket averages: diagnosis **4.617 s**, root cause **0.047 s**.
- No timing is given for baselines, and auto-selection/training time is not reported.

---

## 10. Conclusion and future work (as stated)
- ASFC = unsupervised fault diagnosis + root cause localization from monitoring data.
- A single deep model fits only some scenarios; auto-selection + cascade gives robustness.
- Fault patterns + causal inference improve localization.
- Localization is at **service level** (service KPIs). Resource-level data could give finer resource localization; combining with trace- and log-based methods could locate specific endpoints/modules.
- Future work:
  1. More fault types (e.g., performance bottlenecks) and more real-world microservice systems.
  2. Integrate automated **fault remediation** with diagnosis.
  3. Learn dependencies from **traces, logs, and KPIs** for fine-grained root cause.

---

## 11. [Reviewer note] Weaknesses, gaps and inconsistencies (useful for the user's own paper)

These are observations, not the authors' claims. Double-check before citing.

**Method assumptions**
- "Unsupervised" only in training. **Auto-selection needs labeled fault samples** (100 per fault type) to compute F1. **Thresholds use best-F1**, which also needs labels. So the method needs labeled fault examples per fault type per service.
- The fault types must be **known in advance** (m faults). A new, unseen fault type cannot be named; it would be either caught by a wrong level or called normal.
- Each cascade model is trained on one chosen metric (CPU → M1, memory → M2, tx bytes → M3). The mapping fault → metric seems hand-chosen.
- Cascade has **error propagation**: a false positive at level 1 is never seen by later levels. Order is fixed by F1 ranking only.
- Only single-fault scenarios; no concurrent/multiple faults.
- Root cause graph uses only **service latency**; PC with α = 0.05 on short fault windows.
- β = 0.5 and a = 0.85 are fixed; **no sensitivity analysis** on β, window size, or pool size.
- No separate ablation study section. The CAS_ baselines (no auto-selection) and PC-based baseline (no fault degree) act as implicit ablations.

**Evaluation size**
- Root cause results use **very few cases**: Sock-Shop PR values are multiples of 1/7 (7 services), Train-Ticket multiples of 1/6. One case changes the score by 14–17 points. No variance or significance tests.
- Train-Ticket has only 50 fault instances per fault in test sets.
- Only 3 fault types per system; both are benchmark systems (no production data).
- "Improvement %" values for root cause are **absolute point differences** in Avg@5 (e.g., 0.886 − 0.571 = 0.315 → "31.4%"), not relative gains.

**Inconsistencies in the paper**
- Text says ASFC's highest Sock-Shop macro-F1 is 0.930 on payment, but Table 1 shows 0.941 on orders.
- Table 1 bolds CAS_CGNN-MHSA-AR (0.937) as best on payment, but CAS_OmniAnomaly shows 0.946 in the same column.
- Text says ASFC is 3% behind on catalogue and 0.9% behind on orders; table gaps are 0.009 (catalogue) and 0.038 (orders). The numbers look swapped.
- Text says fastest diagnosis is shipping (3.446 s), but user is 3.426 s.
- Train-Ticket network delay: text says +13.3% vs LiNGAM as "best baseline", but GES (0.633) is the best baseline; true gap is 0.067.
- Abstract Train-Ticket Avg@5 = 0.525; mean of Table 4 values (0.200, 0.667, 0.700) = 0.522.
- Text cites Fig. 7(d) for both catalogue and orders (orders is Fig. 7(e)).
- Data availability says "on request", but the Sock-Shop link is given in the paper.

**Possible directions for a follow-up paper**
- Label-free model selection and threshold setting (e.g., POT/EVT thresholds, unsupervised model selection).
- Handling unknown/new fault types and multiple concurrent faults.
- Learned or adaptive β; weighted causal graphs; more KPIs than latency.
- Larger root cause evaluation with many injected cases and statistical tests.
- Using traces and logs (multi-modal), as the authors themselves suggest.
- Reporting full cost: auto-selection time (8 models × 5 rounds × m faults × services).

---

## 12. Glossary (quick)
- **Microservice:** a small independent service; many of them form one application.
- **Fault diagnosis:** deciding which fault type happened.
- **Root cause localization:** deciding which service caused the fault.
- **KPI:** key performance indicator (latency, CPU, memory, bytes).
- **Cascade:** a chain of models; each catches one fault type and passes the rest on.
- **Best-F1 threshold:** the anomaly-score cutoff that gives the highest F1 on labeled data.
- **PC algorithm:** builds a causal graph using conditional independence tests.
- **DAG:** directed acyclic graph (arrows, no loops).
- **PageRank:** scores nodes by how the graph's links point to them.
- **Fault degree (η):** largest normalized distance of a service's metric from the fault threshold during the fault.
- **PR@k / Avg@k:** chance the true root cause is in the top-k / average of PR@1..PR@k.
- **Macro-F1:** F1 averaged equally over classes; fair for imbalanced data.
