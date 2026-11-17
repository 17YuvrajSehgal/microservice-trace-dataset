#!/usr/bin/env python3
# egress.py - find one process that pushes a lot of data ONE WAY to one destination.
#
# A bulk transfer out (a backup at the wrong time, a dump, stolen data) breaks nothing: no
# loss, no errors, normal latency. What it has is volume, direction and steadiness. Service
# traffic is request and reply, in bursts; a bulk transfer is one stream that only goes one
# way and never pauses.
#
# This tool reads the transmit events (net_dev_queue), which carry the full TCP header. It
# adds up the TCP payload per (source address -> destination address:port), compares it with
# the payload that comes back, and checks that it flows in every second of the slice.
#
# Usage:
#   python3 egress.py <net_slice.txt> <slice_seconds>
#   python3 egress.py --selftest
#
#   <net_slice.txt>  10 s or more, cut with:
#        extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict
from statistics import median

BULK_MB_S = 5.0        # a stream is "bulk" from this much payload per second
MAX_BACK = 0.01        # one-way: the payload coming back is at most this share of it
MIN_ACTIVE = 0.9       # steady: it flows in at least this share of the seconds
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
    # A packet fires net_dev_queue once per device it crosses (the sender's eth0, then the
    # host side of the receiver's veth), so bytes are added up per device and the largest
    # device is taken, not the sum.
    vol = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))   # stream -> device -> second -> bytes
    # Who owns a stream. The context of a transmit is whoever is on the CPU; the ACKs of the
    # receiver often leave in the SENDER's context (measured), so only segments that carry
    # data vote, and kernel threads never do.
    votes = defaultdict(lambda: defaultdict(int))                      # stream -> (name, pid, pid_ns) -> n
    t0 = None
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp:
            continue
        t = tsec(line)
        if t is None:
            continue
        t0 = t if t0 is None else t0
        payload = int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(3)) * 4
        if payload <= 0:
            continue
        src, dst = ".".join(ip.groups()[2:6]), ".".join(ip.groups()[6:10])
        key = (src, tcp.group(1), dst, tcp.group(2))
        d = re_dev.search(line)
        vol[key][d.group(1) if d else "?"][int(t - t0)] += payload
        c = re_ctx.search(line)
        if c and not c.group(2).startswith(KERNEL_CTX):
            pn = re_pidns.search(line)
            votes[key][(c.group(2), c.group(1), pn.group(1) if pn else "?")] += 1
    return vol, votes


