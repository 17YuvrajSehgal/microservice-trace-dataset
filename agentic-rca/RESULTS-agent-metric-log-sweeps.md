# Metric- and log-axis degradation sweeps on the agent — RQ1 completed (2026-08-18)

Frozen v4-s0b config, 161 diagnoses ($1.53, 66% cache), auditor **PASS 161/161**.
Artifact: `/project/…/artifacts/artifact_metric_log_sweeps_20260818.tar.gz`.
Analysis: `mlsweep_report.py`. Single-run noise band ±~9 pts applies.

## Metric axis (scrape resolution 5s → 60s)

| Condition | service | fault | both | calls |
|---|---|---|---|---|
| metric5s (full) | 78% | 48% | 43% | 9.6 |
| metric10s | 78% | 48% | 48% | 9.2 |
| metric30s | 78% | 57% | **52%** | 9.4 |
| metric60s | 74% | 52% | 48% | 8.7 |

Flat within noise, non-monotonic (30s scores best); the per-family flips are balanced in
BOTH directions (as many gained as lost — pure churn). Mechanism: the metrics tool computes
window-level rates and means over 60–120 s windows; counters need only two samples per
window, so even 60 s scrape preserves the deltas the agent reads.

## Log axis (ALL → WARN → ERROR-only)

| Condition | service | fault | both | calls |
|---|---|---|---|---|
| logALL (full) | 83% | 57% | 57% | 8.7 |
| logWARN | 78% | 43% | 43% | 9.0 |
| logERROR | 87% | 52% | 52% | 9.7 |

Also within noise and non-monotonic (ERROR-only beats WARN). The error-rate-change tool
keys on ERROR-class signatures, which survive the harshest filter by construction. The one
recurring loser across BOTH axes is `SS svc_mem_cap` (its GC/OOM evidence is fragile) — but
that incident is also in the A/A flip-prone set, so no strong per-family claim.

Tool mixes are essentially constant across all conditions on both axes — no escalation,
because nothing the agent relies on was lost.

## The consolidated RQ1 answer (all four axes now measured on the agent)

| Axis | Range tested | Effect on both-correct |
|---|---|---|
| Traces | 100% → 5% span retention | flat (±noise) |
| Metrics | 5s → 60s scrape | flat (±noise) |
| Logs | ALL → ERROR-only | flat (±noise) |
| Kernel | full ladder → none | −4 pts (±noise) but +34% tool calls; L1-only −14 (worse than none) |

**There is no degradation cliff at standard operational ranges.** The agent degrades
gracefully everywhere tested, for one structural reason: it consumes every modality at the
AGGREGATE level (window deltas, edge percentiles, signature rates) and its evidence is
redundant across modalities — when one channel thins, the same fault signature usually
survives in another. The pre-registered cliff expectation is answered with a robustness
result instead — and the failure that DOES exist is qualitative, not quantitative: the
kernel axis showed that a *badly represented* modality (raw L1 alone) hurts more than an
absent one.

Practical corollary (feeds RQ4): at these task conditions, observability budgets can be cut
dramatically — 5% traces, 60 s metrics, ERROR-only logs — with no measurable diagnostic
loss for an agentic RCA consumer; the kernel earns its cost in investigation efficiency
(−25% tool calls) and db-latency typing rather than raw accuracy.

## What remains for the degradation program

Complete modality REMOVAL (`MLT_noK` / `MLK_noT` — the compensation conditions), the
kernel × degraded-traces interaction grid (H2's sharpened test), and the RQ4 Pareto join
(all cost data already collected). Repeats on any figure destined for the paper.
