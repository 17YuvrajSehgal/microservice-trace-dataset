#!/usr/bin/env python3
# net_drops.py - the packet-drop check: how many packets the kernel DROPPED (not
# normally consumed), WHY (the drop reason, if the kernel records it), WHO owned
# them, WHEN they clustered, and whether the receive path had throughput dips at
# the same time.
#
# The kernel frees every packet it finishes with. Two different events say how:
#   skb_consume  - the NORMAL free: the packet was delivered/handled and let go.
#   skb_kfree    - kfree_skb: the packet was DROPPED or freed on an error path.
#                  Modern kernels (>= ~5.17) attach a `reason` (SKB_DROP_REASON_*)
#                  that says why: NO_SOCKET, TCP_*, NETFILTER_DROP, QDISC_DROP,
#                  OTHERHOST, etc. NOT_SPECIFIED means "reason not set" - often a
#                  benign free rather than a true drop.
# So a packet-drop fault shows as a RISE in skb_kfree relative to skb_consume,
# usually with a telling reason and clustered in time, and - on the receive side
# - as DIPS in net_if_receive_skb (fewer packets making it up the stack).
#
# This tool reads a decoded slice that KEEPS these events and reports all of that.
# It does NOT need protocol headers (unlike net_loss.py's retransmission count),
# so it works on switch/router traces where net_dev_queue carries no TCP header.
#
# Usage:
#   python3 net_drops.py <slice.txt> <slice_seconds>
#
#   <slice.txt>  a slice that KEEPS the packet events - cut it with:
#     extract_slice.sh TRACE DAY HH:MM:SS SECS out.txt \
#       'skb_kfree|skb_consume|net_if_receive_skb|net_dev_queue|net_dev_xmit'
import re
import sys
from collections import Counter, defaultdict

if len(sys.argv) < 3:
    print("usage: net_drops.py <slice.txt> <slice_seconds>", file=sys.stderr)
    sys.exit(1)
path, secs = sys.argv[1], float(sys.argv[2])

re_ts = re.compile(r"^\[(\d\d:\d\d:\d\d)")
re_ctx = re.compile(r'procname = "([^"]*)"')
re_reason_enum = re.compile(r'reason = \(\s*"([^"]+)"')   # enum: reason = ( "NO_SOCKET" : ... )
re_reason_num = re.compile(r'reason = (\d+)')             # bare int, older formatting
re_proto = re.compile(r'protocol = (?:\(\s*"([^"]+)"|(\d+))')

drop_total = consume_total = 0
rx_total = 0
drops_by_reason = Counter()
drops_by_proc = Counter()
reason_seen = False
drops_per_sec = Counter()       # HH:MM:SS -> dropped packets that second
rx_per_sec = Counter()          # HH:MM:SS -> net_if_receive_skb that second

with open(path, errors="replace") as f:
    for line in f:
        tsm = re_ts.match(line)
        sec = tsm.group(1) if tsm else None
        if " skb_kfree:" in line:
            drop_total += 1
            if sec:
                drops_per_sec[sec] += 1
            pm = re_ctx.search(line)
            drops_by_proc[pm.group(1) if pm else "?"] += 1
            rm = re_reason_enum.search(line)
            if rm:
                reason_seen = True
                drops_by_reason[rm.group(1)] += 1
            else:
                rn = re_reason_num.search(line)
                drops_by_reason["reason=" + rn.group(1) if rn else "(no reason field)"] += 1
        elif " skb_consume:" in line:
            consume_total += 1
        elif " net_if_receive_skb" in line:   # matches net_if_receive_skb and _entry
            rx_total += 1
            if sec:
                rx_per_sec[sec] += 1


