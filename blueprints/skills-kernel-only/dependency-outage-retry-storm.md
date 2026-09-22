---
name: dependency-outage-retry-storm
version: 1
authored_by: measured from StrataTrace v2 kernel traces
generated_from: blueprints/dependency-outage-retry-storm.json
covers: dependency_outage
---
## When this applies
- requests through one path fail or hang rather than slowing
- one service's activity rises sharply while its peers do not
- no new container appeared during the window

Do NOT use this blueprint when:
- a new container appeared - use the newcomer blueprints instead
- every container moved together, which is host-wide

Cheapest check first: one container's syscall rate rose roughly a hundredfold while containers running the same image did not move

## Problem signature
- requests through one path fail or hang rather than slowing
- one service's resource use rises sharply while its peers do not
- a dependency produces little or no traffic

Telling it apart from its look-alikes:
- **getrusage rate in a single container, against its identical siblings** — this problem: one java container goes from 5.3/s to 2,474-2,701/s while three other java containers stay at 6.7/s (n=2 runs). Not this problem: a host-wide fault moves every container together. If the siblings move too, this is not it.
- **no container is new to the window** — this problem: none. This fault stops an existing container; across every run measured, the newcomer search returns nothing. Not this problem: every other fault family we measured injects a sidecar container, so a newcomer is present.
- **new outbound socket binds in the caller** — this problem: bind 2.7/s -> 22.9/s in the caller container (n=2). Not this problem: bind stays within 1.1-1.6x in every other family.

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
3. Measure what share of its own events that container spends on each kind of work
   needs: `kernel.container.event_shares`
   with your tools: no direct equivalent from a kernel trace - say the step was not run.
   expect: the share profile below, within the measured range
4. Apply the rules and emit the verdict
   needs: `verdict.apply_rules`
   with your tools: do this yourself, from the numbers your own tool calls returned. Quote them.
   expect: a verdict naming the container and the mechanism, or an explicit abstain
5. draw the decision card
   needs: `report.decision_card`
   with your tools: NOT REACHABLE - no plotting here. Skip it; it does not affect the diagnosis.
   expect: one page showing the shares, the cut, and what was ruled out

## What to produce
- json: culprit container pid_ns, its event shares, and the shares of every other container for comparison
- json: per-container event shares for the window
- xy_chart: each family's measured share on the deciding axis, with this run's value marked

## Resolution template
Conclude this problem when ALL of:
- a container is new to the window
- its share profile matches the measured range below
- no sibling container shows the same profile

Prefer a different explanation when:
- cpu-contention-co-tenant — a container IS new to the window - this fault removes a container, it does not add one
- host-cpu-saturation — every container moved together rather than one moving alone

Root cause is: the stopped dependency. The container that spins is the VICTIM, and naming it as the culprit is the mistake this blueprint exists to prevent

## When to stop
- Conclude when: the share profile matches and no sibling container matches it too
- Stop and switch: a discriminating share falls outside its measured range
- Evidence insufficient: no container is new to the window and none stands out
- Do not exceed 3 rounds of gathering more evidence before reporting what is missing.

## Constraints you must respect
- kernel only

## If you are not confident enough
- Do not report a diagnosis below 0.6 confidence.
- report the shares and say which blueprint they sit between
- the container's shares and every sibling's, side by side

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the stopped dependency can be named directly from the kernel trace — **NOT SUPPORTED**. 
- getrusage is the mechanism rather than an artefact of this runtime — **PARTLY SUPPORTED - n=2, and JVM-specific**. 
