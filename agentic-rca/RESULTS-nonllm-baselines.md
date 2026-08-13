# Results — the two non-LLM RCA baselines (methods #1 + #2)

**No-API reference results.** Both methods swept over 93 incidents (43 TT + 50 SS) × 15 degradation
conditions = **1,395 evaluations each**. Metric here = **Top-1 service localization** (= RCAEval's
AC@1), the axis comparable across all methods (RCAEval only localizes; it doesn't classify fault_type).
Regenerate: `sbatch agentic-rca/sweep_stat.sbatch` / `sweep_mmbaro.sbatch`, then
`ANALYZE_METRIC=service_hit python agentic-rca/analyze.py "…/*.json"`.

- **Method #1 — statistical/heuristic** (`baseline_stat.py`): rule tree over metrics/logs/traces/kernel.
- **Method #2 — RCAEval Multi-source BARO** (`rcaeval_adapter.py` → `mmbaro`, RCAEval 1.6.0): published,
  MIT, unsupervised change-point. (M+L+T here — kernel-fold pending pyarrow in the RCAEval env.)

## Headline: the two non-LLM methods have COMPLEMENTARY blind spots (Top-1 localization, `full`)

| family | statistical | mmbaro | expected | who wins |
|---|---|---|---|---|
| anomaly_cpu / disk / mem | 100% | 100% | kernel | tie (both via stress container / change-point) |
| **noisy_neighbor** | **100%** | **0%** | kernel | **statistical** |
| **dependency_outage** | **50%** | **0%** | traces | **statistical** |
| svc_cpu_cap | 80% | 50% | kernel | statistical |
| **slow_db** | **0%** | **50%** | kernel | **mmbaro** |
| **error_storm** | **0%** | **50%** | logs | **mmbaro** |
| **svc_mem_cap** | **0%** | **50%** | logs | **mmbaro** |
| svc_net | 50% | 50% | traces | tie |
| anomaly_net / queue_backlog | 0% | 0% | traces / kernel | both fail |
| **overall (Top-1)** | ~48% | **48%** | | comparable, different faults |

**Reading:** neither non-LLM method dominates. The statistical rule-tree wins the **stress-container /
victim-vs-culprit** faults (noisy_neighbor, dependency); mmbaro's metric change-point wins the
**subtle single-service** faults the rule-tree misses (**slow_db**, error_storm, svc_mem_cap). This
complementarity is exactly the motivation for a third, adaptive (LLM + kernel) method.

## RCAEval-standard metrics (mmbaro) — AC@1 / AC@3 / MRR @ full telemetry
| subset | AC@1 (Top-1) | AC@3 (Top-3) | MRR |
|---|---|---|---|
| ALL | 46% | 63% | 0.54 |
| Sock Shop | 48% | 72% | 0.59 |
| Train Ticket | 44% | 53% | 0.48 |
| kernel-decisive faults | 54% | 73% | 0.62 |
AC@3 ≫ AC@1: mmbaro usually has the target **in its top-3** even when not #1 (MRR 0.54). MRR is
**flat across trace retention** (0.54 at 100%→5%) — robust, as expected for a metric-change-point method.

## Trace-only "expected-to-break" methods (MicroRank / TraceRCA) — the RQ1 finding
Integrated MicroRank + TraceRCA (RCAEval, `rcaeval_adapter.to_trace_df` → Jaeger-µs span records)
and swept the trace-retention grid. **Result — there is no clean cliff, and that is the finding:**
- **TraceRCA** localizes only the service-latency faults whose target emits spans (svc_cpu_cap 20%,
  svc_net 33%) and scores **0% on every DB / host / dependency fault** — those targets (mysql,
  stress containers, a dead dependency) have **no localizable spans**. Overall AC@1 ≈ 5%.
- **MicroRank** ≈ 0% across the board on our fault set.
- Because they never work well *at full telemetry* on our fault distribution (heavy on infra/DB/host
  targets), there is nowhere to fall from — no dramatic trace-sampling cliff, just a low floor.

**Takeaway:** trace-only RCA is **structurally handicapped on exactly the faults where the target is
not an instrumented service** — the same faults where kernel telemetry is decisive. This reinforces
the kernel-safety-net thesis (RQ3) from a third angle. (Our full-instrumentation traces — SS 2.6M
spans — also make these methods very slow, itself an operability point.)

## RQ1 — both non-LLM methods are essentially FLAT under degradation

| axis | statistical | mmbaro |
|---|---|---|
| trace 100→5% | 38→34% (both-hit) / stable (svc) | 48% flat |
| metric / log / kernel | flat | flat |

Both ride **coarse, robust signals** (change-point, stress detection) that survive trace/log thinning,
so their RQ1 curves are nearly flat — the interesting **degradation cliffs will come from the LLM
agent** (which reasons over fine-grained traces/kernel) and from deliberately trace-dependent methods
(MicroRank/TraceRCA — the "expected-to-break" references).

## RQ3 — the kernel gap is wide open for method #3
Both non-LLM methods are **kernel-blind** (`kNone` = `full` for every family) and **both fail
`queue_backlog` (0/0)** and `slow_db`-for-statistical — the pre-registered kernel-decisive faults.
So the "kernel as safety net" claim rests entirely on the **LLM + kernel agent** recovering
`slow_db` / `queue_backlog` / `noisy_neighbor` via the kernel tool (L2 wait-attribution for TT;
L1+L3 for SS). That is the study's central test, now cleanly set up by these two references.

## RQ3-inside-mmbaro: naive kernel fusion does NOT help the published method (a finding)
We enabled `pyarrow` in the RCAEval env and **folded discriminative, time-varying kernel L1 KPIs**
(`sys_lat_p99`, `sys_io`, `sys_futex`, `block_ops`, `net_bytes`) into mmbaro's `metric` frame as extra
`<svc>_kern_<kpi>` columns (anchored to the metric time axis; `sys_lat_p95` excluded — it saturates at
a 500 ms cap = no change-point). Result: **localization is unchanged — `full` == `kNone` for every
family.** BARO's RobustScorer ranks the ~200 cadvisor metric change-points far above the kernel columns
(first kernel column landed at rank ~195), so adding kernel as more columns doesn't shift the top
ranks. **Takeaway:** the kernel's diagnostic value is not accessible by naive feature-fusion into a
metric-change-point method; it requires an agent that *reasons* about kernel wait-attribution (method
#3). This is a clean motivation for the LLM+kernel agent, not a defect.

*Caveat:* SS uses kernel L1+L3 only (L2 = CTF2, VM-only); TT has L1+L2+L3.
