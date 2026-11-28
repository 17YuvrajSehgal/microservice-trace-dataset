#!/usr/bin/env python3
# slow_answers.py - find a dependency where SOME answers became slow while most stay fast,
# and say whether the server was working or waiting during them.
#
# When one kind of query gets expensive (a missing index, a bad plan), the database answers it
# slowly and keeps answering everything else at once. The median answer time does not move;
# only a group of long answers appears. A slow network path or a slow proxy, in contrast,
# slows every answer.
#
# For each (client -> server:port) pair with enough calls:
#   calls      calls in the slice (a data segment from the client on a connection with no call
#              pending, until the server's first answering segment: the rule of call_fanout.py)
#   long       answers that took LONG_MS or more, and their median length
#   before     the same in the baseline slice
# With scheduler slices, also the server container's CPU (cores) before and during, found by
# the pid namespace of the process that sends the server's packets.
#
# It reads the transmit events (net_dev_queue) and, optionally, the scheduling events.
#
# Usage:
#   python3 slow_answers.py <fault_net.txt> <baseline_net.txt> <secs> [fault_sched.txt baseline_sched.txt sched_secs]
#   python3 slow_answers.py --selftest
#
#   net slices: 20 s, extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
#   sched slices: 10 s, extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'sched_switch'
import re
import sys
from collections import defaultdict

LONG_MS = 10.0         # a long answer
MIN_LONG = 20          # long answers in the slice (one a second in 20 s)
MIN_RISE = 10.0        # ... and this many times the baseline's long answers (plus one)
MAX_SHARE = 0.5        # ... and they are at most this share of the calls (otherwise every answer is slow)
MIN_CALLS = 100        # a pair is judged only if it has this many calls
CPU_RISE = 1.5         # the server "works" when its CPU is at least this many times the baseline
MAX_MEDIAN_RISE = 1.25 # the median answer rose by at most this factor: most answers are as fast as before
# Bars set before testing on the labelled runs (28-11-2026). What was seen first: on run 1 of
# slow_query the median answer time from user-db did not move (0.20 ms), so a median is useless.
# CHANGED AFTER THE 70-RUN TEST (28-11-2026): the server is now the side whose port is below 32768 and the
# client the side at 32768 or above (Linux gives clients ports from 32768). The first version took whichever
# side sent first in the slice as the client; on connections already open when the slice starts that is often
# the server, and it named ephemeral ports as servers.
# Also changed then: MAX_MEDIAN_RISE. The tool's verdict already said "most answers are as fast as before"
# without checking it; in one reversed run the catalogue's answers all shifted with its load (median 1.68 to
# 2.79 ms) and the slow tail alone passed the bars.
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'\{ pid = (\d+), tid = (\d+), procname = "([^"]*)".*?pid_ns = (\d+)')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = \d+, data_offset = (\d+)')


def tsec(line):
    m = re_time.match(line)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1e9 if m else None


def read_net(lines):
    rt = defaultdict(list)                       # (client, server, port) -> answer times in ms
    pend = {}
    seen = set()
    ns_of = defaultdict(lambda: defaultdict(int))
    name = {}
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
        if (s, sp, seq) in seen:
            continue
        seen.add((s, sp, seq))
        t = tsec(line)
        cx = re_ctx.search(line)
        if cx and not cx.group(3).startswith(KERNEL_CTX):
            ns_of[s][cx.group(4)] += 1
            name.setdefault((s, cx.group(4)), cx.group(3))
        if from_server:                          # the server's first answer to a pending call
            start = pend.pop((d, dp, s, sp), None)
            if start is not None:
                rt[(d, s, sp)].append((t - start) * 1e3)
            continue
        if (s, sp, d, dp) not in pend and t is not None:
            pend[(s, sp, d, dp)] = t
    ns = {ip: max(v, key=v.get) for ip, v in ns_of.items()}
    return rt, ns, {ip: name[(ip, n)] for ip, n in ns.items()}


