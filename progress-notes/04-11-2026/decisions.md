# 04-11-2026 - decisions

## 1. RCA Studio: the product lives in its own repository
The partner's ask is "RCA inside VS Code, with Jira and the other sources in one place". The
answer is a separate, shippable repo at `rca-studio/` (ignored by this one): a FastAPI server
(SQLite catalogue, bounded run queue, SSE streams, Jira connector with a local JSON mode, a
socket for the related-past-issues component, model settings, blueprint management) and a
VS Code extension (sidebar Traces / Incidents / Runs / Blueprints, a run panel with the live
feed, verdict, ask and feedback, a status-bar model picker, blueprints editable as `rca://`
files). The agent and the blueprint library are vendored in by `scripts/sync_from_research.py`
(commit recorded, partner words refused), never edited there. Design: `Blueprint/VSCODE-RCA-DESIGN.md`;
architecture: `rca-studio/docs/ARCHITECTURE.md`.
Why a separate repo: this one is messy and partly NDA; the partner will ask for code.
Why one worker process per investigation: the agent keeps its run context in module globals.

## 2. First real investigation on the laptop (LM Studio, Bonsai 27B Q1_0)
Pipeline end to end: VS Code -> server in WSL (babeltrace) -> worker process -> LM Studio on
Windows -> verdict streamed back. 11.5 min, 23 tool calls, 14 findings, 819k input tokens.
Three things broke before it worked, each now handled in the product:
- LM Studio loads a model with an **8192-token context** by default; the agent's planner prompt
  is ~12k tokens -> a bare 400. The model test now reports the loaded context (LM Studio
  `/api/v0/models`, vLLM `max_model_len`) and warns below 32k.
- LM Studio **rejects the forced tool_choice object** ("Supported string values: none, auto,
  required"). The research agent already had `RCA_LOCAL_COMPAT=1` for this; the `local`
  provider now sets it.
- Reasoning models answer a tiny test prompt with thinking only; the test says so instead of
  showing an empty reply.
Load command that works on the 8 GB laptop GPU (7.6 GB used, 32k context, one prediction at a
time): `lms load prism-ml/bonsai-27b -c 32768 --gpu max --parallel 1 --identifier bonsai-27b -y`;
UI defaults set once: automatic optimize off, reasoning budget 2048, temperature 0, context
overflow "stop at limit".

**The verdict was wrong**: `noisy_neighbor` 0.95 blaming the host namespace, on a
`svc_cpu_cap` run (matched blueprint given). This is the cpu_cap-vs-noisy confusion the
selector work knows well, now from a 1-bit 27B model instead of Qwen3.8-27B on an H100. The
laptop run proves the plumbing, not the model; quality numbers stay with the cluster runs.

## Open
- rca-studio: extension tests; MCP face of the server; access control for blueprint editing;
  show the edit history in the UI; the coordinator for log/metrics agents.
- Try an 8B model fully on the GPU for faster laptop runs; keep Bonsai for the smoke test.
- Research repo: everything from 03-11's next-steps still stands (C v7 controls, select_d arm,
  fd r4/r5, nsmap for restart loops).
