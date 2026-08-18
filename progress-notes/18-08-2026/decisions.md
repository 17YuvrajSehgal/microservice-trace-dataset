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

## FINAL SWEEPS: interact + removal (138 diagnoses, $1.35, auditor PASS 138/138) - DEGRADATION PROGRAM CLOSED
Interact (kernel x thinned traces): NO kernel compensation under thinning - DiD +4 (full) -> -18
(t025) -> 0 (t010); kernel-decisive families show no kernel edge at any retention; kernel-blind
costs +1.5-2 calls at every level. t025 weak in EVERY sweep containing it: deterministic sampler
keeps the same spans per run -> one unlucky sample recurs (seeding artifact, reported not averaged).
Removal: MLT_noK 78/48/48 replicates kNone (free A/A through a different code path);
**MLK_noT (no traces) = FIRST modality loss that hurts: 70/48/43, +74% calls, losses concentrated
on TT path-shaped faults; SS slow_db stays FULLY correct on kernel wait-attribution alone ->
kernel compensation demonstrated in its pre-registered direction under LOSS, not thinning.**
H2 refined accordingly. Dead-tool thrashing repeats (~37% calls to empty traces/topology) ->
generalize the definitive-unavailable answer to all modality tools (post-program engineering).
Docs: RESULTS-agent-interact-removal.md; paper 05/06/09 + tracker updated; artifact on /project.
Cross-model replication remains blocked on a non-Azure API key (.env has Azure only).
Program totals: ~600 audited diagnoses, ~$6.

## RQ4 BUDGET SWEEP + all remaining analyses DONE (46 diagnoses $0.40; frees the paper)
lean (5%tr+60s+ERROR): 78/48/43 @7.6 calls, 24.5MB touched = **57x less telemetry, >=90% of full
localization; fault typing is the budget-sensitive component**. minimal (lean-kernel): 83/43/39 @
12.1MB (115x) - localization INTACT without kernel at 1/115th the data. Curio: TT slow_db fully
correct under lean (thin traces reduce distraction). Mechanism-adjacent metric (conservative 4-pair
map): 52->65% (n=46) / kAll 61->70%. Paper: RQ-G budget section+table, RQ-E behavior section,
honesty-arc + degradation pgfplots figures, data-generated per-family appendix (7 conds x 23),
mechanism metric in Discussion; trackers updated. Auditor PASS 46/46; artifact on /project.
Cross-model gate: skipped per Yuvraj. Remaining paper work = citations, 2 figures (selector
heatmap, architecture vector), venue call, amendments, repeats-if-quoted.

## Paper reframed as supervisor progress report (per Yuvraj)
Decision: the paper/ directory is now a plain-language progress report for the supervisor,
NOT a venue paper. Why: purpose right now is discussing results/approach/methodology; the
research story is LLM agents for RCA over multi-modal observability -- leakage control is
evaluation hygiene, not a contribution, so it was cut to one paragraph ("Keeping the
evaluation honest" in the agent section) + one takeaway bullet. Removed: abstract/intro/
background/related-work/threats/conclusion apparatus + references.bib (FSE draft preserved
in git history @58e7d58 and paper/fse-draft.md). New structure: article class, sections
00-summary..08-next + 10-appendix; zero run IDs/condition codes anywhere -- plain names
only ("Slow database (T)", "kernel raw", lean/minimal). Compiled clean on cluster (7 pp,
0 errors), PDF md5-verified local==cluster, committed (ac37479, 28426f7) + pushed.
Report-quality bar: readable by someone with zero project context.
