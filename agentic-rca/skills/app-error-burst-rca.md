---
name: app-error-burst-rca
version: 1
authored_by: human
covers: error_storm
user_triggers: errors spiking | 5xx storm | requests failing | error rate up
---
## Problem signature
- logs: THE dominant change — one service's err_per_min multiplies (change_x large) or
  bursts of NEW error signatures appear (connection resets, refusals, 5xx, driver
  errors); the burst is concentrated, not spread thinly everywhere.
- topology/traces: latency only moderately affected; requests FAIL FAST rather than
  hang — p95 may barely move while error counts jump.
- metrics: no meaningful resource movement on the erroring service (cpu/mem/disk quiet).
- kernel: little change; possibly elevated net syscall churn from retries/reconnects.

## Investigation blueprint
1. query_logs (no filter): rank by change_x and NEW signatures — identify the service
   whose error rate CHANGED (ignore chronic signatures present in baseline).
2. Read the new signatures: connection resets/refusals toward a downstream component
   mean the error SOURCE may be the connection path to that component; application-level
   exceptions/5xx mean the erroring service itself.
3. query_traces on the erroring service and its callers: confirm fail-fast (moderate
   latency) vs hang-to-timeout (outage-style).
4. query_metrics/query_kernel on the candidates: confirm the absence of resource cause.

## Resolution template
- fault_type error_storm: a burst of application errors/5xx or connection errors at one
  service/path while latency stays moderate and resources are quiet.
- dependency_outage instead when calls HANG to timeout and the downstream serves
  little/no successful traffic (frozen, not erroring).
- db_latency instead when calls SUCCEED slowly rather than fail.
Root cause service = the service where the new errors ORIGINATE (the deepest component
named in the failing connection path), not the callers that propagate them.
