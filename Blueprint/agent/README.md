# agent (Blueprint copy of agentic-rca)

> **This is the Blueprint workspace's copy of the agent** (copied from the repo's
> `agentic-rca/` on 2026-10-16; that original stays untouched as the record of the
> earlier campaigns). New agent work — especially teaching the agent to drive the
> blueprint tools in `../latency/*/tools/` — happens HERE.
>
> **Portable by design.** Nothing in this folder reaches outside `Blueprint/`:
> - `stratatrace/` (the data layer) is **vendored inside this folder**, and every
>   entry point puts its own dir on `sys.path` first — so `from stratatrace import
>   load_run` resolves locally, with no `pip install -e` and no repo-root import.
> - Every data location is an **env var**: `RUNS_ROOT` (run bundles),
>   `CTF_INDEX_ROOT` (the count index), `BT2` (babeltrace 2.1 wrapper),
>   `RCA_SOURCE_ROOT` (service sources). The in-code defaults are the Trillium
>   cluster paths; off-cluster, set the env vars.
> - Skills load from `skills/` next to `skillreg.py`.
>
> So when `Blueprint/` becomes its own repo, this folder moves with it and nothing
> breaks. Paths like `../transfer/` and `../research-agentic-rca.md` below refer to
> the ORIGINAL repo and do not exist inside `Blueprint/` — they stay for context.

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

> Dataset-prep, extraction, derivation, and transfer scripts live in **`../transfer/`** — this dir
> is agent code only.

## Setup
**Cluster (primary — the study runs on Trillium where the dataset lives):** `source ../transfer/env.sh`
(loads `python/3.11` + `arrow/19.0.1` + the cluster `.venv`). The login node has Anthropic API access.

**Laptop (dev):**
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

## Getting data
**On the cluster (primary):** the working set is already extracted at
`/scratch/yuvraj17/agentic-runs/{trainticket,sockshop}` (small modalities only — no raw L0) by
`../transfer/extract_working_set.sh` / `extract_job.sbatch`; `../transfer/derive_l2_*` add kernel L2.
Point the loader there with `list_runs("/scratch/yuvraj17/agentic-runs/<app>")`.

**On a laptop (optional):** `../transfer/fetch_dev_sample.sh` packs a small sample to download and
unpack into `dev-runs/`.
