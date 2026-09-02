---
name: host-cpu-saturation
version: 3
authored_by: measured from the CPU-cluster sweep, 17 labelled runs across four families
generated_from: blueprints/host-cpu-saturation.json
covers: anomaly_cpu                       # harness metadata: scoring + LOFO; NEVER shown to the model
mutually_exclusive_with: cpu-contention-co-tenant, service-cpu-throttle, healthy-baseline
---
## When this applies
- many services degrade sharply at the same time
- host CPU is reported at or near 100%
- no individual service accounts for the load

Do NOT use this blueprint when:
- the host retains meaningful CPU headroom
- only one service is affected
- the system is doing LESS work than usual rather than more

Cheapest check first: host CPU utilisation over the incident window: if it is not near the ceiling, this blueprint does not apply and a cheaper answer exists

## Problem signature
- many unrelated services degrade sharply and simultaneously
- no single service is itself busy with useful work
- host CPU sits at or near 100% for the whole window
- requests still succeed but take far longer, and throughput falls

Telling it apart from its look-alikes:
- **host CPU utilisation during the incident, computed as busy on-CPU time over available CPU time from sched_switch** — this problem: utilisation reaches the ceiling: 0.99 or above, leaving no headroom. Not this problem: utilisation rises but retains real headroom (co-tenant contention), stays flat (healthy), or FALLS below baseline (a cgroup cap).
- **cores gained by a process that was not consuming CPU in the baseline window** — this problem: a newcomer takes several cores - measured 6.54-6.62 on a 12-CPU host, roughly half the machine. Not this problem: the newcomer takes only one or two cores (co-tenant contention), or there is no newcomer at all (cgroup cap, healthy).
- **runqueue delay: time from sched_waking to the sched_switch that runs the thread** — this problem: inflated severely and broadly - measured 36.97x to 52.54x across 12 processes. Not this problem: runqueue delay alone does NOT separate this problem from anything. It is raised in every CPU-family fault and in healthy bursts too, so it is recorded as corroboration, never as the deciding signal.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_switch, sched_waking

Why this set: MEASURED BASIS. sched_switch alone carries everything the decision needs: it names the thread starting to run on each CPU and when, so the gap between consecutive switches on a CPU is the previous thread's on-CPU time. Summing that per process gives both host utilisation and per-process core consumption. sched_waking is collected only to compute runqueue delay as corroboration; the verdict does not depend on it. No metrics are required - the container-level attribution that earlier drafts took from cadvisor is recoverable from the scheduler stream, verified by recovering the injected cgroup cap to within 1%.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. stage the stored kernel trace for reading
   run: `bash /scratch/yuvraj17/extract_l0.sh <app> the host-saturation family <run_id>`
   expect: a CTF directory the trace reader can open
2. attribute on-CPU time per process, baseline window against incident window
   run: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/oncpu_share.py --ctf <ctf> --gt <ground_truth> --out <out>/oncpu.json`
   expect: host_utilisation per window, and cores gained or lost per process
3. measure runqueue delay as corroboration only
   run: `python3 blueprints/problems/cpu-contention-co-tenant/scripts/runqueue_delay.py --ctf <ctf> --gt <ground_truth> --out <out>/rq.json`
   expect: per-process p95 runqueue delay, baseline against incident
4. Combine into the verdict and its artifacts: the JSON verdict, the CPU breakdown chart, and a plain-English explanation
   run: `python3 blueprints/lib/blueprint_decide.py --pack <pack.json> --out <out>/verdict.json`
   expect: name the workload that exhausted the host, how much it took, and what is left
5. State the recommended action alongside the diagnosis
   run: `python3 blueprints/lib/recommend_action.py --verdict <out>/verdict.json --blueprint host-cpu-saturation --out <out>/recommended_action.txt`
   expect: cap or relocate the offending workload; if the load is legitimate, report the host as undersized for it

## What to produce
- json: verdict, host utilisation both windows, the newcomer and cores it took, and the runqueue corroboration
- xy_chart: per-process cores baseline against incident, with the CPU ceiling drawn
- text: which workload exhausted the host, how much it took, and what remains for everything else
- action: cap or relocate the offending workload; if it is legitimate, the host is undersized for its load

## Resolution template
Conclude this problem when ALL of:
- host CPU utilisation during the incident is at or above 0.95, against a baseline near 0.5
- a process that consumed no CPU in the baseline now consumes several cores
- runqueue delay is broadly inflated, corroborating that threads are queueing rather than working

Prefer a different explanation when:
- cpu-contention-co-tenant — utilisation rises but stays well below the ceiling and the newcomer takes only one or two cores - the host is sharing, not exhausted
- service-cpu-throttle — utilisation FALLS below its baseline and there is no newcomer at all - the system is doing less work, not more
- healthy-baseline — utilisation is flat against baseline and no newcomer took meaningful CPU, even if runqueue delay is somewhat raised by a load burst

Root cause is: the workload that consumed the host's remaining CPU capacity

## When to stop
- Conclude when: utilisation is at the ceiling, a newcomer accounts for the consumption, and runqueue delay corroborates
- Stop and switch: utilisation retains headroom -> cpu-contention-co-tenant; utilisation fell below baseline -> service-cpu-throttle; utilisation is flat -> healthy-baseline
- Evidence insufficient: sched_switch was not recorded, so utilisation cannot be computed -> request it and re-run. Do NOT fall back to runqueue delay alone, which is measured not to separate these causes
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

**Any architecture** — recognise by: no precondition - a ceiling is a ceiling
- What you see: utilisation at or above 0.99 with a newcomer holding a large share of the machine. Measured 0.991-0.998 on one system and 0.994-0.997 on the other, with the newcomer taking 6.5 and 7.8-8.1 cores respectively.
- How much to trust it: high - this is the only signal in the CPU family that needed no re-calibration between two very different applications

## If the evidence does not fit
- If utilisation is at the ceiling but no newcomer is found, then the load is from processes already running. This is a capacity problem rather than an intruding workload; report it as an undersized host and name the largest consumers.
- If the newcomer is a kernel thread, then do not name it as the culprit. Kernel threads consuming CPU are usually a symptom - look for what is driving them, for example reclaim or interrupt load.
- If baseline utilisation is itself above 0.8, then the absolute thresholds here do not apply. Compare the change against that system's own baseline instead, and lower confidence, because the thresholds were measured on a host that idled near 0.48.

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- high runqueue delay identifies host CPU saturation — **NOT SUPPORTED - the signal is present in every CPU-family fault and in healthy bursts**. How long ready threads waited for a CPU. It rises under every kind of CPU trouble, and under ordinary load bursts as well, so on its own it tells you something is loaded, not what is wrong.
