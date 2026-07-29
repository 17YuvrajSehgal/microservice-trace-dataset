# Phase-2 collection campaign COMPLETE (28-07-2026)

**40/40 runs collected. StrataTrace v1 dataset exists.**

## Result
- **40 runs, 164 GB** on the VM (curated kernel gzipped ~3 GB/run + OTLP
  ~1.5 GB + logs + UST + metrics; ~4.6 GB/run).
- **34 fault runs: 31 confirmed + 3 borderline; 6 normal runs.**
  Every fault verified as pre-registered — ZERO genuine failures.
- Final manifest: `campaign_manifest_final.csv` (this dir), regenerated from
  the bundles' verification.json (accurate verdicts).

## Verdicts by fault (all matrix cells)
| Fault (aggressive/steady ×3 unless noted) | Verdict | vs prediction |
|---|---|---|
| slow_db | confirmed ×3 | ✓ app-signal |
| error_storm | confirmed ×3 | ✓ app-signal |
| svc_cpu_cap | confirmed ×3 | ✓ (throttle→latency pivot) |
| svc_mem_cap | confirmed ×3 | ✓ limit-drop |
| queue_backlog | confirmed ×3 | ✓ (beat metrics-weak prediction) |
| noisy_neighbor | confirmed ×3 | ✓ neighbor active, KPIs flat |
| anomaly_cpu | confirmed ×3 | ✓ host CPU |
| dependency_outage | **borderline ×3** | ✓ metrics-weak by design (kernel/traces win) |
| noisy_neighbor subtle | confirmed ×2 | ✓ RQ5 |
| slow_db subtle | confirmed ×2 | ✓ RQ5 |
| svc_cpu_cap subtle | confirmed ×2 | ✓ RQ5 (post NaN-fix, in-line) |
| slow_db burst | confirmed ×2 | ✓ RQ5 |
| error_storm burst | confirmed ×2 | ✓ RQ5 |
| normal | n/a ×6 | (steady ×3 + burst ×3 reference) |

## Bug caught + fixed mid-campaign
verify_injection read svc_cpu_cap aggressive as 'unconfirmed' (histogram_quantile
returns NaN for a sparse baseline window; unfiltered NaN poisoned baseline_mean).
Fixed (filter non-finite samples), pushed, pulled on VM → subsequent runs
(svc_cpu_cap subtle) confirmed in-line; the 3 aggressive bundles re-verified to
confirmed. Collection was never affected — only the verdict.

## Infra events during the campaign
- VM relocated us-east1-b → us-east1-d (b ran out of n2 capacity); snapshot +
  recreate, same name/machine/data. Kernel/lttng/overlay2/stack all healthy.
- Disk resized 200→500 GB (SSD quota max); old us-east1-b disk deleted.
- gzip-per-run kept footprint at 164 GB (half the disk) despite ~9 GB raw
  kernel/run.

## Next (post-campaign)
- Package the release: gzip OTLP (~1.5 GB/run → ~200 MB) for the Full tier;
  build the Lite tier (L1–L3 kernel + app modalities, ~20–30 GB).
- Build the kernel L1–L3 derivers (representation ladder) against these bundles.
- Then the study (Phase 3): run T1–T4 × modality subsets over the 40 runs.
- Mentor: venue split, StrataTrace name, pre-registration freeze (now that the
  campaign is collected, the fault_catalog predictions are effectively frozen —
  amendment log only from here).
- VM STOPPED after the campaign (data persists). Snapshot deleted.
