---
name: dependency-outage-retry-storm
version: 2
authored_by: measured from StrataTrace v2 kernel traces
generated_from: blueprints/dependency-outage-retry-storm.json
covers: dependency_outage
---
## When this applies
- requests through one path fail or hang rather than slowing
- one container stopped producing kernel events while its peers did not
- no new container appeared during the window

Do NOT use this blueprint when:
- a new container appeared - use the newcomer blueprints instead
- every container moved together, which is host-wide
- the suspect is running at a reduced but steady rate rather than near zero

Cheapest check first: rank containers by incident event rate divided by their own baseline rate. If the lowest is at or below 0.02 and the next is at or above 0.2, this is it.

## Problem signature
- requests through one path fail or hang rather than slowing
- one container stops producing kernel events while its peers do not
- no new container appeared during the window

Telling it apart from its look-alikes:
- **each container's total kernel event rate, incident window against its own baseline, ranked lowest first** — this problem: exactly ONE container falls to 0.09-1.19% of its baseline rate while the next quietest container is still at 23-89%. That container is the stopped dependency and it is the answer to WHERE. Not this problem: nothing falls that far, or several containers fall together - several falling together is host-wide, not one dependency.
- **getrusage rate in the container that CALLS the stopped dependency** — this problem: on one of the two applications the caller storms: 6.7/s before against 2474-2701/s during, a 371-404x rise, while sibling containers running the same image stay flat. Not this problem: on the OTHER application the same fault produced NO getrusage rise at all - 1.0x, measured on 2 runs. Absence of a storm is therefore not evidence against this problem, and this signal must never be required. Use it to corroborate and to name the victim, never to decide.

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
4. rank every container by its incident event rate divided by its own baseline rate, lowest first, and name the one that went silent
   needs: `kernel.container.silence_ranking`
   with your tools: this fault REMOVES a workload rather than adding one, so looking for a newcomer finds nothing - measured, there was no new container in 3 of 3 runs on one application. And do not name the busiest container: the one that storms is the VICTIM calling into the dependency that stopped. What to do instead, with run_python: sum `count` per pid_ns over a quiet baseline range and over the range you suspect, divide each container's incident rate by its OWN baseline rate, and rank lowest first. Report the lowest by its pid_ns, and report the SECOND lowest too - the gap between them is what separates one stopped workload from a host-wide slowdown. DO NOT RESTRICT THIS TO THE BUSY CONTAINERS. The ranking is on each container's ratio to ITS OWN baseline, so a container does not need to be large to qualify, and the one you are looking for usually is not: measured, the stopped container ran at 377-1,521 events/s while the busiest on the same host ran at over 87,000. A filter like 'only containers above N events per second' or 'only substantial containers' removes the answer by construction and leaves you reporting, in good faith, that no container went quiet. Include every container with a baseline above roughly 50 events/s - that is only to drop pure noise - and rank all of them. MEASURED on 6 runs across two applications: exactly one container fell to 0.09-1.19% of its own baseline while the next quietest was still at 23-89%. It ranked first in all 6 and was the injected target in both applications. That is a separation of 20x to 75x, so this is not a marginal call. If the lowest is only moderately reduced rather than near zero, this is not an outage - a throttled container keeps running at a steady reduced rate. If several containers fell together, that is host-wide. Say which of the three you saw.
   expect: containers ranked by how far their own rate fell, the lowest named by pid_ns, and the next-lowest reported so the size of the gap is visible
5. Apply the rules and emit the verdict
   needs: `verdict.apply_rules`
   with your tools: do this yourself, from the numbers your own tool calls returned. Quote them.
   expect: name the SILENT container by its pid_ns, its before and after rates, and the next-quietest container's rate as the contrast
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
- exactly one container that was busy before falls to 0.02 or less of its own baseline event rate
- the next quietest container is still at 0.2 or more of its own baseline, so the drop is an outlier rather than a general slowdown
- no new container appeared - this fault removes a workload rather than adding one

Prefer a different explanation when:
- cpu-contention-co-tenant — a container IS new to the window - this fault removes a container, it does not add one
- host-cpu-saturation — many containers fell together rather than one falling alone. Measured, the next quietest container here still runs at 23-89% of its baseline
- service-cpu-throttle — the suspect is still running but held at a flat ceiling. A stopped dependency goes to near zero, not to a steady reduced rate

Root cause is: the container that went silent. It is the stopped dependency and it is the answer to WHERE. A container that storms on getrusage is the VICTIM calling into it, and naming that one is the mistake this blueprint exists to prevent

## When to stop
- Conclude when: exactly one container fell to 0.02 or less of its own baseline while the next quietest stayed at 0.2 or more
- Stop and switch: several containers fell together, which is host-wide; or the lowest is only moderately reduced, which is throttling rather than an outage
- Evidence insufficient: no container fell far below its own baseline. Say so rather than naming the busiest container, which is the victim at best
- Do not exceed 3 rounds of gathering more evidence before reporting what is missing.

## Constraints you must respect
- kernel only

## If you are not confident enough
- Do not report a diagnosis below 0.6 confidence.
- report the per-container before and after rates and say that no container went silent
- the ranked list of containers by incident rate over baseline rate, with the pid_ns of the lowest

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the stopped dependency can be named directly from the kernel trace — **NOT SUPPORTED**. 
- getrusage is the mechanism rather than an artefact of this runtime — **PARTLY SUPPORTED - n=2, and JVM-specific**. 
