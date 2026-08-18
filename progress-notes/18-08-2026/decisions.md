# Decisions — 18-08-2026

## RQ1 COMPLETED on the agent: metric + log axes (161 diagnoses, $1.53, auditor PASS 161/161)
`mlsweep_driver.sh` ran both axes on frozen v4-s0b. **Metric** (5s→60s scrape): both 43-52%,
non-monotonic, flips balanced both directions — flat within noise (window-level rates need only
two samples per counter). **Log** (ALL→ERROR): 57/43/52, ERROR beats WARN — flat within noise
(the error-rate-change tool keys on ERROR-class signatures, which survive the filter by
construction). Tool mixes constant. Recurring fragile incident: SS svc_mem_cap (also A/A
flip-prone → no strong claim). `RESULTS-agent-metric-log-sweeps.md`; artifact on /project.

**Consolidated RQ1 answer (all four axes measured):** NO degradation cliff at standard
operational ranges — traces→5%, metrics→60s, logs→ERROR, kernel→none(-4) all within the ±9-pt
band. Structural reason: aggregate-level evidence consumption + cross-modal redundancy. The
pre-registered cliff expectation resolves as a ROBUSTNESS result; the qualitative exception
stands (kernel L1-only worse than none — representation > presence). RQ4 corollary: dramatic
observability-budget cuts (5% traces / 60s metrics / ERROR logs) cost nothing for agentic RCA;
kernel pays via -25% tool calls + db-typing.

Note: the mlsweep launch initially failed twice — expired ssh master (Duo re-auth by Yuvraj)
and a nohup redirect into a not-yet-created directory (mkdir now precedes launch in the pattern).

Remaining: modality-removal conditions (MLT_noK/MLK_noT), kernel × trace interaction grid,
RQ4 Pareto join, repeats for paper figures.
