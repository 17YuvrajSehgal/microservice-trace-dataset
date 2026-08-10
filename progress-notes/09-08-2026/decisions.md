# Decisions — 09-08-2026

Continues 08-08 (repo reorg + dataset extraction + kernel L2 batch). Today: built the agentic-RCA
harness (P1–P3) and both non-LLM baselines end-to-end on Trillium, **entirely no-API**. All under
`agentic-rca/`; results in `agentic-rca/RESULTS-*.md`; branch `agentic-tracing`.

## Harness built + validated (P1–P3, no API)
- **`tools.py`** — 4 deterministic telemetry tools over `stratatrace/loader.py`, both apps,
  byte-accounted: traces (SERVER-span p50/95/99), logs (error sigs), metrics (curated cAdvisor,
  counter→rate, magnitude-ranked), kernel (L1 peaks + L3 deviations + L2 wait-attribution when present).
  Hard-won perf fix: logs tool was 152s (Java logs are GBs) → **vectorized** `str.contains` (once, C)
  then Python-loop only the matched lines → ~seconds.
- **`agent.py`** — tool-using LLM loop (Anthropic) → contract `{root_cause_service, fault_type,
  evidence, confidence}` + trajectory (RQ2) + tokens/bytes (RQ4). Model via `config.py`. Runs when a
  key exists (P2 sanity gate blocked only on `ANTHROPIC_API_KEY`).
- **`runs.py`** — enumerate 43 TT + 50 SS incidents; `score()` (recipe-aware; ground_truth `family`
  is a taxonomy code, recipe is in `name` — score against that + host-fault/container-name tolerance).
- **`degrade.py`** — seeded offline `DegradedRun` wrapper (trace%/metric-step/log-level/coverage/
  modality/kernel-tier). Sits before the reader → Axis A (data) isolated from Axis B (agent fixed).
- **`evaluate.py`** — `(run × condition × method) → predict → score → aggregate`; `--grid all`
  loads each run ONCE and sweeps all conditions. **Perf fix:** wrap base run in `_MemoRun` — the loader
  re-parses spans on every call (SS 2.4M spans ≈ 65s), so a 15-condition grid re-parsed 16× (17min/run)
  → memoize → ~6min/run.

## RCA method #1 — statistical baseline (`baseline_stat.py`), swept
Rule tree over the 4 tools. Full sweep (job 2074051, 93 inc × 15 cond = 1,395 evals, ~53min).
`RESULTS-stat-baseline.md`. Robust to degradation (flat curves — rides coarse signals), **kernel-blind**
(kNone=full), **0% on slow_db/queue_backlog**. Both-hit 38% (TT 44/SS 32); Top-1 localization ~48%.

## RCA method #2 — RCAEval / Multi-source BARO (`rcaeval_adapter.py`), swept
"CARE" was a misremembered name → real target is **RCAEval/BARO/TORAI** (Luan Pham, RMIT; see
`non-llm-baseline.md`, the supervisor's report). Installed **RCAEval 1.6.0** in a separate
`/scratch/yuvraj17/.venv-rca` (py3.12) + stratatrace. Adapter = raw→time-series into the 4-key dict
`{metric, logts, tracets_err, tracets_lat}` on the SAME (degradable) Run (guardrail holds); mmbaro
localizes (no fault_type) → score **Top-1/Top-3** (= AC@1/AC@3). Debugged: missing error.type col;
a **pandas-3 datetime→unix bug** (unit='s' makes second-resolution datetimes; `.astype(int64)//1e9`
assumed ns → time column collapsed) → `_unix_col` helper; infra-container pollution (filter
cadvisor/nan/exporters). Full sweep (job 2081090). Top-1 localization 48%.

## Headline result: the two non-LLM methods have COMPLEMENTARY blind spots
`RESULTS-nonllm-baselines.md`. Statistical wins stress-container/victim faults (noisy_neighbor 100 vs
0, dependency 50 vs 0); **mmbaro wins subtle single-service faults it misses (slow_db 50 vs 0,
error_storm, svc_mem_cap)**. Neither dominates → motivates method #3. Both flat under degradation
(RQ1 cliffs must come from the agent + trace-dependent methods).

## RQ3-inside-mmbaro: naive kernel fusion does NOT help the published method (finding)
Enabled pyarrow (`arrow/19.0.1` module in `.venv-rca`); folded VARYING kernel L1 KPIs
(sys_lat_p99/sys_io/sys_futex/block_ops/net_bytes; **sys_lat_p95 saturates at 500ms → useless**)
into mmbaro's metric frame, anchored to metric start (**window_start_s is RELATIVE, not unix**).
Result: `full` == `kNone` for every fault — BARO ranks the ~200 cadvisor change-points far above
kernel cols (first kernel col ~rank 195). **Kernel value isn't accessible by feature-fusion into a
metric-change-point method; it needs an agent that reasons about wait-attribution** → clean motivation
for method #3. Didn't re-run the 40min sweep (numbers identical).

## Kernel L2 batch outcome (from 08-08 job 2072784)
TT 43/43 correct (slow_db→mysql 100% off-CPU-io-wait). **SS blocked: CTF2** metadata unreadable by
Trillium's babeltrace 2.0.4 (SS collector VM wrote CTF2; TT wrote CTF1.8). 48 empty SS L2 deleted →
SS kernel tool uses L1+L3. To get SS L2: derive on the SS collector VM (Linux, CTF2-capable) later.

## Env / access facts (hard-won)
- Two cluster venvs: `.venv` (py3.11 + arrow) for stat/tools; `.venv-rca` (py3.12 + arrow + RCAEval)
  for mmbaro. Both have stratatrace. `arrow` module gives pyarrow (load AFTER python).
- Cluster driven via the user's live WSL SSH master: `wsl.exe -d Ubuntu -- ssh trillium bash -s <<'EOF'`
  (heredoc over stdin — inline arg strings mangle vars). **The MFA'd master expires after hours** →
  user re-runs `ssh trillium` + Duo.
- Data at `/scratch/yuvraj17/agentic-runs/{app}/<recipe>/<run>`; sweeps write `agentic-rca/results/`
  (gitignored, regenerable). Compute = whole-node `debug`/`compute`; `$SLURM_TMPDIR`=/dev/shm 566GB.

## Open / next
- **Method #3 (LLM+kernel agent)** — needs `ANTHROPIC_API_KEY` on the login node; plugs into the
  same runner/grid/scoring. The piece expected to break the complementarity ceiling + light up RQ3.
- Optional no-API: "expected-to-break" trace-dependent methods (MicroRank/TraceRCA) as RQ1 cliff
  evidence; SS L2 via the collector VM; MRR/AC@3 columns in analyze.
