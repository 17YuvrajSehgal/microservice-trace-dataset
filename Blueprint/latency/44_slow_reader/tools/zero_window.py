#!/usr/bin/env python3
# zero_window.py - find a peer that reads so slowly that the sender has to stop.
#
# Every TCP segment tells the other side how much more data the sender of that segment can
# take: its receive window. A reader that does not read fills its buffer and then advertises a
# window of ZERO. The other side must stop sending and keep the rest of the data until the
# window opens again. Nothing is lost and nothing is slow on the network: one side simply does
# not take the data.
#
# For each address, from the TCP headers in the slice:
#   zero      segments it sent with a window of zero (resets and connection attempts left out)
#   conns     different connections those were on
#   to        the address and port that had to stop sending
#
# It reads the transmit events (net_dev_queue).
#
# Usage:
#   python3 zero_window.py <slice.txt> <slice_seconds> [baseline_slice.txt]
#   python3 zero_window.py --selftest
#
#   slices: 20 s or more, cut with
#     extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict

MIN_ZERO = 50          # zero-window segments from one address to one server port in the slice
MIN_CONNS = 10         # ... on at least this many connections
MAX_BASE = 0.1         # ... and the baseline has at most this share of them
# Bars set before the first run on labelled data (27-11-2026) and not fitted to it.
# (The first version read a field called `window`; in the trace it is `window_size`, so run 1 showed
# nothing at all. Only the field name was changed. Run 1 also named the wrong program for the
# reader, because every packet from its address voted; and the reader's address is shared by several programs on
# the host. The tool now names the reader by address and interface. It also prints which program was
# running when the stopped side sent its next data: between containers on one host that is the reader
# itself, because its read opens the window and the kernel sends the waiting data at once.)
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_dev = re.compile(r' name = "([^"]*)"')
re_ip = re.compile(r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = (\d+), data_offset = \d+'
                    r', .*?flags = 0x([0-9A-Fa-f]+), window_size = (\d+)')


def read(lines):
    zero = defaultdict(set)                      # (reader ip, sender ip, sender port) -> {(reader port, seq, ack)}
    votes = defaultdict(lambda: defaultdict(int))
    devs = defaultdict(dict)                     # the interfaces the zero-window segments were seen on
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp:
            continue
        src, dst = ".".join(ip.groups()[0:4]), ".".join(ip.groups()[4:8])
        fl = int(tcp.group(5), 16)
        # Who sends from this address: only a connection attempt or a data push is sent while the
        # program itself is running. An ACK is sent from wherever the kernel happened to be.
        cx = re_ctx.search(line)
        if cx and (fl & 0x08 or fl & 0x12 == 0x02) and not cx.group(3).startswith(KERNEL_CTX):
            pn = re_pidns.search(line)
            votes[(src, tcp.group(1), dst, tcp.group(2))][(cx.group(3), pn.group(1) if pn else "?")] += 1
        if tcp.group(6) != "0" or fl & 0x06:     # not zero, or a reset or a connection attempt
            continue
        # the same segment is seen on every interface it crosses: count it once
        zero[(src, dst, tcp.group(2))].add((tcp.group(1), tcp.group(3), tcp.group(4)))
        d = re_dev.search(line)
        if d:
            devs[(src, dst, tcp.group(2))].setdefault(d.group(1), 0)
            devs[(src, dst, tcp.group(2))][d.group(1)] += 1
    return zero, votes, devs


