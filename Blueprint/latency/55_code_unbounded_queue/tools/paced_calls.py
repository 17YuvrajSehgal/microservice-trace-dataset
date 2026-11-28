#!/usr/bin/env python3
# paced_calls.py - find a client whose calls to a service leave on a clock.
#
# Calls from a service to its dependencies normally leave when its requests arrive: in bursts,
# with gaps of every length. A client that puts its calls in a queue and releases them from a
# timer (a throttle, a batcher, a worker that wakes every N ms) sends them on that clock instead:
# many gaps between calls are close to one length, the timer's period. When the queue is not
# empty, every tick sends some calls; so the gaps of that one length become common.
#
# For each (client -> server:port) pair with enough calls, in the suspect and the baseline slice:
#   peak      the most common gap length between 2 and 50 ms (1 ms steps)
#   share     the share of all gaps that fall within 1.5 ms of the peak
#   before    the share of the baseline's gaps in the same band
#
# A call starts with a data segment from the client on a connection with no call pending
# (the same rule as call_fanout.py). It reads the transmit events (net_dev_queue).
#
# WHAT IT CANNOT SEE. A queue served by a pool of workers that never sleep has no clock, and this
# tool does not see it. It also does not say how long the queue is: read the client's own answer
# time for that.
#
# Usage:
#   python3 paced_calls.py <fault_slice.txt> <secs> <baseline_slice.txt>
#   python3 paced_calls.py --selftest
#
#   slices: 20 s, cut with
#     extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict

MIN_CALLS = 1000       # a pair is judged only if it has this many calls in the slice
MIN_SHARE = 0.12       # the band around the peak holds at least this share of the gaps
MIN_RISE = 3.0         # ... and this many times the baseline's share in the same band
BAND_MS = 1.5          # half-width of the band around the peak
MIN_PEAK_MS = 4        # a clock is looked for between this and 50 ms
MIN_BUMP = 2.0         # the peak's 1 ms bin holds at least this many times the bin 3 ms below it
# Bars set before testing on runs 2-5 (27-11-2026). What was seen first: on run 1 and 2 of
# code_unbounded_queue the gaps of 8.5-12 ms from the front-end to the catalogue went from 4-6%
# to 19-21%, and stayed at 5-9% in two other families.
# CHANGED AFTER THE 70-RUN TEST (28-11-2026): the server is now the side whose port is below 32768 and the
# client the side at 32768 or above (Linux gives clients ports from 32768). The first version took whichever
# side sent first in the slice as the client; on connections already open when the slice starts that is often
# the server, and it named ephemeral ports as servers.
# Also changed then: the peak is looked for from 4 ms (not 2) and must be a bump (MIN_BUMP). Busy traffic has
# most gaps short, so its most common gap is the shortest one; the first version called that a 2 ms clock
# (traefik to the front-end, in one reversed run).
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = \d+, data_offset = (\d+)')


def tsec(line):
    m = re_time.match(line)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1e9 if m else None


def read(lines):
    starts = defaultdict(list)                   # (client, server, port) -> call start times
    pend = {}
    seen = set()
    servers = set()                              # (address, port) pairs that answer
    votes = defaultdict(lambda: defaultdict(int))
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp or int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(4)) * 4 <= 0:
            continue
        s, d = ".".join(ip.groups()[2:6]), ".".join(ip.groups()[6:10])
        sp, dp, seq = tcp.group(1), tcp.group(2), tcp.group(3)
        to_server, from_server = int(sp) >= 32768 > int(dp), int(dp) >= 32768 > int(sp)
        if not to_server and not from_server:
            continue
        if (s, sp, seq) in seen:                 # the same segment on its next interface, or a resend
            continue
        seen.add((s, sp, seq))
        cx = re_ctx.search(line)
        if cx and not cx.group(3).startswith(KERNEL_CTX):
            pn = re_pidns.search(line)
            votes[s][(cx.group(3), pn.group(1) if pn else "?")] += 1
        if from_server:                          # an answer from the server ends the pending call
            if (d, dp, s, sp) in pend:
                pend[(d, dp, s, sp)] = False
                servers.add((s, sp))
            continue
        if not pend.get((s, sp, d, dp)):
            t = tsec(line)
            if t is not None:
                starts[(s, d, dp)].append(t)
                pend[(s, sp, d, dp)] = True
    who = {ip: max(v, key=v.get) for ip, v in votes.items()}
    return {k: sorted(v) for k, v in starts.items() if (k[1], k[2]) in servers}, who


def gaps(ts):
    return [(b - a) * 1e3 for a, b in zip(ts, ts[1:])]


