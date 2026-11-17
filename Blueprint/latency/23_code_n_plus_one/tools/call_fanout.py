#!/usr/bin/env python3
# call_fanout.py - how many calls a service makes to each of its dependencies for every
# request it receives, and whether those calls overlap in time.
#
# Two code defects leave the dependency healthy and fast and change only the SHAPE of the
# calls to it:
#   - an extra call per row of a result (N+1): the calls per received request multiply
#   - a lock held across the call: the calls to that dependency never overlap any more
#
# It reads the transmit events (net_dev_queue). A call = a data segment from the client on a
# connection with no call pending; its answer = the next data segment from the server.
#
# Usage:
#   python3 call_fanout.py <net_slice.txt> <slice_seconds> [baseline_slice.txt]
#   python3 call_fanout.py --selftest
#
#   The baseline must be at the SAME steady load as the suspect slice. Calls per request
#   depend on what the users are doing: measured on our runs, a baseline cut while the load
#   was still ramping up gave a 1.6x rise for a healthy service.
#
#   slices: 20 s or more, cut with
#        extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict
from statistics import median

MIN_CALLS = 200        # a pair is judged only if the client made this many calls to the server
                       # AND received this many requests itself in the slice
MIN_RATIO_UP = 1.35    # amplification: calls per received request grew by this factor. Fitted:
                       # the 6 labelled runs are at 1.45-1.57, the next healthy pair at 1.28
MAX_SLOWER = 1.1       # ... while the answers did not get slower than this factor (more calls
                       # to a slow or lossy dependency are retries, a different fault)
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_dev = re.compile(r' name = "([^"]*)"')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = \d+, ack_seq = \d+, data_offset = (\d+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    # conn -> device -> [(t, from_client)] for segments that carry data. A packet fires once
    # per device it crosses, so the device with the most segments is used, not the sum.
    segs = defaultdict(lambda: defaultdict(list))
    votes = defaultdict(lambda: defaultdict(int))        # client ip -> (name, pid_ns) -> n
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp:
            continue
        if int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(3)) * 4 <= 0:
            continue
        t = tsec(line)
        if t is None:
            continue
        src, dst = ".".join(ip.groups()[2:6]), ".".join(ip.groups()[6:10])
        sp, dp = int(tcp.group(1)), int(tcp.group(2))
        from_client = (dp < 32768 <= sp) or (not (sp < 32768 <= dp) and dp < sp)
        d = re_dev.search(line)
        segs[(src, sp, dst, dp) if from_client else (dst, dp, src, sp)][d.group(1) if d else "?"].append((t, from_client))
        if from_client:
            cx = re_ctx.search(line)
            if cx and not cx.group(2).startswith(KERNEL_CTX):
                pn = re_pidns.search(line)
                votes[src][(cx.group(2), pn.group(1) if pn else "?")] += 1
    pairs = defaultdict(lambda: {"calls": 0, "rt": [], "iv": []})     # (client ip, server ip, port)
    for (cip, cport, sip, sport), devs in segs.items():
        p = pairs[(cip, sip, sport)]
        t0 = None
        for t, fc in sorted(max(devs.values(), key=len)):
            if fc and t0 is None:
                t0 = t
                p["calls"] += 1
            elif not fc and t0 is not None:
                p["rt"].append(t - t0)
                p["iv"].append((t0, t))
                t0 = None
    who = {ip: max(v, key=v.get) for ip, v in votes.items()}
    return pairs, who


def overlap(iv, secs):
    # share of the slice with at least 1 and at least 2 calls in flight
    ev = sorted([(a, 1) for a, _ in iv] + [(b, -1) for _, b in iv])
    n, last, one, two = 0, None, 0.0, 0.0
    for t, d in ev:
        if last is not None:
            one += (t - last) if n >= 1 else 0
            two += (t - last) if n >= 2 else 0
        n, last = n + d, t
    return one / secs, two / secs


def table(pairs, secs):
    inbound = defaultdict(int)
    for (cip, sip, sport), p in pairs.items():
        inbound[sip] += p["calls"]
    rows = {}
    for k, p in pairs.items():
        if p["calls"] < MIN_CALLS or inbound.get(k[0], 0) < MIN_CALLS:
            continue
        one, two = overlap(p["iv"], secs)
        rows[k] = {"calls": p["calls"], "per_in": p["calls"] / inbound[k[0]],
                   "rt": median(p["rt"]) * 1000 if p["rt"] else 0.0, "one": one, "two": two}
    return rows


