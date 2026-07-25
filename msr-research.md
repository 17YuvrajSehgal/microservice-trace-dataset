# Research plan v2 — "How much does each observability modality actually buy you?"

**A kernel-trace-augmented, four-modality incident dataset + a per-task modality
ablation study for operations reasoning.**

**Working name candidates:** `FourSight` (four modalities / incident foresight),
`KODA` (Kernel-augmented Observability Dataset & Analysis), `ModSense`.
Decide after a collision check.

**Primary target:** MSR 2027 — *two* coupled submissions:
1. **Data & Tool Showcase** (4 pages + 1 refs): the dataset + loader + collection rig.
   Verified deadlines: **abstract Nov 5, 2026; paper Nov 10, 2026** (AoE).
2. **Technical track** (same deadline window): the empirical modality-ablation study.
   Fallback for the study paper: FSE/ASE 2027, EMSE journal.

This plan supersedes the scope of `research-idea1.md` (the "OmniMicro" 3-app /
Kubernetes / 60 TB benchmark). Following the mentor's guidance
(`research-idea-mahsa.txt`): **start from the systems and pipeline we already
have**, add the missing modalities, and make the *study* the intellectual core.
The benchmark-scale ambitions (multi-app, multi-host) move to future work.
Several pieces of idea1 are explicitly carried over (§7 verification harness,
ground-truth schema, datasheet/DOI discipline).

---

## 1. What we already have (asset inventory)

From the JSS/LMAT work, this repo already contains a pressure-tested,
single-VM collection rig around Weaveworks Sock Shop (Docker Compose, GCP VM,
12 vCPU / 40 GB, Ubuntu 24.04, LTTng 2.15):

| Asset | Where | State |
|---|---|---|
| **Lossless full-kernel LTTng capture** (all tracepoints + syscalls, pid/tid/procname contexts, 8 MB × 32 sub-buffers/CPU, CTF) | `microservice-lttng-data-collection-scripts/collect_trace.sh` | Working; validated 0 dropped events under disk stress (`DOCS/final/collection_changes_notebook.md`) |
| **OTel span capture** via Java agent → `LoggingSpanExporter` → docker-logs relay → LTTng UST | `docker-compose.otel.yml`, `agents/otel-to-lttng.py` | Working but weak: export-time events only, 4 Java services only |
| **Prometheus KPI export** (~33 series: per-service QPS/p50/p95/errors + VM CPU/mem/disk/net) | `download_metrics.sh` | Working (query_range, 10 s step) |
| **Container/process metadata snapshots** every 10 s (docker inspect/top, ps -eLo, cgroup/ns) — the kernel-pid↔service join key | `collect_trace.sh:snapshot_metadata` | Working |
| **Fault injection**: host-wide stress-ng CPU/disk/mem + tc netem/tbf network | `1_cpu…4_net_stress.sh` | Working, host-level only |
| **Workload generator**: 200 VUs, weighted realistic journeys, per-request CSV | `load_generator.py` | Working |
| **Per-modality overhead measurement harness** (baseline / lttng_only / lmat_sync / lmat_async, rotated fair protocol) | `baseline_load.sh`, `lttng_only_run.sh`, `run_reviewer_overhead_*.sh`, `analyse_*.py` | Working — rare asset, see RQ4 |
| **Kernel-trace ML pipeline** (CTF→100 ms tid windows→NPZ shards; LSTM/Transformer next-syscall+latency models; OOD eval; root-cause prototypes) | `microservice/*.py` (imports `models/`, `dataset/Dictionary.py` from the sibling `adaptive_tracer` project — must be vendored or re-released) | Working |
| **Existing 148 GB dataset**: 5 scenarios × 5 runs × 100 s (normal, cpu, disk, mem, net) | external `traces/` (gitignored) | Collected; older runs pre-date the lossless fix |

Two modality gaps: **application logs are not collected at all** (the relay
consumes docker logs but keeps only span lines), and **distributed traces are
degraded** (export-time, partial coverage). Fixing these two cheaply is most of
the new engineering.

---

## 2. Positioning: the gap (verified against July 2026 literature)

Closest related datasets/benchmarks — none has a kernel layer:

