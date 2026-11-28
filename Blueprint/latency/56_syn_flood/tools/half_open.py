#!/usr/bin/env python3
# half_open.py - find a stream of connection attempts that are never completed.
#
# A TCP connection opens in three steps: the client sends SYN, the server answers SYN-ACK, the
# client confirms with ACK. A SYN flood sends only the first step, again and again, often from a
# false address, so the server keeps answering and waiting for confirmations that never come.
# Real clients complete almost every connection they start.
#
# For each (source address -> server address and port), from the TCP headers in the slice:
#   attempts   different connection attempts (SYN without ACK, counted once per source port and
#              sequence number, so the same packet on two interfaces counts once)
#   completed  of those, how many the source later confirmed (any segment from it on that
#              connection without the SYN flag)
#   ports      how many different server ports the source tried
#
# The server's SYN-ACKs to a false address may never be sent at all (the address cannot be
# resolved), so they are not needed. It reads the transmit events (net_dev_queue).
#
# Usage:
#   python3 half_open.py <fault_slice.txt> <secs> [baseline_slice.txt]
#   python3 half_open.py --selftest
#
#   slices: 20 s, cut with
#     extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict

MIN_RATE = 50          # connection attempts per second from one source to one server port
MAX_DONE = 0.05        # ... of which at most this share completed
MAX_PORTS = 5          # ... from a source that tried at most this many ports (more is a scan)
MAX_BASE = 0.1         # ... and the baseline has at most this share of the attempts
# Bars set before the first run on labelled data (28-11-2026), from what a SYN flood is; run 1
# was looked at first only to see that the attempts are in the trace (201,280 in 20 s).
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_ip = re.compile(r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = \d+, data_offset = \d+'
                    r', .*?flags = 0x([0-9A-Fa-f]+)')
re_dev = re.compile(r' name = "([^"]*)"')


def read(lines):
    tries = defaultdict(set)                     # (src, dst, dport) -> {(sport, seq)}
    done = defaultdict(set)                      # (src, dst, dport) -> {sport} confirmed
    devs = defaultdict(lambda: defaultdict(int))
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp:
            continue
        s, d = ".".join(ip.groups()[0:4]), ".".join(ip.groups()[4:8])
        sp, dp, fl = tcp.group(1), tcp.group(2), int(tcp.group(4), 16)
        k = (s, d, dp)
        if fl & 0x12 == 0x02:
            tries[k].add((sp, tcp.group(3)))
            dv = re_dev.search(line)
            if dv:
                devs[s][dv.group(1)] += 1
        elif not fl & 0x02 and k in tries:
            done[k].add(sp)
    return tries, done, devs


def report(data, secs, base=None):
    tries, done, devs = data
    btries = base[0] if base else {}
    ports = defaultdict(set)
    for (s, d, dp) in tries:
        ports[s].add((d, dp))
    rows = []
    for k, t in tries.items():
        sports = {sp for sp, _ in t}
        rows.append((k, len(t), len(done[k] & sports) / max(1, len(sports)), len(ports[k[0]]), len(btries.get(k, ()))))
    rows.sort(key=lambda r: -r[1])
    out = [f"Connection attempts per source and server port in this {secs:.0f} s slice (most first)",
           f"  {'source':<16} {'server':<22} {'attempts':>9} {'per s':>7} {'completed':>10} {'ports tried':>12} {'before':>7}"]
    for k, n, share, np, b in rows[:10]:
        out.append(f"  {k[0]:<16} {k[1] + ':' + k[2]:<22} {n:>9} {n / secs:>7.0f} {share:>10.0%} {np:>12} {b if base else '-':>7}")
    out.append("  completed = attempts the source later confirmed; ports tried = different server ports from that source; before = the baseline slice")
    hits = 0
    for k, n, share, np, b in rows:
        if n / secs < MIN_RATE or share > MAX_DONE or np > MAX_PORTS or (base and b > MAX_BASE * n):
            continue
        dv = ", ".join(sorted(devs[k[0]], key=lambda x: -devs[k[0]][x])[:2])
        out.append(f"VERDICT: CONNECTION ATTEMPTS ARE NEVER COMPLETED: {k[0]} tried to connect to {k[1]}:{k[2]} {n} times in {secs:.0f} s "
                   f"({n / secs:.0f} per second) and completed {share:.0%} of them" + (f"; {b} attempts in the baseline" if base else "")
                   + f"; seen on {dv} - half-open connections, a SYN flood on {k[1]}:{k[2]}")
        hits += 1
    if not hits:
        why = (f"most: {rows[0][1]} attempts from {rows[0][0][0]} to {rows[0][0][1]}:{rows[0][0][2]}, {rows[0][2]:.0%} completed" if rows
               else "no connection attempt in the slice")
        out.append(f"VERDICT: NO HALF-OPEN FLOOD ({why}; the bars are {MIN_RATE} attempts per second to one port, at most {MAX_DONE:.0%} "
                   f"completed, at most {MAX_PORTS} ports, baseline at most {MAX_BASE:.0%} of it)")
    return out


def selftest():
    def seg(t, src, sp, dst, dp, flags, seq, dev="eth0"):
        a, b = src.split("."), dst.split(".")
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, procname = "x", pid_ns = 1 }}, '
                f'{{ skbaddr = 0x1, len = 74, name = "{dev}", network_header = {{ ipv4 = {{ version = 4, ihl = 5, tot_len = 60, '
                f'saddr = [ [0] = {a[0]}, [1] = {a[1]}, [2] = {a[2]}, [3] = {a[3]} ], daddr = [ [0] = {b[0]}, [1] = {b[1]}, [2] = {b[2]}, [3] = {b[3]} ], '
                f'transport_header = {{ tcp = {{ source_port = {sp}, dest_port = {dp}, seq = {seq}, ack_seq = 0, data_offset = 10, reserved = 0, '
                f'flags = {flags}, window_size = 500, checksum = 0x1, urg_ptr = 0 }} }} }} }} }}')

    normal = []
    for i in range(1500):                        # real clients: every connection is completed
        normal += [seg(i * 0.01, "10.0.0.7", 30000 + i, "10.0.0.10", 3306, "0x02", 5 * i),
                   seg(i * 0.01 + 0.0002, "10.0.0.10", 3306, "10.0.0.7", 30000 + i, "0x12", 9),
                   seg(i * 0.01 + 0.0003, "10.0.0.7", 30000 + i, "10.0.0.10", 3306, "0x10", 5 * i + 1)]
    flood = list(normal)
    for i in range(40000):                       # 2,000 attempts per second, each seen on two interfaces
        for dev in ("br0", "veth5"):
            flood.append(seg(1 + i * 0.0004, "10.0.0.250", 1024 + i % 60000, "10.0.0.5", 8079, "0x02", 77 * i, dev))
    out = "\n".join(report(read(flood), 20, read(normal)))
    assert "CONNECTION ATTEMPTS ARE NEVER COMPLETED: 10.0.0.250 tried to connect to 10.0.0.5:8079 40000 times in 20 s (2000 per second) and completed 0% of them; 0 attempts in the baseline; seen on br0, veth5" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(normal), 20, read(normal)))
    assert "NO HALF-OPEN FLOOD (most: 1500 attempts from 10.0.0.7 to 10.0.0.10:3306, 100% completed" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: half_open.py <fault_slice.txt> <secs> [baseline_slice.txt]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        d = read(f)
    b = None
    if len(sys.argv) > 3:
        with open(sys.argv[3], errors="replace") as f:
            b = read(f)
    print("\n".join(report(d, float(sys.argv[2]), b)))
