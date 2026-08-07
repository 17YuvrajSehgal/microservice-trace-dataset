# Next steps — after 01-08-2026 (branch `agentic-tracing`)

## State
**Full REPEATS=3 wave-2 collected: 15/15 runs confirmed** (anomaly_disk/net/mem ×3,
svc_mem_cap ×3, svc_net ×3), gzipped to v1 format. VM `stratatrace-collector` (us-east1-d)
is **STOPPED**. Disk 135 GB free; 16 GB swap persisted in `/etc/fstab`. Dataset READ-ONLY;
snapshot `stratatrace-dataset-safe-20260729`.

New/changed this session: `collect_wave2.sh` (+post-audit gzip), `gzip_reclaimer.sh` (on VM
`$HOME`), `anomaly_mem.sh` (uncapped `--vm-hang` final recipe).

## Do first next VM start
1. **RQ4 overhead matrix** — `./collect_overhead.sh` (no LMAT model on VM → kernel-overhead
   baseline vs lttng_only; the headline RQ4 number). Stop the VM after.
2. **Optional: subtle group** — `REPEATS=3 ./collect_wave2.sh subtle` for the RQ5 near-
   threshold variants (anomaly_disk/mem subtle) if we want them in v2.
3. Sanity-check a couple of gzipped wave-2 runs decode cleanly end-to-end (gunzip → babeltrace
   → deriver), confirming the gz storage is analysis-ready.

## Decisions still owed to Naser (from `dataset-collection-gaps.md`)
- Memory tracepoints: keep the `KERNEL_MEM` augmented subset vs none.
- Full-Prometheus scope: whole label space vs expanded curated set.
- Wave-2 size: shipped 15 core runs — add subtle/RQ5 (+~6) or freeze at 15?

## Then — Phase 3 (dataset) + agentic (parallel)
- **Dataset:** L1 kernel-KPI deriver (Parquet) · L2 productionize `wait_attribution.py` ·
  L3 NL digest · loader SDK (`stratatrace`) · coverage matrix · Tier-2 trace status.
- **Agentic:** wire the 5th skill (cpu-saturation → 5/5) · adaptive-tracing skill · validate
  `applog_source.py` bt2 wrapper · compound-fault stress-test.

## Guardrails (unchanged)
- `fault_catalog.md` predictions FROZEN — amend only via §7.
- `verification_targets.json` IS tunable (QC gate).
- Dataset analysis READ-ONLY on `~/traces`; compression is OK (reversible), deletion is the
  user's call. VM costs money — stop when idle.
- Wave-2 runs balloon raw (~20 GB); **always keep the gzip step** (in `collect_wave2.sh` now).
