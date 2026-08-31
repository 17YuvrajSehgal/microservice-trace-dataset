---
name: network-path-degradation
version: 1
authored_by: measured from the packet-loss sweep, 40 labelled runs across 8 families and two applications
generated_from: blueprints/network-path-degradation.json
covers: network_impairment                       # harness metadata: scoring + LOFO; NEVER shown to the model
mutually_exclusive_with: healthy-baseline
---
## When this applies
- services that talk to each other are slow while each is individually idle
- latency is erratic rather than uniformly raised
- the slowdown follows a path rather than a component

Do NOT use this blueprint when:
- one component is blocked in a socket call for an order of magnitude longer while data still arrives intact
- the host is short of CPU
- requests are failing outright rather than slowing

Cheapest check first: count retransmissions on any one busy interface: if the rate is near zero, this blueprint does not apply and a cheaper answer exists elsewhere

## Problem signature
- services that talk to each other are slow and erratic, while each is individually idle
- latency is variable rather than uniformly higher, and gets worse for chattier callers
- requests still succeed, but throughput falls
- the slowdown follows a network path rather than a single component

Telling it apart from its look-alikes:
- **TCP retransmission rate per interface: segments carrying a sequence number already seen on the same flow, as a share of segments** — this problem: at least one interface retransmits heavily - measured 18.5% to 60.7% across both applications. Not this problem: retransmission stays low or absent. Every non-network fault measured at or below 7.1%, and most sit at exactly 0.
- **baseline retransmission rate, as a sanity check before trusting the incident figure** — this problem: baseline is near zero, so any retransmission during the incident is signal rather than normal behaviour. Not this problem: the baseline already retransmits, in which case this environment is lossy in general and the incident figure needs comparing against it rather than against zero.
- **packets queued to a device but never transmitted (net_dev_queue with no matching net_dev_xmit for the same buffer)** — this problem: a small but non-zero share of buffers are dropped inside the queue, where the impairment sits. Not this problem: every queued buffer is transmitted.
- **how many interfaces retransmit heavily** — this problem: reports the SCOPE of the impairment - one interface means a single service's path, many means the whole host's networking. Not this problem: this does not decide whether the problem is present; it describes it once the retransmission test has fired.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: net_if_receive_skb, net_dev_queue, net_dev_xmit

Why this set: MEASURED BASIS. net_if_receive_skb carries the full IP and TCP header, including the sequence number, so a segment repeating a sequence number already seen on its flow is a retransmission - the one effect only packet loss produces. net_dev_queue and net_dev_xmit both carry the buffer address, so a buffer queued to a device and never transmitted was dropped inside the queue, which is where the impairment sits; this corroborates. Nothing else in the kernel trace is needed, and in particular the scheduler events are irrelevant here: this fault does not change how threads are scheduled, only what happens to their packets.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. stage the stored kernel trace for reading
   run: `bash /scratch/yuvraj17/extract_l0.sh <app> <family> <run_id>`
   expect: a CTF directory the trace reader can open
2. count retransmissions and queue drops per interface, baseline window against incident window
   run: `python3 blueprints/problems/network-path-degradation/scripts/net_loss_signature.py --ctf <ctf> --gt <ground_truth> --out <out>/netloss.json`
   expect: per-interface retransmission and drop rates, and the list of impaired interfaces
3. Combine into the verdict and its artifacts: the JSON verdict, the per-interface chart, and a plain-English explanation
   run: `python3 blueprints/lib/blueprint_decide.py --pack <pack.json> --out <out>/verdict.json`
   expect: name the impaired interfaces, the retransmission rate on each, and the scope
4. State the recommended action alongside the diagnosis
   run: `python3 blueprints/lib/recommend_action.py --verdict <out>/verdict.json --blueprint network-path-degradation --out <out>/recommended_action.txt`
   expect: map the impaired interfaces to their containers and inspect the queueing discipline and link health on that path

