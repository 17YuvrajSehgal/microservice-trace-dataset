---
name: host-disk-saturation
version: 2
authored_by: measured from the block-layer sweep, 58 runs across all 13 fault families and two applications
generated_from: blueprints/host-disk-saturation.json
covers: anomaly_disk                       # harness metadata: scoring + LOFO; NEVER shown to the model
mutually_exclusive_with: healthy-baseline
---
## When this applies
- several services slow at once with none of them busy
- host disk activity is far above normal
- per-request disk latency looks unremarkable

Do NOT use this blueprint when:
- disk arrivals are flat
- the host is short of CPU
- one component is blocked on a socket rather than on storage

Cheapest check first: compare total disk requests per second against the hour before: if it has not risen several-fold, this blueprint does not apply

## Problem signature
- several services slow at once, none of them busy with useful work
- disk activity on the host is far above its normal level
- requests still succeed; throughput falls
- per-request disk latency looks normal, which is why this is easy to miss

Telling it apart from its look-alikes:
- **requests per second gained by a process that was barely using the disk before, from block_rq_issue** — this problem: one process arrives on the disk with thousands of requests per second it was not making before - measured 4724 to 6944. Not this problem: no process gains meaningful disk work. The largest gain in any other family is 1170 requests per second, and most are under 120.
- **total disk requests per second across the whole host** — this problem: total I/O rises several-fold - measured 4.0x to 10.1x. Not this problem: total I/O is flat or falls. Every other family measured at or below 2.9x, and most below 1.1x.
- **which process is doing the I/O, taken from block_rq_issue** — this problem: the flooding process is named directly, because the block layer records who issued each request. Not this problem: n/a - this identifies the culprit once the problem is established; it does not decide whether the problem is present.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: block_rq_issue, block_rq_complete

Why this set: MEASURED BASIS. block_rq_issue carries the device, the sector, the byte count AND the process that issued the request, which is everything needed to say who arrived on the disk and how much work they brought. block_rq_complete closes each request so service time can be measured - not because it decides anything, but because it is what proves latency is NOT the signal, and that retraction is worth carrying. Nothing else in the kernel trace is required: this fault changes neither scheduling nor networking, only what reaches the block device.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. stage the stored kernel trace for reading
   run: `bash /scratch/yuvraj17/extract_l0.sh <app> <family> <run_id>`
   expect: a CTF directory the trace reader can open
2. measure disk arrivals per process and service time per device, both windows
   run: `python3 blueprints/problems/host-disk-saturation/scripts/block_io_signature.py --ctf <ctf> --gt <ground_truth> --out <out>/blockio.json`
   expect: requests per second per process, and the newcomer if there is one
3. Combine into the verdict and its artifacts: the JSON verdict, the per-process I/O chart, and a plain-English explanation
   run: `python3 blueprints/lib/blueprint_decide.py --pack <pack.json> --out <out>/verdict.json`
   expect: name the flooding process, how much I/O it brought, and what share of the device it now holds
4. State the recommended action alongside the diagnosis
   run: `python3 blueprints/lib/recommend_action.py --verdict <out>/verdict.json --blueprint host-disk-saturation --out <out>/recommended_action.txt`
   expect: identify the container owning the flooding process, then throttle its I/O or move it off this device

## What to produce
- json: verdict, the flooding process, requests per second gained, its share of all disk work, total I/O change, and the device latency that deliberately did not decide it
- xy_chart: requests per second per process, baseline against incident
- text: which process flooded the disk and why per-request latency looks normal despite the device being overwhelmed
- text: map the process to its container, then throttle its I/O or move it to another device

## Resolution template
Conclude this problem when ALL of:
- a process gains at least 2000 disk requests per second over its baseline
- total host disk requests rise several-fold over the same window
- that process was doing little or no disk work before

Prefer a different explanation when:
- host-memory-pressure — disk arrivals rise only moderately - around a thousand requests per second - but device latency rises sharply and queue depth roughly doubles. That is reclaim and swap reaching the disk, not a workload flooding it
- healthy-baseline — no process gains meaningful disk work, even if some other measure looks raised
- db-latency-dependency-wait — disk arrivals are flat and a component is blocked in a socket call - it is waiting on the network, not on storage

Root cause is: the process flooding the block device

## When to stop
- Conclude when: a process gained thousands of disk requests per second it was not making before, and total host I/O rose several-fold
- Stop and switch: arrivals rise only moderately while device latency and queue depth rise sharply -> host-memory-pressure; arrivals flat and a component blocked on a socket -> the dependency-wait blueprint
- Evidence insufficient: block_rq_issue was not recorded, so arrivals cannot be attributed -> request it and re-run. Do NOT fall back to device latency, which was measured to move the wrong way under this fault
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## Constraints you must respect
- Use evidence that already exists before enabling any new collection. Escalate a tier only when the cheaper tier leaves a candidate cause unresolved, and record why.
- Keep total added collection overhead under 5%.
- do not collect request payloads
- record only packet headers, never packet contents
- do not retain personally identifiable data
- These need human approval before you do them: active collection estimated above 3% overhead; widening the host scope or time window; any change to production configuration; any remediation action.

## If you are not confident enough
- Do not report a diagnosis below 0.7 confidence.
- name the unresolved question, pick the ONE additional capability that would settle it, check it against the overhead budget, and request it.
- if the floor is still not met after the allowed rounds, report the best-supported hypothesis, its confidence, and precisely what evidence is missing - never present a guess as a diagnosis

## If the evidence does not fit
- If a process gained heavy I/O but is a kernel thread, then do not name it as the culprit. Kernel threads doing I/O are usually flushing writes made by something else; look for what is dirtying the pages.
- If total I/O rose but no single process accounts for it, then the load is spread across processes already running. Report it as a capacity problem rather than an intruding workload, and name the largest consumers.
- If device latency rose sharply while arrivals rose only moderately, then prefer memory pressure. Measured: memory pressure raises latency 10.7-14.5x with about a thousand extra requests per second, whereas disk flooding brings thousands of requests and leaves latency flat.

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- disk saturation makes disk requests slower — **NOT SUPPORTED - it is measured to do the opposite**. How long each disk request takes. Under heavy sequential writing it stays flat or improves, because those requests are efficient. It rises under memory pressure instead. Do not read it as a measure of how busy the disk is.
- queue depth rises when the disk is saturated — **NOT SUPPORTED by our data**. How many disk requests are outstanding at once. It moves the opposite way to the intuition here, so it is reported but never used.
