---
name: service-cpu-throttle
version: 3
authored_by: measured from the CPU-cluster sweep, 17 labelled runs across four families
generated_from: blueprints/service-cpu-throttle.json
covers: svc_cpu_cap
mutually_exclusive_with: cpu-contention-co-tenant, host-cpu-saturation, healthy-baseline
---
## When this applies
- one service is slow and its callers slow behind it
- the host looks quiet or quieter than usual
- nothing new is running on the machine

Do NOT use this blueprint when:
- host CPU rose during the incident
- a new or unexpected process is consuming CPU
- the affected component is blocked on an external call rather than on the CPU

Cheapest check first: compare host CPU usage during the incident against the hour before: if it did not fall, this blueprint does not apply

## Problem signature
- one service is slow, and its callers slow behind it
- the host looks quiet - CPU usage falls rather than rises
- requests still succeed, but latency is high and throughput drops
- no new process appeared and nothing is competing for the machine

Telling it apart from its look-alikes:
- **host CPU utilisation during the incident, computed from sched_switch on-CPU time** — this problem: utilisation FALLS well below its own baseline - the system is doing less work, not more. Not this problem: utilisation rises (co-tenant contention, host saturation) or stays flat (healthy).
- **presence of a process consuming CPU it did not consume in the baseline** — this problem: there is none - nothing arrived to take the CPU. Not this problem: a newcomer took one or two cores (co-tenant) or several (host saturation).
- **direction of on-CPU time across the process population** — this problem: broad, simultaneous LOSS of CPU time across many unrelated processes, because callers stall behind the throttled one. Not this problem: on-CPU time is redistributed or added to, not withdrawn from everyone at once.
- **runqueue delay: time from sched_waking to the sched_switch that runs the thread** — this problem: raised - measured 13.54x to 15.70x - while the host is doing LESS work. Waiting more while working less is the throttle signature. Not this problem: runqueue delay alone separates nothing: it is raised in every CPU-family fault and in healthy load bursts. Only its combination with falling utilisation is diagnostic.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_switch, sched_waking

Why this set: MEASURED BASIS. sched_switch gives on-CPU time per process per CPU, which yields both host utilisation and the per-process gain or loss - the two facts that decide this verdict. sched_waking adds runqueue delay, which is corroboration rather than evidence, since it is raised in every neighbouring fault. No metrics are needed: cgroup throttling counters would confirm the mechanism but are not required to reach the verdict, and the falling-utilisation signal is measured to separate this family from all three neighbours on its own.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. stage the stored kernel trace for reading
   run: `bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh <app> the cgroup-cap family <run_id>`
   expect: a CTF directory the trace reader can open
2. attribute on-CPU time per process, baseline window against incident window
   run: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/oncpu_share.py --ctf <ctf> --gt <window> --out <out>/oncpu.json`
   expect: host_utilisation falling between windows, no newcomer, broad per-process losses
3. measure runqueue delay as corroboration only
   run: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/runqueue_delay.py --ctf <ctf> --gt <window> --out <out>/rq.json`
   expect: per-process p95 runqueue delay raised while utilisation falls
4. Combine into the verdict and its artifacts: the JSON verdict, the CPU breakdown chart, and a plain-English explanation
   run: `python3 blueprints/lib/blueprint_decide.py --pack <pack.json> --out <out>/verdict.json`
   expect: state that a CPU quota is throttling some service, why the host looks quiet, and that the service is NOT identified by this evidence
5. State the recommended action alongside the diagnosis
   run: `python3 blueprints/lib/recommend_action.py --verdict <out>/verdict.json --blueprint service-cpu-throttle --out <out>/recommended_action.txt`
   expect: inspect cgroup cpu.max and cpu.stat throttling counters for the services on the stalled path, and raise or remove the quota on the one that is throttling

## What to produce
- json: verdict, host utilisation both windows, per-process losses, runqueue corroboration, and an explicit statement that the throttled service is not identified
- xy_chart: per-process cores baseline against incident, showing system-wide withdrawal with no newcomer
- text: that a CPU quota is throttling some service, why the host looks quiet, and what evidence would name the service
- action: inspect cgroup cpu.max and cpu.stat throttling counters for the services on the stalled path, and raise or remove the quota on the one that is throttling

