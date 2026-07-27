# Fault recipe catalog (Phase 1)

Service-targeted and application-level fault recipes complementing the four
host-wide stressors (`1_cpu_stress.sh` … `4_net_stress.sh`). Every recipe:

- exposes `inject [subtle|aggressive]`, `cleanup`, `status`;
- writes a machine-readable ground-truth record
  (`$FAULT_STATE_DIR/<name>.ground_truth.json`, default `~/fault-state/`)
  with the exact injection window, parameters, target, expected blast
  radius, and remediation — the `ground_truth.json` seed for each run;
- restores the system to its pre-fault state on `cleanup` (restore paths
  are part of the recipe and were verified against cgroup ground truth,
  not docker's display fields).

The Toxiproxy recipes require `docker-compose.toxiproxy.yml` in the stack
(proxy is ALWAYS in-path so toxics toggle without restarts; see the
methodological note in that file). Container names resolve as
`${CONTAINER_PREFIX:-docker-compose}_<svc>_1`; override with
`TARGET_CONTAINER` for testing.

## Pre-registered predictions (fault → expected winning modality)

Committed BEFORE any modality-ablation experiment runs; the study tests
these predictions (msr-research.md §5). "Winner" = the modality expected to
contribute most to diagnosing this fault's mechanism; every fault should be
*detectable* from several.

| Recipe | Family | Scope | Target | Trace visibility | Predicted winner | Rationale |
|---|---|---|---|---|---|---|
| `1_cpu_stress.sh` (existing) | A resource | host | host | n/a | kernel | app modalities see uniform slowdown; sched events disambiguate CPU from the other stressors |
| `2_disk_stress.sh` (existing) | A resource | host | host | n/a | kernel | block-I/O events vs. generic latency |
| `3_mem_stress.sh` (existing) | A resource | host | host | n/a | kernel | reclaim/page-fault storm vs. generic latency |
| `4_net_stress.sh` (existing) | A resource | host | bridge | n/a | kernel | netdev events + retransmits vs. generic latency |
| `slow_db.sh` | C application | service | catalogue-db | **blind spot** | kernel | DB uninstrumented, no DB client spans; traces see only the inflated catalogue span, logs silent (slow ≠ failing); kernel wait-attribution shows catalogue blocked on the DB socket |
| `error_storm.sh` | C application | service | catalogue | covered | logs | driver errors with explicit cause strings (verified: "connection reset by peer", "driver: bad connection"); metrics flag 5xx cheaply; traces localize but carry less mechanism |
| `svc_cpu_cap.sh` | B service resource | service | carts (param) | covered | kernel | cgroup throttling = runnable-but-not-running gaps; app modalities just see "slow service" |
| `svc_mem_cap.sh` | B service resource | service | carts (param) | covered | logs | OOM-kill / JVM heap errors are textual; kernel reclaim activity is the early-warning signal (secondary prediction: kernel detects before app signals move) |
| `dependency_outage.sh` | D dependency | service | payment (param) | covered | traces | span at orders pointing at the dead hop localizes instantly; logs carry exception detail |
| `queue_backlog.sh` | D dependency | service | queue-master | **blind spot** | kernel | silent failure: no errors anywhere, orders still 200; consumer cgroup goes quiet while rabbitmq grows — absence-of-activity is only directly visible in kernel; cadvisor memory trend is the metrics echo |
| `noisy_neighbor.sh` | E infrastructure | host | host | **blind spot** | kernel (only) | capped so KPIs barely move; contention visible exclusively as scheduler pressure |
| per-container netem | B service resource | service | tbd | covered | traces | *planned; VM-only (sch_netem)* — per-hop latency isolates the degraded edge in the span tree |

## Local verification record (27-07-2026, Docker Desktop)

- `slow_db` end-to-end vs. instrumented catalogue + real catalogue-db:
  0.22 s baseline → 1.1–1.3 s under aggressive toxic → 0.21 s after cleanup;
  ground-truth window exact.
- `error_storm` end-to-end: 200 → 500s under reset_peer → 200 after cleanup;
  catalogue logs show the predicted cause strings.
- `svc_cpu_cap` / `svc_mem_cap`: caps and restores verified against
  `/sys/fs/cgroup/{cpu.max,memory.max}` (not docker inspect, whose fields
  can go stale — see recipe comments for three docker-update API gotchas).
- `dependency_outage` / `queue_backlog`: pause/unpause cycle verified.
- `noisy_neighbor`: 2 workers throttled to exactly the 1.0-CPU cap
  (99.7% observed), clean removal.
- VM-remaining: intensity calibration against real KPIs (esp. the
  noisy-neighbor "KPIs barely move" property), netem recipe, and
  `verify_injection.py` automation on top of these ground-truth records.
