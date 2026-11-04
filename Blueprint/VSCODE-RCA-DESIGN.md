# RCA in VS Code: design for the partner's ask

_Draft, 2026-11-03. Builds on `demo/` (the streaming web app), `Blueprint/agent/agent_v2.py`,
the blueprint library under `Blueprint/latency/` and the selectors under `Blueprint/select*`._

## The ask, in one line

Engineers have Jira, logs, traces and source in one place (VS Code). They want the blueprint
agent there too, able to pull the other sources in, so an RCA is one guided session instead of
five tools and a notebook.

## Answer first: three pieces, one protocol

| piece | what it is | what it reuses |
|---|---|---|
| **1. VS Code extension** (TypeScript, thin) | sidebar (incidents, artifacts, runs, blueprints), a run panel (webview), commands, a `@rca` chat participant | `demo/ui.html` becomes the webview; the extension holds no logic |
| **2. RCA server** (Python package, runs where the traces are) | the agent + orchestrator behind a REST/stream API, and the **same capabilities exposed as an MCP server** | `agent_v2`, `demo/app.py` (streaming, sessions, "ask", "connect code"), the blueprint folders, the selectors |
| **3. Connectors** (MCP servers) | Jira, source/git, logs, metrics now; Sherlog, Racoon miner, Trace Compass later | nothing to write for Jira/git (official servers exist); in-house tools get a thin MCP wrapper each |

**One protocol for every source: MCP.** The orchestrator sees every connector as a set of tools;
adding Sherlog later is one more server in a config file, not a code change in the agent.

**Where it runs.** The agent must sit next to the traces (tens of GB, LTTng CTF). So the RCA
server runs on the lab box; VS Code reaches it either through **Remote-SSH** (the extension host
runs on the lab box, nothing to expose) or over HTTPS with a token. Recommend Remote-SSH first:
it is what the engineers already use for lab boxes and it keeps data inside their network.

## Architecture

```
 VS Code (laptop or Remote-SSH on the lab box)
 ┌──────────────────────────────────────────────────────────────────────┐
 │ RCA sidebar          Run panel (webview = demo tabs)    @rca chat     │
 │  Incidents (Jira)     Trace · Discriminator · Agent feed · Verdict    │
 │  Artifacts            Ask · Connect code · Past sessions              │
 │  Blueprints           verdict file:line → opens in editor             │
 └───────────────▲──────────────────────────────────────────▲───────────┘
                 │ REST + SSE (/api/analyze, /api/ask, /api/sessions)    │ (optional) VS Code agent
                 │                                                       │ mode / Copilot via MCP
 ┌───────────────┴───────────────────────────────────────────┴───────────┐
 │ RCA server (Python, on the lab box)                                    │
 │  Orchestrator (LangGraph)                                              │
 │   intake → collect artifacts → select blueprint → run specialists →    │
 │   merge → report → write back                                          │
 │  Specialists: kernel-trace agent (agent_v2 + blueprints), log agent,   │
 │               metrics agent (your other projects), code explorer       │
 │  Blueprint registry (folders: README + tools, versioned, evidence)     │
 │  Job queue (one model ≈ 8 concurrent agents), sessions, audit log      │
 │  MCP server: list_blueprints · select_blueprint · diagnose · ask ·     │
 │              get_evidence                                              │
 └──────┬──────────────┬──────────────┬──────────────┬───────────────────┘
        │ MCP          │ MCP          │ MCP          │ MCP (later)
   Jira server    git / files     logs (Sherlog)  Racoon miner · Trace Compass (TSP)
        │
   LLM endpoint: OpenAI-compatible (on-prem vLLM / Azure / Anthropic), pluggable
```

### Layer by layer

**UI (extension).**
- `RCA: Diagnose this trace` on a folder in the explorer (or a Jira attachment) → picks a
  blueprint (selector suggestion, engineer can override) → streams the run into the panel.
- `RCA: Open incident` → the Jira ticket, its attachments (traces, logs), related tickets, the
  runs already done on it, and a "Write report to Jira" button.
