# Decisions — 11-08-2026

Continues 09-08 (harness P1–P3 + methods #1 statistical & #2 RCAEval/mmbaro swept). Today: finished
the 3-method comparison (added trace-only baselines + AC@3/MRR), made the agent **multi-provider**,
and **validated method #3 (the LLM+kernel agent) — it beats both baselines**. All under `agentic-rca/`;
branch `agentic-tracing`. Results in `agentic-rca/RESULTS-*.md`.

## RCAEval-standard metrics: AC@1 / AC@3 / MRR
Threaded `ranked_services` through the runner; `analyze.py` now reports AC@1/AC@3/MRR (`ANALYZE_METRIC`).
mmbaro: **AC@1 46% / AC@3 63% / MRR 0.54** (kernel-decisive AC@3 73%). AC@3 ≫ AC@1 → mmbaro usually
has the target in its top-3. Service Top-1 is the metric comparable across ALL methods (RCAEval localizes,
no fault_type). `RESULTS-nonllm-baselines.md`.

## Trace-only "expected-to-break" methods (MicroRank + TraceRCA) → the RQ1 finding
Integrated both (`rcaeval_adapter.to_trace_df` → RCAEval Jaeger-µs span records; added spanID/parentSpanID;
restricted to baseline-covered operations to survive their SLO lookup; disabled tqdm). Swept the trace grid.
**Finding — NO clean cliff, and that's the result:** TraceRCA localizes only service-latency faults whose
target emits spans (svc_cpu_cap 20%, svc_net 33%) and is **0% on every DB/host/dependency fault**;
MicroRank ~0%. They never work well enough at full telemetry to fall from → floor, not cliff. **Trace-only
RCA is structurally handicapped on exactly the faults where the target isn't an instrumented service —
the faults where kernel is decisive.** Reinforces the kernel thesis from a 3rd angle. (Also: full SS traces
= 2.6M spans → these methods are very slow.)

## kernel-fold-inside-mmbaro (pyarrow) → does NOT help the published method
Enabled pyarrow in `.venv-rca` (`arrow/19.0.1` module). Folded VARYING kernel L1 KPIs
(sys_lat_p99/sys_io/sys_futex/block_ops/net_bytes; **sys_lat_p95 saturates at 500ms → useless**) into
mmbaro's metric frame, anchored to metric start (**window_start_s is RELATIVE, not unix**). Result:
`full` == `kNone` for every family — BARO ranks the ~200 cadvisor change-points far above kernel cols
(first kernel col ~rank 195). **Kernel's value isn't accessible by feature-fusion into a change-point
method; it needs an agent that reasons about wait-attribution** → motivates method #3.

## Agent made MULTI-PROVIDER (config-driven; keep Claude)
`config.py` now supports Anthropic + the OpenAI-compatible family (Azure OpenAI / Gemini / OpenAI / Ollama)
via `RCA_PROVIDER` + env keys — two SDK families cover all. `agent.py` has two tool-loops
(`_loop_anthropic`, `_loop_openai`) dispatched by `config.sdk_kind()`. GPT-5 reasoning models reject a
custom temperature → default `RCA_SEND_TEMPERATURE=0` (omit temp; use `max_completion_tokens`). Secrets
live in `.env` (git-ignored; `.env.example` template committed) — never in code. `openai` installed in the
cluster `.venv`. Prof's key = **Azure OpenAI gpt-5.4** at `…/openai/v1`.

## METHOD #3 VALIDATED — the LLM+kernel agent beats both baselines
P2 sanity gate PASSED (Azure **gpt-5.4**), 23 incidents (TT 11 + SS 12): **service 74% / fault 74% /
both 61%** — vs statistical both 38% and mmbaro service ~46%. **Recovers `slow_db` (mysql/db_latency)**,
which both baselines miss, by reasoning over **kernel L2 wait-attribution** ("mysql 100% off-CPU external
I/O wait, no saturation → induced DB latency, not an app bug"). ~15 tool-calls/incident, ~12k total
out-tokens (cheap). Misses cluster on network faults (anomaly_net/svc_net), error_storm (fault-type
confusion), dependency_outage. `RESULTS-agent-sanitygate.md`. All 3 RCA methods now work.

## Operational constraints (hard-won; critical for the full agent sweep)
- **Agent = login-node ONLY.** Compute nodes have **no internet** (verified: curl to the Azure endpoint
  times out, no proxy) → agent runs can't be Slurm jobs.
- **Login-node watchdog kills long processes.** One incident ≈ 2 min / 7.4 GB is fine; 23 back-to-back got
  killed mid-run (SS half lost). **Run the agent in short per-family chunks** (fresh process each).
- Python **block-buffers stdout** to a file → use `python -u` for live progress (else logs look empty).
- `evaluate.py --app both --out` was overwriting per app → fixed (per-app + combined json).
- **Full agent degradation sweep = 93×15 = 1,395 agent runs**: login-node-chunked + a real Azure-credit
  budget. Subsample deliberately (blind-spot families × trace/kernel axes first), do NOT brute-force.

## State
Nothing running (queue empty, no login-node procs). Three methods done + documented
(`RESULTS-stat-baseline.md`, `RESULTS-nonllm-baselines.md`, `RESULTS-agent-sanitygate.md`).
SS kernel = L1+L3 (L2 = CTF2, VM-only, deferred).
