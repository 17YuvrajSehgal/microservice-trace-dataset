---
name: db-latency-dependency-wait
version: 5
authored_by: human
generated_from: blueprints/db-latency-dependency-wait.json
covers: slow_db
mutually_exclusive_with: cpu-contention-co-tenant
---
## When this applies
- caller latency inflates sharply while error rates stay flat
- the slow call paths all end at the same downstream component
- that component is not busy

Do NOT use this blueprint when:
- calls fail or hang to timeout rather than returning slowly
- every hop slows by a similar factor, which points at the network
- many unrelated processes are delayed together, which points at CPU contention

Cheapest check first: one component has slow incoming edges and no slow outgoing edges

## Problem signature
- caller latency inflates sharply, often by 10x or more
- the slow call edges all converge on one shared downstream component
- that component is resource-quiet: CPU flat or falling, no disk or memory pressure
- requests still succeed, so error rates barely move

Telling it apart from its look-alikes:
- **blocking-syscall duration of the suspect component** — this problem: ONE socket-waiting syscall inflates by an order of magnitude while everything else stays flat. Not this problem: no syscall inflates by more than about 2x.
- **runqueue delay of the suspect** — this problem: flat - the component is not waiting for a CPU, it is waiting for a reply. Not this problem: runqueue delay inflates several-fold across many processes.
- **call-graph convergence** — this problem: slow edges converge on ONE component that has no slow outgoing edges of its own. Not this problem: nothing converges; edge slowdowns stay near 1x.
- **the SAME socket wait, as an upper bound** — this problem: inflates into the tens - at most 144x across 22 runs. Not this problem: a defect in the calling service parks it at 651x or more, in every one of 25 runs on five different defects.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_waking, sched_switch, syscall_entry_poll, syscall_exit_poll, syscall_entry_recvfrom, syscall_exit_recvfrom, syscall_entry_epoll_wait, syscall_exit_epoll_wait
- metrics: container_cpu_usage_seconds_total, container_fs_reads_bytes_total, container_fs_writes_bytes_total, container_network_receive_bytes_total
- traces: caller to callee edge latency, baseline versus incident, so convergence can be seen
- logs: error-rate change per container, to confirm calls succeed rather than fail

Why this set: MEASURED BASIS. The verdict rests on how long the component blocks inside its socket-waiting syscall, so entry AND exit of those calls are required - entry alone gives no duration. The two scheduler events are needed for the negative control: showing runqueue delay is FLAT is what rules out CPU starvation. This is strictly more than the CPU-contention blueprint needs, and that difference is the point: the two problems genuinely require different collection sequences.

## Investigation blueprint
Each step names the capability it needs, how to get at it with the tools you have, and what a correct result looks like. There are no commands: you have a raw kernel trace and six read-only query tools, and nothing else. The 'with your tools' line is a starting point, not an instruction - if you see a better way with the same tools, take it and say what you did. A step marked NOT REACHABLE cannot be done from kernel data: skip it, say you skipped it, and do not treat its absence as evidence either way.

1. Make the kernel trace readable
   needs: `trace.stage_ctf`
   with your tools: already done - the trace is loaded. ctf_timespan gives its real start and end.
   expect: a CTF directory with metadata and channel streams
2. Find which component the slow call paths converge on
   needs: `traces.call_graph.convergence`
   with your tools: NOT REACHABLE from a kernel trace - there are no spans, so there is no call graph. Do not guess at one. Say the check could not be run, and do not treat its absence as either supporting or refuting the blueprint.
   expect: one component with slow incoming and no slow outgoing edges; it may be the CALLER of the culprit if the culprit emits no spans
3. Measure how long the suspect blocks inside each syscall
   needs: `kernel.syscall.blocking_duration`
   with your tools: query_ctf on syscall_entry_poll, syscall_entry_epoll_wait, syscall_entry_recvfrom, syscall_entry_read per range. Rates only - durations need pairing with the exits, which these tools cannot do. Say so rather than implying you measured duration.
   expect: one socket-waiting syscall inflated by roughly an order of magnitude
4. NEGATIVE CONTROL: confirm the suspect is not merely CPU-starved
   needs: `kernel.scheduler.runqueue_delay`
   with your tools: the delay is sched_waking to the sched_switch that runs the thread. You cannot join those two per thread with these tools, so use the rate of sched_waking against sched_switch as a proxy, and say in your evidence that it is a proxy.
   expect: runqueue delay flat; if it inflates broadly this is the CPU-contention blueprint instead
5. Combine into the verdict and its artifacts
   needs: `verdict.dependency_wait`
   with your tools: do this yourself, from the numbers your own tool calls returned. Quote them.
   expect: a named component, the syscall it blocked in, its inflation factor, and the flat runqueue delay that rules out CPU starvation
