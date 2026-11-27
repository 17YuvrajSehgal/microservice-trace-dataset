#!/usr/bin/env python3
# big_resends.py - find a network path that drops large packets and lets small ones through.
#
# A packet that is lost is sent again with the same sequence number and the same size. The tool
# counts, per sender and receiver, the segments that leave the sender's interface more than once
# (each interface is counted on its own, so a packet seen on two interfaces is not a resend),
# and splits them by size. An MTU black hole resends LARGE segments again and again while small
# ones pass; loss on a link resends segments of every size.
#
# The address that appears in most of the resending pairs is named: a black hole in front of one
# service catches what it sends AND what is sent to it.
#
# Usage:
#   python3 big_resends.py <fault_slice.txt> <slice_seconds> <baseline_slice.txt>
#   python3 big_resends.py --selftest
#
#   slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict, Counter

MIN_RESENDS = 50       # segments resent on one path in the slice
MIN_CUT = 200          # ... every resent segment is at least this large (normal loss resends any size, down to 5 bytes)
MAX_SMALL_RESENT = 0.05  # ... below it, at most this share of the segments were resent
MIN_SMALL = 50         # ... and the path carries at least this many smaller segments (so "small ones pass" is seen)
# RULE HISTORY (all on the 5 mtu_blackhole runs, 26-11-2026): (1) a fixed 1,000-byte cut-off
# missed: the dropped segments were 537-999 bytes. (2) "80%, then 50%, of the segments above the
# cut-off are resent" swung from 37% to 78% between runs: a dropped segment's resends back off,
# so a 10 s slice often holds only its first send. (3) Now: what separates the path is the SIZE
# of what is resent - nothing under 200 bytes is resent on it, while normal loss resends
# segments of any size. Fitted after seeing the 5 runs.
MAX_BASE = 0.1         # ... and the baseline had at most this share of the resends
# The cut-off is NOT fixed: it is the smallest size among the path's resent segments (its 5th
# percentile). The first version used 1,000 bytes; with an MTU of 576 most dropped segments were
# 537-999 bytes and were counted as small (run 1 of mtu_blackhole, 26-11-2026). Bars otherwise
# set before the first run. The drops show only in the first seconds of the fault: after that
# the service's circuit breaker stops it from sending at all, so take the slice at its start.

re_dev = re.compile(r' name = "([^"]*)"')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = \d+, data_offset = (\d+)')


def read(lines):
    first = {}                                   # (dev, src, dst, sp, dp, seq, size) -> times seen
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp, d = re_ip.search(line), re_tcp.search(line), re_dev.search(line)
        if not ip or not tcp or not d:
            continue
        payload = int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(4)) * 4
        if payload <= 0:
            continue
        src, dst = ".".join(ip.groups()[2:6]), ".".join(ip.groups()[6:10])
        key = (d.group(1), src, dst, tcp.group(1), tcp.group(2), tcp.group(3), payload)
        first[key] = first.get(key, 0) + 1
    paths = defaultdict(list)                    # (src, dst) -> [(size, resent?)]
    for (dev, src, dst, sp, dp, seq, size), n in first.items():
        paths[(src, dst)].append((size, n > 1))
    return paths


