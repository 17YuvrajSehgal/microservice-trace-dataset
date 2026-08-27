---
name: db-latency-dependency-wait
version: 4
authored_by: human
generated_from: blueprints/db-latency-dependency-wait.json
covers: slow_db                       # harness metadata: scoring + LOFO; NEVER shown to the model
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
- caller latency inflates sharply, often by orders of magnitude
- the slow call edges all converge on one shared downstream component
- that component is resource-quiet: CPU flat or falling, no disk or memory pressure
- requests still succeed, so error rates barely move

Telling it apart from its look-alikes:
- **blocking-syscall duration of the suspect component** — this problem: ONE socket-waiting syscall inflates by an order of magnitude while everything else stays flat. Not this problem: no syscall inflates by more than about 2x.
- **runqueue delay of the suspect** — this problem: flat - the component is not waiting for a CPU, it is waiting for a reply. Not this problem: runqueue delay inflates several-fold across many processes.
- **call-graph convergence** — this problem: slow edges converge on ONE component that has no slow outgoing edges of its own. Not this problem: nothing converges; edge slowdowns stay near 1x.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_waking, sched_switch, syscall_entry_poll, syscall_exit_poll, syscall_entry_recvfrom, syscall_exit_recvfrom, syscall_entry_epoll_wait, syscall_exit_epoll_wait
- metrics: container_cpu_usage_seconds_total, container_fs_reads_bytes_total, container_fs_writes_bytes_total, container_network_receive_bytes_total
- traces: caller to callee edge latency, baseline versus incident, so convergence can be seen
- logs: error-rate change per container, to confirm calls succeed rather than fail

Why this set: MEASURED BASIS. The verdict rests on how long the component blocks inside its socket-waiting syscall, so entry AND exit of those calls are required - entry alone gives no duration. The two scheduler events are needed for the negative control: showing runqueue delay is FLAT is what rules out CPU starvation. This is strictly more than the CPU-contention blueprint needs, and that difference is the point: the two problems genuinely require different collection orders.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. Make the kernel trace readable
   needs: `trace.stage_ctf`
   run [local]: `cp -r <run_dir>/kernel/kernel <tmp>/ctf && gunzip -f <tmp>/ctf/*.gz`
   expect: a CTF directory with metadata and channel streams
2. Find which component the slow call paths converge on
   needs: `traces.call_graph.convergence`
   run [otlp-spans]: `python3 blueprints/problems/db-latency-dependency-wait/scripts/edge_convergence.py --run <run_dir> --app <app> --out <out>/convergence.json`
   expect: one component with slow incoming and no slow outgoing edges; it may be the CALLER of the culprit if the culprit emits no spans
3. Measure how long the suspect blocks inside each syscall
   needs: `kernel.syscall.blocking_duration`
   run [babeltrace2-cli]: `python3 blueprints/problems/db-latency-dependency-wait/scripts/blocking_syscall.py --ctf <ctf> --gt <ground_truth> --comms <comms> --out <out>/blocking.json`
   expect: one socket-waiting syscall inflated by roughly an order of magnitude
4. NEGATIVE CONTROL: confirm the suspect is not merely CPU-starved
   needs: `kernel.scheduler.runqueue_delay`
   run [babeltrace2-cli]: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/runqueue_delay.py --ctf <ctf> --gt <ground_truth> --out <out>/rq.json`
   expect: runqueue delay flat; if it inflates broadly this is the CPU-contention blueprint instead
5. Combine into the verdict and its artifacts
   needs: `verdict.dependency_wait`
   run [local]: `python3 blueprints/problems/db-latency-dependency-wait/scripts/dependency_verdict.py --convergence <out>/convergence.json --blocking <out>/blocking.json --rq <out>/rq.json --out <out>/verdict.json --chart <out>/blocking.svg --text <out>/explanation.txt`
   expect: a named component, the syscall it blocked in, its inflation factor, and the flat runqueue delay that rules out CPU starvation

## What to produce
- json: the blocked component, the syscall and its inflation, the convergence point, and the runqueue-delay control
- xy_chart: syscall duration p95 baseline vs incident, per component and syscall
- text: what was waiting, on what, and why its callers are victims

## Resolution template
Conclude this problem when ALL of:
- one component socket-waiting syscall inflates by roughly an order of magnitude
- that component runqueue delay stays flat, so it is not short of CPU
- slow call edges converge on it or on its nearest traced caller
- traffic continues to succeed, so error rates barely move

Prefer a different explanation when:
- co-tenant CPU contention — runqueue delay inflates broadly across many processes while no syscall inflates much
- a frozen dependency — calls fail or hang to timeout instead of returning slowly
- host disk saturation — the inflated wait is a disk syscall and other disk users degrade too

Root cause is: the converged-on datastore component itself, never its callers, which are victims

## When to stop
- Conclude when: one component's socket-waiting syscall is inflated by roughly an order of magnitude while its runqueue delay stays flat
- Stop and switch: runqueue delay is broadly inflated instead -> use the CPU-contention blueprint
- Evidence insufficient: the suspect emits no spans AND no kernel trace is available for it -> the culprit cannot be identified from the traced layer alone; request kernel collection for that component
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## If the evidence does not fit
- If convergence names a component that itself has slow outgoing edges, then it is a pass-through victim: follow its slow edge and re-run convergence one hop deeper.
- If the inflated wait is a disk syscall rather than a socket syscall, then this is storage, not a downstream dependency; check whether other disk users degraded too.
- If no component emits spans on the suspected path, then fall back to kernel evidence alone and identify the blocked component by syscall duration, accepting that the call graph cannot confirm it.

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the converged-on component shows dominant off-CPU external I/O wait, and that is what identifies it — **TRUE BUT NOT DISCRIMINATIVE**. A dominant off-CPU external-I/O SHARE on the suspect. Measured at 98-99% for every labelled fault, because that share is dominated by ordinary idle waiting. Use the DURATION of the specific blocking syscall instead.
