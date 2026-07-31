# Next steps — after 31-07-2026 (dataset wave-2, branch `agentic-tracing`)

## State
Wave-2 collection is **built, validated, and 4/5 faults confirmed end-to-end.** The
collection machinery (six-modality alignment, full metrics, `KERNEL_MEM`, overhead wrapper)
is proven. VM `stratatrace-collector` (us-east1-d) is **STOPPED**; 16 GB swap added +
persisted in `/etc/fstab`; dataset READ-ONLY, snapshot `stratatrace-dataset-safe-20260729`.

Key files this session: `dataset-collection-gaps.md`, `todolist-31-07-2026.md`,
`faults/anomaly_{disk,mem,net}.sh`, `faults/svc_net.sh`, `faults/verification_targets.json`,
`collect_wave2.sh`, `collect_overhead.sh`, `collect_trace.sh` (KERNEL_MEM knob).

## Do first next VM start
1. **Confirm `anomaly_mem` with the `--bigheap` recipe** — one run
   `KERNEL_MEM=1 ./run_scenario.sh anomaly_mem aggressive anomaly_mem_bigheap_r1 200`.
   Expect MemAvailable < the 0.25-ish gate this time (reclaim tracepoints already fire).
   If the cgroup-capped container still under-fills, fall back to a tmpfs fill (dead-simple,
   bounded) — noted in the recipe header rationale.
2. **Full wave-2 at REPEATS=3** — `./collect_wave2.sh` once anomaly_mem is green. Gives the
   per-fault variance the paper needs. Then **stop the VM.**
3. **RQ4 overhead matrix** — `./collect_overhead.sh` (no LMAT model on VM → kernel-overhead
   measurement; fine for the baseline vs lttng_only headline).

## Decisions still owed to Naser (from `dataset-collection-gaps.md`)
- Memory tracepoints: augmented subset (current `KERNEL_MEM`) vs none.
- Full-Prometheus scope: whole label space vs expanded curated set.
- Wave-2 size: full ~30 runs vs lean must-only (~20).

## Then — Phase 3 (dataset) + agentic (parallel)
- **Dataset:** L1 kernel-KPI deriver (Parquet) · L2 productionize `wait_attribution.py` ·
  L3 NL digest · loader SDK (`stratatrace`) · coverage matrix · Tier-2 trace status.
- **Agentic:** wire the 5th skill (cpu-saturation → 5/5) · adaptive-tracing skill (feedback
  loop) · validate `applog_source.py` bt2 wrapper · compound-fault stress-test (the gap that
  becomes a paper contribution).

## Guardrails (unchanged)
- `fault_catalog.md` predictions FROZEN — amend only via §7, never in place.
- `verification_targets.json` IS tunable (QC gate, not a prediction).
- All dataset analysis READ-ONLY on `~/traces`; work copies in `~/mvp_work/`, live in
  `~/mvp_captures/`. VM costs money — stop when idle.
