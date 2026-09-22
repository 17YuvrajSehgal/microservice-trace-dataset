---
name: lock-contention-futex-storm
version: 1
authored_by: measured from StrataTrace v2 kernel traces
generated_from: blueprints/lock-contention-futex-storm.json
covers: lock_contention
---
## When this applies
- a service is slow without being CPU-saturated
- latency is erratic rather than uniformly raised
- a kernel trace is available and futex syscalls are traced

Do NOT use this blueprint when:
- the suspect container is nearly idle - see deadlock-lock-order
- no container is new to the window
- futex is not in the collection profile, in which case this cannot be measured at all

Cheapest check first: one container's futex share is above 40% while every other is near zero

## Problem signature
- a service is slow but its CPU is not saturated
- latency is erratic rather than uniformly higher
- the slowdown does not follow a call path to a dependency

Telling it apart from its look-alikes:
- **share of the container's own events spent on futex** — this problem: 47.0% (n=5, range 46.6-47.3). Not this problem: a deadlock sits at 4.3% because parked threads make no calls; a stress container, a memory stressor and a connection-pool holder all sit at 0%.
- **thread migration share, which separates it from priority inversion** — this problem: 5.0% (n=5) - threads bounce between CPUs chasing the lock. Not this problem: priority inversion sits at 2.0% and carries more softirq (13.4% against 5.9%). This is the weaker of the two discriminators and must not decide on its own.
- **the container is busy, not idle** — this problem: sched churn 26.4% and on-CPU 14.7% (n=5): work is being done. Not this problem: a deadlock is nearly silent - measured 70-84 events/s against 62,780-63,647 here, a factor of 800.

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
- deadlock-lock-order — the container's futex share is near 4% and it produces only tens of events per second - parked, not spinning
- priority-inversion-nice — softirq is above 10% and migration below 3%, measured 13.4% and 2.0% there against 5.9% and 5.0% here
- cpu-contention-co-tenant — futex is 0% and softirq above 35% - a stress container, not a lock

Root cause is: the container whose futex share is far above every other container

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
- raised runqueue delay identifies lock contention — **NOT TESTED HERE - and known to fire everywhere**. 