| Work | Metrics | Logs | App traces | **Kernel traces** | LLM-task harness | Collection-cost data | Agent trajectories |
|---|---|---|---|---|---|---|---|
| RCAEval (ASE'24/WWW'25/FSE'26) — 735 failures, 3 systems, 11 fault types | ✓ | ✓ | ✓ | ✗ | partial (RCA only) | ✗ | ✗ |
| LEMMA-RCA (NEC) — real faults, microservice + OT | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| OpenRCA (ICLR'25) — 335 failures, 68 GB, LLM RCA | ✓ | ✓ | ✓ | ✗ | ✓ (RCA only) | ✗ | ✗ |
| AIOps Challenge / MSDS / LO2 / Nezha corpora | ✓ | some | some | ✗ | ✗ | ✗ | ✗ |
| AIOpsLab (MSFT), ITBench (IBM) — live agent testbeds | ✓ | ✓ | ✓ | ✗ | ✓ (live, not a static dataset) | ✗ | ✗ |
| AgentSight (eBPF agent observability) — a *tool*, no dataset | – | – | – | ✓ (tool) | ✗ | ✗ | ✓ (tool) |
| TRAIL / Who&When / TraceElephant — agent-failure datasets | ✗ | ✗ | ✗ | ✗ | ✓ (attribution) | ✗ | ✓ |
| **This work** | ✓ | ✓ | ✓ | **✓** | **✓ (4 tasks × modality subsets)** | **✓ (measured)** | v2 (paper 2) |

Defensible novelty claims (each checkable against the artifact):

1. **First public incident dataset that time-aligns kernel traces with
   application traces, logs, and metrics under labeled fault injections.**
2. **First per-task modality-ablation study of operations reasoning** (RCA,
   anomaly detection, incident explanation, repair) **that includes the kernel
   modality** — with LLMs and with classical baselines.
3. **Only dataset shipping measured collection-side cost for every modality on
   the same testbed** (CPU/latency/throughput overhead + bytes/min), enabling a
   real cost–benefit answer rather than a hand-wave.
4. **First LLM-consumable kernel-trace representations** (the "representation
   ladder", §4) released as reusable tooling.

What we do *not* claim: production data, multi-host generality, complete fault
coverage (see §12 honesty rules, carried over from idea1 Appendix B).

---

## 3. The four modalities: current state → required changes

The mentor's four modalities map onto the stack as follows. Changes are ordered
by leverage; none requires leaving Docker Compose or the single VM.

### M1 — Metrics / KPIs (small change)
*Today:* Prometheus (5 s scrape) + `download_metrics.sh` exporting ~33 curated
series; Grafana PDFs as human evidence.
*Change:*
- Export **all** Prometheus series over the run window (`query_range` sweep of
  the whole label space, or a TSDB snapshot per run), not just the KPI subset —
  downstream users should choose their own features. Keep the curated KPI JSON
  as the "lite" view.
- Add **cAdvisor** so per-container CPU/mem/net/blkio series exist (today only
  node-exporter host series + app histograms). Per-container metrics are the
  metrics-modality's only chance at service-level RCA — without them the
  comparison against traces is unfairly handicapped.
- Automate the Grafana evidence exports (idea1 §4.7 style PNGs) instead of
  manual PDFs.

### M2 — Logs (new, cheap)
*Today:* not collected.
*Change:* per run, capture `docker logs --timestamps --since <run-start>` for
**every** container into `logs/<service>.log` (raw) + a parsed JSONL
(`ts, service, container, level, message`). No new infrastructure needed — the
relay already proves docker-logs capture works. Optionally enable the upstream
`docker-compose.logging.yml` (Fluentd/ES) later; do not block on it.
Sock Shop's Java services log exceptions, connection failures, and GC events —
exactly the signals the log modality should win on for application-level faults.

### M3 — Distributed traces (the main upgrade)
*Today:* export-time span log-lines from 4 Java services relayed into LTTng UST.
Flagged as a caveat in our own README; a reviewer will flag it too.
*Change:*
- Run an **OpenTelemetry Collector** container in the compose stack.
- Flip `agents/otel.properties` from `otel.traces.exporter=logging` to
  `otlp` (endpoint = collector), and have the collector write **OTLP-JSON files**
  per run (`file` exporter). This upgrades the 4 Java services from export-time
  lines to **native spans with start/end timestamps, parent/child links, and
  attributes** with a ~2-line config change.
- Extend coverage beyond the Java four: front-end (Node) via
  `@opentelemetry/auto-instrumentations-node`, catalogue/payment/user (Go) via
  upstream builds if feasible — otherwise **document partial coverage honestly**
  and add the edge-router (nginx) access log with trace-context headers as a
  cheap topology-wide fallback. Coverage of carts/orders/shipping/queue-master +
  front-end already spans every request path in the load generator's journeys.
- Keep the LTTng-UST relay running **in addition** — it is our cross-layer
  clock bridge (spans and kernel events in one LTTng clock domain) and a
  differentiator; now it relays OTLP-export confirmations rather than being the
  only span record.

### M4 — Kernel traces (keep; add derived representations)
*Today:* the strongest asset — full lossless capture.
*Change:* none to collection (keep `--all '*'` + the 8M×32 buffers; optionally
add a curated-event profile `syscalls+sched+block+net+irq` as a storage-saving
knob). The real work is **consumability** — see §4.

### M0 — Ground truth & joins (glue)
Keep the 10 s metadata snapshots (they are the pid↔container↔service join key).
Add per-run `ground_truth.json` + `verification.json` (§6). Keep per-request
load-generator CSVs — they are the client-side truth of user-visible impact and
serve as the SLO reference for all four tasks.

**Time alignment:** all modalities on one host, one clock. Kernel + UST share
the LTTng monotonic domain; docker logs / OTLP / Prometheus carry wall-clock
timestamps; record the monotonic↔realtime offset at run start/end (plus NTP
offset via `chronyc tracking`) into `runinfo` so any pair of records is alignable
to well-bounded error. This "same time base" property is claim #1 — make it a
measured, per-run number, not an assertion.

---

## 4. Making kernel traces consumable: the representation ladder

Raw CTF at ~8 GB/100 s is unusable by LLMs and painful even for ML researchers.
The dataset ships each run's kernel modality at four levels (derived offline
with `bt2`; the deriver is part of the release — this is a contribution, not
plumbing):

- **L0 — raw CTF.** For systems researchers. (Released for a subset of runs;
  see §8 storage tiers.)
- **L1 — kernel KPIs.** Per (service, 1 s window): syscall counts by family,
  syscall latency percentiles, sched_switch/wakeup rates, run-queue delay,
  block-I/O ops/latency, net dev throughput, page-fault/reclaim counters,
  cgroup CPU-throttle counts. Compact Parquet; directly comparable to M1 and
  usable as features by any tabular method. (Builds on
  `preprocess_lmat_kernel.py`'s windowing machinery.)
- **L2 — per-request wait attribution.** For each traced request (join via span
  window × pid/tid, the mechanism `preprocess_sockshop.py --seg_mode ust`
  already implements): where did wall-time go — on-CPU, runnable-but-waiting
  (contention!), blocked-on-disk, blocked-on-net, blocked-on-futex. This is the
  kernel's unique semantic: *why* a request was slow, not just that it was.
  No app-level modality can produce this.
- **L3 — natural-language kernel digest.** Deterministic, templated textual
  summary per (window, service): "carts: p95 syscall latency 4.1× baseline;
  runnable-wait share rose 3%→41%; disk write latency normal" — the
  LLM-consumable form, with a fixed token budget per window. Templated (not
  LLM-generated) so it is reproducible and cannot hallucinate.

The ablation study (§7) feeds LLMs L3 (and L1 tables); L2 powers the RCA
baselines; L0/L1 serve the ML community. "How should kernel data be presented
to an LLM?" is itself an open question nobody has answered — L1 vs L2 vs L3 is
a secondary ablation inside the study.

---

## 5. Fault & workload catalog v2

### Why the current catalog can't answer the mentor's RQs
All four existing faults are **host-wide resource stressors**. Two consequences:
(a) "which service is the root cause?" is ill-posed — the answer is always "the
host"; (b) the modality comparison degenerates — there are no faults where logs
or traces should *win*, so "kernel is informative" would be baked in by design.
A reviewer will see this immediately. The fix is a two-axis catalog:

**Axis 1 — scope:** host-wide vs service-targeted.
**Axis 2 — layer:** resource vs application/dependency.

### Catalog (~12 faults × 2 intensities, all feasible on Compose + single VM)

**A. Host-wide resource (keep, now with 2 intensities each):**
1. CPU saturation (stress-ng, aggressive = current params; subtle = ~50% load)
2. Memory pressure (stress-ng)
3. Disk I/O saturation (stress-ng)
4. Network delay/loss + shaping on the docker bridge (tc netem+tbf)

**B. Service-targeted resource (new; makes RCA well-posed):**
5. CPU throttle one service: `docker update --cpus 0.2 <svc>` (cgroup quota —
   visible in kernel as throttle events + runnable-wait; app-level just "slow")
6. Memory cap one service: `docker update -m` → GC pressure / OOM-kill
7. Per-service network impairment: netem on one container's veth (pumba or
   `nsenter`-applied tc) — e.g., only carts↔carts-db degraded

**C. Application & dependency faults (new; where logs/traces should win):**
8. Slow database: Toxiproxy between orders and orders-db, latency toxic
   (published-postmortem-style "slow query" recipe)
9. Dependency outage: `docker pause payment` → order failures, exceptions,
   retry behavior at orders
10. Error storm: Toxiproxy reset/timeout toxics → 5xx bursts on one route
11. Message-queue backlog: pause queue-master → RabbitMQ queue growth,
    delayed async shipping
12. **Noisy neighbor** (the kernel-only showcase): co-located stress container
    pinned to shared cores with cgroup caps tuned so service KPIs barely move
    while kernel contention (runnable-wait, cache/sched pressure) is blatant.

Each fault recipe declares its **expected winning modality** a priori
(pre-registered in the recipe file): A→kernel/metrics disambiguate; B→traces
localize, kernel explains; C→logs/traces win; 12→kernel-only. The study then
*tests* these predictions — that is the paper's narrative spine.

**Workload conditions** (per mentor: repeat analysis across conditions):
- `steady` — current 200 VU profile;
- `low` — 50 VU (do subtle faults disappear under light load?);
- `burst` — ramp 50→300 VU (does bursty load mask or mimic faults?).
Run every fault under `steady`; run a selected subset under `low`/`burst`.
Keep run length 180–300 s (60 s baseline, ~120 s injection, 60 s recovery) so
every run contains onset and recovery — required for explanation/repair tasks.

**Scale estimate:** 12 faults × 2 intensities × 5 repeats (steady) + normals +
condition subset ≈ **150–200 runs**. Kernel raw ≈ 8 GB/100 s → ~2.5–4 TB total;
manageable with the tiering in §8.

---

## 6. Ground truth and injection verification (carried over from idea1)

Adopt idea1 §4.6–4.7 nearly verbatim — it was the strongest part of that plan:

- `ground_truth.json` per run: fault family/name/intensity, parameters,
  injection window (UTC + monotonic), target service/resource, expected blast
  radius, expected winning modality, remediation applied, tooling manifest,
  git SHA.
- `verification.json` per run: automated check that the fault demonstrably
  moved its declared target metrics (baseline/injection/recovery windows,
  σ-deltas, thresholds), verdict `confirmed | borderline | unconfirmed`,
  auto-generated impact PNG. Unconfirmed runs are released but excluded from
  canonical splits. This automates what `pdf_proofs_of_injection/` did by hand.
- Canonical train/val/test splits shipped in the metadata (following the
  five-run OOD split convention already in `preprocess_lmat_kernel.py`).

**Repair-task ground truth** falls out for free: every injection script's
cleanup **is** the correct mitigation (remove tc qdisc, kill stress-ng, restore
`docker update` limits, unpause container, remove toxic). Record it as a
structured action in `ground_truth.json` and verify recovery in the recovery
window — that gives T4 an objective reference, which almost no repair benchmark
has.

---

## 7. The study: tasks, experimental design, research questions

### Tasks (mentor's four, operationalized)

| Task | Input | Output | Ground truth | Metric |
|---|---|---|---|---|
| **T1 Anomaly detection** | telemetry window (modality bundle) | anomalous? + fault family | injection window + family | F1 / AUROC; detection latency |
| **T2 RCA** | full-run bundle | (a) scope: host vs service; (b) resource/fault type; (c) target service | injection manifest | top-1 / top-3 accuracy per sub-question |
| **T3 Incident explanation** | full-run bundle | structured postmortem: onset, symptom, mechanism, blast radius, evidence citations | manifest + verification data | fact-checklist score (onset ±10 s, cause match, blast-radius overlap) + rubric LLM-judge, human-audited subset |
| **T4 Repair/mitigation** | full-run bundle | action from a fixed action space + free-text rationale | recorded remediation (§6) | action-match accuracy + judge for rationale |

Evaluators: 2–3 LLMs (one frontier, one open-weight, one small — the capability
axis is itself informative) **plus** non-LLM baselines where they exist (the
existing LMAT LSTM/Transformer for T1 kernel; metric z-scores for T1; trace/
metric RCA baselines from RCAEval for T2). LLM-only studies get attacked;
mixed baselines defuse that.

### Design: modality bundles under a fixed token budget
For each (task, run): evaluate modality subsets — 4 singletons, all 6 pairs,
4 leave-one-out triples, all-four (15 subsets; at ~40 evaluated runs per
condition this is a few thousand LLM calls per model — tractable). **Budget
matching is the key methodological control:** every bundle is serialized to the
same token budget (each modality gets budget/|bundle|), so "traces beat logs"
means information quality, not "traces got more tokens." Report a second
uncapped configuration as sensitivity analysis. Fixed serializers per modality
(L3/L1 for kernel, span-tree text for traces, template-parsed logs, KPI tables
for metrics) are shipped with the harness.

### Research questions (mentor's four, sharpened + one added)

- **RQ1 (informativeness):** per-task, per-modality single-modality performance
  matrix. Hypothesis: metrics ≈ best cheap detector (T1); traces dominate
  service localization (T2c); kernel dominates resource-type disambiguation
  (T2b) — the four stress scenarios are *mutually confusable* at app level
  (all present as "latency up") and kernel sched/block/net evidence separates
  them; logs dominate mechanism explanation for C-family faults (T3).
- **RQ2 (task→modality mapping):** minimal sufficient bundle per task — the
  smallest subset within ε of the all-four score. Output: a practitioner-facing
  task×modality prescription table.
- **RQ3 (marginal value):** leave-one-out deltas + add-one-in gains over each
  coalition (with 15 subsets we can compute exact per-modality Shapley values —
  a clean, novel framing for observability). Identifies redundancy (metrics vs
  kernel-L1?) and complementarity (traces+kernel?).
- **RQ4 (cost–benefit):** three measured cost axes vs accuracy: (i) collection
  runtime overhead — extend the existing fair-overhead harness
  (`run_reviewer_overhead_200_fair.sh` protocol) to conditions {baseline,
  +metrics, +logs, +otel, +lttng, all}, reusing the JSS methodology (which
  already showed lttng_only vs baseline and LMAT-async ≈ +13% P95);
  (ii) storage bytes/min per modality (incl. L1–L3 vs L0 for kernel);
  (iii) consumption cost — tokens/latency/$ per task query. Output: Pareto
  frontiers, e.g. "accuracy per 1k tokens" and "accuracy per GB-hour".
  No existing dataset paper can produce this figure; we can, on day one.
- **RQ5 (condition sensitivity):** how the RQ1–RQ3 picture shifts with
  (a) intensity (aggressive→subtle), (b) workload (steady/low/burst),
  (c) fault scope (host/service). Hypothesis: kernel's marginal value *grows*
  as faults get subtler and more app-invisible — the noisy-neighbor recipe is
  the existence proof at the extreme (app-level modalities near-blind by
  construction).
- **RQ6 (kernel representation, secondary):** L1 vs L2 vs L3 for LLM
  consumption — which representation, at equal token budget, best preserves the
  kernel modality's value?

### Paper split
- **Data paper (4 pp):** dataset, schema, collection rig, verification,
  representation ladder, loader, one teaser figure (RQ1 matrix).
- **Study paper (full):** RQ1–RQ6 with the pre-registered per-fault
  winning-modality predictions as the narrative device.

---

## 8. Release engineering

- **Loader SDK** (`pip install <name>`): one call → time-aligned per-run
  dataframes per modality + ground truth; handles CTF (bt2) for L0 and Parquet
  for L1–L3.
- **Tiers:** `Lite` (≤ ~150 GB, Zenodo DOI): all runs at L1–L3 kernel + full
  M1–M3 + ground truth — sufficient to reproduce every headline result.
  `Full` (+L0 raw CTF for ≥1 repeat per condition, ~2–4 TB): institutional
  object store / HF Datasets with manifest + checksums. (Precedent: our
  existing 148 GB release; OpenRCA ships 68 GB.)
- **Reproducibility:** pinned images/digests, one-command `collect.sh
  <fault> <intensity> <workload> <run>`, CI smoke run (60 s normal), datasheet
  (Gebru et al.), CC-BY-4.0 data / Apache-2.0 code.
- **Repo hygiene prerequisites:** vendor or re-release the sibling
  `models/` + `dataset/Dictionary.py` dependencies (currently imported from the
  parent `adaptive_tracer` project — the baselines don't run without them);
  fix DOCS path drift.

---

## 9. Extension to agentic systems (paper 2 — design hooks now)

Mentor's call is right: separate paper. But paper 1 must be **modality-extensible
by construction** so paper 2 is additive, not a rebuild.

**The move:** agent trajectories become modality **M5**; kernel traces stay the
ground-level truth. AgentSight (2025) demonstrated eBPF-level agent observability
as a *tool*; TRAIL/Who&When/TraceElephant ship agent-trajectory *datasets* with
no system layer. Nobody has released **trajectory + kernel + app-telemetry
aligned data with labeled agent incidents** — that is paper 2's gap, and it
mirrors paper 1's gap one level up.

**Three agentic system classes to include:**
1. **SRE/AIOps agent on this very testbed** (elegant + cheap): an LLM agent
   with tool access (query Prometheus, grep logs, read L3 digests) diagnosing
   the paper-1 incidents live. Its trajectory (OTel GenAI semantic conventions:
   LLM calls, tool calls, tokens, latencies) is captured alongside the same
   four system modalities — and paper 1's ground truth already labels every
   incident it investigates. Bonus: its task accuracy *is* an online replication
   of the paper-1 offline study.
2. **A multi-agent application under load** (e.g., a LangGraph/AutoGen RAG or
   workflow service embedded as a Sock Shop-adjacent service): agent system as
   *subject*, receiving requests from the load generator, with faults injected
   into its dependencies (slow vector DB via Toxiproxy, LLM-API latency/rate-limit
   faults, tool failures, prompt-injection payloads in inputs, degraded host via
   paper-1 stressors).
3. **A coding agent in a sandboxed repo** performing SWE tasks while the host
   is instrumented — kernel view of spawned processes, file/network activity vs
   the agent's claimed actions (AgentSight's divergence framing, as a dataset).

**Agent-specific fault catalog:** tool failure/timeout, degraded environment
(reuse paper-1 stressors — unique cross-paper link: *how does an agent behave
when its machine is the incident?*), model downgrade, prompt injection,
misconfigured tool schema, rate-limiting, context truncation.

**Tasks (paper-1 tasks, lifted):** trajectory anomaly detection; failure
attribution (which step/agent — Who&When framing, but now with system-level
evidence); incident explanation (did the agent *cause* the syscall storm or
react to it?); trajectory repair (minimal edit that fixes the run).

**Hooks to bake into paper 1 now (near-zero cost):**
- Run-bundle schema with modalities as a first-class list (`modalities:
  [metrics, logs, traces, kernel]` → later `+ trajectory`).
- Serializer interface in the eval harness keyed by modality name.
- Time-alignment protocol documented modality-agnostically.
- Ground-truth schema's `fault.layer` enum already includes `application` —
  add `agent` as a reserved value.

---

## 10. Execution plan (today = Jul 25, 2026 → MSR deadline Nov 5/10, 2026 ≈ 14 wks)

**Phase 0 — spike, 1–2 wks (de-risk everything):** on the existing VM: OTel
Collector + OTLP file export from the 4 Java services; per-container docker-logs
dump; full Prometheus export; clock-offset recording; one end-to-end run with
all four modalities + a hand-audit of cross-modality alignment on a single
request. *Gate: nothing else starts until one perfectly-aligned run exists.*
**Phase 1 — catalog + verification, 2–3 wks:** fault recipes 5–12 (Toxiproxy,
docker update, pumba/nsenter-tc, pause), `ground_truth.json` +
`verify_injection.py`, subtle-intensity calibration, pre-registered
winning-modality predictions committed to the repo.
**Phase 2 — collection campaign, ~3 wks:** 150–200 runs with nightly QC
(verification-confirmed rate per recipe; fix recipes >20% unconfirmed before
continuing). Overhead-matrix runs (RQ4-i) interleaved.
**Phase 3 — representations + study, 3–4 wks:** L1–L3 derivers; loader SDK;
serializers + budget-matched harness; run T1–T4 × 15 bundles × models;
classical baselines (reuse LMAT models for T1-kernel; RCAEval baselines for T2).
**Phase 4 — papers + release, 2–3 wks:** Zenodo DOI for Lite, datasheet,
4-page data paper + study paper, artifact freeze.

Budget: one GCP VM as before (+~2–4 TB storage). No Kubernetes, no new apps.
**Scope-cut order if time runs short:** drop `burst`/`low` conditions → drop
RQ6 → drop faults 7/11 → drop the third LLM. The four-modality alignment, the
catalog's two-axis structure, and RQ1–RQ4 are the non-negotiable core.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Go/Node services resist OTel instrumentation | Ship with Java-4 + front-end coverage; nginx access logs w/ trace headers as topology fallback; document honestly (coverage already spans all load-gen journeys) |
| Single-host criticized as unrealistic | Frame as explicit scope: modality-informativeness questions are orthogonal to distribution; multi-host = future work; cite mentor-style "start from what exists" economy |
| "Synthetic faults" criticism | C-family recipes mirror published postmortem patterns (slow query, retry storm, dependency outage) — cite postmortems per recipe (idea1 mitigation, kept) |
| LLM-judge validity for T3 | Fact-checklist scoring against machine-readable ground truth is primary; judge is secondary; human audit on a sample |
| Token-budget serialization biases results | Budget-matched primary + uncapped sensitivity; serializers released for scrutiny |
| Kernel storage blows up | Curated-event profile knob; L0 for 1 repeat/condition only; L1–L3 for all |
| LMAT sibling code missing (`models/`, `Dictionary.py`) | Vendor into this repo early in Phase 0 |
| MSR data-track page limit (4 pp) too tight for both contributions | Data paper = dataset only; study = technical track; they cite each other |

---

## 12. Honesty rules (kept from idea1, Appendix B)

Not "production data" — a labeled testbed. Not "first observability dataset" —
first *kernel-aligned four-modality* incident dataset. Not "complete fault
coverage" — a two-axis catalog with stated limits. Not "zero clock error" —
measured per-run offset bounds. Coverage of OTel instrumentation stated
per-service.

---

## 13. Immediate next steps

1. Phase-0 spike (§10) — the OTLP-file-export flip is the single highest-leverage
   change in the plan; everything else layers on it.
2. Vendor `models/` + `dataset/Dictionary.py` from `adaptive_tracer`.
3. Commit this plan; open issues per phase; pre-register the fault→modality
   prediction table as `fault_catalog.md` when Phase 1 starts.
4. Literature deep-pass before writing: RCAEval (FSE'26), LEMMA-RCA, OpenRCA
   (ICLR'25), LO2, Nezha, AIOpsLab, ITBench, AgentSight, TRAIL, Who&When —
   the §2 table must survive adversarial review.
5. Name collision check, then rename repo artifacts.
