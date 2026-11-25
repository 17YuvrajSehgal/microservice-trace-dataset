#!/usr/bin/env python3
# dev_delay.py - find a container whose packets wait at its own network interface.
#
# A packet from a container is queued twice on its way out: on the container's interface, and
# then on the interface of the next hop. Normally the two are a few microseconds apart. When a
# rate limit (or any queue) sits on the container's interface, the packet waits there, and the
# gap between the two sightings is that wait. The limit is on the sender, so the tool names the
# sender.
#
# For each sending address:
#   packets   packets seen on two interfaces in the slice
#   p50, p95  the gap between the first and the second sighting, in ms
#   kbit/s    what it sent (IP bytes), over the slice
#
# It reads the transmit events (net_dev_queue).
#
# Usage:
#   python3 dev_delay.py <slice.txt> <slice_seconds> [baseline_slice.txt]
#   python3 dev_delay.py --selftest
#
#   slices: 20 s or more, cut with
#     extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict

MIN_PKTS = 500         # packets of one sender seen on two interfaces
MIN_P50_MS = 5.0       # half of them waited at least this long
MIN_P95_MS = 20.0      # and one in twenty this long
MIN_RISE = 10.0        # ... and this many times the baseline's p95 (when a baseline is given)
# Bars set before the first run on labelled data (25-11-2026) and not fitted to it.
#
# RATE LIMIT OR FIXED DELAY. Both make packets wait at the sender's interface. They differ in
# how the wait is spread:
#   a fixed delay (netem) holds every packet about the same time: p95 is 1.4-1.6 times the median
#   a rate limit (tbf) holds a packet only while the queue is busy: p95 is 4.5-5.3 times the median
# Measured on the verdict lines of the sweep of 25-11-2026 (job 2931081): 102 senders in the 21
# runs of svc_net and anomaly_net (both applications) against the 5 net_bandwidth runs. The two
# bars below sit between those groups and were chosen AFTER seeing them.
SPREAD_LIMIT = 3.0     # p95 / median at or above this: the wait depends on load
SPREAD_DELAY = 2.0     # below this: about the same wait for every packet
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_dev = re.compile(r' name = "([^"]*)"')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = (\d+), data_offset = (\d+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    first = {}                                   # packet -> (time, device) of its first sighting
    gaps = defaultdict(list)                     # sender ip -> [seconds between the two sightings]
    sent = defaultdict(int)                      # sender ip -> IP bytes
    votes = defaultdict(lambda: defaultdict(int))
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp, d = re_ip.search(line), re_tcp.search(line), re_dev.search(line)
        t = tsec(line)
        if not ip or not tcp or not d or t is None:
            continue
        src = ".".join(ip.groups()[2:6])
        key = (src, ".".join(ip.groups()[6:10]), tcp.group(1), tcp.group(2), tcp.group(3), tcp.group(4), ip.group(2))
        f = first.get(key)
        if f is None:
            first[key] = (t, d.group(1))
            sent[src] += int(ip.group(2))
            cx = re_ctx.search(line)
            # a packet is first queued in the context of the process that wrote it
            if cx and not cx.group(3).startswith(KERNEL_CTX):
                pn = re_pidns.search(line)
                votes[src][(cx.group(3), pn.group(1) if pn else "?")] += 1
        elif f[1] != d.group(1):                 # same device again = a retransmission, not a hop
            gaps[src].append(t - f[0])
            del first[key]
    who = {ip: max(v, key=v.get) for ip, v in votes.items()}
    return gaps, sent, who


def pct(x, p):
    x = sorted(x)
    return x[min(len(x) - 1, int(p * len(x)))] * 1e3 if x else 0.0


def report(data, secs, base=None):
    gaps, sent, who = data
    bg = base[0] if base else {}
    rows = sorted(gaps.items(), key=lambda kv: -pct(kv[1], 0.95))
    out = [f"Wait of each sender's packets at its own interface, in this {secs:.0f} s slice (senders with {MIN_PKTS} packets or more)",
           f"  {'sender':<16} {'packets':>8} {'p50 ms':>8} {'p95 ms':>8} {'kbit/s':>8} {'p95 before':>11}  program"]
    for ip, g in rows:
        if len(g) < MIN_PKTS:
            continue
        nm = who.get(ip, ("?", "?"))
        out.append(f"  {ip:<16} {len(g):>8} {pct(g, .5):>8.2f} {pct(g, .95):>8.2f} {sent[ip] * 8 / secs / 1000:>8.0f} "
                   f"{('%.2f' % pct(bg.get(ip, []), .95)) if base else '-':>11}  {nm[0]} (pid_ns {nm[1]})")
    out.append("  wait = time between a packet's queueing on the sender's interface and on the next interface; before = the baseline slice")
    hits = 0
    for ip, g in rows:
        b = pct(bg.get(ip, []), .95) if base else 0.0
        if len(g) < MIN_PKTS or pct(g, .5) < MIN_P50_MS or pct(g, .95) < MIN_P95_MS or (base and pct(g, .95) < MIN_RISE * b):
            continue
        nm = who.get(ip, ("?", "?"))
        spread = pct(g, .95) / max(pct(g, .5), 0.001)
        if spread >= SPREAD_LIMIT:
            kind = (f"KIND: A RATE LIMIT OR A FULL QUEUE (the wait depends on load: p95 is {spread:.1f} times the median; "
                    f"the limit is about what it sent, {sent[ip] * 8 / secs / 1000:.0f} kbit/s)")
        elif spread < SPREAD_DELAY:
            kind = (f"KIND: A FIXED DELAY (about the same for every packet: p95 is {spread:.1f} times the median; "
                    f"the delay is about {pct(g, .5):.0f} ms)")
        else:
            kind = f"KIND: UNCLEAR (p95 is {spread:.1f} times the median, between a fixed delay and a rate limit)"
        out.append(f"VERDICT: PACKETS WAIT AT THE SENDER'S INTERFACE: {nm[0]} (pid_ns {nm[1]}) at {ip}: {len(g)} packets waited "
                   f"{pct(g, .5):.0f} ms (median) and {pct(g, .95):.0f} ms (p95) before leaving its interface"
                   + (f", {b:.2f} ms in the baseline" if base else "") + f"; it sent {sent[ip] * 8 / secs / 1000:.0f} kbit/s; {kind}")
        hits += 1
    if not hits:
        top = next(((ip, g) for ip, g in rows if len(g) >= MIN_PKTS), None)
        why = (f"longest: p95 {pct(top[1], .95):.2f} ms at {top[0]}" if top else "no sender with enough packets")
        out.append(f"VERDICT: NO PACKETS WAITING AT A SENDER'S INTERFACE ({why}; the bars are {MIN_PKTS} packets, "
                   f"median {MIN_P50_MS:.0f} ms, p95 {MIN_P95_MS:.0f} ms, {MIN_RISE:.0f}x the baseline)")
    return out


def selftest():
    def seg(t, dev, src, sp, dst, dp, seq, n, comm="app", ns=7):
        a, b = src.split("."), dst.split(".")
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, procname = "{comm}", pid_ns = {ns} }}, '
                f'{{ skbaddr = 0x1, len = {n + 14}, name = "{dev}", network_header_type = ( "_ipv4" : container = 1 ), network_header = '
                f'{{ ipv4 = {{ version = 4, ihl = 5, tos = 0, tot_len = {n}, id = 0x1, frag_off = 0, ttl = 64, protocol = ( "_tcp" : container = 6 ), '
                f'checksum = 0x0, saddr = [ [0] = {a[0]}, [1] = {a[1]}, [2] = {a[2]}, [3] = {a[3]} ], '
                f'daddr = [ [0] = {b[0]}, [1] = {b[1]}, [2] = {b[2]}, [3] = {b[3]} ], '
                f'transport_header_type = ( "_tcp" : container = 1 ), transport_header = {{ tcp = {{ source_port = {sp}, dest_port = {dp}, '
                f'seq = {seq}, ack_seq = 1, data_offset = 5, reserved = 0, flags = 0x18, window = 500, checksum = 0x0, urg_ptr = 0 }} }} }} }} }}')

    def flow(src, comm, ns, gap, n=1000):
        out = []
        for i in range(n):
            t = 1 + i * 0.015
            out += [seg(t, "eth0", src, 80, "10.0.0.2", 40000, 1000 + i * 1000, 1040, comm, ns),
                    seg(t + gap(i), "veth9", src, 80, "10.0.0.2", 40000, 1000 + i * 1000, 1040, "swapper/1", 0)]
        return out

    quick = lambda i: 0.000005
    normal = flow("10.0.0.9", "srv", 9, quick) + flow("10.0.0.8", "other", 8, quick)
    # a rate limit: most packets wait a little, the ones behind a burst wait long
    capped = flow("10.0.0.9", "srv", 9, lambda i: 0.02 if i % 10 < 7 else 0.30) + flow("10.0.0.8", "other", 8, quick)
    out = "\n".join(report(read(sorted(capped, key=tsec)), 20, read(normal)))
    assert "PACKETS WAIT AT THE SENDER'S INTERFACE: srv (pid_ns 9) at 10.0.0.9: 1000 packets waited 20 ms (median) and 300 ms (p95)" in out, out
    assert "it sent 416 kbit/s; KIND: A RATE LIMIT OR A FULL QUEUE" in out and out.count("VERDICT") == 1, out
    # a fixed delay: every packet waits 150 ms, give or take
    delayed = flow("10.0.0.9", "srv", 9, lambda i: 0.13 + (i % 10) * 0.004) + flow("10.0.0.8", "other", 8, quick)
    out = "\n".join(report(read(sorted(delayed, key=tsec)), 20, read(normal)))
    assert "KIND: A FIXED DELAY (about the same for every packet: p95 is 1.1 times the median; the delay is about 150 ms)" in out, out
    out = "\n".join(report(read(normal), 20, read(normal)))
    assert "NO PACKETS WAITING AT A SENDER'S INTERFACE (longest: p95 0.01 ms" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: dev_delay.py <slice.txt> <slice_seconds> [baseline_slice.txt]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        d = read(f)
    b = None
    if len(sys.argv) > 3:
        with open(sys.argv[3], errors="replace") as f:
            b = read(f)
    print("\n".join(report(d, float(sys.argv[2]), b)))
