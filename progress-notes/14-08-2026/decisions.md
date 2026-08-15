# Decisions — 14/15-08-2026

## New system design from supervisor → `new_design.md` (branch `new-agentic-architecture`)
Supervisor proposed evolving the agentic RCA into a Ciena-shaped **Analysis Backend** (diagram in
`img/new-design-architecture.png`, analysis + gap map in `new_design.md`). Key mappings: bundles/
extraction/RCA are built; timeline + correlation are partial (alignment exists, no unified-timeline
artifact; correlation lives in the LLM); **Investigation Context Builder, Shared Investigation
Context, JIRA/source-code retrieval, and the AI-skills feedback loop are the missing pieces**.

Decisions recorded in the doc:
- Build order: Context Builder → Shared Context store → retrieval sources (source code first —
  in-repo and leakage-safe; pseudo-JIRAs from our own 93 incidents pre-Ciena) → skills loop → MCP/
  Trace Compass bridges (kernel L0 is Trace Compass-native LTTng CTF — nearly free integration).
- **Skills feedback = a hint channel**: must be an explicit assistant-mode vs evaluation-mode
  switch (skills-on as a *measured condition*, not silent default); retrieval must exclude the
  incident under investigation (+ its family for headline numbers); extend audit_leakage.py when
  retrieval lands.
- **Versioning: v3 agent stays FROZEN for the degradation sweep; v4 (this architecture) developed
  in parallel** — never co-vary. 8 open questions for the supervisor listed in the doc (§7),
  headline ones: Issue-Analysis scope, deterministic-vs-LLM correlation engine, which mode is the
  deliverable, where kernel telemetry sits in the Ciena input list.

## 15-08: v4 = SKILL-BASED RCA (Yuvraj decision) + the unseen-fault evaluation design
Decision: replace the single monolithic prompt with an MVP-style **skill library** — the product
story is "anyone can author a skill for the problems they face" — WITHOUT re-opening the leak we
closed: MVP skills were selected by the user's problem statement (= the ground-truth label in
evaluation) and their bodies hard-coded answers (`fault_source`, `target_services`, expected
finding). Design added to `new_design.md` §5–§6; draft skill format + first evaluation-grade
example in `agentic-rca/skills/` (README + db-latency-rca.md — service-agnostic, evidence-
signature-selected).

Core architecture: **two-phase flow** — Phase 1 generic survey (Context Builder seed) → evidence
signature → selector with explicit ABSTAIN → Phase 2a skill-guided investigation OR Phase 2b
first-principles fallback (= frozen v3 method). Generic method is the floor; empty library = v3.
Two selection modes: assistant (user_triggers allowed) vs evaluation (evidence-only).

**Unseen-fault proof = S2 LOFO (leave-one-family-out)**: evaluate every incident with the library
minus that incident's own family — 11 present skills act as distractors; system must ABSTAIN and
fall back. Conditions: S0 skills-off (=v3, measured 83/48/48), S1 skills-full (skill lift per
family), S2 LOFO (graceful-degradation claim: S2 ≈ S0; S2 < S0 would mean distractor damage — a
result either way). Report selection precision (S1), abstention recall (S2), false-match confusion,
cost deltas. Later strengthening: cross-app transfer (skills authored on SS, evaluated on TT) and
F13+ faults. Integrity: masking stays on, eval-grade skills are service-agnostic (auditor to lint
skill content once wired), transcripts + audit PASS remain shipping criteria.
