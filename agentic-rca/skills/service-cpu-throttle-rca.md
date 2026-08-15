---
name: service-cpu-throttle-rca
version: 1
authored_by: human
covers: svc_cpu_cap
user_triggers: one service slow | service pegged | cpu limit | throttled
---
## Problem signature
- metrics: ONE service's cpu_throttled_s/s jumps from ~0 to sustained positive — the
  single most diagnostic signal; its cpu_cores flattens at a ceiling; host_cpu overall
  is NOT saturated.
- topology: that service's SERVER latency inflates and the slowdown radiates only to
  its callers (edges INTO it slow; unrelated paths healthy).
- kernel: the service shows runnable/CPU-starved waits (waiting for CPU, not for I/O);
  sched contention on it, not host-wide.
- logs: little NEW error activity; possible timeout complaints from its callers only.

## Investigation blueprint
1. query_metrics (no filter): scan for any container with a cpu_throttled_s/s jump —
   if found, that is the prime suspect.
2. query_topology: confirm the blast radius is exactly that service's caller subtree.
3. query_kernel on the suspect: runnable-wait flavored delay, no external I/O wait
   dominance, no disk/memory fingerprints.
4. query_metrics with service 'host': confirm the HOST is not CPU-saturated (rules out
   host-wide pressure).

## Resolution template
- fault_type cpu_throttling: one service pinned by its CPU limit (throttled-seconds
  positive and sustained), only its subtree degrades.
- cpu_saturation instead when host_cpu_busy_cores is exhausted and many unrelated
  services degrade.
- db_latency instead when the slow component is a datastore waiting on external I/O
  rather than starved of CPU.
Root cause service = the throttled service itself.
