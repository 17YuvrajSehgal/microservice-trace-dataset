# TODO — Agentic RCA under telemetry degradation

Working checklist for the research build. Rationale + design in **`research-agentic-rca.md`**;
dataset in **`DATASET_GUIDE.md`**; reuse target is **`agent-first-mvp/`** + **`stratatrace/loader.py`**.
Guardrail everywhere (Mahsa): degradation is a *deterministic offline transform on stored runs* — the
agent is **held fixed** within any sweep; never vary telemetry and agent in the same comparison.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · **(gate)** blocks downstream work.

---

## P0 — Decisions & environment (do first)
- [ ] **(gate)** Confirm the agentic-degradation direction with **Naser** (meeting action item). — **MSR dataset paper = SECOND priority** (data already collected; revisit "how to submit the dataset" later, not now).
- [x] **LLM/model**: made **configurable**, default **Claude** (`agentic-rca/config.py` — one `chat()`→`Turn`; swap via `RCA_PROVIDER`/`RCA_MODEL`, adding a model = one adapter). Temp 0 for reproducibility.
- [~] **Tool interface**: default to **in-process Python tools** for the study runner (fast, deterministic, cheap to sweep thousands of run×condition), keep the **MCP** server (`agent-first-mvp/mcp_server.py`) as the demo/interactive face. Same underlying tool fns behind both. *(Elaboration in this session's note.)*
- [x] **RCA baselines** — method #1 **statistical** (`baseline_stat.py`, done + swept) and method #2 **RCAEval/mmbaro** (`rcaeval_adapter.py`, installed in `.venv-rca` py3.12, working: TT slow_db→mysql Top-1, which the statistical baseline missed). "CARE" was a misremembered name → the real target is the **RCAEval/BARO/TORAI** family (see `non-llm-baseline.md`). TORAI (needs py3.8) deferred.
- [x] **Data access — DONE on cluster** (no laptop copy): extracted all runs' small modalities to `/scratch/yuvraj17/agentic-runs/{trainticket,sockshop}` via `agentic-rca/extract_working_set.sh` + `extract_job.sbatch` (job 2072606, whole-node debug). **93 loader-enumerable fault incidents** (43 TT + 50 SS) + baseline/normal controls; all modalities validated (kernel_l2 empty for TT — use L1+L3). Raw L0 stays in `/project` archives.
- [x] Python env — **two**: laptop `.venv` (dev), and **cluster** `.venv` on Trillium (`python/3.11`+`arrow/19.0.1`+venv, `agentic-rca/env.sh`). Both verified importable. **The study runs on the cluster** (login node has Anthropic API access; data is there).

## P1 — Harness foundation — **BUILT + VALIDATED on the cluster** (agentic-rca/)
- [x] Built fresh over the loader instead of reusing the MVP's Sock-Shop-coupled `modalities.py` (log-filename + service hardcoding). MVP kept as the interactive/demo face.
- [x] **Run enumeration + scoring** (`runs.py`): `iter_runs(app)` → 43 TT + 50 SS labeled incidents (+ manifest verification); `score(diagnosis, gt)` with host-fault + container-name tolerance.
- [x] **Four telemetry tools** (`tools.py`) over `stratatrace/loader.py`, both apps, byte-accounted: `traces` (SERVER-span p50/95/99), `logs` (error sigs), `metrics` (curated cAdvisor, counter→rate, magnitude-ranked), **`kernel`** (L1 lat peaks + L3 deviations + L2 wait-attribution when present). Validated across cpu/mem/noisy/slow_db — culprit surfaces on resource faults; slow_db correctly metrics-blind.
- [x] Known edges handled: `ground_truth["fault"]`, sibling metrics/load, `STRATATRACE_APP` per app.
- [x] **Output contract frozen** + agent loop (`agent.py`): tool-using LLM → `{root_cause_service, fault_type, evidence, confidence}` + **trajectory** (RQ2) + tokens/bytes (RQ4). Model via `config.py`.
- [x] **Evaluation runner** (`evaluate.py`): `(run × method) → predict → score → aggregate` (Top-1 service/fault/both, by-family, tool-calls/tokens). Degradation axis slots in later.

## P2 — Sanity gate **(gate — RUN blocked only on ANTHROPIC_API_KEY)**
- [x] Sample ready: `evaluate._sample(per_family=1)` → **23 incidents** (11 TT + 12 SS, all families).
- [x] **Both non-LLM baselines swept** over ALL 93 incidents × 15 conditions (not just 23): statistical (job 2074051) + RCAEval/mmbaro (job 2081090). `RESULTS-stat-baseline.md`, `RESULTS-nonllm-baselines.md`.
- [ ] **Run the LLM-agent sanity gate** `python evaluate.py --app both --per-family 1 --method agent --grid full` at 100% telemetry — **needs `export ANTHROPIC_API_KEY=…` on the Trillium login node** (has internet). Confirm Top-1 is solid before its degradation sweep.

## P3 — Degradation module → **RQ1** — **BUILT + PIPELINE PROVEN (no API)**
- [x] **Degradation module** (`degrade.py`): seeded `DegradedRun` wrapper — trace sampling, metric resample, log level, service-coverage removal, whole-modality removal, kernel tier. Sits before the reader (agent unchanged = Mahsa's guardrail). All knobs validated (trace_keep 0.25→23.8%, log ERROR 221k→722, etc.).
- [x] **Grid sweep wired** into `evaluate.py` (`--grid trace|metric|log|kernel|compensate`; loads each run once, sweeps conditions over cached frames). First RQ1 curve produced with the **statistical baseline, no API**.
- [x] **Full sweep DONE (no API):** 93 incidents × 15 conditions = 1,395 evals, statistical baseline (job 2074051, 53min). Results + interpretation in `agentic-rca/RESULTS-stat-baseline.md`. Headline: baseline robust to degradation (flat curves), kernel-blind (kNone=full), **0% on slow_db/queue_backlog** — the gap the kernel agent must close.
- [x] **Method #2 (RCAEval/mmbaro) swept** over the same 93×15 grid (`rcaeval_adapter.py`, job 2081090). Headline: the two non-LLM methods have **complementary blind spots**; both **flat under degradation** (RQ1 cliffs must come from the agent + trace-dependent methods); folding kernel into mmbaro doesn't help (**RQ3-inside-mmbaro finding**). `RESULTS-nonllm-baselines.md`.
- [ ] **Method #3 (LLM+kernel agent) sweep** over the same grid — **needs `ANTHROPIC_API_KEY`**. Expected to break the complementarity ceiling + expose the degradation cliffs the flat baselines lack.
- [x] **(no-API) MRR/AC@3** added (`ranked_services` through the runner → `analyze.py` AC@1/AC@3/MRR). mmbaro: AC@1 46% / AC@3 63% / MRR 0.54.
- [x] **(no-API) Trace-only methods MicroRank + TraceRCA integrated + swept** (`to_trace_df`, trace grid). Finding: **no cliff** — they floor-out on our fault set (TraceRCA ~5%, MicroRank ~0%) because most targets (DB/host/dead-dependency) emit no localizable spans → reinforces the kernel thesis. `RESULTS-nonllm-baselines.md`.
- [ ] **AD F1** (anomaly-detection) still open; MRR curves ready for the agent sweep.

## P4 — Trajectory logger → **RQ2**
- [x] Trajectory logging **built into `agent.py`** (persists every `tool→service→window→result→next-tool` + tokens/bytes per diagnosis, in the evaluation-runner rows).
- [ ] Compare **full vs degraded** trajectories: #calls, modality order, repeated/failed queries, **strategy change** (escalates to lower-level telemetry vs hammers dead traces). *(needs the API agent runs.)*

## P5 — Cross-modality compensation → **RQ3**  *(setup done; execution = method #3)*
- [x] **Setup framed by the baselines:** both non-LLM methods are kernel-blind (`kNone`=`full`) and fail `slow_db`/`queue_backlog`; naive kernel-fusion into mmbaro doesn't help → the kernel value must come from an agent that reasons about wait-attribution.
- [ ] **M+L+T vs M+L+T+K** with the LLM agent on the blind-spot faults + SS partial-trace-coverage (the `compensate` grid already exists). Measure **recovery rate** (adding kernel flips a wrong diagnosis to correct).
- [ ] **SS kernel L2** (currently L1+L3 only — CTF2/babeltrace): derive on the SS collector VM (CTF2-capable Linux) + push the ~50 tiny L2 files, so SS matches TT for the kernel-compensation test.

## P6 — Minimum-observability Pareto → **RQ4**
- [x] **Cost axes wired:** every tool returns `bytes_touched` and the agent/runner records tokens per diagnosis (in the result rows) — the RQ4 x-axis is already captured per run×condition.
- [ ] Join RCA accuracy to **collection cost** (bytes/CPU/latency from the repo's overhead data + tool `bytes_touched` + agent tokens).
- [ ] Search configs (e.g. `{metrics 10s, logs ERROR, traces 10%, kernel L1-critical}`); plot **accuracy vs cost**; identify **Pareto-optimal** budgets (cheapest retaining ≥90% of full RCA).

## P7 — Analysis, artifacts, write-up
- [ ] **Skill × fault × data** utility table (accuracy/efficiency per skill × fault, and which data each skill actually needs) — extends the `skill.json` `decisive_modality`/`requirements`.
- [ ] Fault × Observability-Degradation **map** (which faults survive which degradation).
- [ ] Figures: degradation curves, Pareto frontier, trajectory-adaptation plots. (Use the MVP `dashboard/` for per-run inspection.)
- [ ] Draft paper sections; keep the pre-registered predictions (`fault_catalog.md`) as the reference.

---

## Cross-cutting (keep true throughout)
- [ ] **Reproducibility**: every result keyed by `(run_id, degradation_spec, seed, rca_method)`; degraded views regenerable from the full bundle + seed.
- [ ] **Confound discipline**: degradation = data-only; agent fixed within a sweep (RQ1/3/4). Agent behavior (RQ2) is observed, not co-varied.
- [ ] **Both apps** (Sock Shop, Train Ticket) in every RQ where feasible — the shared-DB vs per-service-DB contrast is the generality claim.

## Immediate next actions (as of 2026-08-09)
**Done:** harness (P1–P3), degradation module, both non-LLM baselines swept + documented — all no-API.
1. **(API-gated — the crux) Method #3, the LLM+kernel agent.** On the Trillium login node: `source transfer/env.sh; export ANTHROPIC_API_KEY=…`, then the P2 sanity gate (`--method agent --grid full`), then the full degradation sweep (`--grid all`). This is the last RCA method and drives RQ2 (trajectories) + RQ3 (kernel safety net).
2. ✅ **(done, no-API) MicroRank/TraceRCA + MRR/AC@3** — integrated + swept; trace-only methods floor-out on our fault set (finding, `RESULTS-nonllm-baselines.md`).
3. **(no-API) SS kernel L2** — derive on the SS collector VM (CTF2-capable) so SS has L1+L2+L3 like TT.
4. **Confirm the agentic direction with Naser** (the still-open P0 gate) before heavy write-up.
