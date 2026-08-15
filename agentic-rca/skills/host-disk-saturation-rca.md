---
name: host-disk-saturation-rca
version: 1
authored_by: human
covers: anomaly_disk
user_triggers: disk is slow | io saturated | storage slow | high disk latency
---
## Problem signature
- metrics: host_disk_io_time_s/s rises toward/past ~1.0 (device saturated) and
  host_disk_read_KB/s or host_disk_write_KB/s jumps by an order of magnitude; ONE
  container's fs_read/fs_write throughput appears from nothing or dominates.
- kernel: block_ops_per_s / block_sectors_per_s explode on a workload with no baseline
  activity, and host-kernel block activity multiplies; blk_lat_p95_ms rises for every
  disk-using service (shared device queue).
- topology: latency inflation concentrated on services that touch disk; call-path shape
  is weak or mixed.
- logs: little NEW error activity; possible slow-query/flush warnings on datastores.

## Investigation blueprint
1. query_metrics with service 'host': confirm host_disk_io_time_s/s and disk KB/s rose
   sharply baseline->incident.
2. query_kernel (no filter): find the entity whose block_ops/block_sectors are NEW or
   dominate, and check host-kernel block figures.
3. query_metrics (no filter): match it to the container whose fs_* throughput appeared;
   confirm it is not part of any user call path (query_topology: no edges).
4. Distinguish victims: datastores with elevated blk_lat but modest own throughput are
   queue victims, not the source.

## Resolution template
- fault_type disk_io: host disk saturated by an extra/unexplained disk-heavy workload;
  all disk users see elevated block latency.
- db_latency instead when only ONE datastore's callers are slow and host disk io_time
  is NOT saturated.
- memory_pressure instead when writeback/reclaim drive the disk activity (check reclaim
  and available memory).
Root cause service = the unexplained disk-heavy workload when visible; otherwise 'host'.