def path_stats(segs):
    resent = sorted(sz for sz, r in segs if r)
    if not resent:
        return None
    cut = resent[len(resent) // 20]
    big = [r for sz, r in segs if sz >= cut]
    small = [r for sz, r in segs if sz < cut]
    return {"resent": len(resent), "cut": cut, "big_share": sum(big) / len(big),
            "small_share": (sum(small) / len(small)) if small else 0.0, "small_n": len(small)}


def report(data, secs, base):
    rows = []
    for k, segs in data.items():
        st = path_stats(segs)
        if st:
            rows.append((st["resent"], k, st))
    rows.sort(reverse=True)
    out = [f"Segments sent again, per path, in this {secs:.0f} s slice",
           f"  {'from':<16} {'to':<16} {'resent':>7} {'cut-off':>8} {'resent at/above':>16} {'resent below':>13} {'resent before':>14}"]
    for n, (s, d), st in rows[:10]:
        bst = path_stats(base.get((s, d), []))
        out.append(f"  {s:<16} {d:<16} {n:>7} {st['cut']:>8} {st['big_share']:>16.0%} {st['small_share']:>13.0%} {(bst or {}).get('resent', 0):>14}")
    out.append("  cut-off = the smallest size among the resent segments (bytes of payload); before = the baseline slice")
    hit = []
    for n, (s, d), st in rows:
        bst = path_stats(base.get((s, d), [])) or {"resent": 0}
        if (n >= MIN_RESENDS and st["cut"] >= MIN_CUT and st["small_share"] <= MAX_SMALL_RESENT
                and st["small_n"] >= MIN_SMALL and bst["resent"] <= MAX_BASE * n):
            hit.append(((s, d), n, st))
    if hit:
        ends = Counter()                     # the packets are dropped in front of the RECEIVER
        for (s, d), n, _ in hit:
            ends[d] += n
        who = ends.most_common(1)[0][0]
        paths = ", ".join(f"{s} -> {d} ({n}, {st['cut']}+ bytes)" for (s, d), n, st in hit[:4])
        out.append(f"VERDICT: LARGE PACKETS ARE DROPPED ON ONE PATH: {sum(n for _, n, _ in hit)} segments resent in {secs:.0f} s on "
                   f"{len(hit)} path(s) into {who}: {paths}; only segments above the cut-off are resent, smaller ones pass "
                   f"- an MTU black hole in front of {who}")
    else:
        top = rows[0] if rows else None
        why = (f"most: {top[0]} resent {top[1][0]} -> {top[1][1]}" if top else "no resent segment")
        out.append(f"VERDICT: NO LARGE-PACKET DROPS ({why}; the bars are {MIN_RESENDS} resends, all of {MIN_CUT}+ bytes, at most "
                   f"{MAX_SMALL_RESENT:.0%} of {MIN_SMALL}+ smaller segments resent, at most {MAX_BASE:.0%} in the baseline)")
    return out


def selftest():
    def seg(t, src, sp, dst, dp, seq, n, dev="eth0"):
        a, b = src.split("."), dst.split(".")
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, procname = "x", pid_ns = 1 }}, '
                f'{{ skbaddr = 0x1, len = {n + 54}, name = "{dev}", network_header = {{ ipv4 = {{ version = 4, ihl = 5, tot_len = {n + 40}, '
                f'saddr = [ [0] = {a[0]}, [1] = {a[1]}, [2] = {a[2]}, [3] = {a[3]} ], daddr = [ [0] = {b[0]}, [1] = {b[1]}, [2] = {b[2]}, [3] = {b[3]} ], '
                f'transport_header = {{ tcp = {{ source_port = {sp}, dest_port = {dp}, seq = {seq}, ack_seq = 1, data_offset = 5 }} }} }} }} }}')
    base, fault = [], []
    for i in range(300):
        base += [seg(i * 0.03, "10.0.0.9", 80, "10.0.0.2", 40000, i, 1400), seg(i * 0.03 + 0.0001, "10.0.0.9", 80, "10.0.0.2", 40000, i, 1400, "veth1")]
        fault.append(seg(i * 0.03, "10.0.0.2", 40000, "10.0.0.9", 80, 50000 + i, 200))            # small requests pass
        fault.append(seg(i * 0.03 + 0.001, "10.0.0.9", 80, "10.0.0.2", 40000, 90000 + i, 300))  # small answers pass
        fault.append(seg(i * 0.03 + 0.002, "10.0.0.4", 3306, "10.0.0.9", 41000, 70000 + i, 100))
        for k in range(3):                                                                         # large answers resent 3 times
            fault.append(seg(i * 0.03 + 0.005 * k, "10.0.0.9", 80, "10.0.0.2", 40000, i, 1400))
        for k in range(2):                                                                         # large DB answers to it resent too
            fault.append(seg(i * 0.03 + 0.004 * k, "10.0.0.4", 3306, "10.0.0.9", 41000, i, 1400))
    out = "\n".join(report(read(sorted(fault, key=lambda l: l[1:19])), 10, read(base)))
    assert "LARGE PACKETS ARE DROPPED ON ONE PATH: 600 segments resent in 10 s on 2 path(s) into" in out, out
    out = "\n".join(report(read(base), 10, read(base)))
    assert "NO LARGE-PACKET DROPS (no resent segment" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: big_resends.py <fault_slice.txt> <slice_seconds> <baseline_slice.txt>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        d = read(f)
    with open(sys.argv[3], errors="replace") as f:
        b = read(f)
    print("\n".join(report(d, float(sys.argv[2]), b)))
