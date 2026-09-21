---
name: host-disk-saturation
version: 2
authored_by: measured from the block-layer sweep, 58 runs across all 13 fault families and two applications
generated_from: blueprints/host-disk-saturation.json
covers: anomaly_disk
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
- **the identity of the process that arrived on the disk** — this problem: an application or workload process - in our runs, the injected disk load generator, in every single run. Not this problem: the trace collector itself. Our own instrument writes the trace to disk and shows up as a process arriving on it.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: block_rq_issue, block_rq_complete

Why this set: MEASURED BASIS. block_rq_issue carries the device, the sector, the byte count AND the process that issued the request, which is everything needed to say who arrived on the disk and how much work they brought. block_rq_complete closes each request so service time can be measured - not because it decides anything, but because it is what proves latency is NOT the signal, and that retraction is worth carrying. Nothing else in the kernel trace is required: this fault changes neither scheduling nor networking, only what reaches the block device.

## Investigation blueprint
Each step names the capability it needs, how to get at it with the tools you have, and what a correct result looks like. There are no commands: you have a raw kernel trace and six read-only query tools, and nothing else. The 'with your tools' line is a starting point, not an instruction - if you see a better way with the same tools, take it and say what you did. A step marked NOT REACHABLE cannot be done from kernel data: skip it, say you skipped it, and do not treat its absence as evidence either way.

1. stage the stored kernel trace for reading
   needs: `trace.stage_ctf`
   with your tools: already done - the trace is loaded. ctf_timespan gives its real start and end.
   expect: a CTF directory the trace reader can open
2. measure disk arrivals per process and service time per device, both windows
   needs: `storage.io_attribution`
   with your tools: query_ctf on block_rq_issue and block_rq_complete per range, with top_procnames for who is issuing the I/O. Rates, not latencies.
   expect: requests per second per process, and the newcomer if there is one
3. Combine into the verdict and its artifacts: the JSON verdict, the per-process I/O chart, and a plain-English explanation
   needs: `verdict.apply_rules`
   with your tools: do this yourself, from the numbers your own tool calls returned. Quote them.
   expect: name the flooding process, how much I/O it brought, and what share of the device it now holds
4. State the recommended action alongside the diagnosis
   needs: `report.recommended_action`
   with your tools: write it in your own words in the diagnosis.
   expect: identify the container owning the flooding process, then throttle its I/O or move it off this device
5. draw the decision card
   needs: `report.decision_card`
   with your tools: NOT REACHABLE - no plotting here. Skip it; it does not affect the diagnosis.
   expect: one page showing where every fault family sits on this blueprint's deciding number, which gates passed and by how much, and what else was ruled out

## What to produce
- xy_chart: the decision itself: every fault family on the deciding axis with the cut drawn, the closest fault to that cut, each gate with its measured value and its bar, and the other blueprints with the number that ruled each one out
- json: verdict, the flooding process, requests per second gained, its share of all disk work, total I/O change, and the device latency that deliberately did not decide it
- xy_chart: requests per second per process, baseline against incident
- text: which process flooded the disk and why per-request latency looks normal despite the device being overwhelmed
- text: map the process to its container, then throttle its I/O or move it to another device

## Resolution template
Conclude this problem when ALL of:
- the process arriving on the disk brings more than 450 requests per second for each unit of rise in device interrupt time. It is the MIX that decides, not the arrival count: a flood is many requests per unit of interrupt rise, reclaim inside one cgroup is the reverse
- total host disk requests rise several-fold over the same window
- that process was doing little or no disk work before
- the process doing the flooding is not the trace collector. Our own instrument writes to the same disk, and measuring the observer instead of the system is not a diagnosis

Prefer a different explanation when:
- nothing - there is no disk fault here — the only process that arrived on the disk is the trace collector. That is the instrument writing, not the application.
- host-memory-pressure — disk arrivals rise only moderately - around a thousand requests per second - but device latency rises sharply and queue depth roughly doubles. That is reclaim and swap reaching the disk, not a workload flooding it
- healthy-baseline — no process gains meaningful disk work, even if some other measure looks raised
- db-latency-dependency-wait — disk arrivals are flat and a component is blocked in a socket call - it is waiting on the network, not on storage

Root cause is: the process flooding the block device

## When to stop
- Conclude when: a process gained thousands of disk requests per second it was not making before, and total host I/O rose several-fold
- Stop and switch: arrivals rise only moderately while device latency and queue depth rise sharply -> host-memory-pressure; arrivals flat and a component blocked on a socket -> the dependency-wait blueprint
- Evidence insufficient: block_rq_issue was not recorded, so arrivals cannot be attributed -> request it and re-run. Do NOT fall back to device latency, which was measured to move the wrong way under this fault Also stop if the only process arriving on the disk is the trace collector: that is the observer, and it is evidence about the measurement rather than about the system.
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
