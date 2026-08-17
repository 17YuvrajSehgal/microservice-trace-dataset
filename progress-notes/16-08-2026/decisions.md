# Decisions — 16-08-2026

## As-built architecture diagram added to new_design.md §2b
Mermaid diagram of the current system (built components only), color-mapped to the supervisor's
requirements diagram, with a legend of what maps 1:1, what's partial, and what's absent.

## Mined all 71 old runs (zero API cost) → readiness verdict + 3 boundary fixes (f242957)
Question (Yuvraj): learn from old runs or go straight to the full run? Mined every results dir
(gate_v3 + all v4 rounds): selector confusion matrix, svc-right/fault-wrong evidence audit,
repeat-variance, trajectory stats, skill-influence table.

**Going well:** host-family selection 7/7, svc_cpu_cap + dependency_outage 3/3; selection quality
gates outcome (sel_ok → both 8/11; sel_wrong → both 3/14 — the lever, quantified); brief mode ~11
calls vs 18–20 for skills-without-brief; Azure prompt cache already covers 68% of input tokens
(~25k in / 500 out per incident → full S0/S1/S2 campaign ≈ 1.7M in, cheap; the degradation sweep
is the only expensive item).

**Systematic failures (≥2–3 repeats each) → three generic skill-boundary fixes applied:**
1. svc_mem_cap → frozen-dependency (3/3): silence-direction missing — frozen = callers keep
   TRYING (timeouts toward it); callers quiet too = starved victim, look upstream.
2. noisy_neighbor → cpu_saturation/throttling (×3): the co-tenant is itself CPU-capped, so
   limit_signals shows ITS throttle → rule: throttled container with NO call-path edges = co-tenant.
3. anomaly_net → disk_io (×3): block-LATENCY wobble read as disk — rule: disk_io requires
   throughput/io_time rise, latency percentiles alone prove nothing.
NOT chased: error_storm → dependency_outage (agent mechanism descriptions are accurate — injected
connection resets; handle as a mechanism-correct secondary metric in analysis, not skill edits).

**Also answered (16-08, cost design):** more skills = no (coverage complete; selection is the
bottleneck); more agent observability = capture already 100% (and Azure chat completions return
zero hidden-CoT — Responses API not worth the behavior risk); MCP = interface, zero accuracy
effect, defer.

## CAMPAIGN RUN + ANALYZED (102 runs, $1.80 proxy-rate total, auditor PASS 102/102)
Pre-flight: archived the ENTIRE old results tree (433 files) to
`/project/…/artifacts/results_pre_campaign_20260816.tar.gz` (md5-verified) then cleaned
`results/` → `results/campaign/{s0,s0b,s1,s2}`. Added `cost_report.py` (post-hoc $ per incident
from transcript usage incl. cache split; configurable rates) + `campaign_driver.sh` (committed).

**Headline (RESULTS-v4-campaign.md):** S0 83/57/57 @15.2 calls · **S0b 87/61/57 @9.0 calls,
58% less input — the winner** · S1 (skills+brief) 78/43/43 · S2 (LOFO) 70/39/39.
Findings: (1) **Context Builder validated** — best accuracy at lowest cost; ship S0b.
(2) **Skills net-negative as selected** — entirely TT (shared-datastore db-edge pull: 5/8
misselections = db-latency-rca); skill content works where selection is right (SS noisy_neighbor
fixed ONLY by skill; TT dep_outage stable-Y 3/3) → the selector is the single blocking component.
(3) **S2 negative result**: abstention 3/23; agent override limits damage to −18 pts vs floor —
distractor skills actively mislead; honest deployment advice = S0b for unknown faults.
(4) Fault-gap concentrates on 3 label boundaries (error_storm→dep_outage ×7 with accurate
reset-mechanism descriptions; noisy_neighbor→cpu_* ×6; svc_net→db_latency ×4) → mechanism-correct
secondary metric would credit most. (5) Repeats: TT slow_db stable-WRONG under S1 (0/3; earlier
one-off not reproduced); TT dep_outage stable-right in S1+S2.
Artifacts: `artifact_campaign_20260816.tar.gz` on /project (102+102, sha256, md5-verified).
Also fixed bundle_artifact arcname collisions across condition dirs (first bundle silently
deduplicated same-named files — 31/102; refuse-worthy trap, now parent-dir-prefixed).

## SS kernel L2 DERIVED — dataset gap closed, NO VM (job 2132315, 1h36m, 50/50)
Ran the fixed `transfer/derive_l2_working_set.sh` (babeltrace 2.1.2 first in PATH/LD_LIBRARY_PATH —
the old 2.0.4 lib otherwise shadows it; plus new working-set-only guard) as a compute-node Slurm
job. All 50 SS working-set fault runs now have `kernel_l2.jsonl`. Spot-check is textbook:
SS slow_db → catalogue-db (mysqld, 517 TIDs) off_cpu_io_wait **100%**, verdict external — the
same signature that cracked TT slow_db. **Both apps now L1+L2+L3**; the RQ3 SS-side data gap is
closed. (L2 rows still carry fault_name/fault_target QC columns — tools whitelist unchanged.)

## Campaign 2 LAUNCHED (Yuvraj): identical 102-run design, SS L2 included
Same code (agent untouched since campaign 1 — only bundler/L2-script/driver-env commits), same
conditions/repeats, out → `results/campaign2/`. This is a clean **data-only (Axis A) comparison**:
campaign2 vs campaign1 SS side = the value of L2 wait-attribution; TT side (data unchanged) =
a free A/A run-to-run variance measurement at n=23×4.

## Campaign design (as executed)
- **Primary skill condition = skills+brief** (never tested together; brief removes the re-survey
  the verify-first step forces → expect ~40% cost cut in skills mode and same/better accuracy).
- Repeats r=3 ONLY on the 5 flip-prone incidents found by the variance audit (tt_slow_db,
  tt_dependency_outage ×2 configs, tt_svc_cpu_cap, ss svc_mem_cap-brief); r=1 elsewhere.
- Conditions: S0 (off), S0+brief, S1(=skills+brief), S2 LOFO(+brief) over the 23 gate incidents.
- Analysis adds a mechanism-correct secondary metric (label-strict remains primary).
