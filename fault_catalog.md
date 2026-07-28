# Fault catalog and pre-registered modality predictions

**Status: PRE-REGISTRATION.** This document records, *before any
modality-ablation experiment is run*, which observability modality we expect
to be most informative for each fault and task. The git history of this file
is the timestamp proof. Predictions freeze at the start of the Phase-2
collection campaign; after that, changes may only be made as dated entries in
the Amendment log (§7) — the original predictions are never edited.

Companion documents: `msr-research.md` (study design, §5–§7),
`microservice-lttng-data-collection-scripts/faults/README.md` (recipe
implementation + local verification record).

---

## 1. Why pre-register

The study's headline question — *which modality is informative for which
diagnostic task* — invites hindsight bias: any result can be rationalized
after the fact. Committing predictions (with rationale and expected
per-modality signatures) before data collection turns the study from
description into hypothesis testing, and the failed predictions become
findings rather than embarrassments.

## 2. Scoring rules (frozen with the predictions)

For each (fault, task) pair, the ablation study (msr-research.md §7) yields a
per-modality single-modality performance score.

- A **winner prediction is confirmed** if the predicted modality is top-1 on
  that (fault, task), or statistically indistinguishable from top-1
  (overlapping 95% CIs over runs/repeats).
- A **signature prediction is confirmed** if the expected evidence (§5 cards)
  is present in the collected data for ≥80% of that fault's confirmed runs —
  checked mechanically where possible (grep patterns, metric thresholds),
  manually on a sample otherwise.
- **Rival hypotheses** (explicitly listed per card) are scored the same way;
  "rival wins" is reported as a refutation of the primary prediction, not
  reframed.
- Results are reported for ALL predictions, confirmed or not.

## 3. Catalog design

Two axes (msr-research.md §5): **scope** (host-wide vs service-targeted) ×
**layer** (resource vs application/dependency vs infrastructure). Each fault
runs at two intensities (`subtle`, `aggressive`) except the pause-based
faults (binary by nature). Fault runs cross with workload conditions
(`steady` all faults; `low`/`burst` for a selected subset). Every run's
recipe emits `ground_truth.json` with the injection window, parameters, and
this catalog's predictions embedded (`expected_winning_modality`,
`target_trace_visibility`).

**Trace-coverage alignment rule** (msr-research.md §3/M3): each fault's
target is either trace-covered (Tier 1/2 instrumented) or a deliberate,
labeled blind spot. No accidental gaps.

## 4. Summary prediction matrix

Informativeness prediction per modality: **H**igh / **M**edium / **L**ow /
**0** ≈ none. "Winner (T1/T2/T3)" = predicted most-informative modality for
anomaly detection / root-cause analysis / incident explanation.

| # | Fault | Scope | Metrics | Logs | Traces | Kernel | Winner T1 | Winner T2 | Winner T3 |
|---|---|---|---|---|---|---|---|---|---|
| F1 | host CPU saturation | host | H | L | M | H | metrics | **kernel**¹ | kernel |
| F2 | host disk saturation | host | H | L | M | H | metrics | **kernel**¹ | kernel |
| F3 | host memory pressure | host | H | M | M | H | metrics | **kernel**¹ | kernel |
| F4 | host network impairment | host | M | L | H | H | metrics | traces | kernel |
| F5 | slow DB (catalogue-db, blind spot) | service | M | L | M | H | metrics | **kernel** | kernel |
| F6 | error storm (catalogue) | service | H | H | M | L | metrics | logs | **logs** |
| F7 | service CPU cap | service | H² | L | M | H | metrics | kernel² | kernel |
| F8 | service memory cap | service | H² | H | M | H | metrics | logs² | logs |
| F9 | dependency outage (payment) | service | M | H | H | M | metrics | **traces** | traces |
| F10 | queue backlog (blind spot, silent) | service | L³ | 0 | 0 | H | **kernel** | kernel | kernel |
| F11 | noisy neighbor (blind spot) | host | L³ | 0 | 0 | H | **kernel** | kernel | kernel |
| F12 | per-container netem (planned, VM) | service | M | L | H | H | traces | traces | kernel |

