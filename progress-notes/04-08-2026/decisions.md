# Decisions — 04-08-2026 (branch `agentic-tracing`)

## Batch L1+L3 re-derivation across all runs — COMPLETE + clean

Ran the full clean re-derivation (after the shell-wrapper TGID fix + system-collapse) with a
proper pre-flight and an auto-stop watcher. Outcome:

- **46/46 runs OK, 0 failures.** Batch ran ~10.5 h (01:55→12:18 UTC), concurrency 2. Every
  real run now has fresh `kernel_l1.parquet` + `kernel_l3.jsonl` with the corrected mapping.
- **Quality sweep across all 46 parquets:** service count 16 (×32) / 17 (×14) — tight, no
  outliers; **java split present in 46/46** (carts + orders as distinct services);
  `kernel` + `system` buckets in 46/46; **0 runs** with >25 services or leftover
  `system:<comm>` noise. The fix + collapse held across every fault family.
- **Auto-stop worked:** guest-shutdown watcher fired on the `BATCH DONE` marker
  (`DONE_marker=1 ok=46 fail=0`) → VM TERMINATED at 12:19, no idle billing. Outputs persisted
  on the boot disk; started briefly only to read the tally + run the sweep, then stopped again.

### How we got here (this session)
1. Spotted that the first batch left `n_services`≈100–150 (raw `system:<comm>` proliferation)
   and was re-deriving 4 superseded calibration runs. User chose to redo it clean rather than
   post-process the dataset.
2. **`--collapse-system`** (default on): fold non-container host processes → one `system`
   bucket; real services + `kernel` (kswapd/F3 actor) + known comms preserved. Offline-tested.
3. **Excluded** the 4 anomaly_mem calibration runs (bigheap/fix/swap/vmhang) in the batch glob;
   empty `normal/gate01` auto-excluded (no ground_truth).
4. **Full pre-flight** before relaunch: code version, deps, 46-run inventory, disk headroom,
   and an **end-to-end smoke test** on the smallest run (svc_cpu_cap → 16 clean services)
   — only then launched the 46-run batch.
5. Wiped stale pre-fix outputs first (derived artifacts, not the dataset), seeded the manifest
   with the smoke run, launched detached (`setsid`), recorded the PGID for clean shutdown.

### Notes carried forward
- **Ops:** killing/heavy SSH commands intermittently 128'd under derive load; used the process
  **group** (PGID) to kill the batch cleanly, and ran launches as minimal standalone commands.
- **Cosmetic:** the progress manifest writes event counts with thousands-commas, breaking that
  one CSV column's field alignment (the *log* is the source of truth). Tidy next script touch.
- **Deriving is expensive:** every trace is 100–370 M events (~18–38 min/run). Full 46-run
  batch ≈ 10.5 h at concurrency 2. Unavoidable at full fidelity; run unattended.

## State
Kernel representation ladder is **fully derived for the whole dataset**: L0 (raw CTF, gz) +
**L1 (46 KPI parquets)** + **L3 (46 NL-digest jsonl)** + L2 engine validated (per-run L2 is
on-demand, scoped). Loader validated. VM STOPPED.
**Next:** package the derived tiers + the modality-ablation study (which modality wins per
fault), and the agentic 5th-skill/compound-fault work.
