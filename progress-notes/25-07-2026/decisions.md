# Progress notes — 25-07-2026

## Decisions

### 1. Research direction pivoted to a modality-ablation study (plan: `msr-research.md`)
Superseded the earlier "OmniMicro" benchmark-scale plan (3 apps, Kubernetes,
~20 faults, ~60 TB) with a study-first plan per mentor's (Mahsa) guidance:
keep the existing single-VM Sock Shop pipeline, add the missing modalities,
and make the **per-task modality ablation** (4 modalities × 4 tasks) the
intellectual core.
**Why:** mentor's explicit advice to start from existing systems; feasibility
within the MSR 2027 window (Data & Tool Showcase deadlines verified: abstract
Nov 5, paper Nov 10, 2026); a study paper's contribution survives a smaller
testbed, a benchmark-claim paper's does not.
**Reporting note:** the OmniMicro draft's verification harness (per-run
`ground_truth.json` + automated `verification.json` + impact plots) and its
honesty rules were deliberately carried over into the new plan.

### 2. Novelty gap verified against July-2026 literature
RCAEval (FSE'26), LEMMA-RCA, OpenRCA (ICLR'25), AIOps corpora: all lack a
kernel-trace layer. AgentSight = eBPF agent observability *tool*, no dataset.
TRAIL / Who&When / TraceElephant = agent-trajectory datasets, no system layer.
**Claimable:** first public incident dataset time-aligning kernel traces with
app traces/logs/metrics under labeled faults; first modality-ablation study of
ops reasoning tasks including the kernel modality; only dataset with measured
per-modality collection overhead (reusing our JSS fair-overhead harness).
**Why noted:** these are the claims the §2 gap table must survive review with;
re-verify before submission.

### 3. Fault catalog must be two-axis (host-wide vs service-targeted × resource vs application)
Current 4 faults are all host-wide stressors. Two problems: service-level RCA
is ill-posed (answer is always "the host"), and the modality comparison is
rigged toward kernel by design (no faults where logs/traces should win).
**Decision:** ~12-fault catalog with service-targeted resource faults
(docker update cpu/mem caps, per-container netem) and application/dependency
faults (Toxiproxy slow-DB, dependency pause, error storm, queue backlog) plus
a noisy-neighbor kernel-showcase recipe. Each recipe pre-registers its
predicted winning modality — the prediction table is the paper's narrative
spine.

### 4. Kernel representation ladder (L0–L3)
Raw CTF (~8 GB/100 s) is unusable by LLMs and most researchers. Dataset ships
kernel modality at 4 levels: L0 raw CTF → L1 per-service kernel KPIs →
L2 per-request wait attribution (on-CPU / runnable-wait / blocked-on-X) →
L3 templated natural-language digests (deterministic, budget-bounded).
**Why:** makes the kernel modality comparable to others in the LLM study;
"how to present kernel data to an LLM" is itself an open sub-question (RQ6).
Templated (not LLM-generated) so digests are reproducible and cannot
hallucinate.

### 5. Study methodology: budget-matched modality subsets
Evaluate all 15 modality subsets per task under a **fixed token budget** so
"modality A beats B" measures information quality, not serialization length.
15 subsets → exact per-modality Shapley values. Uncapped run as sensitivity
analysis. Mixed evaluators (LLMs + classical baselines: LMAT models, z-scores,
RCAEval baselines) to defuse "LLM-only study" criticism.

### 6. Replaced untracked Sock Shop clone with pinned fork submodule (commit 508f0e1)
`microservices-demo/` was an untracked clone of upstream master — invisible to
repo history, so runs couldn't cite the deployment code. Now a **git submodule
of the 17YuvrajSehgal fork**, pinned at 9dff06f (upstream is deprecated/frozen;
fork also insures against upstream/image disappearance).
Also forked `front-end` and `catalogue` on GitHub (not yet cloned/modified).
**Why fork > overlays now:** OTel-instrumenting Node/Go services requires
source changes + image rebuilds; overlay files stay for anything achievable
via compose overrides (Java agent, collector) to keep the diff-vs-upstream
small and citable.
**Reporting note:** per-run `ground_truth.json` should record the submodule
SHA; discipline = push submodule first, then bump the pin in the parent repo.

### 7. Instrumentation coverage: three tiers with deliberate blind spots
- **Tier 1 (must):** front-end (Node, auto-instr) + catalogue (Go, otelhttp in
  source) — entry point of every journey + most-hit service.
- **Tier 2 (should):** user + payment (Go) — login and checkout paths.
- **Tier 3 (deliberately NOT instrumented):** DBs (mongo 3.4, mysql),
  rabbitmq, edge-router — kept as **controlled trace blind spots**, visible
  only via client-side spans, metrics, logs, and kernel traces.
**Why:** trace coverage gaps would confound RQ1/RQ3 (traces losing due to
instrumentation, not information) — but *deliberate, documented* blind spots
become a research asset: "can kernel traces compensate where traces are
blind?" (e.g., slow disk under catalogue-db).
**Disciplines:** ship a per-service coverage matrix in dataset metadata;
every service-targeted fault targets either a covered service or an
explicitly-labeled blind-spot case. Cheap add: nginx access logs with
traceparent header = topology-wide request log for the logs modality.

