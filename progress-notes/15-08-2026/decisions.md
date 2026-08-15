# Decisions — 15-08-2026

## v4 skill layer BUILT (registry + evidence-driven selector + 12 skills) — branch `new-agentic-architecture`
Implemented new_design.md §5 in one pass (commit 5470e58), offline-tested (both SDK families) and
API-smoke-verified on the cluster:

- `skillreg.py` — markdown skill registry (simple frontmatter + `## Problem signature` /
  `## Investigation blueprint` / `## Resolution template`; NO YAML dependency — cluster venv has no
  pyyaml). `covers: <family>` is harness metadata (LOFO + selection scoring), never shown to the
  model. **Lint**: evaluation-grade skills are service-agnostic — benchmark identifiers (SS/TT
  service names, injection containers, gt vocab, `aggressor`, `stress-ng`) are forbidden in bodies;
  `load_skills(strict=True)` refuses a dirty library.
- Selector: ONE structured LLM call (select_skill tool, dict/str args both parsed), input = the
  **masked Phase-1 evidence survey only** (evaluation mode: nothing states the problem), explicit
  ABSTAIN ("a wrong skill misleads and is worse than none").
- `context_builder.py` — deterministic survey digest (topology top edges / trace p95 top / log
  changes / metric movers + host / kernel changes) — the Context Builder seed. NOT injected into
  the diagnosis agent yet (kept out so the skill effect is the only variable vs v3; brief-injection
  is a separate future toggle).
- `agent.py` — `skills=` param: survey → mask → select (retry-wrapped) → skill body appended to the
  system prompt with "abandon it if evidence contradicts it"; abstain = plain frozen-v3 path. New
  transcript events: `survey`, `skill_selection` (evidence + skills shown + tokens),
  `skill_injected`. Selector tokens/survey bytes counted into the row costs.
- `evaluate.py --skills off|full|lofo` (+`--skills-dir`); LOFO removes the incident's own family
  per incident; `selection_correct` scored harness-side (full: covers==family; lofo: abstained).
- `audit_leakage.py` — new channels: survey/selector evidence = full per-incident scan; skill
  library text + injected bodies + system prompt = static scan + service-name lint (imports
  skillreg's forbidden pattern). This caught the base v3 prompt's phrase "no visible aggressor" →
  reworded to "no visible culprit workload" (one-word prompt change; S0 is re-measured within the
  v4 campaign anyway; master's frozen v3 untouched).
- `skills/` — **12 evaluation-grade skills**, one per injected family, written against the real
  tool vocabulary (host_disk_io_time_s/s, off_cpu_io_wait, cpu_throttled_s/s, change_x, …), each
  with discriminating look-alike rules (db_latency vs dependency_outage vs error_storm;
  cpu_saturation vs noisy_neighbor vs cpu_throttling; host vs single-service scope). All lint-clean.

## Smoke results (4 incidents, real API) — the design behaves as intended, both ways
- **S1 SS anomaly_disk: right skill @0.98 → aggressor/disk_io fully correct in 11 calls.**
- **S2 (LOFO) SS anomaly_disk: correct ABSTAIN @0.91 with 11 distractors → first-principles
  fallback still fully correct** — the never-seen-fault path demonstrated end-to-end.
- TT slow_db false-matches `service-network-path-rca` in BOTH modes (0.81/0.77) and the wrong
  skill steers the agent to a victim — this incident's evidence is genuinely path-shaped (~30s
  timeout plateaus). Exactly the false-match/distractor phenomenon §6 is designed to measure; the
  agent did NOT exercise its "abandon the skill" permission (worth analyzing in the campaign).
- Auditor PASS 4/4 including the new skill channels.

## Full S1+S2 campaign LAUNCHED (46 incidents)
`gate_skills_driver.sh` (resumable, per-family fresh python) running S1 (skills-full) then S2
(LOFO) over the 23 gate incidents; results → `results/gate_s1/`, `results/gate_s2/`;
`skills_status.sh` for progress. Compare against S0 = gate v3 (83/48/48). Monitor note: inline
`$(…)` through `wsl ssh` breaks — always use a status SCRIPT on the cluster (second time this bit).