def spread(counter):
    """median and the min/max per-second buckets, for burst/dip judgement."""
    if not counter:
        return 0, 0, 0, None, None
    items = sorted(counter.items())                    # by time
    vals = sorted(counter.values())
    med = vals[len(vals) // 2]
    lo_t, lo = min(items, key=lambda kv: kv[1])
    hi_t, hi = max(items, key=lambda kv: kv[1])
    return med, lo, hi, lo_t, hi_t


print(f"=== packet frees in this {secs:.0f} s slice ===")
total_free = drop_total + consume_total
if total_free == 0:
    print("no skb_kfree / skb_consume events in this slice - check how it was cut "
          "(it must keep skb_kfree and skb_consume).")
    sys.exit(0)
dr = drop_total / secs
print(f"skb_kfree  (DROPPED/error-freed): {drop_total:>9}  ({dr:,.0f}/s)")
print(f"skb_consume (normal delivery)   : {consume_total:>9}  ({consume_total/secs:,.0f}/s)")
share = drop_total / total_free if total_free else 0
print(f"drop share of all frees         : {share:.1%}   "
      f"(skb_kfree / (skb_kfree + skb_consume))")
print()

print("=== why they were dropped (reason) ===")
if reason_seen:
    for r, n in drops_by_reason.most_common(10):
        tag = "  <- benign: 'reason not set'" if r == "NOT_SPECIFIED" else ""
        print(f"  {n:>9}  {r}{tag}")
    real = sum(n for r, n in drops_by_reason.items() if r != "NOT_SPECIFIED")
    print(f"  drops with a real reason (not NOT_SPECIFIED): {real} ({real/secs:,.0f}/s)")
else:
    print("  this kernel did not record a drop reason on skb_kfree. Judge by the RATE,")
    print("  the CLUSTERING in time, and the receive dips below, not by reason.")
print()

print("=== who owned the dropped packets ===")
for p, n in drops_by_proc.most_common(8):
    print(f"  {n:>9}  {p}")
print()

med, lo, hi, lo_t, hi_t = spread(drops_per_sec)
print("=== drops over time (per second) ===")
print(f"  median {med}/s, peak {hi}/s at {hi_t}, quietest {lo}/s at {lo_t}")
if med and hi >= 3 * max(med, 1):
    print(f"  -> BURST: the peak second is {hi/max(med,1):.0f}x the median. Drops cluster "
          f"around {hi_t} - a candidate incident window, not steady background.")
else:
    print("  -> drops are roughly steady, no sharp burst (steady background, or the "
          "whole slice is inside the event).")
print()

rmed, rlo, rhi, rlo_t, rhi_t = spread(rx_per_sec)
print("=== receive path over time (net_if_receive_skb per second) ===")
if rx_total == 0:
    print("  no net_if_receive_skb in this slice (egress-only path, or not kept in the cut).")
else:
    print(f"  median {rmed}/s, lowest {rlo}/s at {rlo_t}, highest {rhi}/s at {rhi_t}")
    if rmed and rlo <= 0.5 * rmed:
        print(f"  -> RECEIVE DIP: the lowest second ({rlo}/s at {rlo_t}) is {1-rlo/max(rmed,1):.0%} "
              f"below the median - packets are not making it up the stack there. If it lines "
              f"up with the drop burst, that is the loss landing on the receive path.")
    else:
        print("  -> receive throughput is roughly flat, no clear dip.")
print()

print("Read it:")
print("- REAL DROPS: skb_kfree rises well above its baseline AND carries a real reason")
print("  (not NOT_SPECIFIED) OR clusters in a burst that lines up with a receive dip.")
print("  Name the reason, the per-second rate, the window, and the owning process.")
print("- NORMAL: skb_kfree is a small, steady fraction of skb_consume with reason")
print("  NOT_SPECIFIED (or no reason field) and no burst - routine frees, not a fault.")
print("- Always compare against a baseline slice outside the suspected window: the drop")
print("  rate alone means little without the quiet-period number to compare it to.")
print("- No net_dev_queue headers here is fine - this check does not need them. If you")
print("  also need per-flow TCP retransmission, that is net_loss.py (needs headers).")
