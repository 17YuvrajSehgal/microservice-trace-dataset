---
name: service-network-path-rca
version: 1
authored_by: human
covers: svc_net
user_triggers: one service unreachable-ish | slow to one service | path latency | interface degraded
---
## Problem signature
- topology: edges TOUCHING one component (into it, and possibly out of it) slow by a
  large factor while unrelated paths stay healthy — path-shaped, single-locus, unlike
  host-wide per-hop inflation.
- metrics: the affected component is resource-QUIET (cpu/mem/fs unremarkable); its
  net throughput may drop (fewer completed requests); host network signals normal.
- kernel: the component (and its direct peers) show network-flavored waits — sys_net /
  net_events changes, off-CPU external waits on network syscalls; no disk/CPU/memory
  fingerprints.
- logs: timeouts/retries mentioning that component from its immediate peers only.

## Investigation blueprint
1. query_topology (no filter): identify the single component whose touching edges
   carry the slowdown; verify unrelated edges are healthy (rules out host network).
2. query_metrics on it + 'host': confirm it is not resource-degraded and the host
   network is fine — the slowness lives in ITS network path.
3. query_kernel on it: network-wait flavor, nothing internal.
4. query_logs on its peers: retries/timeouts naming it, none elsewhere.

## Resolution template
- fault_type service_network: one service's network path degraded — only traffic
  through it is slow/lossy, the service itself is internally healthy.
- network_latency instead when ALL cross-service hops inflate host-wide.
- db_latency instead when the single slow locus is a datastore with external I/O wait.
- dependency_outage instead when traffic to it HANGS/fails and it goes silent.
Root cause service = the component whose network path is degraded (it may look like a
victim — the distinction is that nothing internal to it is wrong AND host network is
healthy).
