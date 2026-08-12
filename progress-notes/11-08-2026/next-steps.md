# Next steps (as of 2026-08-11)

Read this day's `decisions.md` + `todolist.md` + `agentic-rca/RESULTS-*.md` first.

## State in one line
All THREE RCA methods work and are documented. The LLM+kernel agent (Azure gpt-5.4) passed the sanity
gate and **beats both non-LLM baselines** (both 61% vs 38%), recovering `slow_db` via kernel reasoning.
Nothing is currently running.

## Do next — the full agent degradation sweep (RQ1/RQ2/RQ3), cost-bounded
The agent works; the remaining science is running it under degradation. Two hard constraints:
**login-node only** (compute nodes have no internet) and a **login-node watchdog** (run in short
per-family chunks), plus **Azure credits** (1,395 runs at full 93×15 scale). So DON'T brute-force —
propose a subsample:
1. **Blind-spot families first** (`slow_db`, `queue_backlog`, `noisy_neighbor`) × the **kernel + trace**
   axes (`--grid kernel` / `--grid trace`, and `compensate`) → the RQ3 "kernel as safety net" + RQ1
   cliff for the agent. ~a few hundred runs, not 1,395.
2. Reuse the chunked driver pattern (loop families, fresh `python -u evaluate.py … --method agent …`
   process each; `set -a; source .env; set +a` first).
3. Then RQ2: analyze the agent **trajectories** (now persisted in the result rows) full vs degraded —
   does it escalate to kernel when traces thin, or hammer dead traces?

## Also (no-API / small)
- Merge the agent gate into a comparison table alongside the baselines in `RESULTS-nonllm-baselines.md`.
- Refine agent prompt/tooling for the miss clusters (network faults, error_storm fault-type).
- SS kernel L2 on the collector VM (CTF2-capable) if RQ3 needs SS wait-attribution.

## Don't rediscover
- Provider config: `RCA_PROVIDER` + env keys in `.env` (git-ignored). Azure gpt-5.4 → `RCA_PROVIDER=azure`,
  `AZURE_OPENAI_ENDPOINT=…/openai/v1`, `RCA_SEND_TEMPERATURE=0`. Cluster `.env` already set up.
- Agent runs on the **login node**, chunked, `python -u`. Two venvs: `.venv` (py3.11, agent+stat+openai),
  `.venv-rca` (py3.12, RCAEval). Cluster access = user's WSL ssh master (expires → re-`ssh trillium`+Duo).