- Verdicts carry `comm tid N`, `pid_ns`, `file:line`; the last one opens in the editor (the
  demo's "Connect code" already does the exploring).
- `@rca` in the Chat view: "diagnose the trace in ticket X", "why did you pick blueprint 8",
  "show the runq_wait line". Same server, same session.

**Orchestration (server).**
- *Intake*: ticket text + attachments → what kinds of evidence exist (kernel trace? logs?
  metrics? which host kind?).
- *Select*: `select_d` (one pid_ns → line-card ladder; containers → microservice ladder) proposes
  a blueprint; the engineer confirms. Measured tonight: 5/5 on the partner traces, ~76% on the
  microservice families, so the human confirm step stays.
- *Run*: the specialist agent follows the blueprint with the blueprint's own tools; every verdict
  quotes the tool lines it rests on; the transcript is saved and replayable.
- *Merge*: when logs or metrics agents also ran, one report with each source's finding and the
  places they agree or disagree (no silent averaging).
- *Write back*: markdown comment + structured JSON on the ticket; the run folder stays on the box.
- *Feedback*: the engineer marks the verdict right / wrong / partly and writes one line; that
  becomes the input to the blueprint-improvement loop we ran by hand today.

**Connectors (MCP).**
- Jira: the official Atlassian MCP server (read issue, attachments, search related, add comment).
- Source: the git/GitHub MCP server, or the local workspace through the extension.
- Logs / metrics: the agents from your other projects, each behind its own small MCP server.
- In-house tools later: Sherlog, Racoon miner as MCP wrappers; Trace Compass through its Trace
  Server Protocol (TSP, an HTTP API) wrapped as MCP tools. Design for them now by keeping every
  tool call behind the MCP tool interface; build them when the partner gives access.

**Model.** One OpenAI-compatible endpoint, configured per deployment. Measured: one H100 serving
a 27B model holds ~9 long contexts, so the server needs a queue and a concurrency cap; the
partner's on-prem endpoint decides the real number.

## Why MCP both ways

- *Inbound*: the RCA server **is** an MCP server. VS Code's agent mode, Copilot, Claude, or any
  internal tool can call `diagnose(trace, blueprint)` without our extension. Our extension is the
  dedicated UI, not the only door.
- *Outbound*: every source the agent reads is an MCP server. The orchestrator never learns a
  Jira or Sherlog API; it learns tool names.

## Build order

| phase | weeks | what ships | done when |
|---|---|---|---|
| 0 | 1 | `pip install strata-rca`: today's demo server + agent as a package; REST/SSE API; the same five capabilities as an MCP server; token auth; job queue | `curl /api/analyze` and an MCP client both run a trace end to end |
| 1 | 2-3 | extension MVP: sidebar (artifacts, runs, blueprints), run panel from `ui.html`, "Diagnose this trace", verdict → `file:line`; Remote-SSH setup doc | an engineer diagnoses a trace from VS Code on the lab box |
| 2 | 2 | Jira: open incident, pull attachments, run, write report back; related-ticket search | a ticket goes from "new" to "report posted" without leaving VS Code |
| 3 | 3-4 | orchestrator + log/metrics agents + merged report; selector in the loop with confirm | one incident, three sources, one report |
| 4 | open | MCP wrappers for Sherlog / Racoon / Trace Compass; `@rca` chat participant; feedback → blueprint loop UI | partner tools appear as tools in the same session |

## Repo layout (new top-level folder)

```
rca-studio/
  server/        Python package: api/ (REST+SSE), mcp/ (server), orchestrator/, registry/
                 imports Blueprint/agent and the blueprint folders as they are
  extension/     VS Code extension (TypeScript): views/, panel/ (ui.html port), chat/
  connectors/    MCP server configs (jira.json, git.json, ...) + wrappers for in-house tools
  docs/          this design, setup, the evidence contract for a blueprint
```

## Decisions to make early

1. **Deployment shape**: Remote-SSH (recommended) vs. a hosted server with HTTPS. Decides auth work.
2. **Model endpoint**: the partner's on-prem vLLM vs. a cloud model. Data residency decides it.
3. **Jira write-back**: comment only, or also attachments and a custom "RCA" field.
4. **Blueprint governance**: who may edit a blueprint, how a change is validated (the matrix we
   run today becomes the regression test).

## Open points

- The framework diagram (Image 4) was not visible to me; the names above (intake / select /
  run / merge / report) should be mapped onto its boxes.
- Trace sizes: the selector's probe slice and the index build take minutes on a 60 s trace; the
  UI must show that as progress, not as a hang.
- The 76% selector number is on microservice traces; on the partner's line cards it is 5/5, and
  that is the number that matters for them.
