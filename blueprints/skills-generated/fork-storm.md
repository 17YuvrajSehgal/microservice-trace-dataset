---
name: fork-storm
version: 1
authored_by: measured across all 303 v2 runs and all 27 fault families, both applications
generated_from: blueprints/fork-storm.json
covers: 
mutually_exclusive_with: healthy-baseline
---
## When this applies
- several services slow with no single resource saturated
- CPU is busy but not at its ceiling
- process creation is measurable from the kernel trace

Do NOT use this blueprint when:
- fork rate is flat
- one component is blocked on a socket or on storage
- host CPU is at its ceiling

Cheapest check first: count sched_process_fork per second in the incident window and compare against the baseline window. If no single child command gained more than ~26 per second, this blueprint does not apply.

## Problem signature
- services slow across the board with no single resource saturated
- CPU busy but with headroom left
- process counts churn rather than grow
- nothing in the disk or network layer is unusual

Telling it apart from its look-alikes:
- **processes per second gained by a process that was barely forking before, from sched_process_fork** — this problem: one process arrives forking ~96 times a second when it was doing 3.6. Not this problem: no other fault family gains more than 26.3 forks per second on either application.
- **host fork rate, incident against baseline** — this problem: rises 1.51x to 1.77x. Not this problem: no other family exceeds 1.23x.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: sched_process_fork

Why this set: MEASURED BASIS. sched_process_fork carries the parent and the child command name, which is everything needed to say who started forking and how much they brought. One event type decides this blueprint. Nothing else in the kernel trace is required: the fault changes neither what reaches the disk nor what crosses the network, and while it does add scheduler work, the scheduler signals it moves are the same ones every CPU fault moves and therefore cannot identify it.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. stage the stored kernel trace for reading
   run: `bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh <app> <family> <run_id>`
   expect: a CTF directory the trace reader can open
2. measure process creation per command name, both windows, and report the newcomer
   run: `python3 blueprints/lib/process_probe.py --ctf <ctf> --gt <window> --out <out>/process.json`
   expect: forks per second in each window, and the process whose fork rate rose most
3. combine into the verdict and its artifacts
   run: `python3 blueprints/lib/blueprint_decide.py --pack <pack.json> --out <out>/verdict.json`
   expect: a verdict naming the forking process, or an explicit non-fire with the reason

## What to produce
- json: verdict, the forking process, forks per second gained, what it was forking before, and the host total that deliberately did not decide it
- xy_chart: forks per second per command name, baseline against incident
- text: which process started forking, and why the host-wide rate looks almost normal while one process changed by 27x
- text: map the command name to its container, then cap its PIDs with a cgroup pids.max limit rather than killing it

## Resolution template
Conclude this problem when ALL of:
- a process gains more than 26 forks per second over its baseline
- that process was forking little or nothing before
- the process is not part of the trace collector or the container runtime

Prefer a different explanation when:
- cpu-contention-co-tenant — a process takes CPU it was not using but its fork rate is flat. A co-tenant burns CPU inside one long-lived process; this fault burns it creating new ones.
- host-cpu-saturation — host CPU is at its ceiling. A fork storm leaves headroom, because each child does almost nothing before exiting.
- healthy-baseline — no process gains meaningful fork rate, even when the host total looks raised. The host total alone is not evidence - see the discriminator note.

Root cause is: a workload creating processes in a loop, identified by the command name of the child it spawns

## When to stop
- Conclude when: one process gained tens of forks per second it was not making before
- Stop and switch: fork rate flat but a process gained CPU -> cpu-contention-co-tenant; host CPU at its ceiling -> host-cpu-saturation
- Evidence insufficient: sched_process_fork was not recorded, so creation cannot be attributed -> request it and re-run. Do NOT fall back to the host fork total, which was measured to move only 1.77x under this fault and is therefore not decisive.
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## If you are not confident enough
- Do not report a diagnosis below 0.7 confidence.
- name the unresolved question, pick the ONE additional capability that would settle it, check it against the overhead budget, and request it.
- if the floor is still not met after the allowed rounds, report the best-supported hypothesis, its confidence, and precisely what evidence is missing - never present a guess as a diagnosis