¹ Metrics *detect* host-resource faults cheaply and even name the resource
(node-exporter series are resource-explicit). The kernel prediction for
T2/T3 is about **cause attribution**: identifying the aggressor process
(stress-ng procname in sched/syscall events) and the victims' wait states —
information no metrics series carries. If reviewers' intuition ("metrics
suffice for resource faults") holds at T2 as well, that is a *finding
against* the kernel modality's added value at this fault family.
² Rival hypothesis registered (see cards F7/F8): cAdvisor exposes
`container_cpu_cfs_throttled_*` and `container_memory_*` which may match
kernel/logs evidence at far lower cost. We predict kernel/logs win on
mechanism detail, but flag metrics as a serious rival.
³ Detectable in metrics only as a slow trend (rabbitmq memory growth /
new-container CPU appearing), not an alarm-shaped signal.

**Aggregate hypotheses (H1–H4), also frozen:**
- **H1**: kernel is the only modality with ≥M informativeness across *every*
  fault in the catalog (no blind spots), but is never the cheapest detector.
- **H2**: for the three blind-spot faults (F5, F10, F11), removing the
  kernel modality causes the largest single-modality ablation drop of any
  (fault, modality) pair in the study.
- **H3**: metrics win T1 detection on all aggressive-intensity faults;
  their advantage shrinks or disappears at subtle intensity.
- **H4**: no single modality is top-1 for T2 across all fault families —
  the task→modality prescription table (RQ2) is non-trivial.

## 5. Per-fault cards: expected signatures per modality

Each card lists the evidence each modality is *expected* to contain. These
double as the fact-checklists for grading T3 (incident explanation) output.

### F1 host CPU saturation — `1_cpu_stress.sh`
Mechanism: stress-ng, 2×nproc matrixprod workers, host-wide.
- metrics: node CPU ~100% (non-idle); all services' p95 up together.
- logs: largely silent; occasional client-side timeout lines.
- traces: uniform span inflation across services; no broken edges.
- kernel: stress-ng procnames dominating sched_switch; services
  runnable-but-waiting; run-queue latency up host-wide.
- Rival: none registered.

### F2 host disk saturation — `2_disk_stress.sh`
- metrics: node disk io_time ≈ 1; write throughput saturated.
- logs: possible slow-flush warnings from DBs.
- traces: DB-touching routes inflate more than static routes (weak
  localization signal).
- kernel: block-rq events dominated by stress-ng; DB threads in D-state
  (uninterruptible) waits.

### F3 host memory pressure — `3_mem_stress.sh`
- metrics: MemAvailable collapse; swap/reclaim counters.
- logs: possible JVM GC storms; OOM-killer messages if it fires.
- traces: GC-pause span inflation on Java services.
- kernel: reclaim/pgfault/kswapd activity; allocation-stall waits.

### F4 host network impairment — `4_net_stress.sh`
- metrics: netdev throughput drop; inter-service latency up.
- logs: sporadic connection resets/timeouts.
- traces: inter-hop gap inflation (client-send→server-recv), uniform across
  edges — distinguishes network from service slowness.
- kernel: netem qdisc effects, retransmissions, socket backlog waits.

### F5 slow DB — `faults/slow_db.sh` (blind spot showcase)
Mechanism: Toxiproxy latency toxic on catalogue→catalogue-db.
- metrics: catalogue p95 up; *DB container metrics near-normal* (it is not
  working harder — the delay is in the path).
- logs: **silent** (slow ≠ failing) — locally verified.
- traces: catalogue server span inflated; NO DB child span exists to blame
  (no otelsql); blast stops at catalogue.
- kernel: catalogue threads blocked on socket read to catalogue-db's
  endpoint ≈ full added latency; catalogue-db itself quiet. This is the L2
  wait-attribution showcase.
- Prediction: kernel wins T2/T3; fastest T1 is metrics (latency alarm).

### F6 error storm — `faults/error_storm.sh`
Mechanism: reset_peer/timeout toxic on the same proxy.
- metrics: 5xx rate spike on catalogue (alarm-shaped, cheap detection).
- logs: explicit mechanism strings — locally verified: mysql
  "connection reset by peer", "driver: bad connection", per-request error
  lines with route context.
- traces: 500-status spans at catalogue; localization but thin mechanism.
- kernel: RST packets/short-lived connections — redundant given logs.
- Prediction: logs win T2/T3.

### F7 service CPU cap — `faults/svc_cpu_cap.sh`
Mechanism: docker update --cpus on one service (default carts).
- metrics: carts latency up; **rival:** cAdvisor
  `container_cpu_cfs_throttled_seconds_total` names throttling directly.
- logs: silent.
- traces: carts spans inflate; upstream (front-end) sees slow carts.
- kernel: cfs throttle events + runnable-gaps on carts threads only;
  per-thread timing of when throttling bites.
