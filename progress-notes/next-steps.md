# Next steps (updated 16-08-2026, post-campaign)

## State in one line
**v4 campaign DONE and analyzed** (102 runs, $1.80, auditor PASS 102/102):
**S0b (Context Builder brief, no skills) is the configuration of record — 87/61/57 at 9 calls
and $0.01/incident**; skills are net-negative until the selector is redesigned (db-edge pull on
shared-datastore apps, 15/23 selection); S2 shows distractor skills cost ~18 pts on unseen
faults (honest negative result). Full write-up `agentic-rca/RESULTS-v4-campaign.md`; artifacts
+ pre-campaign archive on `/project/…/artifacts/`. Branch `new-agentic-architecture`; v3 stays
frozen on `master` for the degradation sweep.

## Do next
1. **Selector redesign** (the single blocking component for skills): candidates —
   two-stage selection verifying each candidate's discriminator checks against SIC claims
   before committing; an architecture prior discounting ubiquitous datastore edges; skip
   injection below a confidence threshold. Iterate CHEAPLY via selector-lab replay over the
   102 saved survey digests (no agent runs) before paying for any re-campaign.
2. **Mechanism-correct secondary metric** in analyze (error_storm→dep_outage ×7 etc. describe
   the injected mechanism accurately) — zero API cost, changes the fault-gap story.
3. **Degradation sweep (RQ1–RQ3) on frozen v3 (master)** — unchanged plan, subsampled,
   independent of the v4 skill story; needed for the MSR paper.
4. Report to supervisor: as-built diagram (new_design.md §2b) + campaign table + the two
   headline claims (Context Builder win; skills-need-selection negative result) + open
   questions §7.
5. MSR deadlines: abstract Nov 5, paper Nov 10, 2026.

## Don't rediscover
- Campaign driver/status/report/cost tooling all committed in agentic-rca/ (campaign_driver.sh,
  campaign_status.sh on cluster, campaign_report.py, cost_report.py, v4_report2.py).
- Cost: ~25k in (50-68% cached) + ~500 out per incident; ~$0.01-0.02/incident at GPT-5 proxy
  rates; whole 102-run campaign = $1.80. Time ~2.5 min/incident sequential, login node only.
- wsl→ssh quoting eats `$(...)`/`$var` — ALWAYS install cluster scripts via
  `wsl ssh trillium 'cat > path' <<'EOF'` stdin heredoc (bit us three times).
- Old results all archived: `/project/…/artifacts/results_pre_campaign_20260816.tar.gz` +
  per-gate bundles; campaign artifact `artifact_campaign_20260816.tar.gz` (102+102, manifest).
