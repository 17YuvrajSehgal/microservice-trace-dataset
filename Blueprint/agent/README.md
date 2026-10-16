# agent — the Blueprint kernel-trace RCA agent

The LLM agent that investigates a Linux kernel trace and commits to a diagnosis
(what went wrong, where, when, with evidence). Distilled from the repo's
`agentic-rca/` research harness on 2026-10-16: **only the agent itself lives
here** — two modules plus their support files. The campaign machinery, the v1
agent, the four-modality tools, the old skills and all study results stay in
`agentic-rca/` in the main repo.

The agent needs **only a run directory** (the folder holding the LTTng trace).
There is no data-layer dependency:

```bash
python agent_v2.py /path/to/run_dir
```

So far there is **one blueprint**: `../latency/1_svc_cpu_cap/README_v1.md`
(CPU cap from a kernel trace) with its eight tools in
`../latency/1_svc_cpu_cap/tools/`. The next step is wiring those tools into
this agent as its investigation toolkit. `skillreg.py` (the blueprint
loader/selector mechanism) is the mount point; it loads nothing until
blueprint-backed skills exist.

## Files

| File | Role |
|---|---|
| `agent_v2.py` | ★ the agent: a LangGraph plan / work / review / synthesise loop. `diagnose(run_dir)` for one investigation; `Chat(run_dir)` for grounded follow-up questions |
| `utils.py` | the agent's support module: the kernel-only system prompt + fault vocabulary, the 7 tool schemas, result fitting (row-trimming, never broken JSON), the retrying API call, the ctf tool dispatch, diagnosis unmasking |
| `ctf_tool.py` | the six kernel-trace tools (timespan, timeline, query, lines, procdiff, proclife), babeltrace2-backed |
| `codetool.py` | `run_python`: a sandboxed interpreter with the trace pre-loaded as a DataFrame |
| `coderepo.py` | read-only code-repo tools (`code_tree`/`code_grep`/`code_read`) for Chat |
| `skillreg.py` | skill (blueprint) registry + evidence-driven selector — empty for now |
| `leakguard.py` | masks fault-revealing names before the model sees them |
| `transcript.py` | full-fidelity audit log: every prompt, raw response, tool result |
| `config.py` | the ONE place the model/provider is chosen (env-driven) |
| `AGENT-V2-ARCHITECTURE.md` | the v2 design, phase by phase |

## Model / provider

Default is Claude. Swap by env var — no code change (`python config.py` prints
the active choice):

```
ANTHROPIC_API_KEY=...                       # default: RCA_PROVIDER=claude
RCA_PROVIDER=openrouter OPEN_ROUTER_API_KEY=... RCA_MODEL=openai/gpt-6-luna
RCA_PROVIDER=ollama RCA_MODEL=llama3.1:8b   # local, no key
```

## Environment

| Var | What |
|---|---|
| `CTF_INDEX_ROOT` | the kernel-trace count index (built per dataset; `run_python` loads it) |
| `BT2` | path to a babeltrace **2.1** wrapper (2.0 cannot read our traces) |
| `RCA_TRANSCRIPT` | where `python agent_v2.py <run_dir>` writes the transcript |
| `RCA_MASK_NAMES` | leakguard on/off (default on) |

Defaults point at the Trillium cluster; off-cluster, set the vars.

## Portability contract

Nothing in this folder reaches outside `Blueprint/`: no repo-root imports, no
data layer, every entry point puts its own dir on `sys.path`, every external
location is an env var. When `Blueprint/` becomes its own repo, this folder
moves with it unchanged.