- Prediction: kernel wins T2 mechanism; explicit rival = metrics via the
  throttled counter (if the rival wins, cadvisor's counter is simply the
  cheaper sufficient signal — report as such).

### F8 service memory cap — `faults/svc_mem_cap.sh`
Mechanism: docker update -m below/near JVM heap ceiling.
- metrics: container_memory_usage flat-lining at the limit (**rival**, with
  container_memory_failcnt); latency degradation from GC.
- logs: GC storm lines; on aggressive, container OOM kill (docker events,
  JVM death) — terminal evidence.
- traces: growing GC-pause inflation, then span stream stops on OOM.
- kernel: reclaim + pgfault ramp on the capped cgroup *before* app-level
  signals move (early-warning prediction: kernel leads by ≥1 metric scrape
  interval).
- Prediction: logs win T2/T3 terminal diagnosis; kernel wins early
  detection lead-time (secondary measurement).

### F9 dependency outage — `faults/dependency_outage.sh`
Mechanism: docker pause payment (freezer cgroup; connections hang).
- metrics: orders error rate up; payment container CPU → 0 (subtle to spot).
- logs: orders-side exception storms with payment hostnames.
- traces: orders spans with erroring/timing-out payment client calls — the
  broken edge is directly visible.
- kernel: payment cgroup total silence (absence-of-activity signal);
  orders threads parked in connect/read waits.
- Prediction: traces win T2 (edge localization); logs close second.

### F10 queue backlog — `faults/queue_backlog.sh` (silent failure)
Mechanism: pause queue-master, sole consumer of the shipping queue.
- metrics: NO error signal anywhere; rabbitmq container memory grows slowly
  (trend, not alarm).
- logs: nothing — orders complete normally.
- traces: nothing — the async boundary hides the stall (queue-master emits
  no spans while paused; absence is not an event).
- kernel: queue-master cgroup silent while rabbitmq socket activity
  continues inbound-only; the imbalance is directly observable.
- Prediction: kernel is the ONLY modality that detects within the run
  window (H2's strongest case). If nothing detects it, that itself is a
  headline finding about silent failures.

### F11 noisy neighbor — `faults/noisy_neighbor.sh` (kernel-only by construction)
Mechanism: cgroup-capped stress-ng container co-located with the stack;
caps tuned (VM calibration) so service KPIs stay within normal variance.
- metrics: service KPIs ~normal by design; cAdvisor *does* show a new
  container consuming its cap (rival: an analyst who inventories containers
  can spot it — but nothing flags it as anomalous).
- logs/traces: nothing.
- kernel: neighbor procname prominent in sched events; services' runnable
  wait and cache-pressure up subtly.
- Prediction: kernel only. The subtle intensity is the modality-ablation
  study's hardest detection case.

### F12 per-container netem (planned; VM-only)
Mechanism: tc netem inside one container's netns (nsenter/pumba).
Predictions registered now: traces win localization (single edge inflates);
kernel confirms via socket-level waits on one path. To be implemented in
the VM phase; parameters TBD before the campaign freeze.

## 6a. Realized verification panel

The per-fault "expected metric movement" table is realized as
`faults/verification_targets.json` (canonical + corroborating Prometheus
targets per fault, with direction, σ-threshold, absolute threshold, and
min-fraction-of-window gates) and evaluated by `verify_injection.py`, which
writes a `confirmed | borderline | unconfirmed` verdict + impact PNG per run
from the ground-truth injection window. `run_scenario.sh` wires this into
every fault run (baseline → inject → recover → verify → audit). The verdict
math is regression-tested offline (`verify_injection.py --self-test`);
thresholds calibrate against real KPIs on the VM in Phase 1.

## 6. Verification status

| Fault | Recipe status | Injection verified | Intensity calibrated |
|---|---|---|---|
| F1–F4 | existing scripts, used in 148 GB release | Grafana PDFs (prior release) | aggressive only; subtle = VM task |
| F5, F6 | implemented | locally, end-to-end vs instrumented catalogue (27-07-2026) | VM task |
| F7, F8 | implemented | mechanics locally vs cgroup files (27-07-2026) | VM task |
| F9, F10 | implemented | pause mechanics locally (27-07-2026) | n/a (binary) |
| F11 | implemented | cap mechanics locally (27-07-2026) | **critical VM task** (KPIs-barely-move property) |
| F12 | planned | — | — |

## 7. Amendment log

*(empty — predictions above are as originally registered; any post-freeze
change appears here as a dated entry with rationale, never as an edit above)*