def report(data, secs, base):
    starts, who = data
    bstarts = base[0]
    rows = []
    for k, ts in starts.items():
        if len(ts) < MIN_CALLS:
            continue
        g = gaps(ts)
        hist = defaultdict(int)
        for x in g:
            if 1 <= x < 50:
                hist[int(x)] += 1
        cand = [b for b in hist if b >= MIN_PEAK_MS]
        if not cand:
            continue
        pb = max(cand, key=hist.get)
        bump = hist[pb] / max(1, hist.get(pb - 3, 0))
        peak = pb + 0.5
        lo, hi = peak - BAND_MS, peak + BAND_MS
        share = sum(1 for x in g if lo <= x < hi) / len(g)
        bg = gaps(bstarts.get(k, []))
        bshare = sum(1 for x in bg if lo <= x < hi) / len(bg) if bg else 0.0
        rows.append((k, len(ts), peak, share, bshare, len(bg), bump))
    rows.sort(key=lambda r: -(r[3] / max(r[4], 0.01)))
    out = [f"Gaps between calls per client and server in this {secs:.0f} s slice (pairs with {MIN_CALLS} calls or more)",
           f"  {'client':<15} {'server':<21} {'calls':>6} {'peak gap ms':>12} {'share':>6} {'before':>7}  client program"]
    for k, n, peak, share, bshare, nb, bump in rows[:10]:
        nm = who.get(k[0], ("?", "?"))
        out.append(f"  {k[0]:<15} {k[1] + ':' + k[2]:<21} {n:>6} {peak:>12.1f} {share:>6.0%} {bshare:>7.0%}  {nm[0]} (pid_ns {nm[1]})")
    out.append(f"  peak = the most common gap from {MIN_PEAK_MS} to 50 ms; share = gaps within {BAND_MS} ms of it; before = the same band in the baseline")
    hits = 0
    for k, n, peak, share, bshare, nb, bump in rows:
        if share < MIN_SHARE or nb < 10 or share < MIN_RISE * bshare or bump < MIN_BUMP:
            continue
        nm = who.get(k[0], ("?", "?"))
        out.append(f"VERDICT: CALLS LEAVE ON A CLOCK: {k[0]} ({nm[0]}, pid_ns {nm[1]}) sent {n} calls to {k[1]}:{k[2]} in {secs:.0f} s and "
                   f"{share:.0%} of the gaps between them are {peak - BAND_MS:.1f} to {peak + BAND_MS:.1f} ms, {bshare:.0%} in the baseline - "
                   f"the client releases its calls from a timer of about {peak:.0f} ms (a queue, a throttle or a batcher)")
        hits += 1
    if not hits:
        why = (f"most: {rows[0][3]:.0%} of gaps near {rows[0][2]:.1f} ms from {rows[0][0][0]} to {rows[0][0][1]}:{rows[0][0][2]}, "
               f"{rows[0][4]:.0%} before" if rows else "no pair with enough calls")
        out.append(f"VERDICT: NO PACED CALLS ({why}; the bars are {MIN_SHARE:.0%} of the gaps in one band, {MIN_RISE:.0f}x the baseline, a peak of {MIN_BUMP:.0f}x the bin 3 ms below)")
    return out


def selftest():
    import random
    rnd = random.Random(7)

    def seg(t, src, sp, dst, dp, seq, comm="node", ns=5, length=200):
        a, b = src.split("."), dst.split(".")
        h, m = divmod(int(t), 60)
        return (f'[10:{h:02d}:{m:02d}.{int((t % 1) * 1e9):09d}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, '
                f'procname = "{comm}", pid_ns = {ns} }}, {{ skbaddr = 0x1, len = 74, name = "eth0", network_header = {{ ipv4 = {{ '
                f'version = 4, ihl = 5, tot_len = {length}, saddr = [ [0] = {a[0]}, [1] = {a[1]}, [2] = {a[2]}, [3] = {a[3]} ], '
                f'daddr = [ [0] = {b[0]}, [1] = {b[1]}, [2] = {b[2]}, [3] = {b[3]} ], transport_header = {{ tcp = {{ source_port = {sp}, '
                f'dest_port = {dp}, seq = {seq}, ack_seq = 1, data_offset = 8, reserved = 0, flags = 0x18, window = 500 }} }} }} }} }}')

    def traffic(times):
        out, n = [], 0
        for t in times:
            n += 1
            port = 40000 + n % 20
            out += [seg(t, "10.0.0.5", port, "10.0.0.7", 80, n), seg(t + 0.0008, "10.0.0.7", 80, "10.0.0.5", port, n, "app", 7)]
        return sorted(out)

    t, free = 0.0, []
    while t < 20:                                # calls when requests come: Poisson, 150 per second
        t += rnd.expovariate(150)
        free.append(t)
    tick, paced = 0.0, []
    while tick < 20:                             # a timer every 10 ms that sends 2 calls
        tick += 0.0102
        paced += [tick, tick + 0.0001]
    out = "\n".join(report(read(traffic(paced)), 20, read(traffic(free))))
    assert "VERDICT: CALLS LEAVE ON A CLOCK: 10.0.0.5 (node, pid_ns 5) sent" in out and "to 10.0.0.7:80 in 20 s and" in out, out
    assert "the client releases its calls from a timer of about 10 ms" in out and out.count("VERDICT") == 1, out
    out = "\n".join(report(read(traffic(free)), 20, read(traffic(free))))
    assert "VERDICT: NO PACED CALLS (most:" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: paced_calls.py <fault_slice.txt> <secs> <baseline_slice.txt>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        d = read(f)
    with open(sys.argv[3], errors="replace") as f:
        b = read(f)
    print("\n".join(report(d, float(sys.argv[2]), b)))