def report(data, secs, base=None):
    zero, votes, devs = data

    def program(pairs):
        """Who sends on these connections: (address, port, peer address, peer port) tuples. An address can
        be shared by several programs (the host's bridge address is), so the vote is per connection."""
        tally = defaultdict(int)
        for c in pairs:
            for k, v in votes.get(c, {}).items():
                tally[k] += v
        return max(tally, key=tally.get) if tally else ("?", "?")
    bzero = base[0] if base else {}
    rows = sorted(zero.items(), key=lambda kv: -len(kv[1]))
    out = [f"Segments with a receive window of zero in this {secs:.0f} s slice (most first)",
           f"  {'reader':<16} {'sender that must stop':<24} {'zero':>6} {'conns':>6} {'zero before':>12}"]
    for (src, dst, port), segs in rows[:10]:
        out.append(f"  {src:<16} {dst + ':' + port:<24} {len(segs):>6} {len({s[0] for s in segs}):>6} "
                   f"{len(bzero.get((src, dst, port), ())) if base else '-':>12}")
    out.append("  zero = segments that advertised a window of zero; conns = connections they were on; before = the baseline slice")
    hits = 0
    for (src, dst, port), segs in rows:
        conns = len({s[0] for s in segs})
        b = len(bzero.get((src, dst, port), ())) if base else 0
        if len(segs) < MIN_ZERO or conns < MIN_CONNS or (base and b > MAX_BASE * len(segs)):
            continue
        ports = {s[0] for s in segs}
        sd = program([(dst, port, src, sp) for sp in ports])
        dv = ", ".join(sorted(devs[(src, dst, port)], key=lambda k: -devs[(src, dst, port)][k])[:2])
        out.append(f"VERDICT: A PEER READS TOO SLOWLY: {src} advertised a receive window of zero {len(segs)} times in {secs:.0f} s "
                   f"on {conns} connections to {dst}:{port} (seen on {dv})"
                   + (f", {b} in the baseline" if base else "")
                   + f" - {dst} has data to send and must wait for {src} to read; its next data left while {sd[0]} "
                   f"(pid_ns {sd[1]}) was running, which on one host is the program that just read")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"most: {len(top[1])} from {top[0][0]} to {top[0][1]}:{top[0][2]} on {len({s[0] for s in top[1]})} connections" if top
               else "no zero window in the slice")
        out.append(f"VERDICT: NO SLOW READER ({why}; the bars are {MIN_ZERO} zero-window segments on {MIN_CONNS} connections, "
                   f"baseline at most {MAX_BASE:.0%} of it)")
    return out


def selftest():
    def seg(t, src, sp, dst, dp, flags, win, seq=1, ack=1, comm="app", ns=7, dev="eth0"):
        a, b = src.split("."), dst.split(".")
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, procname = "{comm}", pid_ns = {ns} }}, '
                f'{{ skbaddr = 0x1, len = 74, name = "{dev}", network_header = {{ ipv4 = {{ version = 4, ihl = 5, tot_len = 52, '
                f'saddr = [ [0] = {a[0]}, [1] = {a[1]}, [2] = {a[2]}, [3] = {a[3]} ], daddr = [ [0] = {b[0]}, [1] = {b[1]}, [2] = {b[2]}, [3] = {b[3]} ], '
                f'transport_header = {{ tcp = {{ source_port = {sp}, dest_port = {dp}, seq = {seq}, ack_seq = {ack}, data_offset = 8, reserved = 0, '
                f'flags = {flags}, window_size = {win}, checksum = 0x1, urg_ptr = 0 }} }} }} }} }}')

    normal = []
    for i in range(400):                         # normal traffic, and resets (which carry a zero window)
        normal.append(seg(i * 0.02, "10.0.0.3", 40000 + i % 5, "10.0.0.9", 80, "0x10", 501, ack=i, comm="node", ns=3))
        normal.append(seg(i * 0.02, "10.0.0.9", 80, "10.0.0.3", 40000 + i % 5, "0x18", 502, seq=i, comm="app", ns=4))
        normal.append(seg(i * 0.02, "10.0.0.9", 80, "10.0.0.4", 30000 + i, "0x14", 0, comm="app", ns=4))
    slow = list(normal)
    for i in range(300):                         # 30 connections, each advertising zero 10 times, seen on two interfaces
        for dev in ("br0", "veth1"):
            slow.append(seg(5 + i * 0.01, "10.0.0.1", 50000 + i % 30, "10.0.0.9", 80, "0x10", 0, ack=1000 + i, comm="traefik", ns=2, dev=dev))
    slow += [seg(4, "10.0.0.1", 50000 + i, "10.0.0.9", 80, "0x02", 500, comm="python3", ns=1) for i in range(30)]
    slow += [seg(4.5, "10.0.0.9", 80, "10.0.0.1", 50000 + i, "0x18", 502, seq=7, comm="python3", ns=1) for i in range(30)]
    out = "\n".join(report(read(slow), 20, read(normal)))
    assert "A PEER READS TOO SLOWLY: 10.0.0.1 advertised a receive window of zero 300 times in 20 s on 30 connections to 10.0.0.9:80 (seen on br0, veth1), 0 in the baseline - 10.0.0.9 has data to send and must wait for 10.0.0.1 to read; its next data left while python3 (pid_ns 1) was running" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(normal), 20, read(normal)))
    assert "NO SLOW READER (no zero window in the slice" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: zero_window.py <slice.txt> <slice_seconds> [baseline_slice.txt]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        d = read(f)
    b = None
    if len(sys.argv) > 3:
        with open(sys.argv[3], errors="replace") as f:
            b = read(f)
    print("\n".join(report(d, float(sys.argv[2]), b)))
