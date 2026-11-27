#!/usr/bin/env python3
# conn_rate.py - find a client that opens a new connection for every call.
#
# Services keep connections open and send many calls over each one. A client that has
# keep-alive switched off opens a connection, sends one call, gets one answer and closes it,
# again and again. Every call then pays for a handshake and a close, and both sides spend
# kernel time on connections that live for a few milliseconds. Nothing fails.
#
# For each (client address -> server address and port), from the TCP headers in the slice:
#   opened    connections the client opened (SYN)
#   calls     data segments the client sent on those connections, per connection (median)
#   closed    share of them that the client or server closed normally (FIN), and reset (RST)
#
# It reads the transmit events (net_dev_queue).
#
# Usage:
#   python3 conn_rate.py <slice.txt> <slice_seconds> [baseline_slice.txt]
#   python3 conn_rate.py --selftest
#
#   slices: 20 s or more, cut with
#     extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict

MIN_RATE = 50          # connections opened per second from one client to one server port
MIN_RISE = 10.0        # ... and this many times the baseline (when a baseline is given)
MAX_CALLS = 2          # ... each carrying at most this many data segments from the client (median)
MIN_FIN = 0.8          # ... and at least this share closed normally
MAX_RST = 0.1          # ... and at most this share reset (a reset storm is another problem)
# Bars set before the first run on labelled data (27-11-2026) and not fitted to it.
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = \d+, data_offset = (\d+)'
                    r', .*?flags = 0x([0-9A-Fa-f]+)')


def read(lines):
    conns = defaultdict(dict)                    # (client, server, server port) -> {client port: [data seqs, fin, rst]}
    votes = defaultdict(lambda: defaultdict(int))
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp:
            continue
        src, dst = ".".join(ip.groups()[2:6]), ".".join(ip.groups()[6:10])
        sp, dp, fl = tcp.group(1), tcp.group(2), int(tcp.group(5), 16)
        if fl & 0x12 == 0x02:                    # SYN without ACK: the client opens a connection
            conns[(src, dst, dp)].setdefault(sp, [set(), False, False])
            cx = re_ctx.search(line)
            if cx and not cx.group(3).startswith(KERNEL_CTX):
                pn = re_pidns.search(line)
                votes[src][(cx.group(3), pn.group(1) if pn else "?")] += 1
            continue
        c = conns.get((src, dst, dp), {}).get(sp)            # a segment from the client
        if c is not None and int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(4)) * 4 > 0:
            c[0].add(tcp.group(3))               # a set: the same segment is seen on every interface
        if c is None:
            c = conns.get((dst, src, sp), {}).get(dp)        # a segment from the server
        if c is not None:
            c[1] = c[1] or bool(fl & 0x01)
            c[2] = c[2] or bool(fl & 0x04)
    who = {ip: max(v, key=v.get) for ip, v in votes.items()}
    return conns, who


