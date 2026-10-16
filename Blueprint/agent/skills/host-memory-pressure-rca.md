---
name: host-memory-pressure-rca
version: 1
authored_by: human
covers: anomaly_mem
user_triggers: out of memory | memory pressure | host swapping | oom
---
## Problem signature
- metrics: host_mem_available_GB collapses baseline->incident; ONE container's
  mem_working_MB / mem_rss_MB balloons from near-zero while no application service
  explains the growth; host_load1 may rise.
- kernel: reclaim_per_s and writeback_per_s become NON-ZERO / multiply (memory reclaim
  is the fingerprint); pagefault rates rise; host-kernel shows the same; disk activity
  may rise as a SIDE-EFFECT (swap/writeback).
- topology: broad, unfocused latency inflation, or stalls concentrated on
  memory-hungry services.
- logs: possible GC/alloc warnings; restarts if the pressure kills processes.

## Investigation blueprint
1. query_metrics with service 'host': confirm host_mem_available_GB dropped sharply.
2. query_kernel (no filter): look for reclaim/writeback going from 0 to nonzero —
  attribute WHO: an unexplained workload with ballooning memory vs an app service.
3. query_metrics (no filter): find the container whose mem_working_MB grew abnormally
  and check it has no call-path edges (query_topology).
4. Separate side-effects: rising disk KB/s caused by writeback is a consequence, not a
  disk fault.

## Resolution template
- fault_type memory_pressure: host memory exhausted (available memory collapsing +
  reclaim/writeback active), typically via an extra memory-hungry workload.
- memory_limit instead when exactly ONE service hits a FLAT memory ceiling (its cap)
  with GC/OOM restarts and the host overall has memory to spare.
- disk_io instead only if disk saturation exists WITHOUT the memory collapse/reclaim
  fingerprint.
Root cause service = the unexplained memory-hungry workload when visible; otherwise
'host'.
