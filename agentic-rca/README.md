# agentic-rca

The RCA-under-telemetry-degradation harness (plan: `../research-agentic-rca.md`, tasks: `../todolist.md`).
Reuses `agent-first-mvp/` (skills, deterministic deciders, byte-counted readers) and
`stratatrace/loader.py` (the data layer). This dir holds the *new* build.

## Layout (as it grows)
| File | Role | RQ |
|---|---|---|
| `config.py` | single place the model/provider is chosen (`chat()` → `Turn`) | all |
| `dev-runs/` | local sample runs (small modalities only; git-ignored) — see fetch below | — |
| `degrade.py` *(todo)* | seeded OFFLINE telemetry-degradation transforms on a loaded run | RQ1/3/4 |
| `agent.py` *(todo)* | the LLM RCA agent loop over the 4 telemetry tools + trajectory log | RQ2 |
| `evaluate.py` *(todo)* | run (run × condition × method) → predict → score vs ground_truth | RQ1 |

## Setup (done once, from repo root)
```
python -m venv --system-site-packages .venv        # inherits working pandas/pyarrow
.venv/Scripts/python -m pip install -e ./stratatrace -r agentic-rca/requirements.txt
```

## Model / provider (config.py)
Default is Claude. Swap by env var — no code change:
```
export ANTHROPIC_API_KEY=...                        # default: RCA_PROVIDER=claude, claude-opus-4-8
RCA_MODEL=claude-sonnet-5 ...                        # different Claude
RCA_PROVIDER=openai OPENAI_API_KEY=... ...           # GPT (pip install openai)
RCA_PROVIDER=ollama RCA_MODEL=llama3.1:8b ...        # local, no key
```
Adding a model = adding one `_chat_*` adapter in `config.py`; the agent, tools, degradation,
and scoring are provider-agnostic, so RQ numbers stay comparable across models.

## Getting dev data
On Trillium: `transfer/fetch_dev_sample.sh` selects only the small modalities (spans/logs/
metrics/kernel L1-L3 — never the raw L0 CTF) and packs them. Download and unpack into `dev-runs/`.
