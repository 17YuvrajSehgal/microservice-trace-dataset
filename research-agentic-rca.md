# Research direction v3 — Agentic RCA under telemetry degradation

*Sharpened after the 2026-08-07 supervisor meeting (notes:
`meeting-notes/chat-notes-07-08-2026.txt`). This supersedes the framing in `msr-research.md`
for the near-term work; the StrataTrace dataset and fault catalog are unchanged and are exactly
the asset this study needs — **no new data collection is required.***

---

## 0. What changed (the pivot)

The v2 plan (`msr-research.md`) was a **per-task modality-ablation study** ("how much does each
modality buy you?"). The supervisor meeting sharpened this into a more **actionable, operator-facing
and agent-facing** question, and reframed the vehicle as an **agentic RCA system** rather than a
static ablation:

> **"How much observability can we lose before diagnosis breaks — and can an agent adapt (or does
> kernel telemetry act as a safety net) when it does?"**

Two reasons this is stronger: (1) *degradation thresholds* ("RCA is fine down to 25% traces but
collapses at 5%") are directly actionable, unlike "traces are useful"; (2) it lets us study **agent
behavior** — does an RCA agent *shift to lower-level telemetry* when application visibility
degrades, or does it stubbornly keep querying dead traces? That behavioral finding exposes a real
weakness in current RCA agents and is novel.

**Provenance of the design:** the RQs below fuse (a) the supervisor's degradation framing, (b)
Yuvraj's Ciena MVP idea (an agent that starts from a minimal telemetry set and *escalates to
lower-level data like kernel traces when it struggles* — the MVP correctly diagnosed all 3 injected
anomalies), and (c) a refined 4-RQ articulation the team liked. The existing `agent-first-mvp`
(in the related agent repo) is the starting point for the agent.

---

## 1. Research questions

**RQ1 — Robustness to degradation (the headline).**
Build **one** agentic RCA system with four telemetry tools (metrics / logs / traces / kernel).
Produce **degraded copies offline** — trace retention {100, 50, 25, 10, 5}%, metric step
{5→10, 30, 60}s, log level {ALL → WARN+ → ERROR+ / dropping}, and **service-coverage removal**
(uninstrument N services). Run the *same agent* on every condition and measure AD + RCA
(**Top-1 / Top-3 / MRR**). *Expect nonlinear cliffs* (e.g. 100→25% ≈ flat, 25→5% collapse) — the
cliff location per fault/modality is the contribution.

**RQ2 — Investigation strategy (agent behavior).**
Instrument the agent: for every diagnosis log its **trajectory** — `tool called → service queried →
time range → result → next tool`, plus tokens. Compare trajectories **full vs degraded**: number of
calls, order of modalities, repeated/failed queries, and — the key question — **does the agent
change strategy when evidence disappears?** ("shifts to lower-level telemetry" = adaptive; "keeps
hammering degraded traces" = a diagnosable weakness).

**RQ3 — Cross-modality compensation (kernel as a safety net).**
Remove/degrade one modality and compare e.g. **M+L+T vs M+L+T+K**. Measure **how often adding a
modality recovers a previously-wrong diagnosis.** StrataTrace is uniquely suited: kernel covers
services even where application tracing is *incomplete* (Sock Shop deliberately traces only 6/14
services), and the fault catalog **pre-registers** the blind-spot faults where kernel should win
(`slow_db`, `queue_backlog`, `noisy_neighbor`). The claim to test: **kernel telemetry is an
observability safety net** that restores diagnostic accuracy lost to degraded higher layers.

**RQ4 — Minimum observability budget (the Pareto frontier).**
Reuse the RQ1 degradation grid + the repo's **measured per-modality collection cost** (an existing
asset). Search configurations like `{metrics 10s + logs ERROR + traces 10% + kernel L1-critical}`
and plot **RCA accuracy vs cost** (bytes / CPU / collection latency / agent tool-tokens). Identify
**Pareto-optimal configs** — the cheapest setups that retain ≥90% of full-observability RCA. This
is a knob an operator can actually turn.

