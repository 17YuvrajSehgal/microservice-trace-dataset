# Next steps (updated 13-08-2026, end of day)

## State in one line
**Agent v3 is leak-free, robust, and FROZEN for the sweep: service 83% / fault 48% / both 48%**
(RESULTS-agent-sanitygate-masked.md §0; leaky 74/74/61 RETIRED; weak-tools masked v2 was 48/17/9).
Every diagnosis fully transcripted, auditor PASS 23/23, bundles on `/project/…/artifacts/`.
Cluster repo on `master`. Cost: ~450k in / 9.2k out tokens per 23-incident pass, 13.5 calls/incident.

## Do next
1. **The degradation sweep (RQ1–RQ3) with the frozen v3 agent** — subsample first (blind-spot
   families × trace/kernel axes: `--grid kernel`, `--grid trace`, `compensate`), login-node chunked
   via the `gate_v3_driver.sh` pattern (per-family fresh python), transcripts + `audit_leakage.py`
   as standard practice on every batch.
2. **RQ2 trajectory analysis** — v3 trajectories are rich (topology-walking visible); compare full
   vs degraded once sweep data exists.
3. **Masking ablation writes itself into the paper**: leaky 74/74/61 → masked-weak 48/17/9 →
   masked-robust 83/48/48. Naming giveaways inflated fault-typing by ~57 pts; robust generic
   tooling recovered (and exceeded) the loss legitimately. Note the statistical baseline still
   keys off stress NAMES (asymmetry favors baselines → conservative for our claim).
4. SS kernel L2 derivation on Trillium (babeltrace 2.1.2 at `/scratch/yuvraj17/local-bt21`,
   remember the LD_LIBRARY_PATH override; update transfer/derive_l2_working_set.sh which still
   points at the old 2.0.4).
5. Naser gate (still open) + MSR deadlines: abstract Nov 5, paper Nov 10, 2026.

## Don't rediscover
- Masking: `RCA_MASK_NAMES=1` default; leakguard gives the injected-workload CLASS one alias/run
  (kernel says `aggressor`, metrics `anomaly-cpu-stress` — raw-name hashing fragments identity and
  cost 22 points in gate v1). Unmask happens before scoring.
- Transcripts: `evaluate.py --method agent` writes them automatically (`<out>_transcripts/`);
  `audit_leakage.py <results.json>` after every run; `bundle_artifact.py` to share.
- gpt-5.4 intermittently 400s `invalid_prompt` on telemetry-heavy turns — agent auto-retries.
- Gate driver: `agentic-rca/gate_masked_driver.sh` (per-family fresh python, resumable,
  watchdog-safe); status via `gate_status.sh`; report via `gate_report.py <results_dir>`.
- Cluster: `source transfer/env.sh` + `set -a; source .env; set +a`; agent = login node only.
