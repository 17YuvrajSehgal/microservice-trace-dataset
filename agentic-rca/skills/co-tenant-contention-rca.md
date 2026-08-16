---
name: co-tenant-contention-rca
version: 1
authored_by: human
covers: noisy_neighbor
user_triggers: intermittent slowness | jitter | something stealing cpu | neighbor workload
---
## Problem signature
- the SUBTLE sibling of host CPU pressure: an extra workload consumes host resources
  while user-facing KPIs stay NEAR-NORMAL — mild latency jitter at most; if user impact
  is severe and broad, prefer the host-CPU-pressure reading.
- metrics: a container with NO call-path role consumes steady CPU (cpu_cores appears
  from nothing, often capped at a modest share); host_cpu_busy_cores rises but is NOT
  exhausted; host_load1 up moderately. The co-tenant is often itself CPU-capped, so
  limit_signals may show ITS cpu_throttled_s/s — a throttle signal on a non-call-path
  container points HERE, not to cpu_throttling.
- kernel: contention fingerprints WITHOUT app saturation — sched_wakeup churn from the
  extra workload, mild runnable waits on app services; no external I/O wait story.
- topology/traces/logs: little to no change — the ABSENCE of app-level symptoms while a
  foreign workload runs is the signature.

## Investigation blueprint
1. query_metrics (no filter): find the container with meaningful cpu_cores that has no
   topology edges and no baseline presence.
2. query_metrics 'host': CPU busy up but with headroom (not exhausted) — this
   distinguishes contention from saturation.
3. query_topology / query_traces: confirm user-facing latency is only mildly affected.
4. query_kernel on app services: mild scheduling contention, nothing else.

## Resolution template
- fault_type noisy_neighbor: co-tenant workload present, kernel-level contention, app
  KPIs near-normal.
- cpu_saturation instead when host CPU is exhausted and user latency clearly degrades
  across many services.
- cpu_throttling instead when one APP service is pinned by its own limit
  (cpu_throttled_s/s on that service).
Root cause service = the co-tenant workload/container itself.
