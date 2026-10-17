#!/usr/bin/env python3
# net_loss.py - the degraded-network-path check: who is retransmitting, and
# whose packets are being dropped.
#
# TCP hides packet loss from the application: it just sends the lost segment
# again. So loss never shows up as an error anywhere - only as RETRANSMISSION,
# and the kernel trace records every transmit. A segment sent twice with the
# same sequence number is a retransmit.
#
# This tool reads the transmit events (net_dev_queue), which LTTng records
# with the full TCP header, and counts per flow:
#   - data segments sent (payload > 0; pure ACKs repeat their seq legitimately
#     and are NOT counted)
#   - segments sent more than once (retransmits) and the rate
# It groups flows by the sending process and container, so ONE service whose
# path is degraded stands out against everyone else's clean flows.
#
# It also counts skb_kfree (packet drop) events per container as a supporting
# signal - a lossy qdisc frees the packets it drops.
#
# Usage:
#   python3 net_loss.py <slice.txt> <slice_seconds> [min_segments]
#
#   <slice.txt>   a slice that KEEPS network events - cut it with:
#                 extract_slice.sh TRACE DAY HH:MM:SS SECS out.txt \
#                   'sched_switch|sched_waking|sched_wakeup|net_dev_queue|skb_kfree'
#   [min_segments] hide flows smaller than this (default 20)
import re
import sys
from collections import defaultdict

if len(sys.argv) < 3:
    print("usage: net_loss.py <slice.txt> <slice_seconds> [min_segments]", file=sys.stderr)
    sys.exit(1)
path, secs = sys.argv[1], float(sys.argv[2])
min_seg = int(sys.argv[3]) if len(sys.argv) > 3 else 20

re_ctx = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"[^}]*net_ns = (\d+)')
re_ip = re.compile(r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_len = re.compile(r'tot_len = (\d+), .*?ihl = (\d+)|ihl = (\d+), .*?tot_len = (\d+)')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = \d+, '
                    r'data_offset = (\d+)')

# A packet crossing a veth pair or a bridge fires net_dev_queue once per
# device, so the SAME segment appears 2-3 times on different devices - which
# reads as fake "50% retransmission" everywhere. A real retransmit repeats at
# the SAME observation point. So we count per (device, context netns) combo,
# and judge each flow at its busiest single vantage point.
flows = defaultdict(lambda: defaultdict(lambda: {"segs": 0, "dup": 0, "seen": set(),
                                                 "senders": defaultdict(int)}))
drops = defaultdict(int)          # (procname, net_ns) -> skb_kfree count
n_queue = 0

with open(path, errors="replace") as f:
    for line in f:
        if ' skb_kfree:' in line:
            c = re_ctx.search(line)
            if c:
                drops[(c.group(2), c.group(3))] += 1
            continue
        if ' net_dev_queue:' not in line:
            continue
        t = re_tcp.search(line)
        ip = re_ip.search(line)
        if not t or not ip:
            continue
        n_queue += 1
        sport, dport, seq, doff = t.groups()
        # payload bytes = total length - IP header - TCP header; 0 = pure ACK
        lm = re.search(r'ihl = (\d+),', line)
        tm = re.search(r'tot_len = (\d+),', line)
        if lm and tm:
            payload = int(tm.group(1)) - int(lm.group(1)) * 4 - int(doff) * 4
            if payload <= 0:
                continue
        sip = ".".join(ip.groups()[0:4])
        dip = ".".join(ip.groups()[4:8])
        key = (sip, sport, dip, dport)
        c = re_ctx.search(line)
        dv = re.search(r'len = \d+, name = "([^"]+)"', line)
        vantage = (dv.group(1) if dv else "?", c.group(3) if c else "?")
        fl = flows[key][vantage]
        fl["segs"] += 1
        if seq in fl["seen"]:
            fl["dup"] += 1
        fl["seen"].add(seq)
        if c:
            fl["senders"][(c.group(2), c.group(3))] += 1

if not flows:
    print("no TCP data segments found. Either nothing was sent in this slice, or the "
          "slice has no net_dev_queue events - check how it was cut.")
    sys.exit(0)

# one vantage point per flow: the busiest (device, netns) combo
best = {}
for key, combos in flows.items():
    v, fl = max(combos.items(), key=lambda kv: kv[1]["segs"])
    best[key] = fl

total_segs = sum(f["segs"] for f in best.values())
total_re = sum(f["dup"] for f in best.values())
print(f"TCP data segments in this {secs:.0f} s slice: {total_segs} "
      f"({total_re} retransmitted, {total_re / total_segs:.1%} overall)")
print()

# ---- per flow ---------------------------------------------------------------
print(f"Flows with the most retransmission (flows under {min_seg} segments hidden):")
print(f"  {'flow':<44}{'segs':>6}{'rexmit':>8}{'rate':>7}  sender")
rows = [(k, f) for k, f in best.items() if f["segs"] >= min_seg]
rows.sort(key=lambda kv: -kv[1]["dup"])
for (sip, sp, dip, dp), f in rows[:10]:
    snd = max(f["senders"].items(), key=lambda kv: kv[1])[0] if f["senders"] else ("?", "?")
    print(f"  {sip + ':' + sp + ' -> ' + dip + ':' + dp:<44}"
          f"{f['segs']:>6}{f['dup']:>8}{f['dup']/f['segs']:>7.1%}  "
          f"{snd[0]} (net_ns {snd[1]})")

# ---- per sender -------------------------------------------------------------
by_sender = defaultdict(lambda: [0, 0])
for f in best.values():
    if not f["senders"]:
        continue
    snd = max(f["senders"].items(), key=lambda kv: kv[1])[0]
    by_sender[snd][0] += f["segs"]
    by_sender[snd][1] += f["dup"]
print()
print("By sender (process, container):")
print(f"  {'sender':<28}{'net_ns':<14}{'segs':>7}{'rexmit':>8}{'rate':>7}")
for (nm, nsid), (segs, rx) in sorted(by_sender.items(), key=lambda kv: -kv[1][1])[:8]:
    print(f"  {nm:<28}{nsid:<14}{segs:>7}{rx:>8}{(rx/segs if segs else 0):>7.1%}")

# ---- drops ------------------------------------------------------------------
if drops:
    print()
    print("Packet frees (skb_kfree) by context - a lossy queue frees what it drops:")
    for (nm, nsid), n in sorted(drops.items(), key=lambda kv: -kv[1])[:6]:
        print(f"  {nm:<28}net_ns {nsid:<12}{n:>7}")

# ---- read it ----------------------------------------------------------------
print()
print("Read it:")
print("- ONE SERVICE'S PATH IS DEGRADED: the flows to and from one container")
print("  retransmit at a rate far above everyone else's, in both directions,")
print("  and the other containers' flows sit near 0%. Name that container.")
print("- HOST-WIDE network problem: flows of MANY unrelated containers all")
print("  retransmit. That is not one service's path.")
print("- NO retransmission but the victim sleeps on sockets (sched S high):")
print("  the peer is SLOW, not lossy - a slow dependency or a pure-delay")
print("  path. Retransmission proves loss; it cannot rule out added delay.")
print("- A few retransmits everywhere is normal background. Compare with the")
print("  baseline slice before calling anything a fault.")