### 8. Phase-0 collection-rig changes drafted and locally verified (Docker tests)
All four modality upgrades drafted and each tested on the local machine:
- **Traces:** OTel Collector (`otel/opentelemetry-collector-contrib:0.157.0`,
  pinned) + Java agent (2.25.0) flipped to **dual export
  `otel.traces.exporter=otlp,logging`** — OTLP gives native spans (verified
  end-to-end locally: OTLP/HTTP test span → collector → `spans.jsonl`);
  `logging` is deliberately KEPT so the docker-logs→LTTng-UST relay keeps
  working as the cross-layer clock bridge. Per-service `OTEL_SERVICE_NAME`
  added (a shared otel.properties would otherwise make every service report
  `unknown_service:java` in OTLP resources).
- **Per-run OTLP bundling by byte-offset slicing** of the collector's global
  `spans.jsonl` (offset at run start, slice after a 3 s drain at run end;
  exact windowing downstream via native span timestamps). Chosen over
  rotation/truncation because it never touches the collector's open file
  handle.
- **Logs:** single post-run `docker logs --timestamps --since <run-start>`
  dump per container (verified: `--since` accepts our UTC format and filters
  correctly). Post-run rather than streaming so the logs modality adds zero
  load inside the measured window — protects the RQ4 overhead numbers.
- **Metrics:** `download_metrics_full.sh` exports EVERY metric name in the
  run window at native 5 s resolution (verified against a live Prometheus:
  307/307 metrics, valid gzipped multi-series JSON). Curated
  `download_metrics.sh` retained as the "lite" KPI view. cAdvisor added for
  per-container series — via overlay only: compose merges volume mounts by
  target path, so `docker-compose.metrics.yml` mounts our
  `prometheus-cadvisor.yml` (upstream config + cadvisor job) over the
  upstream file. No fork edit needed.
- **Clock anchors:** `snapshot_metadata()` now records
  (CLOCK_REALTIME, CLOCK_MONOTONIC, CLOCK_BOOTTIME) triples + NTP status at
  start / every 10 s tick / end (verified in a Linux container). Rationale:
  LTTng stamps events with MONOTONIC, everything else uses REALTIME; the
  pairs make the per-run alignment offset and drift *measured* numbers, per
  the plan's claim #1.

**Gotchas caught by local verification (reporting-relevant):**
- Current Docker Compose resolves relative bind-mount paths in override files
  against the PROJECT directory (first `-f` file), NOT the override file's
  directory — the old `./agents` comment claim no longer holds. All override
  mounts now use a required `${TRACE_SCRIPTS_DIR:?...}` env var that fails
  fast if unset. Any reproduction instructions (README, datasheet) must
  include `export TRACE_SCRIPTS_DIR=...`.
- jq on Windows (Git Bash) emits CRLF line endings: metric names picked up a
  trailing `\r`, silently producing `name^M.json.gz` files while Prometheus
  accepted the polluted query (CR = whitespace in PromQL) — so the run
  *looked* 100% successful. Fixed with `tr -d '\r'` in
  `download_metrics_full.sh`; harmless on the Linux VM but essential for
  cross-platform reproduction. Full re-verification after the fix:
  273/273 metrics, clean filenames, valid gzipped `query_range` JSON.
- Verified against the submodule (not just asserted): upstream
  `docker-compose.monitoring.yml` has NO cadvisor service (no collision with
  our override), upstream mounts its config at the same
  `/etc/prometheus/prometheus.yml` target (so the merge-by-target-path
  override works), and `prometheus-cadvisor.yml` is functionally identical to
  upstream's scrape config (diff: comments only) + the cadvisor job.
- Remaining Phase-0 verifications done in a clean session: collector 0.157.0
  end-to-end (OTLP/HTTP test span → `spans.jsonl`, one JSON object per line),
  byte-offset slice arithmetic (`tail -c +offset+1` exact, no off-by-one),
  `docker logs --since` honors our UTC format, clock-anchor snippet runs on
  Linux Python 3.12.

## Open items
- ~~Fold the three-tier coverage design into `msr-research.md` §3/M3~~ — done
  same day (§3/M3 tiers, §5 fault-target↔coverage alignment rule with
  `target_trace_visibility` ground-truth field, risk-table fallback updated,
  §8 records the submodule pin).
- ~~Phase-0 rig changes: OTLP file export via collector; logs dump; full
  Prometheus export; clock anchors~~ — drafted AND locally verified (§8).
  Remaining Phase-0 step: deploy on the GCP VM and hand-audit one
  fully-aligned run across all four modalities (needs the VM; not doable on
  the Windows dev machine — no LTTng).
- Vendor `models/` + `dataset/Dictionary.py` from `adaptive_tracer`.
- Decide venue split with mentor: study paper to MSR technical track vs FSE/EMSE.
- Name collision check for dataset name (FourSight / KODA / ModSense).