def report(cur, secs, base=None):
    pairs, who = cur
    rows = table(pairs, secs)
    brow = table(base[0], secs) if base else {}

    def name(ip):
        return f"{who[ip][0]} (pid_ns {who[ip][1]})" if ip in who else "?"

    out = [f"Calls from services to their dependencies in this {secs:.0f} s slice (pairs with {MIN_CALLS} calls or more, "
           f"from a client that also receives requests)",
           f"  {'client':<15} {'server':<21} {'calls/s':>8} {'per request in':>15} {'before':>7} {'answer ms':>10} {'before':>7} "
           f"{'>=1 in flight':>14} {'>=2 in flight':>14} {'before':>7}  client program"]
    for k, r in sorted(rows.items(), key=lambda kv: -kv[1]["calls"])[:12]:
        b = brow.get(k)
        b_in, b_rt, b_two = ("%.2f" % b["per_in"], "%.2f" % b["rt"], "%.1f%%" % (b["two"] * 100)) if b else ("-", "-", "-")
        out.append(f"  {k[0]:<15} {k[1] + ':' + str(k[2]):<21} {r['calls'] / secs:>8.0f} {r['per_in']:>15.2f} "
                   f"{b_in:>7} {r['rt']:>10.2f} {b_rt:>7} "
                   f"{r['one']:>14.1%} {r['two']:>14.1%} {b_two:>7}  {name(k[0])}")
    out.append("  per request in = calls to that server divided by the requests the client itself received; "
               "in flight = share of the slice with that many calls unanswered; before = the baseline slice")
    hits = 0
    for k, r in sorted(rows.items(), key=lambda kv: -kv[1]["per_in"] / max(1e-9, brow.get(kv[0], {}).get("per_in", 1e9))):
        b = brow.get(k)
        if b and r["per_in"] >= MIN_RATIO_UP * b["per_in"] and r["rt"] <= MAX_SLOWER * b["rt"]:
            out.append(f"VERDICT: CALL AMPLIFICATION: {name(k[0])} at {k[0]} makes {r['per_in']:.1f} calls to {k[1]}:{k[2]} "
                       f"per request it receives, {b['per_in']:.1f} in the baseline ({r['per_in'] / b['per_in']:.1f}x); "
                       f"each answer takes {r['rt']:.2f} ms ({b['rt']:.2f} before)")
            hits += 1
    if not hits:
        best = max(((r["per_in"] / brow[k]["per_in"], k) for k, r in rows.items()
                    if k in brow and r["rt"] <= MAX_SLOWER * brow[k]["rt"]), default=None)
        why = (f"largest rise with answers not slower: {best[0]:.2f}x for {best[1][0]} -> {best[1][1]}:{best[1][2]}" if best
               else "no baseline given, or no pair is in both slices")
        out.append(f"VERDICT: NO CALL AMPLIFICATION ({why}; the bar is {MIN_RATIO_UP}x)")
    return out


def selftest():
    def addr(a):
        return ", ".join(f"[{i}] = {x}" for i, x in enumerate(a.split(".")))

    def q(t, nm, ns, src, sport, dst, dport, payload=50):
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 7, tid = 7, procname = "{nm}", '
                f'pid_ns = {ns} }}, {{ skbaddr = 0x1, len = {payload + 40}, name = "eth0", network_header_type = 1, '
                f'network_header = {{ ipv4 = {{ version = 4, ihl = 5, tos = 0, tot_len = {payload + 40}, id = 0x1, frag_off = 0, '
                f'ttl = 64, protocol = 6, checksum = 0x0, saddr = [ {addr(src)} ], daddr = [ {addr(dst)} ], '
                f'transport_header_type = 1, transport_header = {{ tcp = {{ source_port = {sport}, dest_port = {dport}, '
                f'seq = 1, ack_seq = 1, data_offset = 5, reserved = 0, flags = 0x18, window_size = 64 }} }} }} }} }}')

    def slice_(per_req):
        ls = []
        for i in range(300):                       # web -> app:80, and app -> db:3306 per_req times
            t = i * 0.05
            ls += [q(t, "web", 4, "10.0.0.4", 40000, "10.0.0.5", 80)]
            for j in range(per_req):
                ls += [q(t + 0.001 + j * 0.002, "app", 5, "10.0.0.5", 41000, "10.0.0.6", 3306),
                       q(t + 0.002 + j * 0.002, "mysqld", 6, "10.0.0.6", 3306, "10.0.0.5", 41000)]
            ls += [q(t + 0.03, "app", 5, "10.0.0.5", 80, "10.0.0.4", 40000)]
        return sorted(ls, key=tsec)

    base = read(slice_(1))
    out = "\n".join(report(read(slice_(10)), 15, base))
    assert "CALL AMPLIFICATION: app (pid_ns 5) at 10.0.0.5 makes 10.0 calls to 10.0.0.6:3306 per request it receives, 1.0 in the baseline (10.0x)" in out, out
    out = "\n".join(report(base, 15, base))
    assert "NO CALL AMPLIFICATION (largest rise with answers not slower: 1.00x" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: call_fanout.py <net_slice.txt> <slice_seconds> [baseline_slice.txt]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        cur = read(f)
    b = None
    if len(sys.argv) > 3:
        with open(sys.argv[3], errors="replace") as f:
            b = read(f)
    print("\n".join(report(cur, float(sys.argv[2]), b)))