def report(vol, votes, secs):
    n_sec = max(1, int(round(secs)))
    conn = {}                                    # one connection, one direction -> per-second bytes
    for key, devs in vol.items():
        conn[key] = max(devs.values(), key=lambda b: sum(b.values()))
    # A stream = every connection from one address to one destination address:port, so a
    # transfer split over parallel connections is still one row.
    streams = defaultdict(lambda: {"sec": defaultdict(int), "back": 0, "who": defaultdict(int), "conns": 0})
    for (src, sport, dst, dport), sec in conn.items():
        s = streams[(src, dst, dport)]
        s["conns"] += 1
        for k, b in sec.items():
            s["sec"][k] += b
        s["back"] += sum(conn.get((dst, dport, src, sport), {}).values())
        for w, n in votes.get((src, sport, dst, dport), {}).items():
            s["who"][w] += n
    rows = []
    for (src, dst, dport), s in streams.items():
        total = sum(s["sec"].values())
        per = [s["sec"].get(k, 0) for k in range(n_sec)]
        med = median(per)
        active = sum(1 for b in per if b > 0.1 * med and b > 0) / n_sec
        who = max(s["who"], key=s["who"].get) if s["who"] else ("?", "?", "?")
        rows.append((total / secs / 1e6, s["back"] / total, active, who, src, dst, dport, s["conns"]))
    rows.sort(reverse=True)
    all_mb = sum(r[0] for r in rows)
    out = [f"TCP payload sent in this {secs:.0f} s slice: {all_mb:.1f} MB/s over {len(rows)} streams "
           f"(a stream = one source address to one destination address:port)",
           f"  {'MB/s':>7} {'back':>6} {'active':>7}  {'sender':<34}{'from':<16}{'to':<24}{'conns':>5}"]
    for mb, back, active, who, src, dst, dport, nc in rows[:8]:
        out.append(f"  {mb:>7.2f} {back:>6.1%} {active:>7.0%}  "
                   f"{(f'{who[0]} (pid {who[1]})'):<34}{src:<16}{(dst + ':' + dport):<24}{nc:>5}")
    out.append("  back = payload coming back on the same connections, as a share of the payload sent; "
               "active = share of the seconds in which the stream flows")
    oneway = [r for r in rows if r[1] <= MAX_BACK and r[2] >= MIN_ACTIVE]
    bulk = [r for r in oneway if r[0] >= BULK_MB_S]
    if bulk:
        mb, back, active, who, src, dst, dport, nc = bulk[0]
        out.append(f"VERDICT: BULK ONE-WAY TRANSFER: {who[0]} (pid {who[1]}, pid_ns {who[2]}) sends "
                   f"{mb:.1f} MB/s from {src} to {dst}:{dport}, {back:.1%} comes back, flows in "
                   f"{active:.0%} of the seconds, {mb / all_mb:.0%} of all TCP payload in the slice")
    else:
        top = (f"largest steady one-way stream: {oneway[0][0]:.2f} MB/s by {oneway[0][3][0]} to "
               f"{oneway[0][5]}:{oneway[0][6]}") if oneway else "no steady one-way stream at all"
        out.append(f"VERDICT: NO BULK ONE-WAY TRANSFER ({top}; the bar is {BULK_MB_S:.0f} MB/s)")
    return out


def selftest():
    def q(t, pid, nm, src, sport, dst, dport, payload, dev="eth0"):
        s, d = src.split("."), dst.split(".")
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = {pid}, tid = {pid}, '
                f'procname = "{nm}", pid_ns = 77, net_ns = 1 }}, {{ skbaddr = 0x1, len = 1, name = "{dev}", '
                f'network_header = {{ {{ version = 4, ihl = 5, tos = 0, tot_len = {payload + 52}, id = 0x1, '
                f'saddr = [ [0] = {s[0]}, [1] = {s[1]}, [2] = {s[2]}, [3] = {s[3]} ], '
                f'daddr = [ [0] = {d[0]}, [1] = {d[1]}, [2] = {d[2]}, [3] = {d[3]} ], transport_header = {{ {{ '
                f'source_port = {sport}, dest_port = {dport}, seq = 1, ack_seq = 1, data_offset = 8, flags = 0x18 }} }} }} }} }}')

    lines = []
    for i in range(1000):                                    # 10 s, 100 segments/s of 60 kB = 6 MB/s
        t = i * 0.01
        for dev in ("eth0", "veth1"):                        # the same packet on two devices
            lines.append(q(t, 100, "mover", "10.0.0.1", 40000, "10.0.0.2", 9000, 60000, dev))
        lines.append(q(t, 100, "mover", "10.0.0.2", 9000, "10.0.0.1", 40000, 0))        # ACK in the sender's context
        lines.append(q(t, 200, "svc", "10.0.0.3", 41000, "10.0.0.4", 80, 80000))        # 8 MB/s request ...
        lines.append(q(t, 300, "web", "10.0.0.4", 80, "10.0.0.3", 41000, 80000))        # ... and reply
    lines += [q(0.5 + i * 0.001, 400, "burst", "10.0.0.5", 42000, "10.0.0.6", 22, 60000) for i in range(1000)]  # 6 MB/s, 1 s only
    out = "\n".join(report(*read(lines), 10.0))
    assert "BULK ONE-WAY TRANSFER: mover (pid 100, pid_ns 77) sends 6.0 MB/s" in out, out
    out = "\n".join(report(*read([l for l in lines if '"mover"' not in l]), 10.0))
    assert "NO BULK ONE-WAY TRANSFER (no steady one-way stream" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: egress.py <net_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        vol, votes = read(f)
    print("\n".join(report(vol, votes, float(sys.argv[2]))))
