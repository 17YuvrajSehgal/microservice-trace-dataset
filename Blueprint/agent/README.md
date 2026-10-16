# agent — the Blueprint RCA agent

The LLM agent that investigates a run from its telemetry. Copied from the
repo's `agentic-rca/` on 2026-10-16 and then **trimmed to only what the agent
itself uses**. The full research harness (campaign drivers, degradation
study, baselines, sweeps, old results, the 12 old-generation skills) stays at
`agentic-rca/` in the main repo — it was not brought here.

So far there is **one blueprint**: `../latency/1_svc_cpu_cap/README_v1.md`
(CPU cap from a kernel trace) with its eight tools in
`../latency/1_svc_cpu_cap/tools/`. The next step for this agent is to use
those tools as its investigation toolkit. The old skill library was removed
with the old blueprints; `skillreg.py` (the loader/selector mechanism) stays
and simply loads nothing until new blueprint-backed skills exist.

## Files

| File | Role |
|---|---|
| `agent_v2.py` | ★ the agent (LangGraph): phased investigation over the tools. Run: `python agent_v2.py <run_dir>` |
| `agent.py` | v1 loop; `agent_v2` imports its tool definitions and constants |
| `config.py` | the ONE place the model/provider is chosen (env-driven) |
| `tools.py` | the four telemetry tools (traces, logs, metrics, topology) over a loaded run |
| `ctf_tool.py` | kernel-trace tools (babeltrace2-backed timeline/procdiff/lines...) |
| `codetool.py`, `coderepo.py`, `source_tool.py` | sandboxed code execution + service-source reading |
| `context_builder.py`, `shared_context.py` | the evidence survey the agent builds first |
| `skillreg.py` | skill registry + evidence-driven selector (empty for now, see above) |
| `leakguard.py` | masks fault-revealing names before the model sees them |
| `transcript.py` | trajectory/transcript logging |
| `stratatrace/` | **vendored** data layer (`load_run`); resolves locally, no install |
| `AGENT-V2-ARCHITECTURE.md` | how the v2 agent is structured, phase by phase |
| `requirements.txt` | python deps (anthropic/openai, langgraph, pandas) |

## Model / provider

Default is Claude. Swap by env var — no code change (`python config.py` prints
the active choice):

```
ANTHROPIC_API_KEY=...                       # default: RCA_PROVIDER=claude
RCA_PROVIDER=openrouter OPEN_ROUTER_API_KEY=... RCA_MODEL=openai/gpt-6-luna
RCA_PROVIDER=ollama RCA_MODEL=llama3.1:8b   # local, no key
```

## Data locations (all env vars)

| Var | What |
|---|---|
| `RUNS_ROOT` | run bundles (unused by `agent_v2` itself — it takes a run dir argument) |
| `CTF_INDEX_ROOT` | the kernel-trace count index |
| `BT2` | path to a babeltrace **2.1** wrapper (2.0 cannot read our traces) |
| `RCA_SOURCE_ROOT` | service source checkouts for `source_tool` |

Defaults point at the Trillium cluster; off-cluster, set the vars.

## Portability contract

Nothing in this folder reaches outside `Blueprint/`. The data layer is
vendored (`stratatrace/`), every entry point puts its own dir on `sys.path`,
and every data location is an env var. When `Blueprint/` becomes its own
repo, this folder moves with it unchanged.
