---
name: db-latency-rca
version: 1
authored_by: human
covers: slow_db
user_triggers: database is slow | db latency | queries are slow | slow db
---
## Problem signature
- topology: slow caller->callee edges CONVERGE on one shared downstream component —
  typically a datastore — which itself has no slow outgoing edges (or emits no spans).
- kernel: the converged-on component shows dominant off-CPU external I/O wait
  (wait_attribution off_cpu_io_wait high, verdict_hint external) and/or elevated
  syscall latency (sys_lat_p95_ms), WITHOUT cpu/memory/disk saturation.
- metrics: the converged-on component is resource-quiet (cpu_cores, fs_*, net_* flat or
  FALLING) while its callers' latency inflates.
- logs: few or no NEW error signatures on the converged-on component — traffic still
  succeeds, just slowly.

## Investigation blueprint
1. query_topology (no filter): confirm convergence — the suspect has slow INCOMING
   edges only. If its own outgoing edges are also slow, follow them deeper first.
2. query_kernel on the suspect: expect high off_cpu_io_wait / raised sys_lat_p95_ms
   with unremarkable on-CPU share.
3. Rule out look-alikes on the suspect:
   - host disk saturation (host_disk_io_time_s/s, blk_lat_p95_ms up host-wide),
   - CPU cap (cpu_throttled_s/s jump),
   - memory pressure (reclaim/writeback activity).
4. query_logs on the suspect and its top caller: connection resets/refusals point to an
   outage-style fault instead of latency.

## Resolution template
- fault_type db_latency: calls to the datastore SUCCEED but slowly; the datastore waits
  on external I/O while unsaturated.
- dependency_outage instead when calls FAIL or hang to timeout and the component serves
  little/no successful traffic.
- disk_io instead when the whole host's disk is saturated (other disk users degrade too).
Root cause service = the converged-on datastore component itself, not its callers —
they are victims.
