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
- [ ] Pick **RCA baselines** — **DEFERRED (later)**: statistical (reuse `agent-first-mvp/engine/rca.py`) + CARE/RCAEval.
- [x] **Data access — DONE on cluster** (no laptop copy): extracted all runs' small modalities to `/scratch/yuvraj17/agentic-runs/{trainticket,sockshop}` via `agentic-rca/extract_working_set.sh` + `extract_job.sbatch` (job 2072606, whole-node debug). **93 loader-enumerable fault incidents** (43 TT + 50 SS) + baseline/normal controls; all modalities validated (kernel_l2 empty for TT — use L1+L3). Raw L0 stays in `/project` archives.
- [x] Python env — **two**: laptop `.venv` (dev), and **cluster** `.venv` on Trillium (`python/3.11`+`arrow/19.0.1`+venv, `agentic-rca/env.sh`). Both verified importable. **The study runs on the cluster** (login node has Anthropic API access; data is there).

## P1 — Harness foundation (reuse, don't rebuild)
- [ ] Smoke-test `agent-first-mvp` on one pulled run (`demo_cli.py` / `mcp_server.py` `discover_skills`→`run_skill`).
- [ ] **Manifest-driven run enumeration** — parse `release/DATASET_MANIFEST.csv` (Sock Shop) + the Train Ticket manifest into records `{run_id, app, fault_family, target_service, expected_winning_modality, verification, dir}`. (`loader.list_runs()` only walks a filesystem.)
- [ ] Wire the **four telemetry tools** over `stratatrace/loader.py` (clean DataFrames) and/or `agent-first-mvp/engine/modalities.py` (byte-counted): `metrics`, `logs`, `traces` (exist) + **add a `kernel` tool** at parity (wrap L1 parquet + L2 wait-attribution + L3 digest; remember `STRATATRACE_APP`).
- [ ] Fix known edges: `ground_truth` is nested under `["fault"]`; sibling metrics/load via `<run_id>_metrics`/`_load.csv`; set `STRATATRACE_APP` per app.
- [ ] Freeze the **agent output contract**: `{root_cause_service, fault_type, evidence, confidence}` — identical for all 3 RCA families + all conditions.

## P2 — Sanity gate **(gate — do before any degradation)**
- [ ] Select **~20 incidents** (spread across fault families + both apps).
- [ ] Run the LLM agent at **100% telemetry**; confirm **Top-1 is solid** (if it can't diagnose full data, degradation results are meaningless).
- [ ] Run the **statistical** + **CARE** baselines on the same 20; record Top-1/3/MRR.
- [ ] Build the **evaluation runner**: `(run, condition, rca_method) → prediction → score vs ground_truth` → aggregate table.

## P3 — Degradation module → **RQ1**
- [ ] Build the **degradation module** (seeded, deterministic, offline): trace sampling {100/50/25/10/5%}, metric resample {5→10/30/60s}, log level {ALL/WARN+/ERROR+}, **service-coverage removal**, whole-modality removal, kernel tier {L0/L1/L2/L3 / critical-only}. Input `(run, spec, seed)` → a degraded view; keep it **before** the reader.
- [ ] Sweep the grid; produce **degradation curves + cliff locations** (AD F1 + RCA Top-1/3/MRR per condition).

## P4 — Trajectory logger → **RQ2**
- [ ] Persist the agent **trajectory** per diagnosis: `tool → service → time-range → result → next-tool` + tokens (+ per-tool `bytes_touched` from `modalities.py`).
- [ ] Compare **full vs degraded** trajectories: #calls, modality order, repeated/failed queries, **strategy change** (escalates to lower-level telemetry vs hammers dead traces).

## P5 — Cross-modality compensation → **RQ3**
- [ ] **M+L+T vs M+L+T+K** on the blind-spot faults (`slow_db`, `queue_backlog`, `noisy_neighbor`) + Sock Shop's partial-trace-coverage services.
- [ ] Measure **recovery rate**: how often adding a modality flips a wrong diagnosis to correct (kernel-as-safety-net evidence).

## P6 — Minimum-observability Pareto → **RQ4**
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

## Immediate next 3 actions
1. Settle P0 decisions (Naser confirm, model, tool interface, baselines).
2. Pull ~20 dev runs' small data locally (`dev-runs/`).
3. Build the **evaluation runner + degradation module** around the existing MVP (the critical-path new code).
