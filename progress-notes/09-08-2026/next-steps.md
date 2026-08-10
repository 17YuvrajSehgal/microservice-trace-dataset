# Next steps (as of 2026-08-09)

Read `decisions.md` (this day) + `todolist.md` + `agentic-rca/RESULTS-*.md` first.

## State in one line
Agentic-RCA harness (P1–P3) + 2 of 3 RCA methods (statistical, RCAEval/mmbaro) built, swept over
93 incidents × 15 degradation conditions, and documented — all **no-API**, on Trillium. Method #3
(LLM+kernel agent) is coded and waiting on API credits.

## Do next
1. **Method #3 — LLM+kernel agent (needs `ANTHROPIC_API_KEY`).** On the Trillium login node (has
   internet): `source transfer/env.sh; export ANTHROPIC_API_KEY=…;
   python agentic-rca/evaluate.py --app both --per-family 1 --method agent --grid full` (sanity gate),
   then `--grid all` for the degradation sweep. Same runner/scoring as the baselines. This is expected
   to (a) beat the non-LLM complementarity ceiling and (b) recover the kernel-decisive faults
   (slow_db/queue_backlog/noisy_neighbor) → RQ3 "kernel as safety net" + RQ2 trajectories.

## Optional no-API
- **RQ1 cliffs:** add the deliberately trace-dependent "expected-to-break" methods (MicroRank /
  TraceRCA from RCAEval) — their collapse under 5% trace sampling is the RQ1 cliff evidence the flat
  baselines lack.
- **analyze.py:** add AC@3 (Top-3) + MRR columns from `ranked_services` (mmbaro already returns them).
- **SS kernel L2:** derive on the SS collector VM (CTF2-capable Linux stack) + push the ~50 tiny L2
  files (currently SS kernel = L1+L3 only).

## Don't rediscover
- Cluster access = user's WSL SSH master (expires after hours → re-`ssh trillium`+Duo); drive with
  `wsl.exe -d Ubuntu -- ssh trillium bash -s <<'EOF'` (heredoc, not inline arg strings).
- Two venvs: `.venv` (py3.11) stat/tools; `.venv-rca` (py3.12) RCAEval. `arrow` module = pyarrow,
  load after python. pandas-3 datetime resolution bug → use `rcaeval_adapter._unix_col`.
- mmbaro localizes only (no fault_type) → compare methods on **Top-1 service localization**
  (`ANALYZE_METRIC=service_hit`).
