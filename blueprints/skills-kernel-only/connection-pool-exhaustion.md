---
name: connection-pool-exhaustion
version: 2
authored_by: measured from StrataTrace v2 kernel traces
generated_from: blueprints/connection-pool-exhaustion.json
covers: conn_pool_exhaustion
---
## When this applies
- callers of a datastore fail or time out while the datastore is not slow
- the datastore is still running rather than stopped
- the datastore was establishing new connections at a steady rate before the window

Do NOT use this blueprint when:
- the suspect container went silent - that is a stopped dependency
- no container was doing per-connection setup work before the window. Where callers hold pooled connections that are already established, a datastore does almost no setup work and this blueprint can see nothing - measured 0.7-1.1 calls/s on such a system against 169-177 where it works. Report that the check was not applicable rather than naming another container

Cheapest check first: find containers doing at least 20 getpeername/gettid/access calls per second before the window, then see whether any fell to 0.05 or less of that during it

## Problem signature
- callers of a datastore fail or time out while the datastore itself looks healthy
- the symptom is about connection availability, not query latency
- the datastore keeps serving existing clients

Telling it apart from its look-alikes:
- **per-connection setup syscalls inside the datastore - getpeername, gettid and access - as a rate, incident window against its own baseline** — this problem: they collapse while the container keeps running: 169-177/s before against 0.0-0.9/s during, a ratio of 0.00-0.01, in 3 of 3 runs. The container that collapses IS the exhausted datastore and is the answer to WHERE. Not this problem: the datastore goes silent altogether - that is a stopped dependency, not an exhausted pool. An exhausted pool keeps serving the clients it already has.
- **a container present in the window and absent before it, talking on the network** — this problem: the holder: about a third of its events are network and its futex share is zero, measured 36% and 0%. It corroborates, and it tells you WHAT is exhausting the pool. Not this problem: naming this container as the root cause. It is the agent of the fault, not the exhausted resource. The answer is the datastore whose setup work collapsed.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: syscall_entry_futex, sched_switch, sched_stat_runtime, irq_softirq_entry, net_dev_xmit, syscall_entry_ioctl

Why this set: MEASURED BASIS. Every discriminator in this blueprint is a share of these event groups within one container. Nothing else in the trace is required, and no other modality is used - this blueprint was built and validated on kernel traces alone.

## Investigation blueprint
Each step names the capability it needs, how to get at it with the tools you have, and what a correct result looks like. There are no commands: you have a raw kernel trace and six read-only query tools, and nothing else. The 'with your tools' line is a starting point, not an instruction - if you see a better way with the same tools, take it and say what you did. A step marked NOT REACHABLE cannot be done from kernel data: skip it, say you skipped it, and do not treat its absence as evidence either way.

1. Make the kernel trace readable
   needs: `trace.stage_ctf`
   with your tools: already done - the trace is loaded. ctf_timespan gives its real start and end.
   expect: a CTF directory with metadata and channel streams
2. Find containers that are active during the window and absent before it
   needs: `process.creation_attribution`
   with your tools: ctf_proclife shows arrivals and departures directly. sched_process_fork and sched_process_exec rates via query_ctf show how fast processes are being created.
   expect: one container with substantial traffic during the window and none before. If none appears, this blueprint does not apply - say so and stop
3. rank containers by how far their per-connection setup rate fell, counting only those that were doing such work before the window
   needs: `kernel.datastore.connection_setup_collapse`
   with your tools: the answer here is the DATASTORE, not the container that appeared. A container that shows up talking mostly on the network is holding the connections open - it is the agent of the fault, and naming it answers the wrong question. An exhausted datastore does not go quiet and does not saturate: it keeps serving the clients it already has, and stops completing NEW connections. So look for the work it does per new connection. With run_python, count syscall_entry_getpeername, syscall_entry_gettid and syscall_entry_access per pid_ns per second, over a baseline range and over the range you suspect, and keep only containers that were doing at least ~20 of those per second BEFORE - a container that never establishes connections cannot show this. Rank the survivors by how far that rate fell. MEASURED: the exhausted datastore fell from 169-177/s to 0.0-0.9/s while its other events continued, and ranked first among such containers in 3 of 3 runs. IMPORTANT SCOPE. On the second application measured, the datastore did only 0.7-1.1 of these calls per second even before the fault, because its callers hold pooled connections that are already established. There is nothing to collapse, so this check simply does not apply there. If no container clears the baseline floor, say the check was not applicable - do not fall back to naming the busiest container or the newcomer.
   expect: containers that were establishing connections, ranked by the collapse in that work, the steepest named by pid_ns, with its before and after rates
4. Measure what share of its own events that container spends on each kind of work
   needs: `kernel.container.event_shares`
   with your tools: no direct equivalent from a kernel trace - say the step was not run.
   expect: the share profile below, within the measured range
5. Apply the rules and emit the verdict
   needs: `verdict.apply_rules`
   with your tools: do this yourself, from the numbers your own tool calls returned. Quote them.
   expect: name the DATASTORE by its pid_ns, its setup rate before and during, and separately name the holder container if one appeared
6. draw the decision card
   needs: `report.decision_card`
   with your tools: NOT REACHABLE - no plotting here. Skip it; it does not affect the diagnosis.
   expect: one page showing the shares, the cut, and what was ruled out

## What to produce
- json: culprit container pid_ns, its event shares, and the shares of every other container for comparison
- json: per-container event shares for the window
- xy_chart: each family's measured share on the deciding axis, with this run's value marked

## Resolution template
Conclude this problem when ALL of:
- a container was doing at least 20 per-connection setup syscalls per second before the window
- that rate falls to 0.05 or less of itself during the window, while the container keeps producing other events
- the container did NOT go silent overall - an exhausted pool still serves its existing clients

Prefer a different explanation when:
- dependency-outage-retry-storm — the container went silent altogether rather than only stopping new connections - a stopped dependency does no work at all
- db-latency-dependency-wait — the datastore still completes new connections at its usual rate and is merely slow - that is latency, not exhaustion
- cpu-contention-co-tenant — you are about to name the container that APPEARED. That one is holding the connections; the answer is the datastore it is holding them against

Root cause is: the datastore whose per-connection setup work collapsed, named by its pid_ns. The container that appeared is the holder and is not the answer

## When to stop
- Conclude when: a container that was doing per-connection setup work fell to 0.05 or less of its own rate while still producing other events
- Stop and switch: the container went silent altogether, which is a stopped dependency; or its setup rate held, which means the pool is not exhausted
- Evidence insufficient: no container reached 20 setup calls per second in the baseline. Say the check was not applicable on this system - do not substitute another signal
- Do not exceed 3 rounds of gathering more evidence before reporting what is missing.

## Constraints you must respect
- kernel only

## If you are not confident enough
- Do not report a diagnosis below 0.6 confidence.
- report the per-container setup rates before and during, and say whether any container was doing enough of that work to judge
- the ranked setup-rate table with the pid_ns of each container

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the exhausted pool can be seen from the datastore side — **NOT MEASURED**. 