## Resolution template
Conclude this problem when ALL of:
- host CPU utilisation during the incident falls materially below its own baseline
- no process consumed CPU it was not already consuming
- on-CPU time drops across many unrelated processes at once
- runqueue delay is raised over the same window, so threads are waiting more while the system works less

Prefer a different explanation when:
- host-cpu-saturation — utilisation reaches the ceiling rather than falling - the host is exhausted, not idle
- cpu-contention-co-tenant — utilisation rises and a newcomer took one or two cores - something arrived to compete, rather than a quota holding work back
- healthy-baseline — utilisation is flat rather than falling, and per-process losses stay within ordinary variation
- db-latency-dependency-wait — a single component's socket-waiting syscall inflates by an order of magnitude while on-CPU time is otherwise unremarkable - the system is blocked on something external, not held off the CPU

Root cause is: a cgroup CPU quota set below the service's demand

## When to stop
- Conclude when: utilisation fell against its own baseline, no newcomer appeared, losses are broad, and runqueue delay is raised
- Stop and switch: utilisation rose with a newcomer -> cpu-contention-co-tenant; utilisation reached the ceiling -> host-cpu-saturation; utilisation flat -> healthy-baseline
- Evidence insufficient: sched_switch was not recorded, so utilisation cannot be computed -> request it and re-run. Do NOT decide from runqueue delay alone: doing so misdiagnosed both mild-intensity runs as co-tenant contention
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## Constraints you must respect
- Use evidence that already exists before enabling any new collection. Escalate a tier only when the cheaper tier leaves a candidate cause unresolved, and record why.
- Keep total added collection overhead under 5%.
- do not collect request payloads
- do not retain personally identifiable data
- These need human approval before you do them: active collection estimated above 3% overhead; widening the host scope or time window; any change to production configuration; any remediation action.

## If you are not confident enough
- Do not report a diagnosis below 0.7 confidence.
- name the unresolved question, pick the ONE additional capability that would settle it, check it against the overhead budget, and request it.
- if the floor is still not met after the allowed rounds, report the best-supported hypothesis, its confidence, and precisely what evidence is missing - never present a guess as a diagnosis

## How this looks on different systems
The same fault does not look the same everywhere. Work out which case you are
in before you judge the numbers.

**Short call chain - requests pass through most services** — recognise by: a handful of services, and the affected one sits on the path of most requests, so its callers stall behind it
- What you see: host CPU COLLAPSES to a quarter or two-thirds of its usual level while threads still wait longer for a CPU. Measured: utilisation fell to 0.25-0.73 of baseline, runqueue delay rose 13.5-29.2x.
- How much to trust it: high - the signal is large and unambiguous

**Wide fan-out - dozens of independent services** — recognise by: many services, and the affected one is on the path of only a small share of requests
- What you see: NOTHING at the host level. Measured across 4 labelled runs: utilisation ratio 0.995-1.008, no newcomer, biggest process loss 0.03-0.06 cores, runqueue delay 1.55-1.81x. The host keeps working on every other request, so one capped service is invisible in the aggregate.
- How much to trust it: none from host-level kernel data - do not expect to find it there
- Instead: go straight to per-cgroup evidence: cpu.stat nr_throttled and throttled_time for the services on the slow path, or per-container CPU. Host aggregates cannot answer this question on this kind of system, and looking harder at them wastes time.

## If the evidence does not fit
- If the verdict fires but the throttled service must be named, then this blueprint cannot name it from kernel comm alone - the biggest loser is the busiest victim. Request cgroup throttling counters for the services on the stalled path, which is one targeted question rather than broader collection.
- If utilisation falls but runqueue delay is NOT raised, then the system is simply idle - demand fell rather than being held back. Report reduced load, not throttling.
- If utilisation falls and one component also shows a hugely inflated socket-waiting syscall, then prefer the dependency-wait explanation: the system may be idle because it is blocked on something external, which produces the same drop in work done.

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- the process that loses the most CPU is the throttled service — **NOT SUPPORTED by our data**. Which process lost the most CPU time. This identifies the largest victim of the stall, not its cause, so do not report it as the culprit.
- cgroup throttling shows up as a raised runnable-wait share — **NOT SUPPORTED by our data**. The share of wall time a service spends runnable. Measured across every labelled fault it never exceeds 4%, because idle time swamps it.
