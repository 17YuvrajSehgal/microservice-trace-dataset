# Decisions — 02-08-2026 (branch `agentic-tracing`)

Ran the two "immediate" post-wave-2 tasks: **RQ4 collection-overhead** and a **decode
sanity-check** on the gzipped dataset. Both done; VM stopped after.

## 1. RQ4 overhead — measured, with a warmup-artifact caught and fixed
`collect_overhead.sh` (fair rotated baseline / lttng_only; no LMAT model on VM → the
kernel-tracing headline). 200 users.

- **First pass (3 repeats, `warmup=0s`)** gave a *nonsensical* result: lttng_only P95 **lower**
  than baseline (−27.6%), because the baseline P95 was 65.7 **± 31.2 ms** — one cold first
  baseline run spiked and inflated the mean. The signal was below the noise floor.
- **Root cause + fix:** `baseline_load.sh`/`lttng_only_run.sh` support `WARMUP_DURATION`
  (default 0). Re-ran with **`WARMUP_DURATION=30 REPEATS=4 DURATION=120`** so every measured
  run is preceded by warmup load → cold-start removed.
- **Clean result (the one to cite):**
  | | baseline | lttng_only | overhead |
  |---|---|---|---|
  | Throughput (req/s) | 194.2 ± 0.5 | 193.3 ± 0.3 | **−0.5%** |
  | P95 (ms) | 45.1 ± 2.0 | 50.7 ± 2.0 | **+12.6%** |
  | P99 (ms) | 244.9 ± 16 | 259.5 ± 25 | **+6.0%** |
  | error rate | 2.53% | 2.54% | flat |
  Baseline P95 std collapsed **±31 → ±2 ms** with warmup, so the +12.6% P95 is now a
  *resolved* difference (~2.8σ), not noise. **Headline: kernel tracing ≈ 0.5% throughput
  cost + ~13% P95 latency at 200 users** — a modest, well-characterized overhead (the "rare
  asset" no peer dataset ships).
- **Lesson:** always warm up before a latency-overhead measurement; a single cold run at
  low repeats destroys the P95/P99 estimate. Results: `~/experiments/overhead_wave2_clean/`
  (first pass kept in `overhead_wave2/` for the record).

## 2. Decode sanity-check — gz storage is analysis-ready
Confirmed the gzipped wave-2 runs decode end-to-end (gunzip → babeltrace) after the
compression pass:
- `anomaly_disk` r1: **45.7 M events** decoded, metadata present, `mm_vmscan_`=0 (correct —
  KERNEL_MEM=0).
- `anomaly_mem` r1: **46.2 M events** decoded, `mm_vmscan_`=8.7 K in a 120 s sample (correct —
  KERNEL_MEM=1; matches the full-run 2.95 M reclaim events).
- **Verdict:** gz channels + raw metadata/index round-trip cleanly; the dataset is
  analysis-ready in its stored (compressed) form. Derivers/loaders just gunzip on demand.

## Outcome
Data-collection phase is **complete**: v1 (40 runs) + wave-2 (15 confirmed) + RQ4 overhead,
all gzipped/verified. Next is the derived-layer work (L1/L2/L3, loader SDK) that unblocks the
modality-ablation study. VM stopped.