def med(x):
    x = sorted(x)
    return x[len(x) // 2] if x else 0


def report(data, secs, base=None):
    conns, who = data
    bconns = base[0] if base else {}
    rows = sorted(conns.items(), key=lambda kv: -len(kv[1]))
    out = [f"Connections opened per client and server port in this {secs:.0f} s slice (most first)",
           f"  {'client':<16} {'server':<22} {'opened/s':>9} {'calls each':>11} {'closed':>7} {'reset':>6} {'per s before':>13}  program"]
    stats = []
    for (src, dst, port), c in rows:
        n = len(c)
        s = (n / secs, med([len(v[0]) for v in c.values()]), sum(v[1] for v in c.values()) / n, sum(v[2] for v in c.values()) / n,
             len(bconns.get((src, dst, port), ())) / secs if base else 0.0)
        stats.append(((src, dst, port), s))
    for (src, dst, port), s in stats[:10]:
        nm = who.get(src, ("?", "?"))
        out.append(f"  {src:<16} {dst + ':' + port:<22} {s[0]:>9.1f} {s[1]:>11} {s[2]:>7.0%} {s[3]:>6.0%} "
                   f"{s[4] if base else '-':>13}  {nm[0]} (pid_ns {nm[1]})")
    out.append("  calls each = data segments from the client per connection (median); closed = ended with FIN; before = the baseline slice")
    hits = 0
    for (src, dst, port), s in stats:
        if s[0] < MIN_RATE or s[1] > MAX_CALLS or s[2] < MIN_FIN or s[3] > MAX_RST or (base and s[0] < MIN_RISE * max(0.1, s[4])):
            continue
        nm = who.get(src, ("?", "?"))
        out.append(f"VERDICT: A NEW CONNECTION FOR EVERY CALL: {src} ({nm[0]}, pid_ns {nm[1]}) opened {s[0]:.0f} connections per second "
                   f"to {dst}:{port}" + (f", {s[4]:.1f} per second in the baseline" if base else "")
                   + f"; each carried {s[1]} data segment(s) from the client (median), {s[2]:.0%} were closed normally and "
                   f"{s[3]:.0%} reset - connections are not reused (keep-alive is off)")
        hits += 1
    if not hits:
        why = (f"most: {stats[0][1][0]:.1f} per second from {stats[0][0][0]} to {stats[0][0][1]}:{stats[0][0][2]}, "
               f"{stats[0][1][1]} calls each, {stats[0][1][3]:.0%} reset" if stats else "no connection was opened in the slice")
        out.append(f"VERDICT: NO CONNECTION CHURN ({why}; the bars are {MIN_RATE} per second, {MIN_RISE:.0f}x the baseline, at most "
                   f"{MAX_CALLS} calls each, {MIN_FIN:.0%} closed normally, at most {MAX_RST:.0%} reset)")
    return out


def selftest():
    def seg(t, src, sp, dst, dp, flags, length=52, seq=1, comm="app", ns=7, dev="eth0"):
        a, b = src.split("."), dst.split(".")
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, procname = "{comm}", pid_ns = {ns} }}, '
                f'{{ skbaddr = 0x1, len = 74, name = "{dev}", network_header = {{ ipv4 = {{ version = 4, ihl = 5, tot_len = {length}, '
                f'saddr = [ [0] = {a[0]}, [1] = {a[1]}, [2] = {a[2]}, [3] = {a[3]} ], daddr = [ [0] = {b[0]}, [1] = {b[1]}, [2] = {b[2]}, [3] = {b[3]} ], '
                f'transport_header = {{ tcp = {{ source_port = {sp}, dest_port = {dp}, seq = {seq}, ack_seq = 1, data_offset = 8, reserved = 0, '
                f'flags = {flags}, window = 500 }} }} }} }} }}')

    def conn(t, cp, calls, end="0x11", client="10.0.0.3", comm="node"):
        o = [seg(t, client, cp, "10.0.0.9", 80, "0x02", comm=comm, ns=3)]
        for k in range(calls):
            for dev in ("eth0", "br0"):          # the same data segment on two interfaces
                o.append(seg(t + 0.001 * (k + 1), client, cp, "10.0.0.9", 80, "0x18", 300, seq=100 + k, comm=comm, ns=3, dev=dev))
        o.append(seg(t + 0.02, "10.0.0.9", 80, client, cp, end, comm="app", ns=4))
        return o

    pooled = []
    for i in range(5):                           # 5 long connections with 200 calls each
        pooled += conn(0.1 * i, 40000 + i, 200)
    churn = list(pooled)
    for i in range(2000):                        # 100 connections per second, one call each
        churn += conn(i * 0.01, 50000 + i % 9000, 1)
    out = "\n".join(report(read(churn), 20, read(pooled)))
    assert "A NEW CONNECTION FOR EVERY CALL: 10.0.0.3 (node, pid_ns 3) opened 100 connections per second to 10.0.0.9:80, 0.2 per second in the baseline; each carried 1 data segment(s) from the client (median), 100% were closed normally and 0% reset" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(pooled), 20, read(pooled)))
    assert "NO CONNECTION CHURN (most: 0.2 per second from 10.0.0.3 to 10.0.0.9:80, 200 calls each" in out, out
    storm = []                                   # connections that the server resets: another problem
    for i in range(2000):
        storm += conn(i * 0.01, 50000 + i % 9000, 1, end="0x14")
    out = "\n".join(report(read(storm), 20, read(pooled)))
    assert "NO CONNECTION CHURN" in out and "100% reset" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: conn_rate.py <slice.txt> <slice_seconds> [baseline_slice.txt]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        d = read(f)
    b = None
    if len(sys.argv) > 3:
        with open(sys.argv[3], errors="replace") as f:
            b = read(f)
    print("\n".join(report(d, float(sys.argv[2]), b)))
