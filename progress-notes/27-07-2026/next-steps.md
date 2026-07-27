# Next steps — as of 27-07-2026

## 1. Phase-0 gate (immediate, needs the GCP VM)
Deploy the extended stack and hand-audit one fully-aligned run. This is the
single item between us and Phase 1 (msr-research.md §10 gate).

On the VM:
1. `git pull` + `git submodule update --init` (rig changes + submodule are on
   GitHub as of commit 5aa35b4).
2. Bring up the extended stack:
   `export TRACE_SCRIPTS_DIR=~/microservice-trace-dataset/microservice-lttng-data-collection-scripts`
   then the four `-f` compose files per the usage headers in
   `docker-compose.metrics.yml` / `docker-compose.otel.yml`.
3. Pre-tracing sanity checks: spans appear in `otlp-out/spans.jsonl` while
   clicking through the front-end; `container_*` series in Prometheus
   (cAdvisor up); otel-collector in `docker ps`.
4. Run one 30 s sample (`sample_normal.sh` pattern), then audit ONE request
   end-to-end: load-generator CSV row → OTLP span tree → log lines →
   metrics window → kernel syscalls via the pid↔container join
   (meta snapshots). Audit passes ⇒ Phase 0 complete.

Prep that can be done before the VM session (offered, not yet started):
- **Audit helper script**: input = run dir + trace_id (or auto-pick slowest
  request from load CSV); output = matching records from all four modalities
  side by side with timestamps. Later evolves into the loader SDK's
  alignment test.
- **VM runbook**: steps 1–4 as a mechanical checklist file.

## 2. Parallel items (no VM needed)
- Vendor `models/` + `dataset/Dictionary.py` from the `adaptive_tracer`
  checkout into this repo (T1 baselines cannot run without them).
- Mentor conversation: venue split for the study paper (MSR technical track
  vs FSE/EMSE) + sanity pass on msr-research.md. Blocking the paper split,
  nothing else.
- Dataset name collision check (FourSight / KODA / ModSense) before the name
  leaks into file paths and docs.

## 3. After the gate — Phase 1 opens
- Fault catalog recipes 5–12 (Toxiproxy slow-DB, docker-update caps,
  per-container netem, dependency pause, error storm, queue backlog,
  noisy neighbor).
- `ground_truth.json` + `verify_injection.py` + subtle-intensity calibration.
- Pre-registered fault→modality prediction table (`fault_catalog.md`).
- Tier-1 instrumentation (front-end Node auto-instr, catalogue Go otelhttp)
  can start any time — needed before the full campaign, not before the audit.

## Pacing check
Today Jul 27; MSR abstract Nov 5. Plan budgets Phase 0 through week 2 —
VM audit this week keeps us on schedule.
