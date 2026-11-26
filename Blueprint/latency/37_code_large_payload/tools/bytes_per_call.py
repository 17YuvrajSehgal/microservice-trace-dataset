#!/usr/bin/env python3
# bytes_per_call.py - find a service whose answers became much larger while the number of
# calls stayed about the same.
#
# For each server address and port, from the transmit events:
#   calls/s    requests answered per second (a request is the client's data; an answer starts
#              when the server sends data after it, on the same connection)
#   kB/answer  bytes the server sent per answer
# Each packet is counted once, at its first sighting (a packet is seen on several interfaces).
#
# Usage:
#   python3 bytes_per_call.py <fault_slice.txt> <slice_seconds> <baseline_slice.txt>
#   python3 bytes_per_call.py --selftest
#
#   slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict

MIN_RISE = 3.0         # bytes per answer this many times the baseline
MIN_RATE = 500e3       # ... and the server sends at least this many bytes per second
CALLS = (0.5, 2.0)     # ... while its answers per second stay within this factor of the baseline
MIN_CALLS = 50         # answers in the slice, for the server to be judged
# Bars set before the first run on labelled data (26-11-2026) and not fitted to it.
# ONE VERDICT, for the largest rise. Added after run 1: the services in front of the source
# (front-end, edge router, the host's port forward) pass the larger answers on and rose about 4
# times, the source 18 times. They are listed as "also larger" without a verdict.
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_ctx = re.compile(r'procname = "([^"]*)".*?pid_ns = (\d+)')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = \d+, data_offset = (\d+)')


def read(lines):
    seen = set()
    last = {}                                    # connection -> who sent data last ("c" or "s")
    calls = defaultdict(int)                     # (server ip, port) -> answers
    sent = defaultdict(int)                      # (server ip, port) -> payload bytes sent
    votes = defaultdict(lambda: defaultdict(int))
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp:
            continue
        payload = int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(4)) * 4
        if payload <= 0:
            continue
        src, dst = ".".join(ip.groups()[2:6]), ".".join(ip.groups()[6:10])
        sp, dp = int(tcp.group(1)), int(tcp.group(2))
        key = (src, dst, sp, dp, tcp.group(3), ip.group(2))
        if key in seen:
            continue
        seen.add(key)
        # the server is the side with the fixed port: below the ephemeral range, or the smaller
        from_client = (dp < 32768 <= sp) or (not (sp < 32768 <= dp) and dp < sp)
        server = (dst, dp) if from_client else (src, sp)
        conn = (src, sp, dst, dp) if from_client else (dst, dp, src, sp)
        if from_client:
            last[conn] = "c"
            continue
        if last.get(conn) == "c":
            calls[server] += 1
        last[conn] = "s"
        sent[server] += payload
        cx = re_ctx.search(line)
        if cx and not cx.group(1).startswith(KERNEL_CTX):
            votes[src][(cx.group(1), cx.group(2))] += 1
    who = {i: max(v, key=v.get) for i, v in votes.items()}
    return calls, sent, who


def report(data, secs, base):
    calls, sent, who = data
    bcalls, bsent, _ = base
    rows = []
    for s, n in calls.items():
        if n < MIN_CALLS:
            continue
        per = sent[s] / n
        bper = bsent[s] / bcalls[s] if bcalls.get(s) else 0.0
        rows.append((per / max(bper, 1.0), s, n, per, bper))
    rows.sort(reverse=True)
    out = [f"Bytes per answer, per server, in this {secs:.0f} s slice (largest rise first)",
           f"  {'server':<22} {'calls/s':>8} {'before':>7} {'kB/answer':>10} {'before':>8} {'kB/s':>8}  program"]
    for rise, s, n, per, bper in rows[:10]:
        nm = who.get(s[0], ("?", "?"))
        out.append(f"  {s[0] + ':' + str(s[1]):<22} {n / secs:>8.0f} {bcalls.get(s, 0) / secs:>7.0f} {per / 1e3:>10.2f} {bper / 1e3:>8.2f} "
                   f"{sent[s] / secs / 1e3:>8.0f}  {nm[0]} (pid_ns {nm[1]})")
    out.append("  before = the baseline slice")
    hits = 0
    for rise, s, n, per, bper in rows:
        bn = bcalls.get(s, 0)
        if rise < MIN_RISE or sent[s] / secs < MIN_RATE or not bn or not (CALLS[0] <= n / bn <= CALLS[1]):
            continue
        nm = who.get(s[0], ("?", "?"))
        if hits:
            out.append(f"ALSO LARGER (passes it on?): {nm[0]} (pid_ns {nm[1]}) at {s[0]}:{s[1]}, {per / 1e3:.1f} kB per answer, {rise:.1f} times")
            continue
        out.append(f"VERDICT: ANSWERS GOT LARGER: {nm[0]} (pid_ns {nm[1]}) at {s[0]}:{s[1]} sends {per / 1e3:.1f} kB per answer, "
                   f"{bper / 1e3:.1f} kB in the baseline ({rise:.1f} times), {sent[s] / secs / 1e6:.2f} MB/s, with {n / secs:.0f} answers "
                   f"per second against {bn / secs:.0f} before - the same calls carry far more data")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"largest rise: {top[0]:.1f} times at {top[1][0]}:{top[1][1]}" if top else "no server with enough answers")
        out.append(f"VERDICT: NO LARGER ANSWERS ({why}; the bars are {MIN_RISE:.0f} times the baseline, {MIN_RATE / 1e3:.0f} kB/s, "
                   f"calls within {CALLS[0]}-{CALLS[1]} times the baseline)")
    return out


def selftest():
    def seg(t, src, sp, dst, dp, seq, n, comm="app", ns=7):
        a, b = src.split("."), dst.split(".")
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, procname = "{comm}", pid_ns = {ns} }}, '
                f'{{ skbaddr = 0x1, len = {n + 54}, name = "eth0", network_header = {{ ipv4 = {{ version = 4, ihl = 5, tot_len = {n + 40}, '
                f'saddr = [ [0] = {a[0]}, [1] = {a[1]}, [2] = {a[2]}, [3] = {a[3]} ], daddr = [ [0] = {b[0]}, [1] = {b[1]}, [2] = {b[2]}, [3] = {b[3]} ], '
                f'transport_header = {{ tcp = {{ source_port = {sp}, dest_port = {dp}, seq = {seq}, ack_seq = 1, data_offset = 5, flags = 24 }} }} }} }} }}')

    def calls(size):
        ls = []
        for i in range(500):
            t = i * 0.02
            ls.append(seg(t, "10.0.0.2", 40000 + i % 20, "10.0.0.9", 80, i, 200, "node", 3))
            for k in range(size // 1400 + 1):
                ls.append(seg(t + 0.001, "10.0.0.9", 80, "10.0.0.2", 40000 + i % 20, i * 100 + k, min(1400, size - k * 1400) or 1, "srv", 9))
        return ls
    out = "\n".join(report(read(calls(18000)), 10, read(calls(2500))))
    assert "ANSWERS GOT LARGER: srv (pid_ns 9) at 10.0.0.9:80 sends 18.0 kB per answer, 2.5 kB in the baseline (7.2 times), 0.90 MB/s, with 50 answers per second against 50 before" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(calls(2500)), 10, read(calls(2500))))
    assert "NO LARGER ANSWERS (largest rise: 1.0 times at 10.0.0.9:80" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: bytes_per_call.py <fault_slice.txt> <slice_seconds> <baseline_slice.txt>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        d = read(f)
    with open(sys.argv[3], errors="replace") as f:
        b = read(f)
    print("\n".join(report(d, float(sys.argv[2]), b)))
