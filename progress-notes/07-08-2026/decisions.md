# Decisions — 07-08-2026

## Data staged to Trillium; both collector VMs stopped
Both StrataTrace datasets pushed to Trillium `/scratch/yuvraj17/microservice-trace-dataset/`
(trainticket 13 archives/179 GB, sockshop 15 archives/137 GB, per-recipe `.tar.gz`, verified
0-partial + aux gzip-tested). Both GCP VMs TERMINATED (cost halted; GCP disks still hold the
originals as backup). Transfer tooling in `transfer/` (push/extract, ControlMaster for the cluster
MFA, durability guidance: keep archives on `/project`, extract a working copy — non-destructive).

## RESEARCH PIVOT — agentic RCA under telemetry degradation (supervisor meeting 07-08)
`meeting-notes/chat-notes-07-08-2026.txt`. The direction sharpened from the v2 **modality-ablation**
(`msr-research.md`) to a more actionable, agent-centered question:
**"How much observability can we lose before diagnosis breaks — and does the agent adapt / does
kernel act as a safety net?"** Wrote the aligned plan: **`research-agentic-rca.md`**. Key points:
- **4 RQs:** (1) robustness to degradation (trace %, metric step, log level, service coverage →
  RCA Top-1/3/MRR, expect nonlinear cliffs); (2) agent **investigation strategy** — does it shift to
  lower-level telemetry when app visibility degrades, or hammer dead traces (a diagnosable weakness);
  (3) **cross-modality compensation** — M+L+T vs M+L+T+K, kernel as a safety net (test on the
  blind-spot faults slow_db/queue_backlog/noisy_neighbor); (4) **minimum observability budget** —
  Pareto of RCA accuracy vs cost (reuse the measured per-modality collection cost).
- **CRITICAL GUARDRAIL (Mahsa):** don't confound telemetry-degradation with agent effects. Axis A
  (degradation) holds the agent FIXED, varies only the data (a deterministic, seeded OFFLINE
  transform on a stored run — **no re-collection**). Axis B (agent trajectory) is observed while A
  varies. Never change both in one comparison.
- **3 RCA approaches:** statistical baseline + a CARE/RCAEval-style published method + the LLM/agent
  (the focus + the only one giving RQ2 trajectories).
- **Architecture:** StrataTrace bundle → degradation module → `loader.py` reader → 4 deterministic
  telemetry tools/MCP (metrics/logs/traces/kernel) → single RCA agent + trajectory logger →
  `{root_cause_service, fault_type, evidence, confidence}` → evaluation runner (vs `ground_truth.json`).
- **Sanity gate first:** run the agent on ~20 incidents at 100% telemetry, confirm it diagnoses,
  BEFORE any degradation study.
- **The dataset is exactly the asset** — 49+46 labeled incidents, 4 aligned modalities, pre-registered
  blind-spot faults, measured collection cost. Degradation is offline. Yuvraj's Ciena MVP (agent
  escalates to kernel when struggling; found all 3 injected anomalies) + `agent-first-mvp` code are
  the agent starting point.
- **OPEN ITEMS before heavy build:** (1) confirm the agentic direction with **Naser** (he leaned
  agentic over the MSR framing — meeting action item); (2) pick the exact statistical + CARE baseline;
  (3) LLM/model + tool framework (MCP vs in-process). Launched an Explore agent to inventory existing
  agent/skill/loader assets before scaffolding P0.
