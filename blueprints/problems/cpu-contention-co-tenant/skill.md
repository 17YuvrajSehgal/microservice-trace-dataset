---
name: cpu-contention-co-tenant
version: 3
authored_by: human
generated_from: blueprints/cpu-contention-co-tenant.json
covers: noisy_neighbor                       # harness metadata: scoring + LOFO; NEVER shown to the model
mutually_exclusive_with: db-latency-dependency-wait
---
## Problem signature
- mild, intermittent latency jitter across several unrelated services at once
- no service is itself busy: per-container CPU is flat or falling
- no new error signatures; requests still succeed
- host CPU busy rises but is not exhausted, and host load rises moderately

Telling it apart from its look-alikes:
- **runqueue delay: time from sched_waking to the sched_switch that runs the thread** — this problem: p95 runqueue delay inflates several-fold across MANY unrelated processes at once, with the busiest application process among the worst. Not this problem: runqueue delay is flat or falls; the median across processes stays at or below 1x.
- **blocking-syscall duration of the same processes** — this problem: syscall durations stay flat: nothing is blocking longer, the threads simply cannot get a CPU. Not this problem: one component's blocking syscall inflates by an order of magnitude.
- **call-graph convergence** — this problem: no component has slow incoming edges; the slowdown does not converge anywhere. Not this problem: slow edges converge on one component.
- **where the CPU went** — this problem: a container consumes steady CPU it did not consume in the baseline and has NO call-graph edges. Not this problem: the extra CPU belongs to a service that appears in the call graph.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_waking, sched_switch
- metrics: container_cpu_usage_seconds_total, container_cpu_cfs_throttled_seconds_total, node_cpu_seconds_total, node_load1
- traces: server span duration per service, only to confirm the impact is mild

Why this set: MEASURED BASIS. Runqueue delay needs exactly two tracepoints: sched_waking gives the moment a thread became runnable, and sched_switch (next_tid) gives the moment a CPU actually ran it. The difference is the delay. Syscall events are collected only as the NEGATIVE control - showing durations stay flat is what separates this from a component blocked on I/O. Nothing else in the kernel trace is required.

## Investigation blueprint
1. Stage the raw kernel trace (channels are stored gzipped)
   run: `cp -r <run_dir>/kernel/kernel <tmp>/ctf && gunzip -f <tmp>/ctf/*.gz`
   expect: a CTF directory with metadata plus channel0_* streams. The metadata is CTF 2 (JSON preamble), so babeltrace 2.1 or newer is required; 2.0.x fails with an invalid-metadata error
2. Measure runqueue delay per process, baseline window vs incident window
   run: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/runqueue_delay.py --ctf <tmp>/ctf --gt <run_dir>/ground_truth.json --out <out>/rq.json`
   expect: millions of wake->run pairs per window; a broad multi-process inflation of p95 indicates contention
3. NEGATIVE CONTROL: confirm blocking-syscall durations did NOT inflate
   run: `python3 blueprints/problems/db-latency-dependency-wait/scripts/blocking_syscall.py --ctf <tmp>/ctf --gt <run_dir>/ground_truth.json --out <out>/blocking.json`
   expect: no syscall inflates by more than about 2x; a 10x or larger inflation on one component means this is NOT the right blueprint
4. Identify the off-call-path CPU consumer and emit the verdict
   run: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/cpu_attribution.py --run <run_dir> --out <out>/verdict.json --chart <out>/runqueue.svg --text <out>/explanation.txt`
   expect: the top CPU consumer has no call-graph edges and was absent in the baseline

## What to produce
- json: culprit container, per-service runnable-wait share baseline versus incident, host CPU headroom
- xy_chart: runnable-wait share per service over time, with the incident window shaded
- text: which container took the CPU, which services waited, and why this is contention rather than saturation

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

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the delayed services show a raised runnable_wait share (ready to run, waiting for a CPU) — **NOT SUPPORTED by our data**. The share of wall time a service spends in a runnable state. Measured across every labelled fault: it never exceeds 4%, because that share is diluted by ordinary idle waiting. Use per-wakeup runqueue DELAY instead, which shows the effect clearly.
- the wait decomposition of the culprit distinguishes this fault — **CANNOT BE MEASURED for this family**. The wait decomposition of the culprit. For host-attributed faults no culprit-side wait record exists at all, so its absence is meaningless here.
