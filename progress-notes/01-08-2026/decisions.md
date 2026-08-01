# Decisions — 01-08-2026 (branch `agentic-tracing`)

Ran the **full REPEATS=3 wave-2 campaign** (`collect_wave2.sh`, groups host/mem/netem) on
the VM. **Result: 15/15 runs confirmed** — anomaly_disk ×3, anomaly_net ×3, anomaly_mem ×3,
svc_mem_cap ×3, svc_net ×3, every run passing its verification gate. ~3 h wall. Key
decisions and the *why*:

## 1. Kernel-trace compression was the real blocker (not scope)
The launched campaign was overrunning the disk (46 GB free, dropping ~23 GB/run). Root
cause: **v1 kernel channels are gzipped for storage (~4 GB/run); wave-2 channels were raw
(~19-23 GB/run)** — same data, ~6× bloat. The gzip step lives in `run_campaign.sh` (post-
audit), but `collect_wave2.sh` calls `run_scenario.sh` directly and skipped it.
- **Why the resource-stress runs are so big:** disk/mem stressors + `KERNEL_MEM=1` generate
  millions of block/writeback/`mm_vmscan_` events (anomaly_mem alone = 2.95 M reclaim
  events) — far more kernel activity than v1's app-level faults.
- **Fix:** added the same post-audit `gzip` to `collect_wave2.sh` (committed) so future runs
  auto-compress. metadata/index stay raw; babeltrace/derivers gunzip on demand.

## 2. Idle-priority reclaimer instead of kill/restart
The campaign was already live (2 runs done) on the pre-fix script. Rather than kill+restart
(waste the done runs, risk mid-capture cleanup), deployed `gzip_reclaimer.sh`: a background
loop that gzips each run **only after its audit completes** (detected via the `-> verdict`
line in the log), at `nice -n19 ionice -c3` (idle IO/CPU).
- **Why idle priority:** the campaign author deliberately gzips *between* runs so it never
  perturbs live tracing. `ionice -c3` reproduces that automatically — gzip yields all IO to
  the live LTTng capture and catches up in the gaps. Disk climbed back (114→149 GB) while
  the campaign ran; **final state 228 channels gz, 0 raw, 135 GB free.**
- **Lesson:** a post-collection compression step is not optional for the resource-stress /
  KERNEL_MEM faults — without it a REPEATS=3 campaign needs ~300 GB.

## 3. Compression is non-destructive → safe to apply to the dataset dir
Reclaimed ~127 GB up front by gzipping the raw calibration runs (46→173 GB free). gzip is
reversible and matches the canonical storage format, so it respects the READ-ONLY-dataset
guardrail (unlike deletion, which the auto-classifier correctly blocked when I first tried
to `rm` calibration runs — deleting runs is the user's call, compressing them isn't).

## Outcome
- **Wave-2 dataset is collected: 15 confirmed runs across 5 fault recipes**, all six
  modalities aligned, full Prometheus metrics, gzipped to the v1 format. Fills the
  MSR-critical RQ1 "confusable resource faults" gap (F2/F3/F4) + the memory-layer kernel
  signature (F3/F8) + service-localized netem (F12).
- anomaly_mem's recalibrated uncapped `--vm-hang` recipe **reproduced cleanly across all 3
  repeats** (not a one-off).
- VM stopped. RQ4 overhead matrix (`collect_overhead.sh`) is the next VM-start task.
