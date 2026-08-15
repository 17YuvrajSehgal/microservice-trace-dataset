---
name: service-memory-cap-rca
version: 1
authored_by: human
covers: svc_mem_cap
user_triggers: service restarting | oom killed | gc thrashing | memory limit hit
---
## Problem signature
- metrics: ONE service's mem_working_MB / mem_rss_MB sits at a FLAT CEILING (the cap)
  or saw-tooths against it; host_mem_available_GB is fine — the host has memory, the
  SERVICE does not.
- logs: NEW signatures on that service: GC pressure, allocation failures, OOM kills,
  restart/reconnect banners; its callers may log timeouts.
- kernel: pagefault rate elevated on the capped service; possible reclaim confined to
  it; restarts appear as its activity dropping and resuming.
- topology: only that service's SERVER latency (and its callers) degrade; possible gaps
  if it restarts.

## Investigation blueprint
1. query_metrics (no filter): find the container whose memory is pinned at a flat
   ceiling while the host has spare memory (query 'host' to confirm).
2. query_logs on it: GC/OOM/restart signatures that are NEW at onset are decisive.
3. query_kernel on it: pagefault/reclaim activity confined to this service.
4. query_topology: blast radius = its caller subtree only.

## Resolution template
- fault_type memory_limit: one service constrained by its own memory cap (flat ceiling
  + GC/OOM evidence), host memory healthy.
- memory_pressure instead when HOST available memory collapses and reclaim is
  system-wide.
- error_storm instead when the dominant change is an error burst WITHOUT the memory
  ceiling/GC evidence.
Root cause service = the capped service itself.