## What to produce
- json: verdict, the impaired interfaces with their retransmission rates, the baseline rate, the queue-drop rate, and the scope
- xy_chart: retransmission rate per interface, baseline against incident
- text: which paths are losing packets, how badly, and why that explains the slowdown better than any component being busy
- text: map each impaired interface to its container, then check the queueing discipline, the link, and anything shaping traffic on that path

## Resolution template
Conclude this problem when ALL of:
- at least one interface retransmits at 12% or more of its segments during the incident
- the same interface retransmitted at or near zero in the baseline window
- buffers queued to that device were dropped without being transmitted

Prefer a different explanation when:
- db-latency-dependency-wait — retransmission stays below a few percent while one component blocks in a socket call for an order of magnitude longer - the data is arriving intact, just late, so nothing needs re-sending
- healthy-baseline — no interface retransmits meaningfully, even if endpoint latency has risen - latency alone rises under almost every fault and under ordinary load
- cpu-contention-co-tenant — retransmission is low and host CPU rose with a newcomer taking cores - packets are fine, the machine is busy

Root cause is: packet loss on the network path serving the impaired interfaces

## When to stop
- Conclude when: at least one interface retransmits at 12% or more against a near-zero baseline, and queue drops corroborate
- Stop and switch: retransmission is low but one component blocks in a socket call for an order of magnitude longer -> the dependency-wait blueprint; retransmission is low and host CPU rose with a newcomer -> the CPU-contention blueprint
- Evidence insufficient: the network events were not recorded, so retransmission cannot be counted -> request net_if_receive_skb and re-run. Do NOT fall back to endpoint latency, which was measured not to separate this problem from a healthy system
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

## How this looks on different systems
The same fault does not look the same everywhere. Work out which case you are
in before you judge the numbers.

**One service's path is impaired** — recognise by: exactly one or two interfaces retransmitting, while the rest are clean
- What you see: a very high rate on the affected interface. Measured 25.6-52.6% on the first application and 38.1-60.7% on the second, with 1-3 interfaces involved.
- How much to trust it: high - this was the most consistent network signature across both systems
- Instead: map the interface to its container and inspect that container's queueing discipline first, before looking at the host network

**The whole host's networking is impaired** — recognise by: many interfaces retransmitting at once
- What you see: on a short call chain, 7-12 of 16 interfaces at 18.5-40.9%. On a wide fan-out system the SAME fault reached only 0-1 interfaces, and one run showed just 0.15% - so breadth is not a reliable way to recognise this case.
- How much to trust it: medium on a short chain, low on a wide fan-out system
- Instead: do not conclude host-wide impairment from interface count alone. Treat the count as evidence of scope and confirm against the actual container topology, since the same fault produced opposite breadth on the two systems we measured.

## If the evidence does not fit
- If the baseline window already shows meaningful retransmission, then this environment is lossy in general. Compare the incident against that baseline rather than against zero, and lower confidence - every threshold here was measured where the baseline was exactly zero.
- If retransmission is raised but only on a low-traffic interface with few segments, then treat it as weak. A handful of segments can produce a large percentage; require enough samples before naming the path.
- If no interface retransmits but the path is still suspected, then absence is weak evidence here - one run in 40 showed an impaired path at only 0.15%. Report the negative honestly and ask for traffic-level evidence on the specific path rather than concluding it is healthy.

## Signals that do NOT work for this problem
Each of these was measured on our own data and found unusable. Do not reason
from them, and do not let their absence argue against this problem:
- endpoint latency identifies a degraded network path — **NOT SUPPORTED by our data**. How long each service endpoint takes to answer. It rises under almost every kind of fault, so on its own it says something is wrong, not what.
- a heavily retransmitting interface is always present when the path is impaired — **PARTIALLY SUPPORTED - one run in 40 did not show it**. A path can be impaired without the trace showing much retransmission, if there is too little traffic on it during the window. Absence of retransmission is weak evidence of absence; presence is strong evidence of presence.
