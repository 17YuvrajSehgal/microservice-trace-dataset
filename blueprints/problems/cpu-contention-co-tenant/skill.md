---
name: cpu-contention-co-tenant
version: 2
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
- **where the CPU went (container CPU vs call-path role)** — this problem: a container consumes steady CPU during the incident that it did not consume in the baseline, and it has NO caller/callee edges in the call graph. Not this problem: the extra CPU is consumed by a service that appears in the call graph.
- **host CPU headroom** — this problem: host busy cores rise but the host is NOT exhausted. Not this problem: host CPU is exhausted and many services degrade sharply together.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_switch, sched_waking, sched_wakeup, sched_migrate_task, sched_process_exec
- metrics: container_cpu_usage_seconds_total, container_cpu_cfs_throttled_seconds_total, node_cpu_seconds_total, node_load1
- traces: server span duration per service, only to confirm the impact is mild

Why this set: MEASURED BASIS: the verified discriminators for this problem come from container CPU and the call graph, not from wait shares - runnable_wait was 1.6% on the co-tenant run and never exceeds 4% in any family (evidence/wait_signature_all_families.json). The scheduler events are still collected because they are what a host-level wait record WOULD be derived from, which is the open gap for this family.

## Investigation blueprint
1. Stage the kernel trace so babeltrace2 can read it, because channels are stored gzipped
   run: `cp -r <run_dir>/kernel/kernel <tmp>/ctf && gunzip -f <tmp>/ctf/*.gz`
   expect: a CTF directory containing a metadata file and channel0_* streams
2. Decode only the scheduler events inside the incident window
   run: `TZ=UTC babeltrace2 <tmp>/ctf --begin <incident_start_utc> --end <incident_end_utc> | grep -E "sched_switch|sched_waking|sched_wakeup" > <tmp>/sched.txt`
   expect: non-empty output; zero lines means the window is misaligned, because the trace is stamped in the host timezone while ground truth is UTC, so TZ=UTC is required
3. Attribute per-service wall time to on-CPU, runnable-wait and blocked, using the container-to-PID map
   run: `python3 stratatrace/derive_kernel_l2.py <run_dir> --names sched_switch,sched_waking,sched_wakeup --out <out>/wait.jsonl`
   expect: one record per service, with rule_out_pct summing to about 100 and a verdict_hint
4. Rank containers by CPU consumed in the window, mark which have call-path edges, and emit the verdict
   run: `python3 blueprints/lib/cpu_attribution.py --run <run_dir> --wait <out>/wait.jsonl --out <out>/verdict.json --chart <out>/runqueue.svg --text <out>/explanation.txt`
   expect: the top CPU consumer has no call-path edges, and affected services show raised runnable_wait

## What to produce
- json: culprit container, per-service runnable-wait share baseline versus incident, host CPU headroom
- xy_chart: runnable-wait share per service over time, with the incident window shaded
- text: which container took the CPU, which services waited, and why this is contention rather than saturation

## Resolution template
Conclude this problem when ALL of:
- a container consumes steady CPU during the incident that it did not consume in the baseline
- that container has NO caller or callee edges in the call graph
- host CPU rises but retains headroom rather than being exhausted
- user-facing latency is only mildly affected and no new error signatures appear

Prefer a different explanation when:
- host CPU exhaustion — host CPU is exhausted and many services degrade sharply together
- service CPU throttling — throttled seconds jump on an application service that is on the call path
- a fault inside an application service — the extra CPU is consumed by a service that IS on the call path, or no off-call-path container consumed CPU at all

Root cause is: the co-tenant workload container itself, not any application service it delays

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the delayed services show a raised runnable_wait share (ready to run, waiting for a CPU) — **NOT SUPPORTED by our data**. A raised runnable-wait share on the delayed services. Measured across every labelled fault we have: this share never exceeds 4% for any fault type, and was 1.6% on the co-tenant case itself. It cannot separate anything - do not reason from it.
- the wait decomposition of the culprit distinguishes this fault — **CANNOT BE MEASURED for this family**. The wait decomposition of the culprit. For host-attributed faults no culprit-side wait record exists at all, so its absence is meaningless here.