---

## 2. The critical methodological guardrail (do not confound two axes)

From the meeting (Mahsa's point): *"If the question is about the difference of data modalities it is
better to keep the rest of the pipeline unchanged. We cannot measure the effect of skills/agents
**and** the effect of telemetry changes at the same time."* This is the central design constraint:

- **Axis A — telemetry degradation (RQ1/RQ3/RQ4):** hold the **agent and pipeline fixed**; vary only
  the *data* fed to the tools. This isolates the effect of *what telemetry survives*.
- **Axis B — agent behavior (RQ2):** the agent's *trajectory* is the dependent variable, observed
  *while* Axis A varies. We never simultaneously change the agent design and the telemetry within a
  comparison.

Corollary: to make RQ1/RQ3/RQ4 clean, degradation is a **deterministic, offline transform on a
stored run** (not a re-collection, not an agent change) — same incident, same ground truth, only the
telemetry thinned. Every degraded view is reproducible from the full bundle + a seed.

---

## 3. Three RCA approaches (so the agent isn't the only lens)

Per the meeting, evaluate the same incidents with three RCA families so findings aren't
LLM-artifacts:
1. **Statistical / heuristic** baseline (e.g. change-point + metric-anomaly + trace-error
   propagation) — cheap, deterministic.
2. **Established RCA method** — e.g. **RCAEval / CARE**-style (a well-perceived published approach) as
   a strong non-LLM reference.
3. **LLM / agentic** — the tool-using single agent (the focus), which is *also* the only one that can
   produce RQ2's investigation trajectories.

Degradation (Axis A) is applied identically to all three; the agent additionally yields Axis B.

---

## 4. System architecture (the harness)

```
StrataTrace run bundle (full)
        │
        ▼
[ degradation module ]  ── deterministic, seeded transforms (trace %, metric step, log level,
        │                    service-coverage removal) → a "degraded view" of the same run
        ▼
[ StrataTrace data reader ]  ── stratatrace/loader.py: one run → aligned per-modality frames
        │
        ▼
[ 4 telemetry tools / MCP endpoints ]   metrics · logs · traces · kernel   (deterministic,
        │                                each answers scoped queries over ONE modality)
        ▼
[ single RCA agent ]  (statistical | CARE-style | LLM-agent)
        │  └── [ trajectory logger ]  (RQ2: every tool call, service, window, result, next tool, tokens)
        ▼
structured answer: { root_cause_service, fault_type, evidence, confidence }
        │
        ▼
[ evaluation runner ]  ── vs ground_truth.json → Top-1/Top-3/MRR, AD F1, + cost from the config
```

Design notes:
- The **four tools** mirror the four modalities and are **deterministic** (given a run + query, a
  fixed answer) so the only stochasticity is the agent's reasoning. They read the derived, tabular
  forms where possible (kernel **L1 parquet** + **L3 digest**; metrics parquet; OTLP spans; logs).
- The agent's contract is a fixed schema `{root_cause_service, fault_type, evidence, confidence}`
  so all three RCA families and all degradation conditions are scored identically.
- The **degradation module sits *before* the reader** so every downstream component is oblivious to
  whether it's seeing full or thinned telemetry — that's what keeps Axis A clean.

### 4b. What already exists — REUSE, don't rebuild (from the 2026-08-07 repo inventory)

A working agentic RCA MVP is already in this repo under **`agent-first-mvp/`** (built 30-07 on this
branch; the same MVP Yuvraj demoed to Ciena). Map to the harness:

| Harness component | Already exists as | Reuse / change |
|---|---|---|
| **4 telemetry tools** | `agent-first-mvp/engine/modalities.py` — `span_latency`, `log_signals`, `metric_changepoint`, each **returning `(result, bytes_touched)`** (window-scoped, byte-accounted) | Reuse: the byte accounting *is* RQ4's cost x-axis. Add a **kernel tool** (wrap `derive_kernel_l1/l2` + `kernel_l3.jsonl`). Optionally back them with `stratatrace/loader.py` DataFrames. |
| **Agent + skills** | `agent-first-mvp/mcp_server.py` (FastMCP: `discover_skills`, `phase1_requirements`, `run_skill`, `query_result`, `list_runs`; `diagnose` prompt) + **5 skill contracts** `skills/*/skill.json` (cpu-saturation, db-slowness, dependency-outage, error-storm, noisy-neighbor) | Reuse. Each skill already declares `decisive_modality` + per-modality `requirements` — **that is Yuvraj's "which skill needs which data" table, half-built.** Extend to all fault families. |
| **RCA approach #1 (deterministic/statistical baseline)** | `agent-first-mvp/engine/rca.py` — non-hallucinating rule-scored deciders + optional `narrate` LLM layer over the *same* evidence | Reuse as the **statistical baseline** of the 3-RCA comparison. The `narrate` hook is where the LLM/agent layer plugs in. |
| **Data reader** | `stratatrace/loader.py`: `load_run(dir)→Run`, `list_runs(traces_root)`, `Run.spans()/logs()/metrics()/kernel_l1()/l2()/l3()/load()` (clean DataFrames, empty-not-error on missing modality) | Reuse as the tool backend. Note: `ground_truth` is nested under `["fault"]`; set `STRATATRACE_APP` for kernel tools; sibling metrics/load resolved via `<run_id>_metrics`/`_load.csv`. |
| **Orchestration** | `engine/phase2.py` (collect→attribute→onset→reason), `runs.json` replay registry, HTML `dashboard/` | Reuse the pipeline shape + dashboard for result inspection. |

**What is genuinely MISSING and must be built (this is the real P2-P4 work):**
1. **Degradation module** (§5) — deterministic seeded offline transforms on a stored bundle. *New.*
2. **Trajectory logger** (RQ2) — record every `tool→service→window→result→next-tool` + tokens. *New*
   (the MCP server has the hooks but doesn't persist trajectories yet).
3. **Evaluation runner** — enumerate runs (parse `release/DATASET_MANIFEST.csv` + the TT manifest;
   `list_runs()` only walks a filesystem), run the agent × degradation grid, score Top-1/3/MRR + AD
   vs `ground_truth.json["fault"]`, aggregate. *New.*
4. **Kernel tool** at parity with the other three (the MVP's `modalities.py` covers spans/logs/metrics
   but the kernel read lives in `engine/wait_attribution.py` / the derivers — wrap it as a 4th tool).
5. **CARE/RCAEval baseline** (RCA approach #2) — external, to be integrated.

So the agent + 3-of-4 tools + a deterministic baseline + 5 skills **already run**; the study-specific
machinery (degradation, trajectories, evaluation-at-scale) is the new build. That is a strong start.

---

## 5. The degradation module (what "losing observability" means, concretely)

Deterministic offline transforms on a stored bundle (seeded, reproducible):
| Knob | Full → degraded | Applied to |
|---|---|---|
| **Trace sampling** | keep {100, 50, 25, 10, 5}% of spans/requests (head- or tail-based) | `otlp/spans.jsonl` |
| **Metric temporal resolution** | resample 5 s → {10, 30, 60}s | the metrics frames |
| **Log verbosity** | drop below {INFO, WARN, ERROR} | `logs/*.log` |
| **Service coverage** | remove modality X for N chosen services (mimic partial instrumentation) | any modality, per-service |
| **Modality removal** | drop a whole modality (for RQ3 compensation) | any of M/L/T/K |
| **Kernel tier** | swap L0/L1/L2/L3 or restrict kernel to "critical services only" | kernel tool |

Each condition is a `(run_id, degradation_spec, seed)` triple → a view; results are keyed by it.

---

## 6. Evaluation protocol

- **Sanity gate first (meeting requirement):** run the agent on **~20 incidents at 100% telemetry**
  and confirm it actually diagnoses them (Top-1 reasonable) *before* any degradation study — if it
  can't diagnose with full data, degradation results are meaningless.
- **Metrics:** RCA **Top-1 / Top-3 / MRR** on `root_cause_service` + `fault_type`; **AD** F1/AUROC
  + detection latency; RQ2 trajectory stats (calls, modality order, repeats, tokens); RQ4 cost
  (bytes, CPU, tokens) from the config.
- **Labels:** `ground_truth.json` per run (`target_service`, `fault name/family`, blast radius,
  `expected_winning_modality`, `target_trace_visibility`, injection window). The blind-spot faults
  (`slow_db`, `queue_backlog`, `noisy_neighbor`) are the RQ3 stress cases.
- **Two apps** (Sock Shop, Train Ticket) → the shared-DB vs per-service-DB contrast tests
  generality; Sock Shop's built-in partial trace coverage is a *free* RQ3 condition.

---

## 7. Phased plan

1. **P0 — Harness skeleton.** Data reader → 4 deterministic tools → single LLM agent → structured
   answer → evaluation runner. Reuse `stratatrace/loader.py` + `agent-first-mvp`. *No degradation
   yet.*
2. **P1 — Sanity gate.** 20 incidents (mix of fault families, both apps) at 100% telemetry; confirm
   Top-1 is solid. Establish the statistical + CARE-style baselines on the same 20.
3. **P2 — Degradation module + RQ1.** Add the seeded transforms; sweep the trace/metric/log/coverage
   grid; produce the degradation curves + cliff locations.
4. **P3 — RQ2 trajectories.** Turn on the trajectory logger; analyze adaptation vs full/degraded.
5. **P4 — RQ3 compensation.** M+L+T vs M+L+T+K on the blind-spot faults + partial-coverage services.
6. **P5 — RQ4 Pareto.** Join accuracy to the collection-cost numbers; find the Pareto-optimal budgets.

Yuvraj's framing (from the notes) rides on top of this: build the agent's **skills** (metric / log /
trace / kernel investigation), then use it to discover **which skill is useful for which fault type
and which data each skill needs** — a *skill × fault × data* utility table falls out of P2-P4.

---

## 8. Why StrataTrace is exactly the right asset (no re-collection)

- Full traces + logs + metrics + **kernel** + fault ground truth + **aligned timestamps** already
  exist for 49 (Train Ticket) + 46 (Sock Shop) labeled incidents — degradation is an *offline
  transform*, so we never recollect.
- The fault catalog **pre-registers** where each modality should win (incl. the blind-spot faults) —
  ready-made hypotheses for RQ3.
- The repo already measured **per-modality collection cost** — the x-axis of RQ4's Pareto plot.
- If the agent + current data *cannot* solve some incident, that is itself a result: flag it as
  novel → either targeted new collection or "unsolvable with this telemetry/skill set."

---

## 9. Open decisions — confirm before heavy build

1. **Scope check with Naser (meeting action item).** Naser leaned toward *agentic observability* over
   the MSR-ablation framing; the team said "ask him clearly before further effort." Confirm the
   agentic-degradation direction (and whether the MSR dataset paper still ships alongside) before P2+.
2. **Confound discipline (Mahsa).** Keep Axis A (telemetry) and Axis B (agent) separated in every
   comparison, per §2 — bake this into the harness (degradation is data-only; the agent is fixed
   within a degradation sweep).
3. **RCA baselines.** Confirm the exact statistical method and the CARE/RCAEval variant to compare
   against, and whether they run on the same tool interface.
4. **Agent + model.** Which LLM(s), which tool/skill framework (MCP endpoints vs in-process tools),
   token-budget policy — decided at P0.

---

*This file is the near-term compass. `msr-research.md` (§7 tasks, RQs) and `fault_catalog.md`
(pre-registered per-fault predictions) remain the authoritative background; `DATASET_GUIDE.md`
onboards the dataset itself.*
