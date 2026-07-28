# Phase-1 fault calibration — COMPLETE (28-07-2026)

All 7 fault recipes calibrated on the live VM stack; verification targets
corrected against reality; the full Phase-2 pipeline (run_scenario ->
verify_injection -> audit) validated end-to-end on a real fault run.

## Per-fault calibration results (baseline -> injection)

| Fault | Canonical signal | Baseline -> Injection | Verdict |
|---|---|---|---|
| slow_db | catalogue p95 (http_) | 4.8ms -> 2.2s (465x) | CONFIRMED (strong) |
| error_storm | catalogue 5xx (http_) | 0 -> 139/sec | CONFIRMED (strong) |
| svc_cpu_cap | carts p95 | 20ms -> 7s | CONFIRMED (strong); throttle-metric pivot |
| svc_mem_cap | mem limit drop | 42GB -> cap | CONFIRMED (mechanical); usage-ratio unusable |
| dependency_outage | payment CPU | -58% (smeared) | METRICS-WEAK; hangs-not-errors (kernel finding) |
| queue_backlog | queue-master CPU | -77% | METRICS-WEAK silent failure (kernel finding) |
| noisy_neighbor | neighbor CPU / KPIs | 0.75 core active; KPIs flat | CONFIRMED + premise validated |

## Target corrections made (all committed to verification_targets.json)
- **Metric-name split by runtime**: Go/Node (catalogue, frontend) =
  `http_request_duration_seconds`; Java (cart/orders/payment/user/shipping) =
  `request_duration_seconds`. (Prometheus job for carts is `cart`.)
- **No cfs-throttle metric** on this cadvisor build -> svc_cpu_cap verifies via
  app latency, not throttle counters.
- **svc_mem_cap**: usage/limit ratio unusable (uncapped baseline = host total
  42GB) -> use limit-drop; carts working set ~545MB so subtle 300m creates
  pressure, aggressive 160m OOMs.
- **dependency_outage / queue_backlog**: pause faults are metrics-WEAK
  (matches fault_catalog kernel/trace-wins predictions); tuned to soft
  thresholds, documented the metrics-blind finding.

## Two findings that became research assets (reinforce the kernel-wins thesis)
1. **Frozen dependency is metrics/logs-invisible**: docker-pause freezes
   payment, so orders' HTTP call HANGS (blocked socket read) rather than
   fail-fast - orders 5xx stays ~0. The kernel sees orders threads blocked in
   read() on the payment socket. Concrete instance of the study thesis.
2. **Noisy-neighbor premise validated empirically**: neighbor consumes 0.75
   core (host CPU 28->45%) while carts p95 +6% and catalogue p95 0% - CPU
   contention is host/kernel-visible but app-metric-blind.

## Pipeline validation (run_scenario end-to-end on slow_db)
Bundle assembled correctly: ground_truth.json (injection window
06:25:04->06:25:44), kernel 7.2G, otlp 374M, ust, logs 117M, meta,
verification.json.
- verify_injection: CONFIRMED (catalogue p95 4.8ms->1.91s, sigma 87241, frac 1.0)
- audit: all 6 modalities OK (trace 22 spans, logs 6965, load 679, metrics
  1524 series, kernel 5.4M events, clocks 0.003ms drift)

## Bug the validation caught + fixed
verify_injection read UNCONFIRMED on this obviously-fired fault (frac
0.667<0.7) because 1m-rate-windowed metrics take ~a rate-window to ramp after
onset - the first ~1/3 of the injection window still averaged pre-injection
samples. FIX: verify_injection now skips a settle_s (default 30s, capped at
half the window) at injection onset. Regression-tested
(verify_injection --self-test, ramp-up case). **Campaign note: use
INJECTION_S >= 120 so a clean settled segment remains** (calibration probes
used 40s, which is why the fraction was marginal).

## Stack fixes applied during calibration (all in vm_bootstrap / overrides)
- Docker 29 -> overlay2 storage (cadvisor couldn't read containerd-snapshotter)
- prometheus + cadvisor restart policies (were down after reboot)
