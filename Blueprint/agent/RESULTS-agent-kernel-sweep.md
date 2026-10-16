# Kernel-tier degradation sweep on the agent — the RQ3 result (2026-08-17)

First agent-side kernel ablation, now possible symmetrically (both apps L1+L2+L3).
Config of record (brief on, skills off), `--grid kernel`: **kAll / kL1-only / kL3-only /
kNone × 23 gate incidents = 92 diagnoses**, leakage-masked, auditor **PASS 92/92**,
$0.82 total (73% cache hits). Single-run caveat applies throughout: condition aggregates
carry ±~9 pts (measured A/A); the flip lists are the stronger evidence.
Artifact: `/project/…/artifacts/artifact_kernel_sweep_20260817.tar.gz`. Analysis:
`ksweep_report.py`.

## Headline

| Tier | service | fault | both | avg calls |
|---|---|---|---|---|
| **kAll** (L1+L2+L3) | **83%** | **61%** | **61%** | **9.1** |
| kL1 only | 74% | 48% | 43% | 10.1 |
| kL3 only | 78% | 57% | 57% | 10.0 |
| kNone | 78% | 57% | 57% | 12.2 |

## Finding K1 — with v4's cross-modality tools, removing kernel entirely costs little
## accuracy at FULL telemetry… but costs ~25% more work

kNone sits 4 pts below kAll on both-correct (within the noise band) — because the
improved generic tools were *built* to surface equivalent evidence elsewhere: host
anomalies read from node metrics, the co-tenant from limit_signals, SS slow_db's locus
from peer-edge convergence. The agent visibly compensates: 9.1 → 12.2 calls (+34%).
**Kernel telemetry's robust value at full telemetry is efficiency, not rescue.** The
baselines make the contrast: they cannot use kernel at all (kNone ≡ full for them);
the agent converts it into shorter investigations.

## Finding K2 — the one stable accuracy loss is exactly the pre-registered mechanism

The only kAll→kNone both-flip is **SS slow_db (Y → service-only)**: without wait
attribution the agent still localizes catalogue-db but loses the `db_latency` typing —
kernel evidence is what turns "the DB is the locus" into "induced DB latency, not an
app bug". Same in kL3. (TT slow_db missed in all tiers this run — its usual borderline
behavior.) The tier ladder on SS slow_db: kAll ✓, kL1 ✓, kL3 svc-only, kNone svc-only
— the typing signal lives in L1's syscall-latency numbers and L2's wait profile, not
in the L3 narrative.

## Finding K3 (the surprise) — a PARTIAL kernel view is worse than none

kL1-only (raw per-second KPIs without the L3 deviation framing or L2 wait profile) is
the WORST tier: 43% both, −14 vs kNone, losing four families kNone keeps
(noisy_neighbor, svc_mem_cap, dependency_outage, svc_net) with zero gains. Raw kernel
numbers without baseline-anchored interpretation appear to pull the agent into
kernel-noise chases. **Representation quality matters more than kernel presence** —
directly relevant to RQ6-style "which representation" questions and a caution for
anyone shipping raw kernel counters to an LLM.

## Finding K4 — kernel-decisive families hold at 85% service in EVERY tier

The 13 kernel-decisive incidents stay at 85% service / 69–77% both across all tiers —
the v4 tool upgrades (limit_signals, peer edges, host channel) made the pre-registered
"kernel-only" faults substantially metrics/trace-visible. The damage under degraded
kernel concentrates in the OTHER families (kL1: 10% both). Honest consequence for the
pre-registered **H2** ("removing kernel causes the largest ablation drop on blind-spot
faults"): **not confirmed at full telemetry in the v4 system** — to be recorded via
fault_catalog §7 amendment with the explanation (our own cross-modality tooling
absorbed the signal), and re-tested under the trace/metric degradation interaction
(kernel value should grow as other modalities thin — that interaction sweep is the
remaining RQ1×RQ3 experiment).

## RQ2 layer — how the investigation changes as kernel evidence is removed

Tool-call totals across the 23 incidents (`ksweep_rq2.py`):

| tier | kernel | metrics | topology | logs | traces | source | total |
|---|---|---|---|---|---|---|---|
| kAll | 59 | 68 | 37 | 24 | 8 | 13 | 209 |
| kL1 | 72 | 74 | 43 | 33 | 4 | 7 | 233 |
| kL3 | 72 | 68 | 35 | 33 | 11 | 12 | 231 |
| kNone | 83 | 83 | 49 | 40 | 9 | 17 | 281 |

- **Compensation is broad-front, not a single substitute**: under kNone every other tool
  rises (metrics +22%, topology +32%, logs +67%, source +31%).
- **The agent partially "hammers dead telemetry"** — the exact RQ2 failure mode: 83 calls
  to the EMPTY kernel tool under kNone (~30% of all calls; 17/23 incidents probe it >2×).
  It retries per-service instead of concluding once that the modality is gone. It still
  recovers via other tools, but this is measurable wasted work — and an obvious cheap fix
  (tool could answer once, globally, "kernel telemetry unavailable").
- **Label-shift mechanics confirm WHERE the typing signal lives**: on SS slow_db and SS
  anomaly_net, tiers WITH L1 say `catalogue-db/db_latency`; L3-only/none shift to
  `catalogue/dependency_outage` — locus-precision and fault-typing ride on L1's numbers
  (+L2's wait profile), not the L3 narrative. Evidence quotes: kAll cites "98.4% off-CPU
  external I/O wait, no saturation"; kNone argues only from edge latency + absence of
  saturation and lands service-only.
- Curio: under kL3 one diagnosis named a raw IP (`172.18.0.34`, from a peer edge) as root
  cause — peer-edge callees should get IP→service reverse-mapping eventually (cosmetic).

## Status of the degradation program after this sweep

Done: kernel axis on the agent (this), all axes on both non-LLM baselines (flat).
Open: trace/metric/log axes on the agent (RQ1 cliffs), kernel × degraded-traces
interaction (the real compensation test), RQ2 trajectory comparison across tiers
(transcripts captured — kNone's +34% calls is the first data point), RQ4 Pareto join.
