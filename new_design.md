# New System Design — Agentic Analysis Backend (supervisor proposal)

*Drafted 2026-08-14, from the supervisor's design discussion. Maps the proposed architecture
onto the current codebase (branch `new-agentic-architecture`; agent state = frozen gate v3,
`agentic-rca/RESULTS-agent-sanitygate-masked.md`). This is the working design doc for the next
build phase.*

![New design architecture](img/new-design-architecture.png)

## 1. The proposal in one paragraph

The agentic RCA we have today becomes one component inside a larger **Analysis Backend**. Inputs
stay as observability bundles (tarballs — same shape Ciena uses), but the backend gains
components that "give the agent its brain": an **Investigation Context Builder** that assembles
exactly the context the problem needs (and omits what it doesn't), a **Shared Investigation
Context** the components read/write, additional context sources (**source code**, **past/related
JIRAs**), and an **AI Skills collection** (Problem Signatures, Resolution Templates,
Investigation Blueprints) mined from completed RCAs and fed back "akin to training". The backend
fronts onto Ciena's existing AI ecosystem (SherLog, dashboards, Racoon Miner, Trace Compass) via
AI interfaces such as MCP.

## 2. Block-by-block status vs. our code

| Diagram block | Status | Where it lives today |
|---|---|---|
| Observability Bundle (tarball) | **Built** | StrataTrace run bundles (logs/, otlp/spans.jsonl, metrics, kernel L0–L3, meta/, verification.json) — richer than the diagram ("Anomaly Records" ≈ our QC verdicts; kernel modality is our extension) |
| Bundle Extraction & Inventorying | **Built (minor gaps)** | `stratatrace/loader.py`, `transfer/extract_working_set.sh`, `agentic-rca/runs.py` + manifest, `audit_alignment.py` (six-modality QC) |
| Timeline Reconstruction (unified timeline) | **Partial** | Clock anchors (0.001 ms drift) + every tool reslices onto baseline→incident windows — but no *unified timeline artifact* a consumer can query; alignment exists, the timeline product doesn't |
| Correlation Engine | **Partial** | Deterministic pieces inside `agentic-rca/tools.py` (topology edges, cross-modality baseline→incident deltas, kernel↔service PID attribution, L2 wait attribution); correlation itself happens in the LLM's reasoning, not a standalone engine |
| RCA | **Built — strongest block** | `agent.py` + `tools.py` + leakguard + full transcripts; gate v3 = service 83% / fault 48% / both 48%, leakage-controlled; two non-LLM baselines + RCAEval adapters for comparison |
| Investigation Context Builder | **Not built** | Closest thing: the system prompt's step-1 "survey" — context assembly is pushed onto the agent at inference time, every time |
| Shared Investigation Context | **Not built** | Per-diagnosis trajectory/transcript exists; no structured working memory that components (or multiple agents) read/write |
| JIRA / Related JIRAs | **Not built** | No corpus, no retrieval |
| Source Code input | **Not built — cheap to build** | Subjects' code is in-repo (`microservices-demo/`, `train-ticket/` submodules); a `query_source` tool (search / read file / function) is small work |
| Issue Analysis | **Unclear scope** (§5 Q1) | If it means the broader task family (anomaly detection, explanation, repair — the old T1–T4), only RCA exists; AD is an open todo |
| AI Skills (Problem Signature / Resolution Template / Investigation Blueprint) | **Raw material exists; loop not built** | Transcripts *are* investigation blueprints (every tool call, evidence, reasoning); `fault_catalog.md` per-fault cards are hand-authored problem signatures; nothing yet mines RCA outputs into reusable skills or feeds them back |
| AI Interfaces (MCP) | **Exists, stale** | `agent-first-mvp/mcp_server.py` (demo face); predates the v3 tools — needs rewiring to `RunTools` |
| Frontend (SherLog / Dashboard / Racoon Miner / Trace Compass) | **Not built (Ciena-side)** | Synergy to exploit: our kernel L0 is LTTng CTF — **Trace Compass's native format**, so that bridge is nearly free; `agent-first-mvp/dashboard/` is a stale per-run inspector |

## 3. Build plan (proposed order)

1. **Investigation Context Builder** — the headline gap. A deterministic module that runs the
   survey pass *before* the agent starts: extracts the incident window, computes what-changed
   summaries across all modalities, ranks blast-radius candidates, pulls related past
   incidents/code, and emits a compact **investigation brief**. Gate v2→v3 already proved the
   survey discipline is what makes or breaks the agent; today the agent re-derives it with ~5
   tool calls per incident. A deterministic builder makes it cheaper, reproducible, and reusable
   by non-LLM consumers.
2. **Shared Investigation Context** — the substrate the builder writes into: a typed store of
   claims ("edge front-end→catalogue ×11.6", "mysql 100% off-CPU external wait"), each with
   source pointers back into the bundle. The transcript event schema is a good starting shape.
3. **Retrieval sources plugged into the builder** — source-code tool first (corpus in-repo,
   fault-agnostic, zero leakage risk); then related-incidents retrieval — pre-Ciena, our 93
   labeled incidents + transcripts can stand in for JIRA as pseudo-tickets.
4. **Skills loop** — mine Problem Signatures / Resolution Templates / Investigation Blueprints
   from completed RCA transcripts; feed back through the Context Builder. Gated on §4.
5. **MCP face refresh** + Trace Compass bridge when Ciena integration becomes concrete.

## 4. Design tension: the skills loop vs. evaluation integrity

Two gate cycles (13-08) proved the agent's numbers are only meaningful when it isn't handed
hints. **Problem Signatures and Resolution Templates fed back into the backend are, by
construction, a hint channel** — right for a production assistant, contaminating for the research
measurement. Resolution: make it an explicit switch.

- **Assistant mode**: skills + JIRA context ON — the Ciena-facing product.
- **Evaluation mode**: skills OFF, or skills-ON as a *measured condition* with its own results
  column (a paper-worthy ablation: "what is accumulated experience worth?").
- Related-incidents retrieval must exclude the incident under investigation and (for the honest
  headline) its fault family. `audit_leakage.py` grows checks for this once retrieval exists.

Versioning discipline: **v3 = frozen sweep agent** (degradation study runs on this, unchanged);
**v4 = context-builder architecture** developed in parallel on this branch. Never co-vary.

## 5. Open questions for the supervisor

1. **"Issue Analysis" vs "RCA"** — the broader task family (detection, triage, explanation,
   repair)? A post-RCA drill-down? Its own agent? Determines whether it's a new component or a
   relabeling.
2. **Is the Correlation Engine meant to be deterministic/LLM-free?** Today correlation happens in
   the agent's reasoning over deterministic tool outputs. A standalone engine emitting candidate
   correlations without an LLM is a different, substantial component — and overlaps with the
   Context Builder.
3. **Which mode is the deliverable** — production assistant (skills/JIRA on) or the measured
   research system (leakage-controlled)? Presumably both; the diagram doesn't distinguish, our
   evaluation discipline requires it to be explicit.
4. **JIRA corpus before Ciena data** — synthesize pseudo-tickets from our own incidents, or defer
   until real Ciena JIRAs are available?
5. **Shared Investigation Context semantics** — single-investigation working memory vs persistent
   cross-investigation knowledge (which overlaps the Skills collection)? Single-agent or
   multi-agent blackboard?
6. **Where does kernel telemetry sit?** The Network Element list (RTRV-LOG) has no kernel traces —
   our main differentiator. Folded under "Logs/States", or a StrataTrace-side extension the Ciena
   path won't have? Affects how portable the Context Builder must be.
7. **Unified timeline consumers** — the agent, the frontends (Trace Compass/dashboards), or the
   Correlation Engine? Decides its format (queryable store vs rendered artifact).
8. **Freeze discipline** — confirm: degradation sweep runs on frozen v3 while v4 (this design) is
   developed in parallel; v4 gets its own gate before any of its numbers are quoted.
