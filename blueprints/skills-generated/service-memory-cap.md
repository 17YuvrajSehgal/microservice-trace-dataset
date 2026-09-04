---
name: service-memory-cap
version: 1
authored_by: measured from two sweeps: the futex/irq probe (49 the first application + 42 the second application runs) and the block-layer sweep (57 runs), then a joint check across 24 family-application groups
generated_from: blueprints/service-memory-cap.json
covers: svc_mem_cap
mutually_exclusive_with: host-disk-saturation
---
## When this applies
- one service is slow while the rest of the system looks normal
- device interrupt activity on the host is well above its usual level
- disk request arrivals have barely moved
- the host has spare CPU and nothing is stealing it

Do NOT use this blueprint when:
- a process has arrived on the disk with thousands of requests per second
- device interrupt time is flat
- the affected service stopped answering entirely rather than slowing down

## Problem signature
- one service is slow while the rest of the system looks unremarkable
- the host is not short of CPU and no process is stealing it
- device interrupt time on the host is several times its normal level
- disk request arrivals barely move
- requests still succeed, so nothing errors and no log line names the cause

Telling it apart from its look-alikes:
- **time spent inside device interrupt handlers, incident against baseline, from irq_handler_entry/irq_handler_exit** — this problem: 6.23-6.35x on the first application, 3.23-4.25x on the second application. Not this problem: no other family exceeds 1.81x on the first application or 1.65x on the second application - except the disk fault, which goes HIGHER (12.94-14.27x and 5.78-6.67x), and host memory pressure on the first application at 2.36-3.45x.
- **disk requests per second gained by a process that was barely using the disk before, from block_rq_issue** — this problem: 0-282 requests per second - essentially nothing reaches the disk. Not this problem: the disk fault gains 4724-6944; host memory pressure on the first application gains 1142-1170. Both are far above this fault's ceiling.
- **the pair: interrupt time up AND disk arrivals flat** — this problem: fires on 2 of 2 target groups, every run. Not this problem: 0 false fires across 24 family-application groups. The disk fault raises both signals; host memory pressure raises both by less; everything else raises neither.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: irq_handler_entry, irq_handler_exit, block_rq_issue, block_rq_complete

Why this set: MEASURED BASIS. The verdict needs one signal that rises and one that stays flat, and both halves are load-bearing: on the first application the disk test is what excludes host memory pressure, and on the second application the interrupt test is what excludes a healthy run. Interrupt handlers need entry AND exit because the signal is time spent inside them, not a count. block_rq_issue alone is enough for arrivals; block_rq_complete is kept so the negative claim - that service time did not change - can be shown rather than asserted.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. stage the stored kernel trace for reading
   run: `bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh <app> <family> <run_id>`
   expect: a CTF directory the trace reader can open
2. measure device interrupt time in both windows
   run: `python3 blueprints/lib/futex_irq_probe.py --ctf <ctf> --gt <window> --out <out>/irq.json`
   expect: hardirq seconds per second of wall clock, baseline and incident, and their ratio
3. measure disk arrivals per process, to show the disk stayed quiet
   run: `python3 blueprints/problems/host-disk-saturation/scripts/block_io_signature.py --ctf <ctf> --gt <window> --out <out>/blockio.json`
   expect: requests per second gained by any newcomer process; expected to be near zero for this fault
4. combine into the verdict and its artifacts
   run: `python3 blueprints/lib/blueprint_decide.py --pack <pack.json> --out <out>/verdict.json`
   expect: a verdict naming the capped service, or a refusal to decide

## What to produce
- json: verdict, the interrupt ratio that fired it, the disk arrivals that stayed flat, and which of the two tests carried the decision on this application
- xy_chart: interrupt ratio against disk requests gained, one point per family, so the separation is visible rather than asserted
- text: why interrupts rose while the disk stayed quiet, and why that pair points at a container limit rather than a host-wide shortage
- text: map the affected cgroup to its container, then raise its memory limit or reduce its working set

## Resolution template
Conclude this problem when ALL of:
- device interrupt time rises to at least 2.5x its baseline
- AND no process gains 500 or more disk requests per second

