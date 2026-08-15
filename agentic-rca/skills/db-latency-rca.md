---
name: db-latency-rca
version: 1
authored_by: human
user_triggers: ["database is slow", "db latency", "queries are slow", "slow db"]
problem_signature:
  - topology: slow caller->callee edges converge on ONE service which itself has no slow
    outgoing edges (or emits no spans at all)
  - kernel: the converged-on service shows dominant off-CPU external I/O wait
    (wait_attribution off_cpu_io_wait high) WITHOUT cpu/memory/disk saturation
  - metrics: the converged-on service is resource-quiet (cpu/mem/fs flat or falling)
    while its callers' latency inflates
  - logs: few or no NEW error signatures on the converged-on service (traffic succeeds,
    slowly — it is not erroring or down)
---

# Database / datastore latency RCA

## When the evidence fits
Many user-facing services degrade, but their slow edges all point at one shared
downstream component — typically a datastore — which is itself calm on every resource
signal. The datastore is not broken; its RESPONSES are slow, and the slowness is
imposed from outside its own compute (induced latency, a slow proxy/network path in
front of it, or storage-side stall).

## Investigation blueprint
1. `query_topology` (no filter): confirm convergence — the suspect has slow INCOMING
   edges only. If its own outgoing edges are also slow, follow them deeper instead.
2. `query_kernel` on the suspect: expect high off-CPU external-I/O wait and/or elevated
   syscall latency, with unremarkable on-CPU time.
3. Rule out look-alikes on the suspect:
   - disk saturation (block latency / io_time up host-wide -> host disk fault instead),
   - CPU cap (throttled-seconds jump -> cpu_throttling instead),
   - memory pressure (reclaim/writeback -> memory fault instead).
4. `query_logs` on the suspect and its top caller: connection RESETS/refusals point to
   an outage-style fault, not latency.

## Resolution template
- **db_latency** when calls to the datastore SUCCEED but slowly, and the datastore
  waits on external I/O while unsaturated.
- **dependency_outage** instead when calls FAIL or hang to timeout and the component
  serves little/no successful traffic.
- **disk_io** instead when the whole host's disk is saturated (other disk users
  degrade too).

Root cause service = the converged-on datastore component (as named in telemetry),
not its callers — they are victims.