6. State the recommended action alongside the diagnosis
   needs: `verdict.dependency_wait`
   with your tools: do this yourself, from the numbers your own tool calls returned. Quote them.
   expect: an action aimed at the blocked component or its dependency, explicitly not at the victims named by the call graph
7. draw the decision card
   needs: `report.decision_card`
   with your tools: NOT REACHABLE - no plotting here. Skip it; it does not affect the diagnosis.
   expect: one page showing where every fault family sits on this blueprint's deciding number, which gates passed and by how much, and what else was ruled out

## What to produce
- xy_chart: the decision itself: every fault family on the deciding axis with the cut drawn, the closest fault to that cut, each gate with its measured value and its bar, and the other blueprints with the number that ruled each one out
- json: the blocked component, the syscall and its inflation, the convergence point, and the runqueue-delay control
- xy_chart: syscall duration p95 baseline vs incident, per component and syscall
- text: what was waiting, on what, and why its callers are victims
- text: what to do about it: investigate the named component's own downstream dependency or the path between it and its callers, not the callers themselves

## Resolution template
Conclude this problem when ALL of:
- one component's socket-waiting syscall inflates to at least 5x its baseline, but stays below 306x. Both ends matter: below the floor nothing is waiting, and above the ceiling the caller is not waiting for an answer, it has stopped working
- that component's runqueue delay stays below 5x, so it is not short of CPU - it is blocked, not starved
- an endpoint really is answering slowly, at least 18x its baseline. Blocking says a process is waiting; this says something is answering slowly
- retransmission stays below 12%, so the path is not losing packets
- traffic continues to succeed, so error rates barely move
- the endpoint measurement is actually available. If it is missing the answer is 'cannot confirm', not 'assume yes' - an absent measurement is not evidence

Prefer a different explanation when:
- a defect in the calling service, not in what it calls — the socket wait is enormous - 306x baseline or more. A slow dependency still ANSWERS, so its caller keeps working and tops out near half that. A caller parked in one poll call for most of the window has stopped doing work: a blocked event loop, a chain of awaits that no longer overlap, or a lock held across I/O. The thing it calls is healthy.
- co-tenant CPU contention — runqueue delay inflates broadly across many processes while no syscall inflates much
- a frozen dependency — calls fail or hang to timeout instead of returning slowly
- host disk saturation — the inflated wait is a disk syscall and other disk users degrade too

Root cause is: the converged-on datastore component itself, never its callers, which are victims

## When to stop
- Conclude when: one component's socket-waiting syscall is inflated by roughly an order of magnitude while its runqueue delay stays flat
- Stop and switch: socket wait at or above {BLOCK_PARKED_X}x baseline -> the caller has stopped working; look for a defect in the calling service, not in the dependency. Runqueue delay at or above {STARVED_RQ_X}x -> the component is starved of CPU. Retransmission at or above {RETRANS_VETO_PCT}% -> the path is losing packets. IMPORTANT: switching away does not mean the investigation is over. Each of these names a DIFFERENT cause for the same symptom, so carry the measurement across rather than starting again - the wait you measured here is still real, it just has another source.
- Evidence insufficient: the endpoint measurement is missing, so 'something is answering slowly' cannot be confirmed -> request it and re-run. Do NOT treat an unavailable check as passed: three false diagnoses were produced exactly that way before this was changed.
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## Constraints you must respect
- Use evidence that already exists before enabling any new collection. Escalate a tier only when the cheaper tier leaves a candidate cause unresolved, and record why.
- Keep total added collection overhead under 8%.
- do not collect request payloads
- do not retain personally identifiable data
- preserve request identifiers only where permitted
- These need human approval before you do them: active collection estimated above 3% overhead; widening the host scope or time window; any change to production configuration; any remediation action.

## If you are not confident enough
- Do not report a diagnosis below 0.7 confidence.
- name the unresolved question, pick the ONE additional capability that would settle it, check it against the overhead budget, and request it. Do not broaden collection generally.
- if the floor is still not met after the allowed rounds, report the best-supported hypothesis, its confidence, and precisely what evidence is missing - never present a guess as a diagnosis

## If the evidence does not fit
- If convergence names a component that itself has slow outgoing edges, then it is a pass-through victim: follow its slow edge and re-run convergence one hop deeper.
- If the inflated wait is a disk syscall rather than a socket syscall, then this is storage, not a downstream dependency; check whether other disk users degraded too.
- If no component emits spans on the suspected path, then fall back to kernel evidence alone and identify the blocked component by syscall duration, accepting that the call graph cannot confirm it.

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the converged-on component shows dominant off-CPU external I/O wait, and that is what identifies it — **TRUE BUT NOT DISCRIMINATIVE**. A dominant off-CPU external-I/O SHARE on the suspect. Measured at 98-99% for every labelled fault, because that share is dominated by ordinary idle waiting. Use the DURATION of the specific blocking syscall instead.