def read_cpu(lines):
    cpu = defaultdict(float)
    last = {}
    for line in lines:
        if ' sched_switch:' not in line:
            continue
        t, c, m = tsec(line), re_cpu.search(line), re_ctx.search(line)
        if t is None or not c or not m:
            continue
        t0 = last.get(c.group(1))
        last[c.group(1)] = t
        if m.group(1) != "0" and t0 is not None:
            cpu[m.group(4)] += t - t0
    return cpu


def med(x):
    x = sorted(x)
    return x[len(x) // 2] if x else 0.0


def report(fault, base, secs, cpu=None):
    rt, ns, names = fault
    brt = base[0]
    rows = []
    for k, v in rt.items():
        if len(v) < MIN_CALLS:
            continue
        lg = [x for x in v if x >= LONG_MS]
        blg = [x for x in brt.get(k, []) if x >= LONG_MS]
        rows.append((k, len(v), lg, len(blg), med(v), med(brt.get(k, [])), len(brt.get(k, []))))
    rows.sort(key=lambda r: -len(r[2]) / (r[3] + 1))
    out = [f"Answers per client and server in this {secs:.0f} s slice (pairs with {MIN_CALLS} calls or more; most new long answers first)",
           f"  {'client':<15} {'server':<21} {'calls':>6} {'median ms':>10} {'before':>7} {'long':>5} {'long ms':>8} {'long before':>12}  server program"]
    for k, n, lg, nb, m, bm, bn in rows[:10]:
        out.append(f"  {k[0]:<15} {k[1] + ':' + k[2]:<21} {n:>6} {m:>10.2f} {bm:>7.2f} {len(lg):>5} {med(lg):>8.1f} {nb:>12}  "
                   f"{names.get(k[1], '?')} (pid_ns {ns.get(k[1], '?')})")
    out.append(f"  long = answers of {LONG_MS:.0f} ms or more; before = the same pair in the baseline slice")
    hits = 0
    for k, n, lg, nb, m, bm, bn in rows:
        if (len(lg) < MIN_LONG or len(lg) < MIN_RISE * (nb + 1) or len(lg) > MAX_SHARE * n or bn < MIN_CALLS
                or m > MAX_MEDIAN_RISE * max(bm, 0.01)):
            continue
        kind = ""
        if cpu is not None and k[1] in ns:
            c, bc, cs = cpu[0].get(ns[k[1]], 0.0), cpu[1].get(ns[k[1]], 0.0), cpu[2]
            work = c >= CPU_RISE * bc and c > bc + 0.02 * cs
            kind = (f"; the server's CPU went from {bc / cs:.2f} to {c / cs:.2f} cores - "
                    + ("KIND: THE SERVER WORKS LONGER ON SOME QUERIES (an expensive query: a missing index or a bad plan)" if work else
                       "KIND: THE SERVER WAITS (its CPU did not rise: a lock or a delay, not more work)"))
        out.append(f"VERDICT: SOME ANSWERS ARE SLOW: {k[1]}:{k[2]} ({names.get(k[1], '?')}, pid_ns {ns.get(k[1], '?')}) answered {len(lg)} of "
                   f"{n} calls from {k[0]} in {LONG_MS:.0f} ms or more (median {med(lg):.1f} ms), {nb} in the baseline; the median "
                   f"answer is {m:.2f} ms ({bm:.2f} before), so most answers are as fast as before" + kind)
        hits += 1
    if not hits:
        why = (f"most: {len(rows[0][2])} long answers from {rows[0][0][1]}:{rows[0][0][2]} to {rows[0][0][0]}, {rows[0][3]} before" if rows
               else "no pair with enough calls")
        out.append(f"VERDICT: NO NEW SLOW ANSWERS ({why}; the bars are {MIN_LONG} answers of {LONG_MS:.0f} ms, {MIN_RISE:.0f}x the "
                   f"baseline, at most {MAX_SHARE:.0%} of the calls, median at most {MAX_MEDIAN_RISE}x)")
    return out


def selftest():
    import random
    rnd = random.Random(3)

    def seg(t, src, sp, dst, dp, seq, comm, ns):
        a, b = src.split("."), dst.split(".")
        h, m = divmod(int(t), 60)
        return (f'[10:{h:02d}:{m:02d}.{int((t % 1) * 1e9):09d}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, '
                f'procname = "{comm}", cgroup_ns = 1, pid_ns = {ns}, net_ns = 1 }}, {{ skbaddr = 0x1, len = 74, name = "eth0", network_header = {{ ipv4 = {{ '
                f'version = 4, ihl = 5, tot_len = 200, saddr = [ [0] = {a[0]}, [1] = {a[1]}, [2] = {a[2]}, [3] = {a[3]} ], '
                f'daddr = [ [0] = {b[0]}, [1] = {b[1]}, [2] = {b[2]}, [3] = {b[3]} ], transport_header = {{ tcp = {{ source_port = {sp}, '
                f'dest_port = {dp}, seq = {seq}, ack_seq = 1, data_offset = 8, reserved = 0, flags = 0x18, window = 500 }} }} }} }} }}')

    def calls(slow_every):
        out = []
        for i in range(4000):                    # 200 calls per second from user to its database
            t = i * 0.005
            d = 0.033 if slow_every and i % slow_every == 0 else 0.0002 + rnd.random() * 0.0001
            out += [seg(t, "10.0.0.3", 40000 + i % 8, "10.0.0.11", 27017, i, "user", 6),
                    seg(t + d, "10.0.0.11", 27017, "10.0.0.3", 40000 + i % 8, i, "conn9", 8)]
        return sorted(out)

    def sw(cores):
        o, t = [], 0.0
        while t < 10:
            o += [f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = 0 }}, {{ pid = 0, tid = 0, procname = "swapper/0", pid_ns = 1 }}, {{ prev_tid = 0 }}',
                  f'[10:00:{t + cores * 0.01:012.9f}] (+0.0) h sched_switch: {{ cpu_id = 0 }}, {{ pid = 77, tid = 77, procname = "conn9", pid_ns = 8 }}, {{ prev_tid = 77 }}']
            t += 0.01
        return o

    base, fault = read_net(calls(0)), read_net(calls(80))
    cpu = (read_cpu(sw(0.9)), read_cpu(sw(0.05)), 10.0)
    out = "\n".join(report(fault, base, 20, cpu))
    assert "SOME ANSWERS ARE SLOW: 10.0.0.11:27017 (conn9, pid_ns 8) answered 50 of 4000 calls from 10.0.0.3 in 10 ms or more (median 33.0 ms), 0 in the baseline" in out, out
    assert "the server's CPU went from 0.05 to 0.90 cores - KIND: THE SERVER WORKS LONGER" in out and out.count("VERDICT") == 1, out
    out = "\n".join(report(fault, base, 20, (read_cpu(sw(0.05)), read_cpu(sw(0.05)), 10.0)))
    assert "KIND: THE SERVER WAITS" in out, out
    out = "\n".join(report(base, base, 20))
    assert "NO NEW SLOW ANSWERS (most: 0 long answers" in out, out
    out = "\n".join(report(read_net(calls(1)), base, 20))          # every answer slow: a slow path, not a slow query
    assert "NO NEW SLOW ANSWERS" in out, out
    shifted = read_net(calls(0))                 # a load change: every answer 3x slower, and a tail
    shifted = ({k: [x * 3 for x in v] + [12.0] * 60 for k, v in shifted[0].items()}, shifted[1], shifted[2])
    out = "\n".join(report(shifted, base, 20))
    assert "NO NEW SLOW ANSWERS" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: slow_answers.py <fault_net> <baseline_net> <secs> [fault_sched baseline_sched sched_secs]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        fa = read_net(f)
    with open(sys.argv[2], errors="replace") as f:
        b = read_net(f)
    cpu = None
    if len(sys.argv) > 6:
        with open(sys.argv[4], errors="replace") as f:
            c1 = read_cpu(f)
        with open(sys.argv[5], errors="replace") as f:
            c0 = read_cpu(f)
        cpu = (c1, c0, float(sys.argv[6]))
    print("\n".join(report(fa, b, float(sys.argv[3]), cpu)))
