---
name: deadlock-lock-order
version: 2
authored_by: measured from StrataTrace v2 kernel traces
generated_from: blueprints/deadlock-lock-order.json
covers: deadlock
---
## When this applies
- a service stopped responding rather than slowing
- its resource use fell rather than rose
- a kernel trace is available

Do NOT use this blueprint when:
- no container is new to the window
- an EXISTING container went silent - that is a stopped dependency
- the suspect is an ordinary service with a high futex share and no arrival - on a JVM that is normal, not a fault

Cheapest check first: find a container present in the window and absent before it, then read its events per second: at or above 10000 is one of the spinning faults, at or below 2000 is a deadlock.

## Problem signature
- a service stops responding rather than slowing down
- its CPU use falls instead of rising
- requests time out rather than returning late

Telling it apart from its look-alikes:
- **the newcomer container's kernel event rate and softirq share** — this problem: 87-731 events/s across 6 runs on two applications, against 16,476-63,380 for the two spinning faults - roughly a hundredfold apart. Not this problem: DO NOT decide this by finding the container with the highest futex share. Measured on two applications: the injected container sits at 41-47% futex against siblings at 33% on one, and at 52-58% against siblings at 60% on the other. Where services run on a JVM, threads park on futexes and an ordinary service is futex-heavy by nature, so the comparison inverts and the rule names an innocent service. Use the newcomer test and the rate..

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
- a container is present in the window that was absent before it
- it produces 2000 kernel events per second or fewer - it arrived and then stopped working
- no sibling container went silent, which would be a stopped dependency instead

Prefer a different explanation when:
- lock-contention-futex-storm — the newcomer produces 10000 events per second or more - it is spinning, not parked
- dependency-outage-retry-storm — no container is new and an EXISTING one went silent - that is a stopped dependency, not a deadlock

Root cause is: the newcomer container, named by its pid_ns

## When to stop
- Conclude when: a newcomer matched the rate and softirq ranges above
- Stop and switch: a discriminating share falls outside its measured range
- Evidence insufficient: no container is new to the window. Say so rather than naming the most futex-heavy container, which on a JVM application is an ordinary service
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
- a deadlock can be told from a crashed or stopped container — **NOT SUPPORTED by this evidence**. 
