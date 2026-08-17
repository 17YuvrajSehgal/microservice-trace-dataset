# Decisions — 17-08-2026

## Campaign 2 (SS-L2, data-only re-run) DONE + analyzed — L2 within noise on SS; variance quantified
102 runs, agent byte-identical to campaign 1, SS now with kernel_l2 (verified reaching the agent:
wait_attribution in 48/48 SS transcripts). Auditor PASS 102/102; $1.81 proxy-rate; artifact
`artifact_campaign2_20260817.tar.gz` on /project (md5-verified). Full table in
RESULTS-v4-campaign.md ("Campaign 2" section; comparison via `compare_campaigns.py`).

**Finding 5:** paired flips SS 5/48 vs A/A control TT 9/44 → SS's changes sit BELOW the noise
floor measured on unchanged data ⇒ **no measurable aggregate L2 accuracy effect on the
per-service-datastore app** (L1+L3+topology already suffice there; L2's unique value was shown on
the shared-datastore app). Suggestive only: 2/3 SS up-flips are noisy_neighbor. **Methodological
headline: single-run condition aggregates carry ±~9 pts (TT A/A ~20% cell flip rate) — repeats
are mandatory for any per-condition claim in the paper.** This retroactively explains part of
campaign-1's TT S1 slump.

Dataset milestone stands regardless: both apps at L1+L2+L3 parity — RQ3's kernel-tier
degradation conditions are now runnable symmetrically.

## KERNEL-TIER SWEEP ON THE AGENT RUN + ANALYZED (RQ3; 92 diagnoses, $0.82, auditor PASS 92/92)
First agent-side kernel ablation (config of record: brief on, skills off; kAll/kL1/kL3/kNone × 23).
Results: kAll 83/61/61 @9.1 calls · kL1 74/48/43 · kL3 78/57/57 · kNone 78/57/57 @12.2 calls.
`RESULTS-agent-kernel-sweep.md`; artifact on /project. Four findings:
**K1** with v4's cross-modality tools, full kernel removal costs only ~4 pts (within noise) at
FULL telemetry but +34% tool calls — kernel's robust value here = EFFICIENCY, not rescue (contrast:
baselines can't use kernel at all). **K2** the one stable kAll→kNone loss is SS slow_db Y→svc-only:
wait attribution is what supplies the db_latency TYPING (the pre-registered mechanism, in miniature).
**K3 (surprise)** kL1-only is WORSE than kNone (−14 both; loses 4 families, gains 0): raw KPIs
without L3 framing / L2 waits pull the agent into kernel-noise chases — representation quality >
kernel presence. **K4** kernel-decisive families hold 85% svc in every tier — v4's limit_signals/
peer-edges/host tools absorbed the blind-spot signal ⇒ **H2 not confirmed at full telemetry in v4**
(record via fault_catalog §7 amendment; re-test under the kernel × degraded-traces interaction,
where kernel value should grow — that interaction is the remaining RQ1×RQ3 experiment).
