#!/usr/bin/env python3
# scan_fanout.py - find one address that tries to connect to very many different ports.
#
# A service talks to a few peers on a few ports, again and again. A port scan is the opposite:
# one source, hundreds of different destination ports, each tried once, almost all refused.
# It uses no CPU and moves no data, so nothing else shows it.
#
# For each source address, from the connection attempts (SYN packets) in the slice:
#   targets   different (address, port) pairs it tried
#   ports     different destination ports
#   hosts     different destination addresses
#   refused   share of the targets that answered with a reset
#
# It reads the transmit events (net_dev_queue).
#
# Usage:
#   python3 scan_fanout.py <slice.txt> <slice_seconds> [baseline_slice.txt]
#   python3 scan_fanout.py --selftest
#
#   slices: 20 s or more, cut with
#     extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict

MIN_TARGETS = 200      # different (address, port) pairs tried by one source in the slice
MIN_PORTS = 50         # ... on at least this many different ports
MIN_RISE = 10.0        # ... and this many times its targets in the baseline (when a baseline is given)
# Bars set before the first run on labelled data (25-11-2026) and not fitted to it.
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_ip = re.compile(r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = \d+, ack_seq = \d+, data_offset = \d+'
                    r'(?:, .*?flags = 0x([0-9A-Fa-f]+))?')


def read(lines):
    tried = defaultdict(set)                     # source ip -> {(dst ip, dst port)}
    reset = defaultdict(set)                     # source ip -> targets that answered with a reset
    votes = defaultdict(lambda: defaultdict(int))
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp or not tcp.group(3):
            continue
        fl = int(tcp.group(3), 16)
        src, dst = ".".join(ip.groups()[0:4]), ".".join(ip.groups()[4:8])
        if fl & 0x12 == 0x02:                    # SYN without ACK: a connection attempt
            tried[src].add((dst, int(tcp.group(2))))
            cx = re_ctx.search(line)
            if cx and not cx.group(3).startswith(KERNEL_CTX):
                pn = re_pidns.search(line)
                votes[src][(cx.group(3), pn.group(1) if pn else "?")] += 1
        elif fl & 0x04:                          # RST from the target back to the source
            reset[dst].add((src, int(tcp.group(1))))
    who = {ip: max(v, key=v.get) for ip, v in votes.items()}
    return tried, reset, who


def report(data, secs, base=None):
    tried, reset, who = data
    btried = base[0] if base else {}
    rows = sorted(tried.items(), key=lambda kv: -len(kv[1]))
    out = [f"Connection attempts per source address in this {secs:.0f} s slice (most targets first)",
           f"  {'source':<16} {'targets':>8} {'ports':>6} {'hosts':>6} {'refused':>8} {'targets before':>15}  program"]
    for ip, t in rows[:10]:
        nm = who.get(ip, ("?", "?"))
        out.append(f"  {ip:<16} {len(t):>8} {len({p for _, p in t}):>6} {len({h for h, _ in t}):>6} "
                   f"{len(reset[ip] & t) / max(1, len(t)):>8.0%} {len(btried.get(ip, ())) if base else '-':>15}  {nm[0]} (pid_ns {nm[1]})")
    out.append("  targets = different (address, port) pairs tried; refused = share of them that answered with a reset; before = the baseline slice")
    hits = 0
    for ip, t in rows:
        ports, hosts = {p for _, p in t}, {h for h, _ in t}
        b = len(btried.get(ip, ())) if base else 0
        if len(t) < MIN_TARGETS or len(ports) < MIN_PORTS or (base and len(t) < MIN_RISE * max(1, b)):
            continue
        nm = who.get(ip, ("?", "?"))
        out.append(f"VERDICT: ONE SOURCE TRIES MANY PORTS: {ip} tried {len(t)} different address-and-port pairs in {secs:.0f} s "
                   f"({len(ports)} ports on {len(hosts)} addresses, {len(t) / secs:.0f} per second), "
                   f"{len(reset[ip] & t) / len(t):.0%} refused" + (f", {b} pairs in the baseline" if base else "")
                   + f"; the packets were sent by {nm[0]} (pid_ns {nm[1]}) - a port scan from that address")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"most: {len(top[1])} pairs on {len({p for _, p in top[1]})} ports from {top[0]}" if top else "no connection attempt in the slice")
        out.append(f"VERDICT: NO SOURCE TRIES MANY PORTS ({why}; the bars are {MIN_TARGETS} pairs, {MIN_PORTS} ports, {MIN_RISE:.0f}x the baseline)")
    return out


def selftest():
    def seg(t, src, sp, dst, dp, flags, comm="app", ns=7):
        a, b = src.split("."), dst.split(".")
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, procname = "{comm}", pid_ns = {ns} }}, '
                f'{{ skbaddr = 0x1, len = 74, name = "eth0", network_header = {{ ipv4 = {{ version = 4, ihl = 5, tot_len = 60, '
                f'saddr = [ [0] = {a[0]}, [1] = {a[1]}, [2] = {a[2]}, [3] = {a[3]} ], daddr = [ [0] = {b[0]}, [1] = {b[1]}, [2] = {b[2]}, [3] = {b[3]} ], '
                f'transport_header = {{ tcp = {{ source_port = {sp}, dest_port = {dp}, seq = 1, ack_seq = 0, data_offset = 10, reserved = 0, '
                f'flags = {flags}, window = 500 }} }} }} }} }}')

    normal = []
    for i in range(300):                         # a busy client: 300 connections, always to the same two targets
        normal.append(seg(i * 0.05, "10.0.0.3", 40000 + i, "10.0.0.9" if i % 2 else "10.0.0.8", 80, "0x02", "node", 3))
    scan = list(normal)
    for i in range(600):                         # 600 ports on 2 hosts, refused except port 80
        for h in ("10.0.0.8", "10.0.0.9"):
            scan.append(seg(1 + i * 0.01, "10.0.0.3", 50000 + i, h, 1 + i, "0x02", "python3", 1))
            if 1 + i != 80:
                scan.append(seg(1.0001 + i * 0.01, h, 1 + i, "10.0.0.3", 50000 + i, "0x14", "swapper/1", 0))
    out = "\n".join(report(read(scan), 20, read(normal)))
    assert "ONE SOURCE TRIES MANY PORTS: 10.0.0.3 tried 1200 different address-and-port pairs in 20 s (600 ports on 2 addresses, 60 per second), 100% refused, 2 pairs in the baseline" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(normal), 20, read(normal)))
    assert "NO SOURCE TRIES MANY PORTS (most: 2 pairs on 1 ports from 10.0.0.3" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: scan_fanout.py <slice.txt> <slice_seconds> [baseline_slice.txt]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        d = read(f)
    b = None
    if len(sys.argv) > 3:
        with open(sys.argv[3], errors="replace") as f:
            b = read(f)
    print("\n".join(report(d, float(sys.argv[2]), b)))
