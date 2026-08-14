# Decisions — 14-08-2026

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
  in parallel** — never co-vary. 8 open questions for the supervisor listed in the doc (§5),
  headline ones: Issue-Analysis scope, deterministic-vs-LLM correlation engine, which mode is the
  deliverable, where kernel telemetry sits in the Ciena input list.
