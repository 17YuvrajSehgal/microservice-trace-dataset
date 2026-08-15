---
name: host-network-degradation-rca
version: 1
authored_by: human
covers: anomaly_net
user_triggers: network is slow | packet loss | latency everywhere | network degraded
---
## Problem signature
- topology: MANY caller->callee edges slow down TOGETHER by similar factors, across
  unrelated paths — the inflation is per-hop and system-wide, with no single component
  the edges converge on.
- metrics: NO resource mover explains it — cpu, memory, disk quiet on every container;
  host_net throughput may dip (fewer completed requests) but the host is not saturated.
- kernel: services show off-CPU external waits on NETWORK syscalls (sys_net, net_events)
  rather than disk/CPU signals; no single service's kernel profile stands out.
- logs: sparse timeout/retry signatures spread across MANY services (not one hotspot).

## Investigation blueprint
1. query_topology (no filter): check the slowdown SHAPE — uniform per-hop inflation on
   unrelated edges is the discriminator vs single-culprit faults.
2. query_metrics with service 'host' and no-filter: verify NOTHING is resource-saturated
   (that absence is evidence here).
3. query_kernel (no filter): confirm waits are network-flavored and distributed.
4. Contrast: if slow edges all pass THROUGH one component, investigate that component
   instead (single-service network path or datastore fault).

## Resolution template
- fault_type network_latency: host-wide network delay/loss — every cross-service hop
  pays the tax, nothing is saturated, no single culprit component.
- service_network instead when only edges touching ONE component are slow/lossy.
- db_latency instead only when datastore-path edges are DISPROPORTIONATELY slower than
  ordinary service-to-service hops (datastore edges exist in every incident as
  background — their mere presence proves nothing).
Root cause service = 'host' (the shared network layer), not any single application
service — they are all victims.
