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

*Caveat:* mmbaro's kernel-tier conditions are no-ops (no pyarrow in `.venv-rca` → kernel-fold skipped);
adding pyarrow enables RQ3-inside-mmbaro. SS uses kernel L1+L3 only (L2 = CTF2, VM-only).
