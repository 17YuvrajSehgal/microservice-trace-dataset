# Paper Context: Discovering Performance Archetypes (ASE '26)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> It captures every key idea, method detail, number, and limitation of the paper so the
> agent can reason about it, cite it correctly, compare against it, and reuse its ideas
> without re-reading the PDF. All numbers below are taken directly from the paper.
> Where the paper is vague or internally inconsistent, this is flagged under
> "Ambiguities and inconsistencies" (Section 13).

---

## 1. Bibliographic info

- **Title:** Discovering Performance Archetypes: Critical-Path-Aware Pattern Analysis and Regression Detection
- **Authors:** Kaveh Shahedi, Heng Li (corresponding), Maxime Lamothe, Foutse Khomh
- **Affiliation:** Polytechnique Montréal, Dept. of Computer Engineering and Software Engineering (MooseLab)
- **Venue:** 41st IEEE/ACM International Conference on Automated Software Engineering (ASE '26), Oct 12–16, 2026, Munich, Germany. 13 pages.
- **DOI:** 10.1145/3832783.3834426
- **arXiv:** 2609.17179v1 [cs.PF], 15 Sep 2026
- **Received / accepted:** 2026-03-26 / 2026-06-18
- **Replication package:** https://github.com/mooselab/performance-archetypes
- **Funding:** NSERC (ALLRP 597968-24); Fonds de recherche du Québec (#361973)
- **Keywords:** system tracing, performance archetypes, critical path analysis, performance regression detection, execution profiling

```bibtex
@inproceedings{shahedi2026archetypes,
  title     = {Discovering Performance Archetypes: Critical-Path-Aware Pattern Analysis and Regression Detection},
  author    = {Shahedi, Kaveh and Li, Heng and Lamothe, Maxime and Khomh, Foutse},
  booktitle = {Proceedings of the 41st IEEE/ACM International Conference on Automated Software Engineering (ASE '26)},
  year      = {2026},
  address   = {Munich, Germany},
  publisher = {ACM},
  doi       = {10.1145/3832783.3834426}
}
```

---

## 2. One-paragraph summary

The paper argues that static code metrics cannot predict runtime performance, measures
that gap (static complexity explains only 10.4% of variance in critical-path execution
time across six C/C++ programs), and responds with a dynamic, trace-based pipeline. It
fuses three signals per execution: static code features (srcML), application-level
function traces (uftrace), and kernel-level resource traces (LTTng). From ~80,000
top-k critical paths (function-call granularity, root-to-leaf, greedy longest-child
descent), it builds 33-dimensional feature vectors and clusters them with k-means into
**13 performance archetypes**. Five archetypes are near-universal (in ≥5 of 6 apps; three
in all 6) and cover 56.4% of paths. The archetypes then feed a **multi-signal regression
detector** that combines path-structure anomaly, resource anomaly, archetype-distribution
anomaly, and performance-bounds violation. On injected regressions it reaches
**F1 = 0.867** (Precision 0.910, Recall 0.827, AUC 0.923), a **60.4% F1 improvement** over
the best resource-only baseline (F1 0.540).

---

## 3. Motivation and gaps claimed

1. **Static–dynamic gap.** Static analysis cannot know loop iteration counts (possibly
   undecidable), per-instruction/library-call cost, or input-dependent call frequency.
   The authors claim no prior work quantified this gap systematically across applications.
2. **Single-signal dynamic profiling.** Profilers usually track one signal (CPU time or
   call counts) and miss interactions between compute, memory, and I/O.
3. **No transferable pattern models.** Existing tools lack models of recurring execution
   patterns that transfer across workloads/applications.
4. **Regression detection has high false positives** when single signals are used.
5. **Developers optimize the wrong functions** (statically complex but runtime-irrelevant).

Three stated challenges the method addresses:
(a) discover recurring, transferable performance patterns;
(b) detect regressions by triangulating multiple signals;
(c) quantify which functions truly matter for performance instead of static proxies.

---

## 4. Research questions and contributions

- **Preliminary study:** How well do static complexity metrics predict dynamic criticality?
- **RQ1:** Can critical paths be automatically clustered into transferable performance archetypes?
- **RQ2:** Can multi-signal triangulation (path structure + resource consumption + archetype deviation) improve automated regression detection over single-signal approaches?

Stated contributions:
1. Empirical quantification of the static–dynamic gap: static metrics explain 10.4% of performance variance; 14.7% of functions are "misaligned".
2. Archetype discovery method: 33-D feature vectors from traces → 13 archetypes; 5 near-universal (≥5/6 apps), 3 universal (6/6), covering 56.4% of paths.
3. Triangulated regression detection: F1 0.867, +60.4% over resource-only methods, with root-cause attribution.
4. Open-source end-to-end automated pipeline (trace collection → archetypes → regression detection).

---

## 5. Key definitions and terminology

- **Performance** = primarily wall-clock execution time (latency). Secondary: CPU utilization, memory allocation rate, I/O throughput.
- **"Performance variance"** = explained variance ρ² (squared Spearman correlation) of execution time.
- **Critical path (Definition 1):** the longest call path, in wall-clock time, of a thread during an execution. Given an execution E whose function calls form a dynamic call tree, the critical path P* = [f1, f2, …, fn] is a root-to-leaf sequence where:
  1. each fi has entry/exit timestamps from the trace;
  2. f1 is the root call (thread entry point, typically `main()`);
  3. for each consecutive pair (fi, fi+1), fi+1 is the **direct callee of fi with the longest wall-clock duration** among all callees of fi.
- **Difference from classical CPA:** Classical critical path analysis (parallel computing; Yang & Miller 1988) finds the longest dependency chain across concurrent tasks. Here, the method greedily descends the call tree within one thread. Path duration = root's wall-clock time (parent duration includes children). Goal: function-level sequence most responsible for time, not inter-task dependencies.
- **Multi-threading:** critical paths extracted per thread using per-thread timestamps; the longest paths across all threads are reported, with `thread_id` recorded. Concurrency affects durations (scheduling, sharing) but not path structure.
- **Peak vs. aggregate (deliberate design choice):** paths capture the single longest invocation chain, not cumulative time. A function called 1,000 times briefly will not appear if a single longer invocation exists elsewhere. The dynamic criticality score S_dynamic (Eq. 6) covers aggregate importance.
- **Bottleneck function:** the function on the critical path with the highest individual wall-clock time; identified during extraction.
- **Performance archetype:** a cluster of critical paths with a recurring combination of structural, temporal, and resource features; represents a distinct execution mode with a resource profile and optimization strategy.
- **Universality classes:** universal = in all 6 apps; near-universal = in ≥5 of 6; application-specific = in 1 app.
- **Why critical paths matter (paper's 3 reasons):** (1) they directly identify code responsible for most execution time; (2) they carry multi-dimensional info (structural, temporal, resource); (3) they enable cross-input pattern analysis.
- **Why cluster into archetypes:** reveal recurring cross-app patterns, give optimization strategies, and provide a basis for anomaly detection (a shift from one archetype to another may indicate a deviation).

---

## 6. Subject programs and data collection

### 6.1 Applications (Table 1)

| App | Domain | LOC | Avg cyclomatic complexity | Total paths | Avg path length | Median path length | Behavior |
|---|---|---|---|---|---|---|---|
| SQLite | Database | 212K | 6.89 | 15,000 | 11.70 | 12.0 | Alternates I/O-bound and compute-bound |
| OpenSSL | Cryptography | 632K | 6.08 | 11,088 | 14.70 | 16.0 | CPU-intensive math |
| Zstandard | Compression | 95K | 4.64 | 8,969 | 9.50 | 8.0 | CPU + memory buffering + disk |
| FFmpeg | Multimedia | 1.3M | 7.28 | 14,990 | 11.21 | 11.0 | Streaming I/O + parallel encode/decode |
| cURL | Network transfer | 197K | 6.81 | 14,975 | 12.55 | 11.0 | I/O-bound (network, DNS, TLS), CPU bursts for parsing |
| jq | Text processing | 115K | 7.63 | 14,767 | 8.42 | 8.0 | CPU-bound (tree traversal, pattern matching) |

Path length = number of functions per critical path. Stable release versions from official sources.

### 6.2 Workload generation

- **Structured randomization:** enumerate input parameters from each app's official docs, then uniformly randomize over valid ranges.
  - FFmpeg: codec and resolution; SQLite: DML/DDL operations and transaction sizes; OpenSSL: cipher suites and key-exchange algorithms; zstd: compression levels; cURL: protocol and option flags; jq: filter programs.
- **500 distinct inputs per app.** Inputs are deliberately not constrained to known critical paths (to avoid biasing archetypes toward known behavior).
- **3 iterations per input** (chosen after pilot runs showed low variance; cites Georges et al. 2007).
- 500 × 3 = **1,500 executions per app**, **9,000 executions total**.
- Workload generator scripts are in the replication package.

### 6.3 Multi-level trace collection (three synchronized streams)

1. **Static code analysis (srcML)** per function f: LOC, cyclomatic complexity C_cyclo, max loop nesting depth N_nest, number of unique calls |calls|, binary I/O indicator I(has_io). Combined into S_static (Eq. 5). Analysis is **intra-procedural**.
2. **Application-level function tracing (uftrace v0.18):** function entry/exit events with timestamps and call relationships. Compiled with `-g -finstrument-functions`.
3. **Kernel-level resource tracing (LTTng v2.13)**, nanosecond precision. Event categories:
   - CPU: context switches, process lifecycle events
   - Memory: page allocations/deallocations (kernel and user space)
   - Disk I/O: block-level read/write requests and completions
   - Syscalls and network: syscall entry/exit, network device events
   - PID/TID included to correlate with app traces.
   - User-space `malloc`/`free` captured via LTTng's LD_PRELOAD library interposition (UST memory events).

### 6.4 Hardware and cost

- Intel Core i7-11700K (3.60 GHz), 16 GB RAM, 1 TB NVMe SSD. Single platform.
- ~10 machine-days of collection; >350 GB of trace data.

---

## 7. Critical path extraction and correlation

### 7.1 Tooling

- Extraction via **Eclipse Trace Compass** with **TMLL** (the authors' own ML-enhanced trace analysis wrapper, Shahedi et al. 2025) as API wrapper.

### 7.2 Algorithm 1: Top-k critical path extraction

```
Input: call tree T=(V,E) per thread, k
LongestPath(v, excluded_edges):
    best = [v]; best_dur = duration(v)
    for each child c of v where (v,c) not in excluded_edges:
        (p, d) = LongestPath(c, excluded_edges)
        if d > best_dur: best = [v] + p; best_dur = d
    return (best, duration(v))
P1 = LongestPath(root, {})                      # primary critical path
for i = 2..k:
    candidates = {}
    for each node n on P_{i-1} with chosen child c*:
        E' = {(n, c*)}                           # exclude the EDGE, not the node
        (p, d) = LongestPath(n, E')
        add (p, d) to candidates
    P_i = best candidate not in {P1..P_{i-1}}
return {P1..Pk}
```

- Excluding edges (not nodes) keeps intermediate functions that may participate in other call chains.
- **k = 10** paths per execution. Justification: 11.3% of executions already produce fewer than 10 distinct paths; larger k yields near-duplicates of the primary path.
- Result: **79,789 paths** across 9,000 executions (the 11.3% subset contributes fewer than 10).

### 7.3 Correlating functions with kernel resources

- Kernel events aggregated into **10 µs windows** giving CPU utilization, memory alloc/dealloc activity, and I/O throughput per window.
- Each critical-path function's [start, end] interval is matched to overlapping windows; the function inherits those resource statistics.
- 10 µs is well below typical critical-path function durations (median: hundreds of µs), so sub-window skew is treated as noise.
- Purpose: know not only which functions are critical but **why** (CPU, memory pressure, or I/O).

---

## 8. Preliminary study: the static–dynamic gap

### 8.1 Scores

Static complexity score (Eq. 5), weights from Neuhaus et al. 2010:

```
S_static(f) = α1·log(1+LOC) + α2·log(1+C_cyclo) + α3·N_nest + α4·log(1+|calls|) + α5·I(has_io)
α2 = 0.3 (cyclomatic), α1 = α3 = α4 = 0.2, α5 = 0.1
```

Dynamic criticality score (Eq. 6):

```
S_dynamic(f) = Σ_{i=1..N} I(f ∈ CP_i) · T_f^(i) / T_total^(i)
N = 1,500 executions per app; CP_i = critical path of execution i;
T_f^(i) = time in f; T_total^(i) = total path duration
```

- Correlation: **Spearman ρ** (distributions non-normal; Shapiro–Wilk p < 0.001).

### 8.2 Results (Table 3)

| App | Spearman ρ | p-value | ρ² (var. explained) | Functions n |
|---|---|---|---|---|
| SQLite | −0.041 (lowest) | 0.103 | 0.2% | 1,547 |
| OpenSSL | 0.543 (highest) | <0.001 | 29.5% | 108 |
| Zstandard | 0.336 | <0.001 | 11.3% | 565 |
| FFmpeg | 0.175 | <0.001 | 3.1% | 2,615 |
| cURL | 0.407 | <0.001 | 16.6% | 744 |
| jq | 0.136 | <0.001 | 1.8% | 618 |
| **Average** | **0.259** | — | **10.4%** | — |

(Note: 10.4% is the mean of per-app ρ², not the square of the mean ρ.)

### 8.3 Misaligned functions (quadrant analysis)

- Functions split into 4 quadrants by static rank vs dynamic rank (quartile thresholds Q1/Q4).
- **Hidden bottlenecks** (low static, high dynamic): **7.0%**.
- **Misleading complexity** (high static, low dynamic): **7.6%**.
- Total misaligned: **14.7%**. Rest are aligned (high-high, low-low).
- Examples of hidden bottlenecks: single-line wrappers `curl_easy_perform` and `jv_dump` rank among the most critical because they orchestrate expensive callees.
- Misalignment by app: highest in I/O-heavy SQLite (19.9%) and FFmpeg (14.4%); lowest in CPU-bound OpenSSL (4.6%). Interpretation: the gap grows when I/O latency and invocation frequency dominate.
- The authors note inter-procedural static analysis would only partially close the gap, since frequency and I/O latency are inherently dynamic.

**Takeaway:** static complexity explains only 10.4% of runtime variance → dynamic, execution-driven analysis is required.

---

## 9. RQ1: Performance archetypes

### 9.1 Feature vector (33 dimensions, 5 groups)

| Group | Dims | Contents |
|---|---|---|
| Structural | 6 | Path depth; average cyclomatic complexity of on-path functions; complexity trend (increasing / decreasing / stable along the path) |
| Temporal | 6 | Total duration; time concentration via **Gini coefficient** (even vs concentrated in a few functions); bottleneck characteristics (location and intensity of the most time-consuming segment) |
| Resource | 9 | Mean and std; peak values and growth rates for CPU utilization, memory allocation activity, I/O throughput |
| Transition | 7 | Entropy and frequency of transitions between function types; functions labeled CPU-bound, Memory-bound, or I/O-bound by dominant resource. High entropy = frequently changing resource demand |
| Phase | 5 | Number and characteristics of resource phase changes along the path (e.g., CPU-intensive → I/O-intensive) |

(The paper does not enumerate all 33 individual features; exact list is in the replication package.)

### 9.2 Clustering procedure

- Standard scaling (z-normalization) of all features.
- **k-means** chosen for scalability (~80K × 33) and centroid prototypes (interpretability).
- k* chosen by maximizing average **silhouette score** over k ∈ [2, 15]. Upper bound 15 for parsimony/interpretability (beyond 15, clusters split existing patterns).
- **k* = 13**. Silhouette = **0.235**, Calinski–Harabasz = **11,396.0**, Davies–Bouldin = **1.340**. Moderate silhouette attributed to continuous nature of performance behavior. (Silhouette curve roughly 0.195–0.235; k = 13 is the peak, k = 14/15 slightly lower.)
- **Robustness check** on a stratified 20,000-path subsample:
  - Agglomerative-Ward at k = 13 vs k-means: **ARI = 0.571**.
  - HDBSCAN: ~22% noise; non-noise points agree moderately (**ARI = 0.250**).
  - Conclusion drawn: archetypes reflect genuine structure, not a k-means artifact.
- **Labeling:** randomly sampled 50 paths per cluster; manually inspected call sequences, resource profiles, behavior (following Kanellopoulos et al. 2008).
- **Stability metric:** fraction of inputs whose 3 iterations all map to the same archetype; within-cluster sum of squares used for homogeneity.

### 9.3 The 13 archetypes (Table 4)

| ID | Behavioral pattern | Paths (%) | Avg dur. | Avg depth | Univ. | Memory | Resource |
|---|---|---|---|---|---|---|---|
| A0 † | Mid-depth subsystem initialization | 8,992 (11.3%) | 2.49 ms | 13.5 | 5/6 | Volatile | CPU |
| **A1** | **Top-level lifecycle management** | 10,505 (13.2%) | 5.49 ms | 6.3 | **6/6** | Growth | CPU |
| A2 | Concentrated pipeline setup | 6,759 (8.5%) | 38.15 ms | 10.1 | 4/6 | Growth | CPU |
| A3 | Rapid library registration | 9,090 (11.4%) | 0.17 ms | 14.2 | 4/6 | Growth | CPU |
| A4 | Program compilation and parsing | 10,935 (13.7%) | 19.42 ms | 7.0 | 1/6 (jq) | Growth | CPU |
| A5 | Hash-driven function registration | 907 (1.1%) | 2.15 ms | 11.3 | 3/6 | Volatile | CPU+Mem |
| **A6** | **Sustained pipeline execution** | 8,164 (10.2%) | 25.04 ms | 10.1 | **6/6** | Growth | CPU |
| A7 † | Shallow bootstrap dispatch | 4,037 (5.1%) | 3.21 ms | 5.3 | 5/6 | Volatile | CPU |
| **A8** | **Deep multi-layer orchestration** | 13,297 (16.7%) | 4.52 ms | 16.9 | **6/6** | Growth | CPU |
| A9 | Memory-intensive deep initialization | 200 (0.3%) | 43.33 ms | 11.9 | 2/6 | Volatile | CPU+Mem |
| A10 | I/O-concurrent initialization | 780 (1.0%) | 13.72 ms | 14.4 | 4/6 | Growth | CPU+I/O |
| A11 | Recursive schema resolution | 2,347 (2.9%) | 2.64 ms | 19.3 | 1/6 (SQLite) | Volatile | CPU |
| A12 | Heavy codec lifecycle management | 3,776 (4.7%) | 71.67 ms | 11.7 | 1/6 (FFmpeg) | Growth | CPU |

Bold = universal (6/6). † = near-universal (5/6). Memory: Growth = monotonic increase; Volatile = non-monotonic. Resource = dominant resource consumed. Note that CPU dominates 10 of 13 archetypes.

### 9.4 RQ1 findings

1. **Convergence into 13 archetypes** across domains.
2. **Universality:** A1, A6, A8 in all 6 apps; A0, A7 in 5 apps. These 5 cover **44,995 paths = 56.4%**.
3. **Generalization:** 10 of 13 archetypes (76.9%) appear in ≥2 apps. Only 3 are app-specific (A4 jq, A11 SQLite, A12 FFmpeg), together **21.4%** of paths.
4. **Depth does not predict duration:**
   - A11 (depth 19.3) runs 2.64 ms; A12 (depth 11.7) is the slowest at 71.67 ms.
   - A3 (depth 14.2) runs 0.17 ms; A1 (depth 6.3) runs 5.49 ms → **32× difference**, inversely related to depth.
   - The driver is the *nature of operations* (e.g., codec lifecycle vs library registration), not call-stack structural complexity.
5. **Per-application performance signatures** (percent of that app's paths, from text):
   - SQLite: A0 41.3%, A7 22.6%, A11 15.6% (diverse query workload)
   - OpenSSL: A3 64.6% (many short crypto setup ops)
   - Zstandard: A6 48.6%, A1 42.9% (streaming compression pipeline)
   - FFmpeg: A2 40.0%, A12 26.8%, A8 20.4%
   - cURL: A8 54.2%, A1 33.0% (deep protocol stack, network waits)
   - jq: A4 74.1% (its sole occupant; parsing/compiling filter programs)
   - Figure 3 also shows smaller shares (approx., read from chart): SQLite A3 ~13%, A5 ~6%; OpenSSL A0 ~23%, A10 ~6%; cURL A6 ~13%; jq A8 ~15%, A6 ~6%; Zstd A2 ~6%; FFmpeg A1 ~10%, A6 ~6%.
6. **Per-app diversity** (fraction of 13 archetypes observed): 0.31 (Zstandard, cURL) to 0.54 (SQLite, OpenSSL, FFmpeg); jq 0.38.
7. **Iteration stability: 43.4%** of inputs have all 3 iterations in the same archetype; 56.6% have at least one different. Attributed to runtime non-determinism (thread scheduling, cache state, I/O timing), not method instability.

### 9.5 Transferable optimization guidance (near-universal archetypes)

| Archetype | Character | Suggested optimization |
|---|---|---|
| A8 Deep multi-layer orchestration (16.7%, most frequent) | Deep (16.9), moderate duration (4.52 ms); multi-layer protocol/subsystem coordination | Reduce call overhead, inline hot paths, flatten call chains |
| A1 Top-level lifecycle management (13.2%) | Shallow (6.3), 5.49 ms, monotonic memory growth; setup/run/teardown entry points | Reduce per-invocation overhead, streamline lifecycle transitions |
| A6 Sustained pipeline execution (10.2%) | Shallow-ish, 25.04 ms, memory growth; main data-processing loops | Algorithmic efficiency, memory allocation patterns in loops |
| A0 Mid-depth subsystem initialization (11.3%) | Depth 13.5, volatile memory; subsystem init and resource provisioning | Lazy initialization, remove redundant setup across subsystems |
| A7 Shallow bootstrap dispatch (5.1%) | Depth 5.3, 3.21 ms, volatile memory; lightweight bootstrap/dispatch | Batching and caching |

---

## 10. RQ2: Multi-signal regression detection

### 10.1 Regression injection (Table 2)

| Type | Injected code | Simulates |
|---|---|---|
| CPU Bottleneck | Repeated arithmetic operations | Algorithmic inefficiency, unoptimized paths |
| Memory Bloat | Allocate and initialize large memory blocks | Leaks, excessive buffering, inefficient data structures |
| I/O Contention | Repeated file writes | Excessive logging, inefficient I/O, unnecessary disk access |

- Injected at a single function's **entry point** via srcML-based AST manipulation.
- Target functions chosen randomly from functions appearing on at least one trace in baseline runs.
- One regression type per modified build.
- Evaluation set contains **2,525 regressed executions**.

### 10.2 Baseline modeling

- **70% of non-regressed executions** used to model normal behavior; split **by input** (all 3 iterations of an input in the same partition) to prevent leakage. Single split, no cross-validation.
- Four model families:
  1. **Path signature models:** path length distributions, common function sequences (n-grams), frequent bottleneck functions.
  2. **Resource distribution models:** mean, std, percentiles (e.g., p95) of CPU, memory, I/O.
  3. **Archetype distribution models:** probability distribution over the RQ1 archetypes in normal runs.
  4. **Performance bounds models:** statistical limits (p99, IQR-based) on durations and key metrics.

### 10.3 Anomaly scores (each normalized to [0,1] before aggregation)

**Path signature anomaly (Eq. 1):**
```
S_path = w_l · |ℓ(P) − μ_ℓ| / σ_ℓ
       + w_s · (1 − J(ngrams(P), ngrams_base))
       + w_b · I(b_new)
```
- ℓ(P) = path length; μ_ℓ, σ_ℓ from baseline.
- J = Jaccard similarity over **bi-gram and tri-gram** function-name sequences (captures reordering of calls, which length and bottleneck signals miss).
- I(b_new) = 1 if the bottleneck function was unseen in baseline paths.
- Default w_l = w_s = w_b = 1/3.

**Resource anomaly (Eq. 2):**
```
S_res = max( (x_cpu − μ_cpu)/σ_cpu , (x_mem − μ_mem)/σ_mem , (x_io − μ_io)/σ_io )
```
- Flagged when any resource metric exceeds its baseline 95th percentile (z-score > 3.0) (see Section 13 on this wording).

**Archetype distribution anomaly S_arch:** chi-square distance between observed and baseline archetype frequency distributions.

**Performance bounds violation (Eq. 3):**
```
S_bounds = ½ · ( I(d > p99) + I(ℓ > ℓ_max) )
```
- d = path duration; p99 = 99th percentile of baseline durations; ℓ_max = max baseline path length (implied).

**Final score (Eq. 4):**
```
S_anomaly = w1·S_path + w2·S_res + w3·S_arch + w4·S_bounds,   Σw = 1
default w1 = w2 = w3 = w4 = 0.25
flag regression if S_anomaly > τ,  τ = 0.65
```
- Weights and τ set using only baseline (non-regressed) training data.

### 10.4 Evaluation protocol

- Test set: remaining 30% of normal executions (for false positives) + regressed executions (for true positives).
- Metrics: Precision, Recall, F1, AUC-ROC.
- Baselines (Table 5), all applied to the paper's feature space because tools like PerfJIT and PEASS need code-change/version info:

| Baseline | CP-aware? | Description | Features |
|---|---|---|---|
| Threshold | Yes | Flag if path duration > baseline p95 | Path duration |
| Statistical Control (SPC) | Yes | μ ± 3σ on duration | Path duration |
| Isolation Forest | Yes | contamination = 0.1 | Path duration/length, resource averages |
| One-Class SVM | Yes | nu = 0.1 | Path duration/length, resource averages |
| Resource Threshold | No | Any resource > p95 | Resource averages |
| Resource Isolation Forest | No | Resource-only | Resource averages and peaks |
| Resource One-Class SVM | No | Resource-only | Resource averages and peaks |

Our method's inputs: path duration/length, resource averages, archetype ID, bottlenecks.

### 10.5 Results (Table 6)

| Method | F1 | Precision | Recall | AUC |
|---|---|---|---|---|
| **Multi-signal (with CPs)** | **0.867** | 0.910 | 0.827 | **0.923** |
| Threshold (CP) | 0.697 | 0.911 | 0.565 | 0.755 |
| One-Class SVM (CP features) | 0.671 | 0.514 | 0.964 | 0.525 |
| Isolation Forest (CP features) | 0.643 | 0.778 | 0.548 | 0.695 |
| Statistical Control | 0.480 | 0.939 | 0.323 | 0.651 |
| One-Class SVM (Resource) | 0.540 | 0.426 | 0.739 | 0.369 |
| Threshold (Resource) | 0.407 | 0.707 | 0.286 | 0.583 |
| Isolation Forest (Resource) | 0.394 | 0.575 | 0.300 | 0.539 |

- Confusion details: **TP = 2,089 of 2,525** regressions; **FP = 206** normal executions.
- **+60.4% F1** vs best resource-only baseline (0.867 vs 0.540). Resource-only baselines deliberately exclude path features, so the authors frame this as a controlled measure of critical-path awareness.
- Also beats best single-signal CP detector (Threshold, 0.697).
- Note: SPC and CP-Threshold have slightly higher precision than the method (0.939, 0.911) but far lower recall; CP One-Class SVM has higher recall (0.964) but poor precision.

### 10.6 Detection rate by manifested anomaly type

All injection types produce `resource_spike` and `duration_increase`; `path_elongation` and sometimes `new_function` appear when injected code lands on the critical path.

| Manifestation | Detection rate |
|---|---|
| resource_spike | 99.6% |
| new_function | 97.9% |
| path_elongation | 85.5% |
| duration_increase | 79.1% |
| archetype_shift | **53.3%** (hardest) |

Explanation given for archetype shifts: they are out-of-distribution relative to baseline models trained on the original archetype distribution, making them hard to separate from natural cross-input archetype variability.

### 10.7 Ablation (Figure 4; remove one signal at a time)

| Signal removed | F1 | Drop |
|---|---|---|
| None (full) | 0.867 | — |
| Archetype distribution | 0.785 | −9.5% (largest) |
| Performance bounds | 0.789 | −8.9% |
| Path structure | 0.795 | −8.3% |
| Resource consumption | 0.797 | −8.1% |

Conclusion: every signal contributes complementary information.

---

## 11. Automation and practical workflow

- Fully automated pipeline: data collection, critical path extraction, static analysis, archetype discovery, regression detection. Needs only compile flags and optional one-time threshold calibration.
- To add a new C/C++ app:
  1. compile with `-finstrument-functions`;
  2. implement a workload-generator subclass (input parameters + command templates) from the provided abstract base class;
  3. run the pipeline entry point.
- Claimed language-agnostic: works on function-level timing data; Java (JFR, async-profiler), Python (cProfile, py-spy), Rust (uftrace). Only the tracer must change, since features are computed via Trace Compass/TMLL's unified call-graph API.

---

## 12. Threats to validity (as stated by authors)

**External**
- Only 6 open-source C/C++ apps; may not generalize to other languages, paradigms, or proprietary industrial systems. Per-language archetype analysis left to future work.
- Single hardware platform (Intel i7-11700K); timings/resource patterns may differ on AMD/ARM.
- Randomized inputs may not represent real production workloads.

**Internal**
- Regressions are synthetic, single-function, entry-point injections; real regressions come from interaction effects, subtle algorithmic changes, config shifts (Chen & Shang 2017). One regression type per build; real cases may have multiple simultaneous regressions.
- System noise may remain despite 3 iterations and isolated environments.
- Single 70/30 split, no cross-validation; partition sensitivity possible.
- Manual archetype labeling introduces subjectivity.

**Construct**
- S_static is one of many possible formulations (e.g., pointer complexity, template instantiation depth not included).
- k = 10 paths and k* = 13 archetypes discretize continuous behavior.
- "Misaligned" defined via Q1/Q4 quartile thresholds; one of several possible schemes.
- Longest-single-invocation paths may miss cumulatively important, frequently called short functions (S_dynamic only partially addresses this; the two may rank functions differently).
- 33-D features do not model cache behavior or branch prediction.
- Future work: validate archetypes against developer-identified bottlenecks.

**Future work listed:** broader languages and domains, finer microarchitectural signals, validation on more hardware.

---

## 13. Ambiguities and inconsistencies (useful when citing or comparing)

These are observations about the paper text, not claims made by the authors.

1. **Structural features:** labeled 6D but only three items are named (depth, average complexity, complexity trend). Exact composition must come from the replication package. Same for other groups.
2. **Section cross-reference:** RQ1 says clustering follows "Section 3.5", but clustering is described in Section 3.6.
3. **Resource anomaly threshold wording:** "exceeds its baseline 95th percentile (z-score > 3.0)" mixes two different criteria (p95 ≈ z 1.645 for a normal distribution; z > 3 ≈ p99.87).
4. **Normalization of S_res and S_path to [0,1]** is stated but the exact mapping (clipping, min-max, sigmoid) is not given.
5. **S_arch for a single execution:** described as chi-square distance between observed and baseline archetype frequency distributions, but a single execution has one archetype per path (up to 10 paths). How the per-execution distribution is formed is not fully specified (likely over its top-k paths).
6. **ℓ_max** in Eq. 3 is not explicitly defined (presumably max baseline path length).
7. **Weights and τ "determined using baseline data only"** but are also described as uniform defaults; how τ = 0.65 was derived from normal-only data is not detailed.
8. **Detection unit:** described at "execution level", but many features are per critical path; how path-level scores roll up to an execution is not fully explicit.
9. **Iteration stability of 43.4%** is fairly low; the authors attribute it to runtime non-determinism, but this also means an archetype label is noisy per run, which interacts with the S_arch signal and the weak archetype_shift detection (53.3%).
10. **"Performance variance" = ρ²** is Spearman-based (rank), not R² of a regression model.
11. **k is overloaded:** k = 10 paths per execution vs k* = 13 clusters.
12. **Regressions are always injected into functions already on some baseline trace,** which favors CP-aware detection; the resource-only vs CP-aware comparison should be read in that light.
13. Iterations are "3 per input" and each contributes up to 10 paths; per-app path totals (e.g., SQLite exactly 15,000) reflect 1,500 executions × 10.

---

## 14. Related work positioning used by the paper

- **Regression detection:** SPC-based (Nguyen et al. 2012; Jiang et al. 2009; Malik et al. 2013) → ML-based (Isolation Forest, One-Class SVM, PerfJIT by Chen et al. 2020, He et al. 2019). Industrial limitations: detect but fail to localize (Foo et al. 2015), architectural-level only (Liao et al. ICSE '25), unit-test-local (PeASS, Reichelt et al. 2019). Chen & Shang 2017: small config/data-structure changes often cause big regressions.
- **Recent close work, and how it differs:** HybridRCA (Ekhlasi et al., ICSME 2025; critical-path extraction + targeted metrics for RCA in microservices; Lamothe is a co-author), JPerfEvo (Shahedi et al., MSR 2025; per-commit method-level changes in Java), Zhao et al. 2024 (performance bug prediction from code metrics). All need code-change context or source-level analysis. This paper is **execution-level and diff-free**.
- **Performance characterization:** Smith's software performance engineering and execution graphs; workload modeling (Menascé; WESSBAS by Vögele et al.). These describe *external workload* (what users do), not *internal execution behavior* (how the system responds). APM tools (Datadog, New Relic, Dynatrace) work at service/endpoint level, not function-call granularity, and do not auto-discover patterns.
- **Static vs dynamic:** McCabe complexity; defect prediction (Basili 1996, Menzies 2007); dynamic invariants (Ernst 2001). ML approaches usually use either static or dynamic features, not both.
- **Tracing:** LTTng (<1% overhead, used at Google, IBM, Ericsson), uftrace, perf, eBPF. Prior work rarely synchronizes multi-level traces.
- **Critical path analysis:** from parallel computing (Yang & Miller 1988) to distributed systems (Denys et al. 2023), Uber's Canopy (Kaldor et al. 2017, RPC-level paths over 40,000 endpoints), cyber-physical systems (Hendriks et al. 2017). All target explicit parallelism; **none extract critical paths at function-call granularity within dynamic call graphs for cross-app pattern discovery**.
- **Trace analysis:** Trace Compass, Jaeger are visualization-focused; **no prior work applies ML to extract recurring archetypes from multi-dimensional trace data** (authors' claim).

Authors' own related line: "Tracing optimization for performance modeling and regression detection" (Shahedi et al., TOSEM 2026); TMLL (Shahedi et al. 2025).

---

## 15. Claims safe to cite (with exact figures)

- Static complexity explains on average **10.4%** of variance (ρ²) in critical-path execution time across 6 C/C++ apps; mean Spearman ρ = **0.259**; range ρ = −0.041 (SQLite) to 0.543 (OpenSSL).
- **14.7%** of functions are misaligned (7.0% hidden bottlenecks, 7.6% misleading complexity).
- **79,789** critical paths from **9,000** executions; 33-D features; k-means with **13** archetypes (silhouette 0.235).
- **3** universal + **2** near-universal archetypes covering **56.4%** of paths; **10/13** archetypes in ≥2 apps.
- Depth is not predictive of duration (e.g., **32×** duration difference, inversely related to depth).
- Multi-signal detector: **F1 0.867, P 0.910, R 0.827, AUC 0.923**; **+60.4%** F1 over best resource-only baseline.
- Archetype-shift regressions are hardest to detect (**53.3%**).
- Removing the archetype signal causes the largest ablation drop (**−9.5%** F1).

---

## 16. Reusable ideas and open gaps (for a paper building on this work)

Ideas that can be reused or adapted:
- Greedy longest-child critical path extraction at function granularity, plus edge-exclusion to get top-k alternatives.
- Time-window (10 µs) alignment of kernel resource events to function intervals to explain *why* a function is costly.
- Path feature families: structural, temporal (Gini concentration, bottleneck location), resource, transition entropy between CPU/Mem/I/O-bound functions, phase changes.
- Archetypes as a behavioral vocabulary and as a baseline distribution for anomaly detection.
- Multi-signal anomaly fusion (path n-gram Jaccard + new-bottleneck flag + resource z-score + archetype chi-square + p99 bounds) with a single threshold.
- Leakage-safe splitting by input rather than by run.
- Controlled comparison: same detectors with and without path features.

Open gaps and weaknesses a follow-up could target:
- Archetype-shift detection is weak (53.3%) and archetype assignment is unstable across iterations (43.4%). Soft/probabilistic assignment, per-input conditioning, or distance-to-centroid instead of hard labels could help.
- Fixed uniform weights and a fixed threshold; no learned fusion, no calibration study, no per-app tuning analysis.
- Synthetic, single, entry-point injections only; no real regressions from version history, no multiple simultaneous regressions.
- Peak-only critical paths miss cumulative cost of frequent short calls.
- No cache, branch, or microarchitectural features; single Intel machine.
- C/C++ single-process apps only; no microservices, distributed traces, or production telemetry (the AIOps/incident setting is not evaluated).
- Root-cause attribution is claimed as a benefit but not quantitatively evaluated (no localization accuracy metric).
- No cross-validation; manual archetype labeling.
- Moderate cluster quality (silhouette 0.235; HDBSCAN ARI 0.250), suggesting behavior is a continuum more than discrete types.
