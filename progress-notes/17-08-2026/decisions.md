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
