---
name: db-latency-dependency-wait
version: 2
authored_by: human
generated_from: blueprints/db-latency-dependency-wait.json
covers: slow_db                       # harness metadata: scoring + LOFO; NEVER shown to the model
mutually_exclusive_with: cpu-contention-co-tenant
---
## Problem signature
- caller latency inflates sharply, often by orders of magnitude
- the slow call edges all converge on one shared downstream component
- that component is resource-quiet: CPU flat or falling, no disk or memory pressure
- requests still succeed, so error rates barely move

Telling it apart from its look-alikes:
- **direction of the slow call edges** — this problem: the suspect has slow INCOMING edges while its own outgoing edges are normal, or it emits no spans at all. Not this problem: its outgoing edges are also slow, meaning the real cause is further downstream.
- **how the off-CPU time splits (family_seconds), not the coarse wait shares** — this problem: idle_epoll is the largest single share, averaging 42.9% for this family. Not this problem: blocked_futex dominates and idle_epoll is small, e.g. 3.9% for a service pinned by its own CPU limit.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_switch, sched_waking, syscall_entry_recvfrom, syscall_exit_recvfrom, syscall_entry_epoll_wait, syscall_exit_epoll_wait, syscall_entry_futex, syscall_exit_futex
- metrics: container_cpu_usage_seconds_total, container_fs_reads_bytes_total, container_fs_writes_bytes_total, container_network_receive_bytes_total
- traces: caller to callee edge latency, baseline versus incident, so convergence can be seen
- logs: error-rate change per container, to confirm calls succeed rather than fail

Why this set: Unlike the CPU-contention blueprint, this one DOES need syscall entry and exit events: the verdict depends on which syscall the thread was blocked in when it left the CPU. sched_switch alone tells you it stopped running; the open syscall tells you it stopped to wait on the network or a socket rather than on disk or a lock. That distinction is the whole diagnosis, so the cheaper scheduler-only order is not sufficient here.

## Investigation blueprint
1. Stage the kernel trace so babeltrace2 can read it, because channels are stored gzipped
   run: `cp -r <run_dir>/kernel/kernel <tmp>/ctf && gunzip -f <tmp>/ctf/*.gz`
   expect: a CTF directory containing a metadata file and channel0_* streams
2. Find which downstream component the slow call edges converge on
   run: `python3 blueprints/lib/edge_convergence.py --run <run_dir> --out <out>/convergence.json`
   expect: one component with slow incoming edges and no slow outgoing edges; if several, take the deepest
3. Decode scheduler and syscall events for the suspect inside the incident window
   run: `TZ=UTC babeltrace2 <tmp>/ctf --begin <incident_start_utc> --end <incident_end_utc> | grep -E "sched_switch|sched_waking|syscall_entry_|syscall_exit_" > <tmp>/waits.txt`
   expect: non-empty output; zero lines means the window is misaligned, because the trace is stamped in the host timezone while ground truth is UTC, so TZ=UTC is required
4. Attribute the suspect wall time across on-CPU, runnable-wait, disk-wait and external I/O wait
   run: `python3 stratatrace/derive_kernel_l2.py <run_dir> --services <suspect> --out <out>/wait.jsonl`
   expect: off_cpu_io_wait dominant, on_cpu near zero, and a verdict_hint of external_io_or_dependency_wait
5. Confirm the suspect is unsaturated, then emit the verdict and its artifacts
   run: `python3 blueprints/lib/dependency_verdict.py --run <run_dir> --convergence <out>/convergence.json --wait <out>/wait.jsonl --out <out>/verdict.json --chart <out>/wait_shares.svg --text <out>/explanation.txt`
   expect: the suspect shows external wait without CPU, disk or memory saturation

## What to produce
- json: the converged-on component, its wait decomposition, the slowdown factor on its incoming edges, and the resource signals that rule out saturation
- xy_chart: the four wait shares for the suspect over time, with the incident window shaded
- text: which component was waiting, on what, and why its callers are victims rather than causes

## Resolution template
Conclude this problem when ALL of:
- slow call edges converge on one component that has no slow outgoing edges
- that component shows dominant off-CPU external I/O wait with a near-zero on-CPU share
- it is resource-quiet: no CPU, disk or memory saturation
- traffic continues to succeed, so error rates barely move

Prefer a different explanation when:
- a frozen dependency — calls fail or hang to timeout and the component serves little successful traffic
- host disk saturation — block latency is up host-wide and other disk users degrade too
- CPU starvation — the suspect shows runnable_wait rather than external I/O wait
- network degradation — every hop slows by a similar factor, not just the datastore path

Root cause is: the converged-on datastore component itself, never its callers, which are victims

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the converged-on component shows dominant off-CPU external I/O wait, and that is what identifies it — **TRUE BUT NOT DISCRIMINATIVE**. A dominant off-CPU external-I/O share on the suspect. Measured at 98-99% for EVERY fault type we have labelled, because the coarse buckets are dominated by ordinary idle waiting. It is true here and equally true everywhere, so it identifies nothing.
