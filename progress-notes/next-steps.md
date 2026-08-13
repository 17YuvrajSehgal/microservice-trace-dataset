# Next steps (updated 13-08-2026)

## State in one line
Agent results are now **leakage-controlled and fully auditable**: masked sanity gate =
**service 48% / fault 17% / both 9%** (RESULTS-agent-sanitygate-masked.md; 74/74/61 is RETIRED as
leak-inflated), every diagnosis has a full transcript, `audit_leakage.py` passes 23/23, artifact
bundle archived on `/project`. Cluster repo is on `master` (agentic-tracing was merged via PR #2).

## Do next
1. **Agent refinement (non-leaking), then ONE re-gate, then freeze:**
   - fault-type DEFINITIONS in the static system prompt (fixes taxonomy confusion: slow_db called
     "dependency_outage", noisy_neighbor called "cpu_throttling");
   - window-filter the logs/kernel tools (SS carts' chronic 59k-error storm distracts the agent;
     pre-existing tools.py issue that now costs accuracy).
   Do NOT tune per-incident against the gate (overfitting).
2. **Then the degradation sweep** (RQ1–RQ3), subsampled (blind-spot families × trace/kernel axes),
   login-node chunked via the `gate_masked_driver.sh` pattern, transcripts + auditor as standard.
   Budget note: 23 masked incidents ≈ 500k in / 14k out tokens per pass.
3. **Masking ablation is a result**: RCA_MASK_NAMES=0 vs 1 quantifies naming giveaways
   (~26 pts service / ~57 pts fault) — write it up for the paper; also note the statistical
   baseline still keys off stress NAMES (asymmetry favors the baseline → conservative).
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
