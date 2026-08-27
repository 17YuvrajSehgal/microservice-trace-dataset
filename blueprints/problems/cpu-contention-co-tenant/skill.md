---
name: cpu-contention-co-tenant
version: 6
authored_by: human
generated_from: blueprints/cpu-contention-co-tenant.json
covers: noisy_neighbor                       # harness metadata: scoring + LOFO; NEVER shown to the model
mutually_exclusive_with: db-latency-dependency-wait
---
## When this applies
- several unrelated services degrade mildly at the same time
- no single component is saturated
- error rates are unchanged and requests still succeed

Do NOT use this blueprint when:
- one component alone is slow while the rest are healthy
- requests are failing or timing out rather than merely slowing
- the host is fully exhausted and latency collapses rather than jitters

Cheapest check first: host CPU rose but retains headroom, and no container on the call graph accounts for the extra CPU

## Problem signature
- mild, intermittent latency jitter across several unrelated services at once
- no service is itself busy: per-container CPU is flat or falling
- no new error signatures; requests still succeed
- host CPU busy rises but is not exhausted, and host load rises moderately

Telling it apart from its look-alikes:
- **runqueue delay: time from sched_waking to the sched_switch that runs the thread** — this problem: p95 runqueue delay inflates several-fold across MANY unrelated processes at once, with the busiest application process among the worst. Not this problem: runqueue delay is flat or falls; the median across processes stays at or below 1x.
- **blocking duration of socket-WAITING syscalls (poll, epoll_wait, recvfrom, read, select)** — this problem: socket-waiting durations stay flat: nothing is blocking longer, the threads simply cannot get a CPU. Not this problem: one component's socket-waiting syscall inflates by an order of magnitude.
- **call-graph convergence** — this problem: no component has slow incoming edges; the slowdown does not converge anywhere. Not this problem: slow edges converge on one component.
- **where the CPU went** — this problem: a container consumes steady CPU it did not consume in the baseline and has NO call-graph edges. Not this problem: the extra CPU belongs to a service that appears in the call graph.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_waking, sched_switch
- metrics: container_cpu_usage_seconds_total, container_cpu_cfs_throttled_seconds_total, node_cpu_seconds_total, node_load1
- traces: server span duration per service, only to confirm the impact is mild

Why this set: MEASURED BASIS. Runqueue delay needs exactly two tracepoints: sched_waking gives the moment a thread became runnable, and sched_switch (next_tid) gives the moment a CPU actually ran it. The difference is the delay. Syscall events are collected only as the NEGATIVE control - showing durations stay flat is what separates this from a component blocked on I/O. Nothing else in the kernel trace is required.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. Make the kernel trace readable
   needs: `trace.stage_ctf`
   run [local]: `cp -r <run_dir>/kernel/kernel <tmp>/ctf && gunzip -f <tmp>/ctf/*.gz`
   expect: a CTF directory with metadata and channel streams
2. Measure runqueue delay per process, baseline vs incident
   needs: `kernel.scheduler.runqueue_delay`
   run [babeltrace2-cli]: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/runqueue_delay.py --ctf <ctf> --gt <ground_truth> --out <out>/rq.json`
   expect: a broad multi-process inflation of p95 indicates contention
3. NEGATIVE CONTROL: confirm blocking-syscall durations did not inflate
   needs: `kernel.syscall.blocking_duration`
   run [babeltrace2-cli]: `python3 blueprints/problems/db-latency-dependency-wait/scripts/blocking_syscall.py --ctf <ctf> --gt <ground_truth> --comms <comms> --out <out>/blocking.json`
   expect: no syscall inflates much; a large single-component inflation means this is the wrong blueprint
4. Identify the off-call-path CPU consumer and emit the verdict
   needs: `metrics.container.cpu_attribution`
   run [prometheus-cadvisor]: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/cpu_attribution.py --run <run_dir> --out <out>/verdict.json --chart <out>/runqueue.svg --text <out>/explanation.txt`
   expect: the top CPU consumer has no call-graph edges and was absent in the baseline
5. State the recommended action alongside the diagnosis
   needs: `metrics.container.cpu_attribution`
   run [prometheus-cadvisor]: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/cpu_attribution.py --run <run_dir> --out <out>/verdict.json --chart <out>/runqueue.svg --text <out>/explanation.txt`
   expect: a concrete action naming the container to constrain, not a generic suggestion

## What to produce
- json: culprit container, per-service runnable-wait share baseline versus incident, host CPU headroom
- xy_chart: runnable-wait share per service over time, with the incident window shaded
- text: which container took the CPU, which services waited, and why this is contention rather than saturation
- text: what to do about it: identify and reschedule or cap the co-tenant workload, or move the affected services to a less contended host

## Resolution template
Conclude this problem when ALL of:
- p95 runqueue delay inflates several-fold across many unrelated processes
- blocking-syscall durations stay flat over the same window
- the slowdown does not converge on any single component in the call graph
- a container with no call-graph role consumes CPU it did not consume in the baseline

Prefer a different explanation when:
- a component waiting on I/O or a dependency — one component's blocking syscall inflates by an order of magnitude while runqueue delay stays flat
- host CPU exhaustion — host CPU is exhausted rather than merely raised, and user latency collapses instead of jittering
- a service pinned by its own CPU limit — only ONE service is delayed and it is on the call path

Root cause is: the co-tenant workload container itself, not any application service it delays

## When to stop
- Conclude when: runqueue delay is broadly inflated, syscall durations are flat, and an off-call-path container accounts for the CPU
- Stop and switch: a single component's blocking syscall inflates by an order of magnitude while runqueue delay stays flat -> use the dependency-wait blueprint
- Evidence insufficient: runqueue delay cannot be computed because the scheduler events were not recorded -> request them and re-run; do not guess from utilisation alone
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## Constraints you must respect
- Use evidence that already exists before enabling any new collection. Escalate a tier only when the cheaper tier leaves a candidate cause unresolved, and record why.
- Keep total added collection overhead under 5%.
- do not collect request payloads
- do not retain personally identifiable data
- preserve request identifiers only where permitted
- These need human approval before you do them: active collection estimated above 3% overhead; widening the host scope or time window; any change to production configuration; any remediation action.

## If you are not confident enough
- Do not report a diagnosis below 0.7 confidence.
- name the unresolved question, pick the ONE additional capability that would settle it, check it against the overhead budget, and request it. Do not broaden collection generally.
- if the floor is still not met after the allowed rounds, report the best-supported hypothesis, its confidence, and precisely what evidence is missing - never present a guess as a diagnosis

## If the evidence does not fit
- If the runqueue signal is present but no off-call-path container is found, then the contention is internal: re-check whether an on-call-path service is consuming the CPU, which points at a service-level cause instead.
- If only one process shows inflated runqueue delay, then this is not host-wide contention; consider a per-service CPU limit.
- If the trace covers less than the full incident window, then widen the window before comparing, since short windows exaggerate percentiles.

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the delayed services show a raised runnable_wait share (ready to run, waiting for a CPU) — **NOT SUPPORTED by our data**. The share of wall time a service spends in a runnable state. Measured across every labelled fault: it never exceeds 4%, because that share is diluted by ordinary idle waiting. Use per-wakeup runqueue DELAY instead, which shows the effect clearly.
- the wait decomposition of the culprit distinguishes this fault — **CANNOT BE MEASURED for this family**. The wait decomposition of the culprit. For host-attributed faults no culprit-side wait record exists at all, so its absence is meaningless here.
