#!/usr/bin/env python3
# ack_stall.py - find connections that keep waiting for a delayed ACK before they send.
#
# Two TCP features that are fine alone and bad together:
#   Nagle        the sender holds a small write until its earlier data is ACKed
#   delayed ACK  the receiver holds the ACK on a timer, hoping to send it with a reply
# A request written as two small writes (header, then body) hits both: the body waits for an
# ACK that the receiver is holding back. Nothing is lost, nothing is busy. The request is
# just slow by one fixed timer, every time.
#
# In the transmit events (net_dev_queue) one stall looks like this on a connection:
#     A -> B   data                      (the first small write)
#     ... nothing for 20 ms or more ...
#     B -> A   a bare ACK, no data       (the delayed-ACK timer fired)
#     A -> B   data, right away          (the write Nagle was holding)
# The tool counts these per connection. A slow server does NOT make this pattern: there the
# silence ends with the reply, not with a bare ACK followed at once by more data from A.
#
# Usage:
#   python3 ack_stall.py <net_slice.txt> <slice_seconds>
#   python3 ack_stall.py --selftest
#
#   <net_slice.txt>  10 s or more, cut with:
#        extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict
from statistics import median

MIN_STALL_S = 0.020    # shorter silences are ordinary scheduling, not a timer
RELEASE_S = 0.002      # the held write must leave within this long after the bare ACK
MIN_STALLS = 10        # a connection needs this many stalls in the slice to count
MIN_CLUSTER = 0.8      # ... and this share of them within 10% of the median stall (one timer)
MIN_WAIT = 0.2         # ... and the connection spends this share of the slice in these stalls.
                       # Added after the sweep: one healthy run had a telemetry connection with 10
                       # stalls on one timer that cost it 4% of its time. Fault: 46-82%.
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = (\d+), '
                    r'data_offset = (\d+), .*?flags = 0x([0-9A-Fa-f]+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    # ponytail: a connection is its two address:port ends. Two containers that both talk on
    # 127.0.0.1 with the same port pair at the same time would be mixed; add net_ns if seen.
    last_pkt = {}                     # (conn, sender end) -> (seq, ack, payload) of its last packet
    prev = {}                         # conn -> (t, sender end, payload) of the last distinct packet
    pending = {}                      # conn -> (waiting end, stall seconds, t of the bare ACK)
    stalls = defaultdict(list)        # (conn, waiting end) -> [stall seconds]
    votes = defaultdict(lambda: defaultdict(int))     # end -> (name, pid, pid_ns) -> data segments
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp:
            continue
        t = tsec(line)
        if t is None:
            continue
        a = (".".join(ip.groups()[2:6]), tcp.group(1))
        b = (".".join(ip.groups()[6:10]), tcp.group(2))
        payload = int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(5)) * 4
        conn = (a, b) if a < b else (b, a)
        # the same packet shows once per device it crosses: keep the first sighting only
        sig = (tcp.group(3), tcp.group(4), payload)
        if last_pkt.get((conn, a)) == sig:
            continue
        last_pkt[(conn, a)] = sig
        if payload > 0:
            c = re_ctx.search(line)
            if c and not c.group(2).startswith(KERNEL_CTX):
                pn = re_pidns.search(line)
                votes[a][(c.group(2), c.group(1), pn.group(1) if pn else "?")] += 1
        p = pending.pop(conn, None)
        if p and payload > 0 and a == p[0] and t - p[2] <= RELEASE_S:
            stalls[(conn, a)].append(p[1])
        bare_ack = payload == 0 and int(tcp.group(6), 16) & 0x07 == 0      # no SYN, FIN, RST
        pv = prev.get(conn)
        if bare_ack and pv and pv[1] == b and pv[2] > 0 and t - pv[0] >= MIN_STALL_S:
            pending[conn] = (b, t - pv[0], t)
        prev[conn] = (t, a, payload)
    return stalls, votes


