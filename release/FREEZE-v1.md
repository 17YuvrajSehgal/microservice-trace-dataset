# StrataTrace v1 — dataset freeze record

**Frozen 2026-08-04.** This records what the v1 dataset contains, that it is complete, its
known limitations, and how it is preserved. Machine-readable inventory: `DATASET_MANIFEST.csv`.
Per-service modality coverage: `COVERAGE_MATRIX.md`.

## What v1 is
Sock Shop under labeled fault injection, four modalities time-aligned + the kernel
representation ladder derived. **46 runs**, 12 fault types across 5 families, plus RQ5
intensity (subtle) and workload (burst) variants.

| Family | Faults | Runs |
|---|---|---|
| A — host resource | anomaly_cpu, anomaly_disk, anomaly_mem, anomaly_net | 12 |
| B — service resource | svc_cpu_cap, svc_mem_cap, svc_net (carts) | 11 |
| C — application | error_storm (catalogue), slow_db (catalogue-db) | 12 |
| D — dependency | dependency_outage (payment), queue_backlog (queue-master) | 6 |
| E — infrastructure | noisy_neighbor | 5 |
| **Total** | **12 fault types** | **46** |

## Completeness (audited 2026-08-04)
- **All 4 modalities + derived layers present in 46/46 runs**, zero gaps: metrics (incl.
  cAdvisor per-container, 432 series/run), logs (15/15 containers), traces (OTLP spans),
  kernel L0 (gz CTF), **L1 (KPI parquet), L3 (NL digest)**, ground_truth, verification, load
  CSV, meta (clock anchors + docker-top snapshots).
- **Verification: 43 confirmed · 3 borderline · 0 unconfirmed.** Borderline = the 3
  `dependency_outage` runs (released, but excluded from canonical splits per plan §6).
- Kernel L0 total ≈ **109 GB** (gzipped). Full traces on disk ≈ 246 GB (kernel + logs +
  spans + UST).

## Known limitations (for the datasheet — stated, not silent)
1. **Trace coverage = 6 of 14 services** (Java-4: carts/orders/shipping/queue-master +
   Tier-1: front-end/catalogue). **Tier-2 `user` + `payment` are NOT trace-instrumented** —
   deliberate blind spots (plan §3/M3). This is a *design variable* (tests whether
   kernel/logs/metrics compensate where traces are blind), documented in `COVERAGE_MATRIX.md`.
2. **The 3 `dependency_outage_payment` runs are borderline.** The fault (pause payment) is
   real and its effects are in the data, but `verify_injection` didn't clear the confirmed
   threshold on its declared target metric — likely because payment is a trace/metric blind
   path. **Action item:** review the verification target for this recipe (fix the check or
   record why borderline is expected); does not block the freeze.
3. Single host, synthetic (labeled) faults — explicit scope per plan §12; multi-host + a
   second app are future work.

## How v1 is preserved
- **Disk snapshot: `strata-v1-freeze-20260804`** (GCP, boot disk `strata-boot-us-east1-d`) —
  the authoritative frozen copy of `~/traces` + sibling `*_metrics`/`*_load.csv`. Supersedes
  the stale `stratatrace-dataset-safe-20260729` (pre-wave-2, pre-derivation).
- **Code:** git tag `strata-v1-freeze` on branch `agentic-tracing` (collection scripts,
  fault recipes, `stratatrace` deriver+loader package, fault_catalog predictions).
- `DATASET_MANIFEST.csv` (this dir) is the run-level index committed to the repo.

## Not yet done (release packaging — the path from "frozen" to "citable")
These do not change the data; they package it (plan §8):
- [ ] Datasheet (Gebru et al.) + `COVERAGE_MATRIX.md` finalized (matrix drafted here).
- [ ] Canonical train/val/test splits (exclude the 3 borderline from canonical).
- [ ] Lite tier (L1–L3 + M1–M3 + ground truth, no L0 — far smaller) + Full tier (with L0).
- [ ] Zenodo DOI + checksums; pinned service images to GHCR; `pip install stratatrace` finalize.
- [ ] Review the dependency_outage verification target (limitation #2).

## What the freeze unblocks
The dataset is stable and safe to build on. New collection efforts (the agentic M5 track;
optionally a second app) can proceed without risk to v1 — this snapshot + tag is the
rollback/reference point.
