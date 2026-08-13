# StrataTrace Non-LLM Baseline Recommendation: RCAEval + Multi-Source BARO (with TORAI as the SOTA companion)

## TL;DR
- **Adopt RCAEval (github.com/phamquiluan/RCAEval, MIT-licensed, ASE'24 / WWW'25 / FSE'26) as your baseline *framework* and use its Multi-source BARO (`mmbaro`) as the primary published non-LLM reference method, with TORAI (the RCAEval authors' FSE'26 method) as a second, SOTA multi-source baseline.** "CARE" is not a real RCA method name — the well-perceived published approach your design doc is gesturing at is the RCAEval/BARO/TORAI family from Luan Pham et al. at RMIT University.
- **This choice wins on all five selection axes:** reviewer credibility (three top-venue papers, ~161 GitHub stars, actively maintained through June 2026), multimodal coverage (metrics+logs+traces via one dict-based API), degradation survivability (BARO and TORAI are unsupervised, need no complete call graph, and TORAI is explicitly built for "blind spots" = missing traces), low integration effort (pandas-DataFrame in, ranked list out, MIT license), and it runs as a callable Python function rather than a monolithic pipeline.
- **Avoid causal-discovery methods (CIRCA, RCD, MicroCause, CausalRCA, PC/Granger-PageRank) as your *headline* baseline:** they either require a service dependency/call graph (breaks under per-service coverage removal) or need many high-resolution time points for conditional-independence tests (breaks at 60s resampling over ~100s runs). Keep them only as deliberate "expected-to-break" comparison points that make your RQ1 cliff story stronger.

## Key Findings

**1. RCAEval is real, current, and the de-facto SE/AIOps benchmark.** Verbatim from the WWW'25 paper (arXiv:2412.17015), RCAEval is "an open-source benchmark that offers nine datasets with 735 real failure cases… It includes 15 reproducible baselines covering metric-based, trace-based, and multi-source RCA methods" across Online Boutique, Sock Shop, and Train Ticket, and 11 fault types. It is published at ASE'24 (the "How Far Are We?" causal-inference study), WWW'25 (the benchmark paper), and FSE'26 (TORAI). Latest tagged release is 1.2.0 (confirmed on PyPI as `rcaeval-1.2.0-py3-none-any.whl`, Jun 2025), with active commits and an `fse26` branch added June 2026. A 2026 multi-dataset LLM-agent benchmark paper (arXiv:2606.29193) describes RCAEval as "the de-facto baseline for causal-graph and change-point methods (e.g., MicroScope, MicroRCA, RCD, BARO, DiagFusion)."

**2. "CARE" is a mis-remembered name.** There is no RCA method called CARE by the RCAEval authors. The RCAEval authors' own methods are **BARO** (FSE'24, metric-only change-point + robust scorer) and **TORAI** (FSE'26, multi-source, blind-spot-aware). There is a KDD'22 method "CARR" (a Causal-Aware neural approach by Guo et al.), but it is unrelated and not what your framing wants. Treat "RCAEval / CARE-style" in your design doc as shorthand for "the RCAEval/BARO/TORAI family."

**3. Multimodal SOTA field.** The genuinely multimodal (metrics+logs+traces) published methods are: Nezha (FSE'23, event-graph, unsupervised), Eadro (ICSE'23, supervised GNN multi-task), DiagFusion (TSC'23, supervised GNN), Multi-source BARO / CIRCA / RCD (RCAEval WWW'25 extensions), and TORAI (FSE'26). Of these only the RCAEval-bundled ones share a single harness, API, and metric definitions with the benchmark you'll cite.

**4. Degradation-robustness is where the recommendation is decided.** BARO and TORAI are unsupervised and per-run (no training window needed), and TORAI explicitly does not require a call graph — it clusters services by anomaly severity and does causal ranking within clusters, so it degrades gracefully under trace sampling and per-service coverage removal. Causal-discovery baselines structurally break under your transforms.

**5. Metrics align well.** RCAEval reports AC@1, AC@3, Avg@5 at both service-level (coarse) and metric/indicator-level (fine). Your Top-1/Top-3 map exactly to AC@1/AC@3. Avg@5 ≠ Top-5 (it is the mean of AC@1..AC@5), so report both AC@k and MRR and define them explicitly.

**6. Prior art on the degradation angle exists but is not a full scoop.** Several 2025-2026 works touch telemetry-quality robustness (KylinRCA reports F1 drops under log loss and trace sampling; UniSage and Gleaner study trace-sampling effects on RCA; a Jan 2026 LLM study withholds modalities). None combines four modalities *including kernel traces*, deterministic offline degradation transforms held method-fixed, and a cost/Pareto budget analysis. RQ1/RQ4 are defensibly novel, but you must cite and differentiate.

## Details

### A. RCAEval: what it ships and how to plug in your own data

**Repository & license.** github.com/phamquiluan/RCAEval, MIT license for the authors' own code and datasets; bundled third-party baselines carry their original licenses (BARO MIT, CIRCA BSD-3, E-Diagnosis BSD-3, MicroCause Apache-2.0, RCD MIT; CausalRCA and RUN carry "No License" — a real reuse caveat, since "no license" defaults to all-rights-reserved). PyPI: `pip install RCAEval[default]`. ~161 stars, 32 forks.

**Datasets.** RE1 (375 cases, metric-only), RE2 (270 cases, metrics+logs+traces), RE3 (90 cases, code-level faults, multi-source). Systems: Online Boutique, Sock Shop, Train Ticket. Note Sock Shop in RE2/RE3 has logs but **N/A traces** — directly relevant to your partial-trace-coverage framing (your testbed instruments only 6/14 Sock Shop services). Data on Figshare (recommended) and Zenodo (DOI 10.5281/zenodo.14590730).

**Baselines in `RCAEval.e2e`.** RUN, CausalRCA, CIRCA, RCD, MicroCause, EasyRCA, MSCRED, BARO, ε-Diagnosis, TraceRCA, MicroRank, PDiagnose, Multi-source BARO, Multi-source RCD, Multi-source CIRCA, TORAI. Exact importable entrypoint names (verified from source): `baro`, `mmbaro` (multi-source BARO), `mmcirca`, `mmrcd`, `mmnsigma`, `torai`, `causalrca`, `circa`, `rcd`, `microcause`, `e_diagnosis`, `microrank`, `tracerca`, etc. The multi-source set is defined in `main.py` as `MM_METHODS = ("mmbaro", "mmnsigma", "mmrcd", "mmcirca")`. (Note: `nezha` and `pdiagnose` are named as baselines in the papers but are not exposed as importable `e2e` functions in the current `main` branch method list.)

**Python API (single-source), verified from README:**
```python
from RCAEval.e2e import baro
from RCAEval.utility import download_data, read_data
download_data()
data = read_data("data.csv")           # returns a pandas DataFrame, needs a "time" column
root_causes = baro(data, anomaly_detected_timestamp)["ranks"]
```

**Multi-source API (the one you want), verified from `main.py`:** multi-source methods take a **dict of DataFrames**, not a single frame:
```python
from RCAEval.e2e import mmbaro
data = {
    "metric":      metric_df,     # "time" col + <service>_<metric> cols
    "logts":       logts_df,      # "time" col + per-service log-event counts
    "tracets_err": traces_err_df, # "time" col + per-edge/service error counts
    "tracets_lat": traces_lat_df, # "time" col + per-edge/service latency
}
out = mmbaro(data, inject_time, dataset=..., anomalies=None,
             dk_select_useful=False, sli=..., verbose=False,
             n_iter=..., args=...)
ranks = out["ranks"]              # ranked list "<service>_<metric>"
```
Key integration insight: RCAEval does NOT feed raw logs/traces to the method — it pre-aggregates raw `logs.csv`/`traces.csv` into **time-series** CSVs (`logts.csv`, `tracets_err.csv`, `tracets_lat.csv`). Your adapter's real job is this raw→time-series aggregation.

**Disk layout (main.py).** Per-case folder `{benchmark}_{service}_{fault}_{instance}/` containing `data.csv` (metrics) + `inject_time.txt` (Unix ts) + (for multi-source) `logts.csv`, `tracets_err.csv`, `tracets_lat.csv`. There is **no custom-path CLI flag**; `--dataset` maps through a hardcoded `DATASET_MAP` to `data/...` paths. So for a custom dataset you either (a) mimic the folder layout and add a `DATASET_MAP` entry, or (b) bypass `main.py` entirely and call `mmbaro(...)` directly on in-memory DataFrames — recommended for StrataTrace. (There is a minor documented discrepancy: the *distributed* dataset uses `metrics.json`/`logs.csv`/`traces.csv`, while the evaluation harness reads the processed `data.csv`/`logts.csv`/`tracets_*.csv` — your adapter should target the harness formats.)

**Installation friction.** Recommended Ubuntu 20.04/22.04, **Python 3.12** for the default env, plus apt packages `build-essential libxml2 libxml2-dev zlib1g-dev python3-tk graphviz`. RCD needs a separate locked env (`requirements_rcd.lock`); TORAI needs a **separate Python 3.8 env** and its own Figshare datasets (`requirements_torai.lock`). This multi-env split is the single biggest engineering friction. Your Ubuntu 24.04 host differs from the recommended 22.04 — flag as a minor compatibility risk (pyenv-managed interpreters recommended).

### B. Candidate comparison

| Method | Venue/Year | Modalities | Public code | Needs call graph? | Needs training window? | Run-length sensitivity | Degradation verdict |
|---|---|---|---|---|---|---|---|
| **Multi-source BARO (`mmbaro`)** | FSE'24 / WWW'25 | M+L+T | Yes (RCAEval, MIT) | No | No (per-run, unsupervised) | Moderate (BOCPD wants some points) | **Robust; primary pick** |
| **TORAI** | FSE'26 | M+L+T | Yes (RCAEval, sep. py3.8) | **No (by design)** | No (unsupervised) | Moderate | **Most robust to coverage/trace loss; SOTA companion** |
| BARO (metric) | FSE'24 | M | Yes (MIT) | No | No | Moderate | Robust; good metric-only control |
| CIRCA | KDD'22 | M (+graph) | Yes (BSD-3) | **Yes** | No | High (CI tests) | Breaks under coverage removal + 60s resample |
| RCD | NeurIPS'22 | M | Yes (MIT) | Partial | No | High (PC-based) | Breaks at coarse resample / short runs |
| MicroCause | IWQoS'20 | M | Yes (Apache-2.0) | Yes (PCMCI) | No | High | Breaks; PCMCI needs long series |
| CausalRCA | JSS'23 | M | Yes (No License) | Builds graph (DAG-GNN) | Trains per-run VAE | Very high | Breaks; also license risk |
| Nezha | FSE'23 | M+L+T | Yes (IntelligentDDS) | Event graph from traces | Needs fault-free baseline window | High | Fragile under trace loss; needs normal window |
| Eadro | ICSE'23 | M+L+T | Yes | Learns deps | **Yes — supervised** | Very high | Breaks; cross-run training conflicts with per-run degradation |
| DiagFusion | TSC'23 | M+L+T | Yes | Dep graph | **Yes — supervised** | Very high | Breaks; supervised |
| MicroRank / TraceRCA | WWW'21 / IWQoS'21 | T | Yes (RCAEval) | Uses trace structure | No | Depends on trace volume | Trace-only; degrades hard under 5-10% sampling (useful cliff datapoint) |

### C. Degradation-robustness analysis (the heart)

- **Heavy trace sampling (5-10%):** BARO (metric) unaffected (ignores traces). Multi-source BARO degrades gracefully (traces are one of four inputs). TORAI is explicitly designed for missing traces/blind spots — best survivor. Trace-only MicroRank/TraceRCA collapse — deliberately include them to show the cliff. This mirrors published behavior: the KylinRCA paper (arXiv:2509.12231) observes that trace-based topology methods' "accuracy drops sharply when sampling rates dip below 5%, making them ill-suited for high-load production settings."
- **Coarse metric resampling (60s over ~100s runs):** This leaves only ~2-3 metric points per run. **Every conditional-independence / causal-discovery method (CIRCA, RCD, MicroCause, CausalRCA, PC/Granger) breaks** — CI tests need dozens-to-hundreds of samples. BARO's Bayesian Online Change-Point Detection also weakens, but its **RobustScorer** still functions on few points: per the BARO paper (arXiv:2405.09330), it is "a novel nonparametric statistical hypothesis testing technique… which is less sensitive to the accuracy of anomaly detection," leveraging data collected before the anomaly to establish a baseline distribution and ranking metrics by how significantly they deviate. This is your cleanest "structural break" story.
- **Log-level filtering:** Multi-source BARO/TORAI use log-event time-series; dropping below WARN reduces event counts but does not structurally break the pipeline. Nezha's event-pattern mining is more sensitive (fewer templates → sparser event graph).
- **Per-service coverage removal (missing nodes):** Any method needing a complete call/dependency graph (CIRCA, Nezha's trace-derived event graph, Eadro/DiagFusion learned graphs) breaks or silently drops the removed node from candidates. TORAI is the intended winner here — the RCAEval authors literally engaged a DevOps engineer to reconstruct dependency graphs for graph-requiring baselines, direct evidence of how brittle that requirement is.

### D. Run-length feasibility

Your ~100s runs at 5s metric resolution give ~20 metric points — already sparse for causal discovery. RCAEval's own runs are longer and its default `--length 20` windows ~20 samples per side of the injection. BARO/TORAI/N-Sigma operate on short pre/post windows and tolerate this. As a sanity anchor on the difficulty of the task: the WWW'25 RCAEval paper reports that on RE2, "existing methods mostly obtain moderate results — for example, CIRCA and RCD obtain the best average Avg@5 score of 0.46 and 0.54, respectively," i.e., even on the authors' own well-formed data the causal-discovery methods are middling. **Recommendation:** if you can extend runs to ≥300-600s at 5s (≈60-120 points), you materially improve every baseline and make the causal-discovery comparison fairer (so their failure is attributable to *degradation*, not *insufficient data even at full fidelity*). If you keep ~100s runs, pre-register that causal-discovery baselines are data-starved even at 100% fidelity and treat them as lower bounds.

### E. Metric alignment

- Top-1 = AC@1, Top-3 = AC@3 — exact match. AC@k = probability the top-k results include a true root cause.
- Avg@k = (1/k)·Σⱼ AC@j — this is the mean of AC@1..AC@k, NOT Top-5; report separately, define explicitly.
- MRR is not RCAEval-native; compute it yourself from the ranked list `out["ranks"]`. It is monotone-compatible with AC@k so no definitional conflict.
- Granularity: RCAEval supports service-level (coarse) and metric/indicator-level (fine, `<service>_<metric>`). Match your `target_service` (coarse) and `expected_winning_modality`/indicator (fine) to these two granularities respectively.
- AD F1/AUROC + detection latency: BARO is end-to-end (it detects onset via BOCPD then localizes), so you can extract its detection timestamp for latency and F1/AUROC directly — a bonus most pure-RCA baselines cannot provide.

### F. Prior-art / novelty positioning

- **KylinRCA (arXiv:2509.12231, "full-stack observability," HUST, Sep 2025)** reports that under its proposed framework, entity-localization F1 drops only ~4.2% as the missing-log rate goes 0→30%, and ~5.8% as trace sampling drops 100%→3% (via interpolation). This is the closest existing robustness-under-degradation result — but it evaluates *its own* method, not a held-fixed cross-method study, and has no kernel modality. (Caveat: this is a review/proposal-style paper; treat the specific percentages as the authors' reported numbers rather than an independently reproduced benchmark.)
- **UniSage (arXiv:2509.26336)** and **Gleaner (arXiv:2604.16810)** study trace/log *sampling* effects on downstream RCA accuracy (AC@1/AC@3/MRR) — they optimize the sampler, not hold the method fixed while degrading data. Partial overlap with RQ1's trace-sampling axis; cite as the trace-sampling prior art.
- **"Stalled, Biased, and Confused" (arXiv:2601.22208)** withholds whole modalities (metrics/logs/traces) from LLM RCA reasoners and measures accuracy deltas (e.g., withholding metrics gave the largest localization drop, ΔLA ≈ −0.07 to −0.15) — overlaps your whole-modality-removal transform but is LLM-only and has no kernel layer.
- **The FSE'26 "Freezing the Crime Scene" state-snapshot paper** and multi-dataset LLM-agent benchmarks (OpenRCA; arXiv:2606.29193) are adjacent on reproducible agentic RCA evaluation.
- **Nobody** combines: (i) four modalities incl. lossless kernel traces, (ii) deterministic seeded offline degradation transforms applied identically to all methods, (iii) cross-modality compensation (RQ3), and (iv) an observability cost/Pareto budget (RQ4). Your novelty is safe if you explicitly position against KylinRCA (robustness), UniSage/Gleaner (sampling), and 2601.22208 (modality ablation).

## Recommendations

**Primary (do this):** Integrate **RCAEval** and run **Multi-source BARO (`mmbaro`)** as your headline published non-LLM baseline. It is unsupervised, per-run, needs no call graph, ingests all three higher-layer modalities, is MIT-licensed, and is authored by the same group as the benchmark you'll cite — maximum reviewer credibility with minimum "is this really SOTA?" risk. The underlying method is well-decorated: BARO won the FSE'24 Best Artifact Award (Luan Pham, Huong Ha, Hongyu Zhang, "BARO: Robust Root Cause Analysis for Microservices via Multivariate Bayesian Online Change Point Detection," *Proc. ACM Softw. Eng.* 1, FSE, Article 98, pp. 2214–2237, July 2024; github.com/phamquiluan/baro).

**Companion (also do this, budget permitting):** Add **TORAI** as a second, stronger multi-source baseline. It is the FSE'26 SOTA, is explicitly built for the exact "blind spot / missing trace / partial coverage" condition your RQ1 coverage-removal and RQ3 kernel-compensation questions probe, and its "no call graph" design is the cleanest published contrast to your kernel-telemetry hypothesis. Cost: a separate Python 3.8 env and local Figshare data (doi.org/10.6084/m9.figshare.31925976).

**Metric-only control:** Also run plain **BARO** (metric-only) to isolate the value of logs+traces vs metrics alone — directly serves RQ3.

**Deliberate "break" baselines:** Run **CIRCA** and **RCD** (and optionally MicroCause) NOT because they'll win, but because their structural failure under coarse resampling and coverage removal is exactly the nonlinear "cliff" RQ1 predicts. Document them as expected-to-break references.

**Integration plan (adapter/shim):**
1. In `stratatrace/loader.py`, after producing per-modality pandas DataFrames, add an `rcaeval_adapter.py` that emits the four-key dict `{"metric", "logts", "tracets_err", "tracets_lat"}`, each with a `"time"` column.
2. Metrics: pivot to wide format, columns `<service>_<metric>`, resampled to the run's grid; rename any `*_latency-90`→`*_latency` and drop `*_latency-50` to match RCAEval conventions.
3. Logs: aggregate to per-service (or per-service-per-level) event counts per time bucket → `logts.csv` schema. This is where your log-level-filtering degradation transform naturally plugs in.
4. Traces: aggregate OTel spans to per-service (or per-edge) error counts (`tracets_err`) and latency (`tracets_lat`) per bucket. Your trace-sampling transform plugs in *before* this aggregation.
5. Feed `inject_time` from `ground_truth.json`'s injection window start.
6. Call `mmbaro(data, inject_time, sli=<frontend_latency-style SLI>, n_iter=<#cols-1>, args=<Namespace with root_path/data_path>)`; read `out["ranks"]`; compute Top-1/Top-3/MRR against `target_service` (coarse) and indicator (fine).
7. Run RCAEval as a **separate offline pipeline** over the same stored, degraded run bundles — do NOT force it through your four LLM tool interfaces. Your supervisor's "method held fixed, degradation is data-only" guardrail is satisfied because the adapter applies the identical degraded bundle to every method.
8. Kernel tier: RCAEval has no kernel modality. Fold kernel-derived signals into the `metric` frame as extra `<service>_<kernelmetric>` columns so `mmbaro`/`torai` can consume them without code changes — this lets you test RQ3 kernel compensation *within* the published method too.

**Benchmarks that would change the recommendation:** If, at 100% fidelity on your data, `mmbaro` scores at/near random (AC@1 ≈ 1/#services), that signals your runs are too short / QPS too low for *any* statistical method — in which case extend runs to ≥300-600s before drawing degradation conclusions, and lean on your in-house heuristic baseline as the anchor. If TORAI's py3.8 env proves unbuildable on Ubuntu 24.04, drop TORAI to a "reported numbers only" citation and keep `mmbaro` as the sole published baseline.

## Caveats
- **Verified vs inferred:** Entrypoint names (`mmbaro`, `torai`, etc.), the four-key dict schema, `MM_METHODS`, the disk layout, MIT license, dataset stats, and venue history are verified from the repo/papers. The exact `def` signatures of `read_data`, `download_multi_source_data`, and the multi-source demo-notebook cell code could not be fetched verbatim (GitHub blocked raw access) — treat the `mmbaro(...)` argument list as accurate-but-confirm-by-reading `docs/multi-source-rca-demo.ipynb`.
- **"CARE" unresolved as a proper noun:** I found no RCA method named CARE by these authors. If your design doc's "CARE" came from a specific paper, it may be an internal shorthand; the substantive match is BARO/TORAI. Confirm with your supervisor.
- **Ubuntu 24.04 / Python-env risk:** RCAEval targets Ubuntu 20.04/22.04 + Python 3.12 (default) and Python 3.8 (TORAI/RCD). Your 24.04 host may need pyenv-managed interpreters. Not a blocker, but budget ~a day for env setup.
- **License landmine:** CausalRCA and RUN ship with "No License" (all rights reserved). If you redistribute or publish derived code, restrict to the MIT/BSD/Apache baselines (BARO, TORAI-code, CIRCA, RCD, E-Diagnosis, MicroCause).
- **Run-length is the biggest scientific risk:** at ~100s / 5s you have ~20 metric points; several baselines are data-starved before any degradation is applied, which can muddy attribution in RQ1. Strongly consider longer runs.
- **Novelty is defensible but not uncontested:** KylinRCA already shows graceful RCA degradation under log loss and trace sampling; you must cite it and lean on your kernel modality + held-fixed cross-method design + cost-Pareto framing to differentiate.

### Key links
- RCAEval repo: https://github.com/phamquiluan/RCAEval — WWW'25 paper: https://arxiv.org/abs/2412.17015 — dataset (Zenodo): https://zenodo.org/records/14590730
- BARO: https://arxiv.org/abs/2405.09330 — repo: https://github.com/phamquiluan/baro
- TORAI (FSE'26): https://arxiv.org/abs/2604.13522
- ASE'24 "How Far Are We?": https://arxiv.org/abs/2408.13729
- Nezha (FSE'23): https://github.com/IntelligentDDS/Nezha — Eadro (ICSE'23): https://github.com/BEbillionaireUSD/Eadro
- Prior art: KylinRCA https://arxiv.org/abs/2509.12231 · UniSage https://arxiv.org/abs/2509.26336 · Gleaner https://arxiv.org/abs/2604.16810 · modality-ablation LLM study https://arxiv.org/abs/2601.22208