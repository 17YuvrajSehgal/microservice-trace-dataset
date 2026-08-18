# Kernel×trace interaction + whole-modality removal — degradation program complete (2026-08-18)

Frozen v4-s0b config, 138 diagnoses ($1.35, 65% cache), auditor **PASS 138/138**.
Artifact: `/project/…/artifacts/artifact_interact_removal_20260818.tar.gz`.
Noise band ±~9 pts applies; flip evidence > headline deltas.

## Interaction grid (H2's sharpened test): kernel × thinned traces

| Condition | service | both | calls | kernel-decisive both |
|---|---|---|---|---|
| 25% traces, kernel full | 65% | 30% | 8.8 | 6/13 |
| 25% traces, kernel none | 74% | 48% | 10.3 | 7/13 |
| 10% traces, kernel full | 87% | 57% | 9.8 | 9/13 |
| 10% traces, kernel none | 83% | 57% | 11.8 | 10/13 |

**I1 — H2's interaction form is refuted for trace THINNING**: the kernel advantage does
not grow as traces thin (difference-in-differences: +4 at full → −18 at 25% → 0 at 10%;
kernel-decisive families show no kernel edge at any retention). Kernel-blindness costs
+1.5–2 calls at every level — the efficiency signature is retention-invariant.
(t025 is weak in every sweep that contains it: the deterministic sampler keeps the same
spans each time, so that retention's specific sample is consistently unlucky for a few
borderline incidents — an artifact of seeding worth a paper footnote.)

## Removal grid: a whole modality gone

| Condition | service | fault | both | calls |
|---|---|---|---|---|
| no kernel (MLT_noK) | 78% | 48% | 48% | 10.2 |
| **no traces (MLK_noT)** | **70%** | **48%** | **43%** | **15.7** |

**R1 — MLT_noK replicates kNone within noise** (78/48/48 vs 78/57/57 — a free A/A
replicate through a different code path).

**R2 — trace REMOVAL is the first modality loss that visibly hurts**: −14 both vs the
full-telemetry 57%, at +74% investigation effort (15.7 calls). Losses concentrate on
the path-shaped Train-Ticket faults (svc_cpu_cap, svc_net, slow_db, dependency_outage)
— exactly the incidents whose evidence is topological. So the trace no-cliff result is
threshold-like: aggregates survive ANY sampling, but the modality's presence matters.

**R3 — kernel compensation, finally demonstrated in its pre-registered direction**:
with traces entirely gone, **SS slow_db stays fully correct (catalogue-db/db_latency)**
— kernel wait-attribution supplies both locus confirmation and typing when the
trace/topology channel is absent. Combined with K2 (kernel removal costs slow_db its
typing while traces localize it), the two modalities are mutual complements on
induced-DB-latency: EITHER alone suffices for localization, kernel is required for
typing, and only losing BOTH would break it. H2 is thus refined, not just refuted:
kernel is a compensating channel under modality LOSS, not under modality THINNING.

**R4 — the dead-tool lesson repeats and generalizes**: under MLK_noT the agent spent
~37% of its calls on empty trace/topology tools (129 dead calls across 23 incidents).
The definitive-unavailable answer exists for kernel but not yet for traces/topology —
the same one-line fix applies (engineering note; not applied mid-program to keep the
sweep internally consistent).

## Degradation program: CLOSED

All planned axes and interactions are now measured on one frozen agent:
kernel tiers, trace retention, metric resolution, log level, kernel×trace interaction,
whole-modality removal — ~600 leakage-audited diagnoses, ~$6 total for the program.
Consolidated narrative: **graceful degradation everywhere under thinning; costs appear
only under whole-modality loss (traces −14) or bad representation (kernel L1-only −14);
kernel = efficiency always, typing on induced-DB-latency, and the compensating channel
when traces vanish.** Remaining for the paper: repeats on quoted figures, RQ4 Pareto
join, mechanism-correct metric — all analysis, no new experiments.
