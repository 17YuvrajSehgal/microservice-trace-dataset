# RQ4 budget sweep — lean & minimal configurations (2026-08-18)

Frozen v4-s0b config, 46 diagnoses ($0.40, 64% cache), auditor **PASS 46/46**.
Artifact: `/project/…/artifacts/artifact_budget_sweep_20260818.tar.gz`.

| Configuration | service | fault | both | calls | MB touched/incident |
|---|---|---|---|---|---|
| Full reference (s0b, A/A range) | 83–87% | 48–61% | 48–57% | 9.0 | 1,390 |
| **lean** (5% traces + 60s metrics + ERROR logs) | 78% | 48% | 43% | 7.6 | **24.5 (57×)** |
| **minimal** (lean − kernel) | 83% | 43% | 39% | 11.0 | **12.1 (115×)** |

- **B1 — the cheap settings are (largely) free together**: lean keeps ≥90% of full
  localization at 57× less telemetry consumption; both-correct sits at the lower edge
  of the single-run band. **Fault typing, not localization, is the budget-sensitive
  component.**
- **B2** — minimal keeps localization fully intact (83%!) at 115× but drops typing to
  39% and raises effort +45% — consistent with kernel's efficiency+typing role.
- **B3 (curio)** — TT slow_db, unsolved at full telemetry in this pass, is FULLY
  correct under lean: thinner traces reduced distraction on the borderline incident.
- Pareto frontier: minimal (cheapest localization) → lean (balanced) → full (typing).
- Also computed today: **mechanism-adjacent secondary metric** (conservative 4-pair
  map): config-of-record fault+service 52%→65% (n=46 pooled), kAll 61%→70% —
  +9–13 pts; label-strict remains primary (`mechanism_metric.py`).

Paper updated: RQ-G section + budget table, RQ-E behavior section, honesty-arc +
degradation figures (pgfplots), per-family appendix (data-generated), mechanism
metric in Discussion.
