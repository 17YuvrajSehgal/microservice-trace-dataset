---
name: connection-pool-exhaustion
version: 1
authored_by: measured from StrataTrace v2 kernel traces
generated_from: blueprints/connection-pool-exhaustion.json
covers: conn_pool_exhaustion
---
## When this applies
- callers of a datastore fail or time out while the datastore is idle
- the symptom is about connection availability, not query latency
- a kernel trace is available

Do NOT use this blueprint when:
- the datastore is itself busy or slow - see db-latency-dependency-wait
- no container is new to the window

Cheapest check first: a container appeared whose events are mostly network and ioctl, with no futex at all

## Problem signature
- callers of one datastore start failing or timing out
- the datastore itself is not busy
- the failure is about availability of connections, not latency

Telling it apart from its look-alikes:
- **ioctl share** — this problem: 17.3% (n=5). Not this problem: ioctl does not appear at all in any other family measured - 0.0% for lock contention, deadlock, priority inversion, both stress families and the network fault.
- **network share with no futex** — this problem: network 35.6% and futex 0.0% (n=5) - it talks, it does not lock. Not this problem: the delayed-ack fault also carries network (17.9%) but with 25.8% futex alongside it.
- **it is nearly idle for the work it appears to be doing** — this problem: 545-550 events/s with on-CPU at 3.2% (n=5) - holding, not working. Not this problem: a busy client would show far more on-CPU time.

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
- nagle-delayed-ack-stall — network is present but futex is around 26% rather than 0%
- db-latency-dependency-wait — no container is new to the window and the datastore itself is slow

Root cause is: the container holding connections open against the datastore

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
- the exhausted pool can be seen from the datastore side — **NOT MEASURED**. 
