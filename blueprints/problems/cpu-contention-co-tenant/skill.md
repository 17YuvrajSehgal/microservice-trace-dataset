---
name: cpu-contention-co-tenant
version: 1
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
- **kernel wait decomposition of an affected service** — this problem: runnable_wait share rises: the service is READY to run and waiting for a CPU, while its on_cpu share stays low. Not this problem: off_cpu_io_wait dominates, which means it is blocked on something external rather than starved of CPU.
- **host CPU headroom** — this problem: busy cores rise but headroom remains; degradation is jitter, not collapse. Not this problem: host CPU is exhausted and many services degrade sharply and together.
- **where the CPU went** — this problem: a container with NO call-path role and no baseline presence consumes steady CPU. Not this problem: the CPU is consumed by an application service that is on the call path.
- **throttling signals** — this problem: if throttling appears at all it is on the NON-call-path container, because the co-tenant is often capped itself. Not this problem: throttled seconds jump on an application service pinned by its own limit.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_switch, sched_waking, sched_wakeup, sched_migrate_task, sched_process_exec
- metrics: container_cpu_usage_seconds_total, container_cpu_cfs_throttled_seconds_total, node_cpu_seconds_total, node_load1
- traces: server span duration per service, only to confirm the impact is mild

Why this set: The verdict rests on WHY a thread was not running. sched_switch carries prev_state, which separates preempted-while-runnable from blocked-in-a-syscall; sched_waking and sched_wakeup mark the transition back to runnable. sched_process_exec catches the co-tenant appearing mid-run. Syscall events are NOT required, which is what makes this collection order cheap: five tracepoints replace a full kernel trace.

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
- an off-call-path container consumes steady CPU that was absent in the baseline
- affected services show raised runnable_wait while their on_cpu share stays low
- host CPU rises but retains headroom
- user-facing latency is only mildly affected and no new errors appear

Prefer a different explanation when:
- host CPU exhaustion — host CPU is exhausted and many services degrade sharply together
- service CPU throttling — throttled seconds jump on an application service that is on the call path
- dependency or datastore wait — the affected services show off_cpu_io_wait rather than runnable_wait

Root cause is: the co-tenant workload container itself, not any application service it delays
