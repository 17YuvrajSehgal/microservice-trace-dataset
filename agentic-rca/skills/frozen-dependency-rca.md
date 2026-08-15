---
name: frozen-dependency-rca
version: 1
authored_by: human
covers: dependency_outage
user_triggers: service down | dependency dead | requests hanging | timeouts to one service
---
## Problem signature
- traces/topology: callers of ONE component hang to a FLAT timeout plateau (p95/p99
  pinned at a round number like a client timeout); the component itself emits few or
  NO spans during the incident and serves little/no successful traffic.
- metrics: the frozen component's activity COLLAPSES (cpu, net throughput drop toward
  zero) rather than spikes — absence of activity is the fingerprint.
- kernel: near-zero activity for the frozen component (few syscalls/wakeups — it is
  stopped/frozen, not busy); callers show off-CPU external waits on it.
- logs: callers log timeouts/connection failures toward it; the component itself logs
  NOTHING new (it cannot).

## Investigation blueprint
1. query_topology / query_traces: find the flat-timeout plateau and the component the
   hanging edges point at.
2. query_metrics on that component: activity collapse baseline->incident (not a spike).
3. query_kernel on it: minimal activity — distinguishes frozen from slow (a slow
   component still works; a frozen one goes silent).
4. query_logs: verify the SILENCE of the component vs the timeout noise of callers —
   do not blame the loudest logger; the culprit is the quiet one.

## Resolution template
- fault_type dependency_outage: a dependency is down/frozen — calls hang or fail,
  the component produces almost nothing.
- db_latency instead when calls SUCCEED slowly and the component is still active.
- error_storm instead when requests FAIL FAST with error bursts rather than hanging.
Root cause service = the frozen/dead component itself (often the QUIETEST party),
never the callers that time out on it.
