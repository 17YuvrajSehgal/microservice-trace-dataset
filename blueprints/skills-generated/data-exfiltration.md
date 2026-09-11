---
name: data-exfiltration
version: 1
authored_by: measured across all 303 v2 runs and all 27 fault families, both applications
generated_from: blueprints/data-exfiltration.json
covers: data_exfiltration
mutually_exclusive_with: healthy-baseline
---
## When this applies
- outbound traffic is well above normal
- no errors, no loss, and normal latency
- per-process network attribution is available from the kernel trace

Do NOT use this blueprint when:
- packets are being lost or retransmitted heavily
- outbound volume is flat
- a container is at its memory limit

Cheapest check first: sum net_dev_queue bytes per process in each window. If no single process gained more than a few MB per second, this blueprint does not apply.

## Problem signature
- outbound traffic well above normal with no errors anywhere
- no packet loss and no retransmission
- services still answer at normal latency
- the host looks healthy on every saturation measure

Telling it apart from its look-alikes:
- **bytes per second gained by a process that was barely sending before, from net_dev_queue** — this problem: one process arrives sending ~81 MB/s it was not sending before. Not this problem: no other fault family gains more than 3.6 MB/s on either application.
- **host outbound bytes, incident against baseline** — this problem: rises 6.2x on one application and 24.9x on the other, for the same absolute transfer. Not this problem: overlaps with other families on one of the two applications, so it cannot be used.
- **retransmission percentage** — this problem: flat. Not this problem: network-path-degradation runs 18.5-60.7%.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: net_dev_queue

Why this set: MEASURED BASIS. net_dev_queue carries the byte count, the interface, the protocol and ports, AND the process that was on-CPU when the buffer was queued, which is what makes per-process attribution possible at all. One event type decides this blueprint. Loss and retransmission events are not needed to fire it - they are needed only to rule out the network blueprint, and the pack already carries them.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. stage the stored kernel trace for reading
   run: `bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh <app> <family> <run_id>`
   expect: a CTF directory the trace reader can open
2. measure bytes sent per process, both windows, and report the newcomer
   run: `python3 blueprints/lib/process_probe.py --ctf <ctf> --gt <window> --out <out>/process.json`
   expect: bytes per second per process in each window, and the process whose rate rose most
3. confirm the path is healthy, so heavy traffic is not mistaken for a losing path
   run: `python3 blueprints/problems/network-path-degradation/scripts/net_loss_signature.py --ctf <ctf> --gt <window> --out <out>/netloss.json`
   expect: retransmission percentage per interface; this fault leaves it flat
4. combine into the verdict and its artifacts
   run: `python3 blueprints/lib/blueprint_decide.py --pack <pack.json> --out <out>/verdict.json`
   expect: a verdict naming the sending process, or an explicit non-fire with the reason
5. draw the decision card
   run: `python3 blueprints/lib/blueprint_card.py --pack <pack.json> --ruler blueprints/results/ruler.json --blueprint data-exfiltration --problems blueprints/problems --out <out>/card.svg`
   expect: one page showing where every fault family sits on this blueprint's deciding number, which gates passed and by how much, and what else was ruled out

## What to produce
- xy_chart: the decision itself: every fault family on the deciding axis with the cut drawn, the closest fault to that cut, each gate with its measured value and its bar, and the other blueprints with the number that ruled each one out
- json: verdict, the sending process, bytes per second gained, the destination ports it used, and the retransmission rate that rules out a network fault
- xy_chart: outbound bytes per second per process, baseline against incident
- text: which process started sending, how much, and why this is heavy traffic rather than a degraded path
- text: map the process to its container and its destination, then decide whether the transfer is expected before throttling or blocking it

## Resolution template
Conclude this problem when ALL of:
- a process gains more than 3.6 MB per second of outbound traffic over its baseline
- that process was sending little or nothing before
- retransmission stays low, so the path is healthy rather than losing packets

Prefer a different explanation when:
- network-path-degradation — retransmission is high. A losing path also moves bytes, but it moves the SAME bytes repeatedly. Volume alone cannot tell the two apart; loss can.
- service-memory-cap — retransmission is very high and one container is at its memory limit. A capped container cannot drain its sockets, which produces heavy retransmission that looks like traffic.
- healthy-baseline — no process gains meaningful outbound volume, even if the host total looks raised. The host total is application-specific - see the retracted discriminator.

Root cause is: a process sending bulk data it does not normally send, identified by its command name and destination port

## When to stop
- Conclude when: one process gained tens of MB per second of outbound traffic it was not sending before, with the path healthy
- Stop and switch: retransmission high -> network-path-degradation; retransmission very high with a container at its memory limit -> service-memory-cap
- Evidence insufficient: net_dev_queue was not recorded, so egress cannot be attributed -> request it and re-run. Do NOT fall back to the host outbound total, which was measured to separate on one application only.
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## If you are not confident enough
- Do not report a diagnosis below 0.7 confidence.
- name the unresolved question, pick the ONE additional capability that would settle it, check it against the overhead budget, and request it.
- if the floor is still not met after the allowed rounds, report the best-supported hypothesis, its confidence, and precisely what evidence is missing - never present a guess as a diagnosis
