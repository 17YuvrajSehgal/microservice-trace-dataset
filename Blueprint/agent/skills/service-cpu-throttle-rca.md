---
name: service-cpu-throttle-rca
version: 1
authored_by: human
covers: svc_cpu_cap
user_triggers: one service slow | service pegged | cpu limit | throttled
---
## Problem signature
- metrics: ONE service's cpu_throttled_s/s jumps from ~0 to sustained positive (see
  limit_signals) — DECISIVE on its own, even when cpu_cores does NOT visibly flatten
  (moderate caps throttle bursts without pinning average usage); host_cpu overall is
  NOT saturated.
- topology: that service's SERVER latency inflates and the slowdown radiates only to
  its callers (edges INTO it slow; unrelated paths healthy).
- kernel: throttling forcibly deschedules threads, so wait attribution reports it as
  runnable OR off-CPU/external wait — a high off-CPU wait share does NOT contradict
  throttling when throttled-seconds are positive.
- logs: little NEW error activity; possible timeout complaints from its callers only.

## Investigation blueprint
1. query_metrics (no filter): scan for any container with a cpu_throttled_s/s jump —
   if found, that is the prime suspect.
2. query_topology: confirm the blast radius is exactly that service's caller subtree.
3. query_kernel on the suspect: expect wait-flavored delay WITHOUT disk/memory
   fingerprints. Do not discard the throttle hypothesis because waits read as
   off-CPU/external — that is what throttle-wait looks like from the kernel.
4. query_metrics with service 'host': confirm the HOST is not CPU-saturated (rules out
   host-wide pressure).

## Resolution template
- fault_type cpu_throttling: one service's throttled-seconds are positive and sustained
  and only its subtree degrades — decisive even without visible CPU flattening and even
  when kernel waits read as off-CPU/external (throttle-wait looks like that).
- noisy_neighbor instead when the THROTTLED container has no call-path role
  (query_topology: no edges touch it): a capped co-tenant workload throttling against
  its own limit is a noisy neighbor — the throttle signal locates the co-tenant, it
  does not make this a service-cap fault.
- cpu_saturation instead when host_cpu_busy_cores is exhausted and many unrelated
  services degrade.
- db_latency instead when the slow component is a datastore waiting on external I/O
  rather than starved of CPU.
Root cause service = the throttled service itself.
