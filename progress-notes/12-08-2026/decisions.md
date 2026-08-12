# Decisions — 12-08-2026

## Team-facing summary consolidated into `summary.md`
Created `summary.md` at repo root: a plain-language, shareable digest of the last two weeks
(29-07 → 12-08) for the team/supervisors. Rationale: the state was spread across `DATASET_GUIDE.md`,
`RESULTS.md`, three `agentic-rca/RESULTS-*.md`, `todolist.md`, and six daily `progress-notes/` —
no single artifact someone outside the daily loop could read.

Scope decisions for the doc:
- Lead with the **three-method comparison** (statistical ~48% / mmbaro 48% / agent 74% Top-1) since
  that is the current headline, and with `slow_db` as the concrete kernel-wins case.
- Include the three *negative/structural* findings as first-class results, not footnotes:
  (A) the two non-LLM methods have complementary blind spots, (B) naive kernel feature-fusion into
  mmbaro changes nothing, (C) trace-only methods floor-out rather than cliff. Together they are the
  three independent arguments for the kernel-reasoning agent.
- Include real dataset snippets (`ground_truth.json`, an L3 digest line, the bundle tree, the
  manifest row) — the team kept asking "what does a run actually look like".
- Carry the operational constraints (login-node-only agent, watchdog chunking, SS L2/CTF2 gap,
  1,395-run sweep budget) into the shared doc, since they shape what anyone can run next.

No new experiments or method changes this session; results unchanged from 11-08.
