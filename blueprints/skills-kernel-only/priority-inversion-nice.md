---
name: priority-inversion-nice
version: 1
authored_by: measured from StrataTrace v2 kernel traces
generated_from: blueprints/priority-inversion-nice.json
covers: priority_inversion
---
## When this applies
- a service is slow without CPU saturation
- a container shows a high futex share
- a kernel trace is available

Do NOT use this blueprint when:
- the container is nearly idle - see deadlock-lock-order
- futex share is near zero

Cheapest check first: a container with a futex share above 40% and softirq above 10%

## Problem signature
- a service is slow and its CPU is not saturated
- the slowdown is worse than the offered load explains
- some requests are far slower than others

Telling it apart from its look-alikes:
- **futex share, which puts it in the lock family** — this problem: 41.0% (n=5). Not this problem: a deadlock sits at 4.3%; the stress and network families at 0%.
- **softirq share, which separates it from plain lock contention** — this problem: 13.4% (n=5). Not this problem: lock contention sits at 5.9% (n=5), less than half.
- **threads migrate LESS than under plain contention** — this problem: migrate 2.0% (n=5) - they are held off CPU, not bouncing. Not this problem: lock contention 5.0% (n=5).

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
- lock-contention-futex-storm — migration is around 5% and softirq around 6%, measured against 2.0% and 13.4% here
- deadlock-lock-order — futex falls to a few percent and the container goes nearly silent

Root cause is: the container whose threads hold a lock while being scheduled away

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
- the inversion can be seen directly in scheduler priority fields — **NOT MEASURED - and it is the check that would settle it**. 