Prefer a different explanation when:
- host-disk-saturation — a process gains thousands of disk requests per second. Both faults raise interrupt time - the disk fault raises it MORE - so interrupts cannot tell them apart. Arrivals can, and the gap is wide: 4724 at the disk fault's floor against 282 at this fault's ceiling
- host-memory-pressure — disk arrivals rise to roughly a thousand per second and device latency rises sharply. That is reclaim reaching the disk host-wide, not one cgroup working against its own limit. On the first application this is the ONLY thing separating the two, because host memory pressure reaches 3.45x on interrupts - above a second-application memory cap's 3.23x floor
- healthy-baseline — interrupt time stays under 2.5x. Healthy runs reach 1.81x on the first application and 1.65x on the second application, so a quiet interrupt layer rules this fault out on both applications
- dependency-outage — the container was killed rather than throttled. Kernel traces cannot see that (F11-F13); it is defined by an absence of answers, not by any signal

Root cause is: the container whose cgroup memory limit is being hit

## When to stop
- Conclude when: interrupt time rose at least 2.5x while no process gained 500 or more disk requests per second
- Stop and switch: thousands of disk requests per second gained -> host-disk-saturation; roughly a thousand gained with device latency up sharply -> host-memory-pressure; interrupts flat -> neither, look elsewhere
- Evidence insufficient: irq_handler_entry/exit or block_rq_issue were not recorded, so one half of the pair is missing -> request them and re-run. Do NOT decide on interrupt time alone: it was measured to overlap host memory pressure across applications
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## Constraints you must respect
- Use evidence that already exists before enabling any new collection. Both signals here were already in every run we had collected - neither required a new trace.
- Keep total added collection overhead under 5%.

## If you are not confident enough

## How this looks on different systems
The same fault does not look the same everywhere. Work out which case you are
in before you judge the numbers.

**Lightly loaded host, few services** — recognise by: the machine normally idles around half its CPU, and a handful of services share it
- What you see: interrupt time rises 6.23-6.35x while disk arrivals gain only 250-282 requests per second
- How much to trust it: high - the interrupt rise is large and the disk stays plainly quiet

**Busy host, many services** — recognise by: the machine already runs above 80% CPU with 40 or more services
- What you see: interrupt time rises 3.23-4.25x while disk arrivals gain 0-24 requests per second
- How much to trust it: medium - the margin above the bar is 1.29x, the tightest in this blueprint

## If the evidence does not fit
- If you are tempted to decide on interrupt time alone, then do not. host memory pressure on the first application reaches 3.45x, above the 3.23x floor of a second-application memory cap. The disk test is what separates them, and on that application it is the only thing that does.
- If you want to use absolute interrupt seconds instead of the ratio, then do not. They invert between our two applications: the disk fault sits above this fault on one (0.0235 vs 0.0162 s/s) and below it on the other (0.0161 vs 0.0225). Only the ratio keeps a consistent ordering.
- If a third application shows a healthy interrupt ceiling above 2.0x, then raise the bar rather than accepting the false fire, and record the new ceiling as a scenario.
- If the capped container does real page-cache or file work of its own, then re-measure the disk gap before trusting it. The 500 bar sits between this fault's ceiling of 282 and host memory pressure's floor of 1142, and heavy file traffic from the container would close that gap.
- If the container was OOM-killed rather than throttled, then this blueprint does not apply. A killed container stops answering, and that is defined by absence - six measured attempts failed to see it in kernel data (F11-F13).

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- device interrupt time alone identifies this fault — **NOT SUPPORTED by our data**. Interrupt time rising is necessary but not sufficient. Two other conditions raise it too, one higher and one overlapping. Always check whether the disk stayed quiet before concluding.
- absolute interrupt seconds per second can be used instead of the ratio — **NOT SUPPORTED by our data**. Compare each machine against its own baseline. Absolute interrupt time depends on the hardware and the service count, and its ordering between faults is not stable across systems.
- the thresholds here rest on a large sample — **WEAK - stated so it is not mistaken for settled**. The separation is clean on everything we have, but the fault itself was observed only four times. Report the verdict with that caveat rather than as a settled threshold.
