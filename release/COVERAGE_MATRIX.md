# StrataTrace v1 — per-service modality coverage matrix

Which modalities observe each service. This is a **design variable**, not an accident:
service-targeted faults declare in `ground_truth.json` whether their target is trace-covered
or a deliberate blind spot, so partial trace coverage tests *whether kernel/logs/metrics
compensate where traces are blind* (plan §3/M3, §5). Audited 2026-08-04.

Legend: ✓ covered · ✗ not covered · (blind) = deliberate Tier-3/Tier-2 blind spot.

| Service | Kernel (L0/L1) | Logs | Metrics (cAdvisor) | Traces (spans) | Notes |
|---|:---:|:---:|:---:|:---:|---|
| front-end | ✓ | ✓ | ✓ | ✓ | Tier-1 (Node, auto-instrumented) — entry point |
| catalogue | ✓ | ✓ | ✓ | ✓ | Tier-1 (Go, otelhttp) — most-hit service |
| carts | ✓ | ✓ | ✓ | ✓ | Java-4 (agent) |
| orders | ✓ | ✓ | ✓ | ✓ | Java-4 (agent) |
| shipping | ✓ | ✓ | ✓ | ✓ | Java-4 (agent) |
| queue-master | ✓ | ✓ | ✓ | ✓ | Java-4 (agent) |
| user | ✓ | ✓ | ✓ | ✗ (blind) | Tier-2 not instrumented — trace blind spot |
| payment | ✓ | ✓ | ✓ | ✗ (blind) | Tier-2 not instrumented — trace blind spot |
| catalogue-db | ✓ | ✓ | ✓ | (client) | Tier-3 DB — visible via client-side DB spans + kernel |
| carts-db | ✓ | ✓ | ✓ | (client) | Tier-3 DB |
| orders-db | ✓ | ✓ | ✓ | (client) | Tier-3 DB |
| user-db | ✓ | ✓ | ✓ | (client) | Tier-3 DB |
| rabbitmq | ✓ | ✓ | ✓ | ✗ (blind) | Tier-3 broker — kernel/logs/metrics only |
| edge-router | ✓ | ✓ | ✓ | ✗ (blind) | Tier-3 nginx — kernel/logs/metrics only |

(Plus `otel-collector` and the `aggressor` stress container appear in logs / kernel respectively
as infra, not as application services.)

## Summary
- **14 application/infra services** (8 app + 4 DB + rabbitmq + edge-router).
- **Kernel: 14/14** — sees every service's syscalls without instrumentation (the differentiator).
- **Logs: 15 containers** — every service + edge-router + otel-collector.
- **Metrics: all** — node-exporter host + **cAdvisor per-container** + app histograms (432 series/run).
- **Traces: 6/14** — Java-4 + Tier-1 (front-end, catalogue). Tier-2 (`user`, `payment`) and
  Tier-3 infra are trace blind spots by design.

## Why this matters for the study
The trace blind spots are **testable sub-questions**, not weaknesses: e.g. `dependency_outage`
targets `payment` (trace-blind) and `slow_db` targets `catalogue-db` (trace-blind) — precisely
the cases where the kernel modality should compensate. Every service-targeted fault's
`target_trace_visibility` is recorded so no target is an *accidental* gap.
