---
name: dns-delay
version: 1
authored_by: measured across all 272 v2 packs and all 25 fault families
generated_from: blueprints/dns-delay.json
covers: dns_delay
mutually_exclusive_with: healthy-baseline
---
## When this applies
- new connections are slow while established ones are fine
- a service is running out of file descriptors with no leak to explain it
- syscall return values are available from the kernel trace

Do NOT use this blueprint when:
- no syscall is returning EMFILE
- packets are being lost or retransmitted heavily
- the application resolves nothing by name

Cheapest check first: count syscall exits with ret = -24 against all failing syscall exits in the incident window. If EMFILE is zero, this blueprint does not apply.

## Problem signature
- new connections are slow to establish while existing ones are fine
- the service runs out of file descriptors even though nothing is leaking them
- no packet loss and no service is down
- latency is spiky rather than uniformly raised

Telling it apart from its look-alikes:
- **the share of all failing syscalls that are EMFILE, from syscall_exit_* with ret = -24** — this problem: a large fraction of everything that fails - roughly one in fifty to one in twenty. Not this problem: a service hitting its own descriptor limit produces a rate more than ten times lower, because it exhausts descriptors gradually rather than in bursts of stalled lookups.
- **retransmission percentage on the impaired interfaces** — this problem: flat - the path is healthy, it is the lookups that fail. Not this problem: a degraded network path retransmits 23-51% while also raising EMFILE, so volume alone cannot tell the two apart.
- **which process is accumulating the descriptors** — this problem: the service whose lookups are being dropped - it is the victim of the resolver, not the cause. Not this problem: n/a - this names who is affected once the problem is established; it does not decide whether the problem is present.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: syscall_exit_accept, syscall_exit_accept4, syscall_exit_socket, syscall_exit_sendto, syscall_exit_recvfrom, net_dev_queue, netif_receive_skb

Why this set: MEASURED BASIS. The deciding fact is a syscall RETURN VALUE and the total count of failing syscalls, so exit events are what matter and durations are not needed. The two network events are only there for the retransmission gate, which is what excludes a degraded path. Recording every syscall exit also works and is what our own runs did, but syscall exits are 41% of all events and this rule reads five of them.

## Investigation blueprint
Each step names the capability it needs, how to get at it with the tools you have, and what a correct result looks like. There are no commands: you have a raw kernel trace and six read-only query tools, and nothing else. The 'with your tools' line is a starting point, not an instruction - if you see a better way with the same tools, take it and say what you did. A step marked NOT REACHABLE cannot be done from kernel data: skip it, say you skipped it, and do not treat its absence as evidence either way.

1. make the kernel trace readable
   needs: `trace.stage_ctf`
   with your tools: already done - the trace is loaded. ctf_timespan gives its real start and end.
   expect: a CTF directory with metadata and channel streams
2. count failing syscalls by errno, and the total, in both windows
   needs: `syscall.error_attribution`
   with your tools: query_ctf on syscall_exit_* for the calls you care about, then ctf_lines over a narrow range to read the actual return values. Error codes are in the raw lines only.
   expect: EMFILE per second, the total failing-syscall rate, and which process returned them
3. confirm the path is healthy, so a degraded link is not mistaken for this
   needs: `network.retransmission_rate`
   with your tools: query_ctf on net_dev_xmit and netif_receive_skb per range. There is no TCP retransmission tracepoint in this profile, so a retransmission RATE is not measurable - say that rather than inferring one from packet counts.
   expect: retransmission percentage per interface; this fault leaves it flat
4. combine into the verdict
   needs: `verdict.apply_rules`
   with your tools: do this yourself, from the numbers your own tool calls returned. Quote them.
   expect: a verdict naming name resolution as the cause and the accumulating service as the victim, or an explicit non-fire with the reason
5. state the recommended action alongside the diagnosis
   needs: `report.recommended_action`
   with your tools: write it in your own words in the diagnosis.
   expect: fix the resolver, and do NOT raise the descriptor limit on the service that ran out
6. draw the decision card
   needs: `report.decision_card`
   with your tools: NOT REACHABLE - no plotting here. Skip it; it does not affect the diagnosis.
   expect: one page showing where every fault family sits on this blueprint's deciding number, which gates passed and by how much, and what else was ruled out

## What to produce
- xy_chart: the decision itself: every fault family on the deciding axis with the cut drawn, the closest fault to that cut, each gate with its measured value and its bar, and the other blueprints with the number that ruled each one out
- json: verdict, the EMFILE share of failing syscalls, the process accumulating descriptors, and the retransmission rate that rules out a network fault
- text: why a name-resolution problem shows up as descriptor exhaustion, and why the service that ran out of descriptors is the victim rather than the cause
- text: fix name resolution for the affected service; raising its descriptor limit moves the failure later without addressing it

## Resolution template
Conclude this problem when ALL of:
- at least 0.0175 of all failing syscalls are EMFILE. Measured as a share of the failures rather than a rate, because a rate depends on the request load and on the descriptor limit and neither of those travels between deployments
- retransmission stays below 12%, so the path is healthy and the failures are not a degraded link
- the descriptors are being consumed by a service waiting on lookups rather than by one leaking them

Prefer a different explanation when:
- network-path-degradation — retransmission is high. A degraded path is the only other fault that produces EMFILE at all, and on that signal alone the two are close - 0.0156 against 0.0197. They are opposite on loss, so loss is what separates them, not volume.
- fd-exhaustion — EMFILE is a much smaller share of the failures, roughly one in a thousand rather than one in fifty. A service at its own descriptor limit exhausts them gradually; stalled lookups exhaust them in bursts.
- healthy-baseline — no syscall is returning EMFILE. It is exactly zero in every family but two, so its absence is strong evidence.

Root cause is: unreliable name resolution for one service, identified by the service whose lookups stall and which then accumulates descriptors waiting for them

## When to stop
- Conclude when: EMFILE is a large share of all failing syscalls while the path carries traffic without loss
- Stop and switch: retransmission at or above {RETRANS_VETO_PCT}% -> network-path-degradation; EMFILE present but a far smaller share of failures -> fd-exhaustion. IMPORTANT: switching away does not end the investigation. All three name a different cause for the same symptom - descriptors running out - so carry the measurement across rather than starting again.
- Evidence insufficient: syscall exit events were not recorded, so return values are unavailable -> request them and re-run. Do NOT fall back to the total failing-syscall rate: the baseline already runs roughly 16,000 failing syscalls per second, almost all EAGAIN on non-blocking reads, and EMFILE disappears into it.
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## If you are not confident enough
- Do not report a diagnosis below 0.7 confidence.
- name the unresolved question, pick the ONE additional capability that would settle it, check it against the overhead budget, and request it.
- if the floor is still not met after the allowed rounds, report the best-supported hypothesis, its confidence, and precisely what evidence is missing - never present a guess as a diagnosis
