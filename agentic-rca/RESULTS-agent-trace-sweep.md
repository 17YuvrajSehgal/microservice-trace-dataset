# Trace-retention degradation sweep on the agent — RQ1, trace axis (2026-08-18)

Frozen v4-s0b config (brief on, skills off), `--grid trace`: **100 / 50 / 25 / 10 / 5% span
retention × 23 gate incidents = 115 diagnoses**. Leakage auditor **PASS 115/115**; $1.15
(63% cache). Artifact: `/project/…/artifacts/artifact_trace_sweep_20260818.tar.gz`.
Analysis: `tsweep_report.py`. Single-run caveat: ±~9 pts per condition (measured A/A).

## Headline: NO cliff — the agent is flat to 5% span retention

| Retention | service | fault | both | calls |
|---|---|---|---|---|
| 100% | 78% | 52% | 52% | 9.0 |
| 50% | 83% | 57% | 52% | 8.7 |
| 25% | 74% | 52% | 43% | 9.3 |
| 10% | 87% | 57% | **57%** | 9.3 |
| 5% | 74% | 43% | 43% | 9.3 |

Non-monotonic wobble inside the noise band (10% retention scoring best proves it is noise).
Per-family: **18/23 incidents give identical marks at every retention level**; the flips
concentrate in the five already-known borderline incidents. Tool calls flat (~9).

## Finding T1 — why there is no cliff (mechanism, from the RQ2 tool mix)

The agent's span consumption is **aggregate-level**: the brief's latency tops and
`query_topology`'s edge p95s — statistics that survive uniform whole-trace sampling
(5% of 2.4M spans is still 120k spans; edge ratios persist with smaller n). Direct
`query_traces` calls are nearly absent at every retention (1–5 total across 23 incidents —
topology and the brief have replaced raw trace reading). Tool mix is essentially constant
across retentions: there is no escalation because nothing the agent relies on was lost.
The baselines were flat because they never extracted value from traces; **the agent is flat
because its trace value is statistical and its evidence is redundant across modalities** —
same curve, opposite reason.

## Finding T2 — trace-expected families were already fault-typing-limited

The 6 trace-expected incidents sit at 33% both at FULL retention (error_storm / svc_net /
anomaly_net typing boundaries — see the campaign label analysis) and stay ~flat as spans
thin. Their problem is label semantics, not span availability.

## Finding T3 — RQ4 implication: traces are massively over-collected for this task

If 5% whole-trace sampling preserves agent accuracy, the trace modality's collection cost
can drop ~20× with no diagnostic loss at full-stack conditions — a headline datapoint for
the minimum-observability-budget analysis (to be joined with bytes/$ in the RQ4 Pareto).

## Caveats / what could still produce a cliff

Uniform whole-trace sampling is the gentlest degradation: aggregates survive by design.
Harsher regimes remain untested on the agent and are the natural follow-ups: complete
modality removal (`MLK_noT`, already in the `all` grid), per-span (not per-trace) drops,
<1% retention, and the kernel × degraded-traces interaction (H2's real test), where trace
thinning plus kernel absence may finally interact.

## Degradation program status

Kernel axis ✅ (RESULTS-agent-kernel-sweep.md) · trace axis ✅ (this) · metric/log axes and
the kernel×trace interaction remain · RQ4 Pareto join ready once those land.
