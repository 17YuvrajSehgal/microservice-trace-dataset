# CLAUDE.md

## What this repo is

**StrataTrace**: a four-modality observability dataset (metrics, logs,
distributed traces, **kernel traces**) collected from Sock Shop under
labeled fault injections, plus a per-task modality-ablation study (RCA,
anomaly detection, incident explanation, repair). Target: **MSR 2027** —
Data & Tool Showcase (abstract **Nov 5, 2026**, paper Nov 10) + a study
paper. The full research plan is `msr-research.md`; the pre-registered
fault→modality predictions are `fault_catalog.md`.

## How to write (required)

**Use simple, plain English. Keep it short.** No complicated words, no long
walls of text. Short sentences, one idea each. Answer first, then a few
supporting points. Prefer bullets and small tables over paragraphs. This
applies to chat replies AND to any document/report written for the user.

## Session habits (required, every session)

1. **Log research/method decisions** (with the *why*, selectively — not an
   activity log) in `progress-notes/DD-MM-YYYY/decisions.md` (day-first
   date; create the folder per day). Update `next-steps.md` at session end.
2. **Read the latest `progress-notes/` day first** to pick up state; this
   file only summarizes.
3. Commit and push at natural milestones (user expects work on GitHub).
4. `fault_catalog.md` predictions are pre-registered: after the Phase-2
   campaign starts they may only change via its §7 Amendment log — never
   edit the predictions in place.

## Current state (as of 2026-07-28)

- **PHASE 0 GATE PASSED** on the GCP VM `stratatrace-collector` (us-east1-b):
  all six modalities time-aligned on a real run (trace/logs/load/metrics/
  kernel 2.3M events/clocks 0.001 ms drift). Evidence + full debug log in
  `progress-notes/28-07-2026/`. Phase-2 collection is unblocked.
- **Fresh-VM fast path** (do NOT rediscover this session's bugs): after
  `git clone --recursive`, run `microservice-lttng-data-collection-scripts/
  vm_bootstrap.sh` (installs LTTng/Docker, builds the 2 images, brings up the
  7-file stack, health-checks) then `run_gate.sh gate01` (one-command
  collect+load+metrics+audit; expect six OK). Gotchas + fixes are in
  `microservice-lttng-data-collection-scripts/TROUBLESHOOTING.md`.
- The VM is currently STOPPED (disk persists). Restart:
  `gcloud compute instances start stratatrace-collector --zone=us-east1-d`.
  (Relocated b→d on 2026-07-28 when us-east1-b ran out of n2 capacity;
  recreated from a boot-disk snapshot, same name/machine type, data intact.)
- This session drove the VM directly via `gcloud compute ssh --command`; a
  separate on-VM Claude session is optional, not required.
- Tier-1 instrumented services live on fork branches
  (`17YuvrajSehgal/front-end@otel-instrumentation`,
  `17YuvrajSehgal/catalogue@otel-instrumentation`); built locally, verified
  emitting OTLP server spans. Build commands are in the overlay headers.
- 7 fault recipes in `microservice-lttng-data-collection-scripts/faults/`,
  mechanically verified; VM still owes intensity calibration
  (especially noisy_neighbor's "KPIs barely move" property), the F12
  per-container netem recipe, and `verify_injection.py` automation.
- The LMAT/JSS modeling stack (`microservice/` + vendored `models/`, `dataset/`) was
  **archived to `archive/lmat/` on 2026-08-08** (repo reorg) — no current agentic/dataset
  code imports it; kept intact + reversible for the JSS revision. The vendored copies
  (from adaptive_tracer @405e49e) remain the authoritative ones (VENDORED.md in each).

## Key technical facts (hard-won; do not rediscover)

- `microservices-demo/` is a **git submodule** of the pinned fork (upstream
  is frozen/deprecated). Clone with `--recursive`. Never edit it in place;
  service changes go via fork branches + the compose overlays.
- **Deployment = 7 compose `-f` files, order matters.** The full command
  with correct ordering is in the header of
  `microservice-lttng-data-collection-scripts/docker-compose.toxiproxy.yml`.
  `TRACE_SCRIPTS_DIR` (abs path to `microservice-lttng-data-collection-scripts`)
  MUST be exported — compose resolves relative bind mounts against the
  project dir, not the override file's dir.
- Java agents dual-export spans: `otlp` → collector → `otlp-out/spans.jsonl`
  (the dataset's trace modality) AND `logging` → docker logs → the
  otel-to-lttng.py UST relay (cross-layer clock bridge). Both must stay.
- **Toxiproxy sits permanently in the catalogue→catalogue-db path** (fault
  toggling must be restart-free); normal runs include it too. See the
  methodological note in docker-compose.toxiproxy.yml.
- `collect_trace.sh` needs sudo for the kernel LTTng session; it also
  captures per-run logs, slices the OTLP file by byte offset, and records
  (realtime, monotonic, boottime) clock anchors in every meta snapshot.
- Fault recipes write ground truth to `$FAULT_STATE_DIR`
  (default `~/fault-state`). Their docker-update restore paths work around
  real API traps (`--cpus=0` and `-m 0` are silent no-ops; memory limits
  cannot be cleared — details `faults/README.md` and progress-notes
  27-07-2026 §10). Verify restores against `/sys/fs/cgroup/*`, not
  `docker inspect`.
- Instrumented catalogue must run with `command: /app -port=80` (stock
  port); the fork Dockerfile's default is 8080 — overlays pin this.
- Node front-end: instrumentation activates via `NODE_OPTIONS`;
  `OTEL_NODE_RESOURCE_DETECTORS` is pinned (cloud detectors probe metadata
  endpoints and pollute traces off-cloud; keep the same list on GCP for
  span-stream consistency).

## Map

| Path | What |
|---|---|
| `msr-research.md` | The research plan (phases in §10) |
| `fault_catalog.md` | Pre-registered predictions, scoring rules, H1–H4 |
| `progress-notes/` | Daily decision log — **read latest day first** |
| `microservice-lttng-data-collection-scripts/` | All collection tooling: collect_trace.sh, overlays, faults/, audit_alignment.py, download_metrics*.sh, load_generator.py |
| `agentic-rca/` | **Agent research harness** (config.py + agent/tools/degrade/evaluate) — the primary track. Agent code only. |
| `transfer/` | Dataset staging/derivation/transfer scripts: extract_working_set, derive_l2_*, env.sh (cluster env), push/extract/fetch |
| `archive/lmat/` | Archived LMAT/JSS modeling stack (microservice/, vendored models/, dataset/, JSS review docs) — not used by current work |
| `archive/progress-snapshots/` | Superseded dated progress/update files (progress-notes/ is the live log) |
| `microservices-demo/`, `train-ticket/` | Submodules: pinned Sock Shop + Train Ticket app forks |
| `DOCS/` | JSS-era docs; some paths reference the old adaptive_tracer workspace (known drift) |
| `pdf_proofs_of_injection/` | Grafana evidence for the prior 148 GB release |

## Environment note

The dataset collection VM is a GCP Ubuntu 24.04 box with LTTng 2.15,
Babeltrace2, Docker 27+, and (historically) the Sock Shop deployment under
`~/microservices-demo`. All performance/overhead numbers for the paper come
from the VM only — never from laptops/WSL.
