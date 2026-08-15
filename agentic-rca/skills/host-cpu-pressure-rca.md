---
name: host-cpu-pressure-rca
version: 1
authored_by: human
covers: anomaly_cpu
user_triggers: everything is slow | host cpu high | cpu exhausted | node overloaded
---
## Problem signature
- metrics: host_cpu_busy_cores jumps sharply baseline->incident and host_load1 climbs;
  ONE container's cpu_cores appears from nothing (baseline null/0) or spikes to several
  cores while no application service explains the demand.
- topology: MANY unrelated call paths slow down together (broad, unfocused slowdown —
  no single edge dominates).
- kernel: a workload with NEW activity appears (sched_wakeup_per_s from ~0); host-kernel
  scheduler pressure rises; application services show runnable/CPU-contention waits, not
  external I/O waits.
- logs: little or no NEW error signature anywhere — services are slow, not failing.

## Investigation blueprint
1. query_metrics with service 'host': confirm host_cpu_busy_cores and host_load1 rose
   significantly baseline->incident.
2. query_metrics (no filter): find the container whose cpu_cores appeared or spiked and
   which is NOT part of any user-facing call path (query_topology: it has no edges).
3. query_kernel on that container: expect activity that is NEW at onset.
4. Confirm services are victims: their kernel wait is runnable/CPU contention, and their
   latency inflation is broad rather than path-shaped.

## Resolution template
- fault_type cpu_saturation: host CPU pressure from an extra workload; user-facing
  latency clearly degraded across many services.
- noisy_neighbor instead when the co-tenant consumes resources but user-facing KPIs are
  only mildly affected (contention visible mainly in kernel scheduling signals).
- cpu_throttling instead when exactly ONE service is limited (its cpu_throttled_s/s
  jumps) and everything else is healthy.
Root cause service = the unexplained workload/container itself when visible; otherwise
'host'.