def report(stalls, votes, secs):
    rows = []
    for (conn, end), gaps in stalls.items():
        med = median(gaps)
        cluster = sum(1 for g in gaps if abs(g - med) <= 0.1 * med) / len(gaps)
        other = conn[1] if conn[0] == end else conn[0]
        v = votes.get(end)
        who = max(v, key=v.get) if v else ("?", "?", "?")
        rows.append((len(gaps), med, cluster, sum(gaps), who, end, other))
    rows.sort(reverse=True)
    out = [f"connections with at least one delayed-ACK stall in this {secs:.0f} s slice: {len(rows)} "
           f"({sum(r[0] for r in rows)} stalls)",
           f"  {'stalls':>6} {'median ms':>10} {'same timer':>11} {'waiting s':>10}  {'waiting side':<30}{'from':<24}{'to':<24}"]
    for n, med, cluster, lost, who, end, other in rows[:10]:
        out.append(f"  {n:>6} {med * 1000:>10.1f} {cluster:>11.0%} {lost:>10.2f}  "
                   f"{(f'{who[0]} (pid {who[1]})'):<30}{':'.join(end):<24}{':'.join(other):<24}")
    out.append("  same timer = share of the stalls within 10% of the median stall; "
               "waiting s = time this connection spent in these stalls")
    hit = [r for r in rows if r[0] >= MIN_STALLS and r[2] >= MIN_CLUSTER and r[3] >= MIN_WAIT * secs]
    if hit:
        n, med, cluster, lost, who, end, other = hit[0]
        same = [r for r in hit if r[4] == who and r[6][1] == other[1]]
        out.append(f"VERDICT: NAGLE + DELAYED ACK SHAPE: {who[0]} (pid {who[1]}, pid_ns {who[2]}) waits "
                   f"{med * 1000:.0f} ms for a delayed ACK before it sends, {sum(r[0] for r in same)} times on "
                   f"{len(same)} connections to port {other[1]} ({cluster:.0%} of the stalls on the worst one are "
                   f"the same timer; it spent {lost:.1f} of {secs:.0f} s waiting)")
    else:
        top = (f"most on one connection: {rows[0][0]} stalls, {rows[0][2]:.0%} on one timer, "
               f"{rows[0][3]:.2f} s waiting, by {rows[0][4][0]}" if rows else "no stall at all")
        out.append(f"VERDICT: NO NAGLE + DELAYED ACK STALLS ({top}; the bar is {MIN_STALLS} stalls with "
                   f"{MIN_CLUSTER:.0%} on one timer and {MIN_WAIT:.0%} of the slice spent waiting)")
    return out


def selftest():
    def q(t, pid, nm, src, sport, dst, dport, seq, ack, payload, flags="18", dev="lo"):
        s, d = src.split("."), dst.split(".")
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = {pid}, tid = {pid}, '
                f'procname = "{nm}", pid_ns = 77, net_ns = 1 }}, {{ skbaddr = 0x1, len = 1, name = "{dev}", '
                f'network_header = {{ {{ version = 4, ihl = 5, tos = 0, tot_len = {payload + 52}, id = 0x1, '
                f'saddr = [ [0] = {s[0]}, [1] = {s[1]}, [2] = {s[2]}, [3] = {s[3]} ], '
                f'daddr = [ [0] = {d[0]}, [1] = {d[1]}, [2] = {d[2]}, [3] = {d[3]} ], transport_header = {{ {{ '
                f'source_port = {sport}, dest_port = {dport}, seq = {seq}, ack_seq = {ack}, data_offset = 8, '
                f'reserved = 0, flags = 0x{flags}, window_size = 64 }} }} }} }} }}')

    lines = []
    for i in range(50):                                   # the stalled client: header, 100 ms, ACK, body, reply
        t, s = i * 0.11, 1000 + i * 68
        for dev in ("eth0", "veth1"):                     # every packet on two devices
            lines.append(q(t, 100, "cli", "10.0.0.1", 40000, "10.0.0.2", 9000, s, 5 + 2 * i, 4, dev=dev))
            lines.append(q(t + 0.100, 0, "swapper/1", "10.0.0.2", 9000, "10.0.0.1", 40000, 5 + 2 * i, s + 4, 0, "10", dev))
            lines.append(q(t + 0.1001, 0, "swapper/1", "10.0.0.1", 40000, "10.0.0.2", 9000, s + 4, 5 + 2 * i, 64, dev=dev))
            lines.append(q(t + 0.1002, 200, "srv", "10.0.0.2", 9000, "10.0.0.1", 40000, 5 + 2 * i, s + 68, 2, dev=dev))
    for i in range(50):                                   # a slow server: request, 100 ms, ACK, 50 ms, reply
        t, s = i * 0.2, 1000 + i * 64
        lines.append(q(t, 300, "ok", "10.0.0.3", 41000, "10.0.0.4", 80, s, 9 + 2 * i, 64))
        lines.append(q(t + 0.100, 0, "swapper/2", "10.0.0.4", 80, "10.0.0.3", 41000, 9 + 2 * i, s + 64, 0, "10"))
        lines.append(q(t + 0.150, 400, "slow", "10.0.0.4", 80, "10.0.0.3", 41000, 9 + 2 * i, s + 64, 2))
    lines.sort(key=tsec)
    out = "\n".join(report(*read(lines), 10.0))
    assert "NAGLE + DELAYED ACK SHAPE: cli (pid 100, pid_ns 77) waits 100 ms" in out, out
    assert "50 times on 1 connections to port 9000" in out, out
    assert "with at least one delayed-ACK stall in this 10 s slice: 1 (50 stalls)" in out, out
    out = "\n".join(report(*read([l for l in lines if "9000" not in l]), 10.0))
    assert "NO NAGLE + DELAYED ACK STALLS (no stall at all" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: ack_stall.py <net_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        stalls, votes = read(f)
    print("\n".join(report(stalls, votes, float(sys.argv[2]))))
