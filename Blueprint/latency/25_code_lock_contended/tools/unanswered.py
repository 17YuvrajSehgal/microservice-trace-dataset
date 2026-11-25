#!/usr/bin/env python3
# unanswered.py - find a service that has stopped answering, and say whether slow clients are
# the reason.
#
# inside_wait.py times a request from the client's last data segment to the server's first
# answer. A request that is never answered has no end, so that tool does not see it at all
# (measured on the 5 slow_client runs: the stuck service is not even in its table).
#
# This tool counts the opposite: connections on which the client sent data and the server sent
# NO data for the rest of the slice. For each server address and port:
#   silent     connections with client data and no server data, silent for MIN_SILENT_S or more
#   trickle    silent connections whose client keeps sending very small segments at a slow,
#              steady pace (a request body sent a byte at a time: every such connection holds
#              one worker thread of a server that reads bodies on worker threads)
#   answered   connections on which the server sent data in the slice
#
# It reads the transmit events (net_dev_queue).
#
# Usage:
#   python3 unanswered.py <slice.txt> <slice_seconds> [baseline_slice.txt]
#   python3 unanswered.py --selftest
#
#   slices: 20 s or more, cut with
#     extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
import re
import sys
from collections import defaultdict
from statistics import median

MIN_SILENT_S = 5.0     # a connection is silent if the server sent nothing for this long after client data
MIN_CONNS = 20         # silent connections to one server address and port
MIN_SHARE = 0.5        # ... and this share of that server's connections that carried client data
MIN_RISE = 5.0         # ... and this many times the baseline (when a baseline is given)
TRICKLE_BYTES = 16     # a "very small" segment
TRICKLE_SEGS = 5       # this many of them on one connection, and nothing larger after the first
# Bars set before the first run on labelled data (25-11-2026) and not fitted to it.
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
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
    segs = defaultdict(lambda: defaultdict(list))    # conn -> device -> [(t, from_client, payload)]
    votes = defaultdict(lambda: defaultdict(int))    # ip -> (comm, pid_ns) -> data segments sent
    end = None
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        t = tsec(line)
        if t is None:
            continue
        end = t
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp:
            continue
        payload = int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(3)) * 4
        if payload <= 0:
            continue
        src, dst = ".".join(ip.groups()[2:6]), ".".join(ip.groups()[6:10])
        sp, dp = int(tcp.group(1)), int(tcp.group(2))
        # the server is the side with the fixed port: below the ephemeral range, or the smaller
        from_client = (dp < 32768 <= sp) or (not (sp < 32768 <= dp) and dp < sp)
        d = re_dev.search(line)
        # one packet fires once per device it crosses: keep them apart, use the fullest
        segs[(src, sp, dst, dp) if from_client else (dst, dp, src, sp)][d.group(1) if d else "?"].append(
            (t, from_client, payload))
        cx = re_ctx.search(line)
        if cx and not cx.group(3).startswith(KERNEL_CTX):
            pn = re_pidns.search(line)
            votes[src][(cx.group(3), pn.group(1) if pn else "?")] += 1
    srv = defaultdict(lambda: {"silent": 0, "trickle": 0, "answered": 0, "peers": defaultdict(int), "gaps": []})
    waiting = defaultdict(int)                       # ip -> its own requests to others that got no answer
    for (cip, cport, sip, sport), devs in segs.items():
        # One connection is seen on several interfaces, and an interface can carry only ONE
        # direction of it. The first version looked at the interface with the most segments
        # only: when that one carried just the client's side, an answered connection was
        # counted as silent (measured 25-11-2026: 30-51 "silent" connections at the edge router
        # in every normal slice; with all interfaces together, 0 of 151). So: answered if ANY
        # interface shows server data; the client's segments from the interface with most of them.
        c = sorted(max(([(t, n) for t, fc, n in v if fc] for v in devs.values()), key=len))
        r = srv[(sip, sport)]
        if any(not fc for v in devs.values() for _, fc, _ in v):
            r["answered"] += 1
            continue
        if not c or end - c[0][0] < MIN_SILENT_S:
            continue
        r["silent"] += 1
        waiting[cip] += 1
        small = [t for t, n in c[1:] if n <= TRICKLE_BYTES]
        if len(small) >= TRICKLE_SEGS and len(small) == len(c) - 1:
            r["trickle"] += 1
            r["peers"][cip] += 1
            r["gaps"] += [b - a for a, b in zip(small, small[1:])]
    who = {ip: max(v, key=v.get) for ip, v in votes.items()}
    return srv, who, waiting


def report(data, secs, base=None):
    srv, who, waiting = data
    bsrv = base[0] if base else {}
    if base:
        # a server that sends nothing cannot be named from this slice: use the baseline's name
        who = {**base[1], **who}
    rows = sorted(srv.items(), key=lambda kv: -kv[1]["silent"])
    out = [f"Connections that got no answer, per server address and port, in this {secs:.0f} s slice",
           f"  {'server':<22} {'silent':>7} {'trickle':>8} {'answered':>9} {'before':>7}  program"]
    for (ip, port), r in rows[:12]:
        if not r["silent"] and not r["answered"]:
            continue
        nm = who.get(ip, ("?", "?"))
        out.append(f"  {ip + ':' + str(port):<22} {r['silent']:>7} {r['trickle']:>8} {r['answered']:>9} "
                   f"{bsrv.get((ip, port), {}).get('silent', 0) if base else '-':>7}  {nm[0]} (pid_ns {nm[1]})")
    out.append(f"  silent = the client sent data and the server sent none for {MIN_SILENT_S:.0f} s or more, to the end of the slice; "
               f"trickle = silent, and the client keeps sending segments of {TRICKLE_BYTES} bytes or less; before = silent in the baseline slice")
    hits = 0
    for (ip, port), r in rows:
        b = bsrv.get((ip, port), {}).get("silent", 0) if base else 0
        tot = r["silent"] + r["answered"]
        if r["silent"] < MIN_CONNS or r["silent"] < MIN_SHARE * tot or (base and r["silent"] < MIN_RISE * b):
            continue
        nm = who.get(ip, ("?", "?"))
        # A service that waits for another one does not answer either. It is a caller, not the
        # cause, when it has unanswered requests of its own. A port forward on the host is a
        # caller too, but its outgoing side has another address, so it is recognised by address.
        # ponytail: by address only; a proxy that changes address inside a container is not seen
        if waiting.get(ip, 0) or ip.startswith("127."):
            out.append(f"ALSO NOT ANSWERING, as a caller: {nm[0]} (pid_ns {nm[1]}) at {ip}:{port} has {r['silent']} unanswered connections"
                       + (f" and {waiting[ip]} unanswered requests of its own to other services" if waiting.get(ip, 0) else " (a port forward on the host)"))
            continue
        v = (f"VERDICT: SERVICE DOES NOT ANSWER: {nm[0]} (pid_ns {nm[1]}) at {ip}:{port} has {r['silent']} connections with a request "
             f"and no answer for {MIN_SILENT_S:.0f} s or more, {r['answered']} answered" + (f", {b} silent in the baseline" if base else ""))
        if r["trickle"] >= MIN_SHARE * r["silent"]:
            peer = max(r["peers"], key=r["peers"].get)
            v += (f"; SLOW CLIENTS: {r['trickle']} of them keep sending segments of {TRICKLE_BYTES} bytes or less, one about every "
                  f"{median(r['gaps']):.1f} s, {r['peers'][peer]} from {peer} - each holds a worker thread if the server reads bodies on worker threads")
        out.append(v)
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"most: {top[1]['silent']} silent and {top[1]['answered']} answered at {top[0][0]}:{top[0][1]}" if top else "no connection with data")
        out.append(f"VERDICT: NO SERVICE THAT DOES NOT ANSWER ({why}; the bars are {MIN_CONNS} silent connections, "
                   f"{MIN_SHARE:.0%} of those with client data, {MIN_RISE:.0f}x the baseline)")
    return out


def selftest():
    def seg(t, src, sp, dst, dp, n, comm="app", ns=7):
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 5, tid = 5, procname = "{comm}", pid_ns = {ns} }}, '
                f'{{ skbaddr = 0x1, len = {n + 52}, name = "veth1", network_header_type = ( "_ipv4" : container = 1 ), network_header = '
                f'{{ ipv4 = {{ version = 4, ihl = 5, tos = 0, tot_len = {n + 40}, id = 0x1, frag_off = 0, ttl = 64, protocol = ( "_tcp" : container = 6 ), '
                f'checksum = 0x0, saddr = [ [0] = {src.split(".")[0]}, [1] = {src.split(".")[1]}, [2] = {src.split(".")[2]}, [3] = {src.split(".")[3]} ], '
                f'daddr = [ [0] = {dst.split(".")[0]}, [1] = {dst.split(".")[1]}, [2] = {dst.split(".")[2]}, [3] = {dst.split(".")[3]} ], '
                f'transport_header_type = ( "_tcp" : container = 1 ), transport_header = {{ tcp = {{ source_port = {sp}, dest_port = {dp}, '
                f'seq = 1, ack_seq = 1, data_offset = 5, reserved = 0, flags = 0x18, window = 500, checksum = 0x0, urg_ptr = 0 }} }} }} }} }}')

    normal = []
    for i in range(60):                               # 60 healthy connections, each answered
        normal += [seg(1 + i * 0.2, "10.0.0.2", 40000 + i, "10.0.0.9", 80, 300, "cli", 3),
                   seg(1.01 + i * 0.2, "10.0.0.9", 80, "10.0.0.2", 40000 + i, 900, "srv", 9)]
    normal.append(seg(19.99, "10.0.0.2", 39999, "10.0.0.9", 80, 5, "cli", 3))     # marks the end of the slice
    slow = []
    for i in range(40):                               # 40 slow bodies: a header, then one byte per second
        slow.append(seg(0.5, "10.0.0.1", 50000 + i, "10.0.0.9", 80, 180, "py", 1))
        slow += [seg(1.5 + k, "10.0.0.1", 50000 + i, "10.0.0.9", 80, 1, "py", 1) for k in range(18)]
    stuck = normal[:1] + slow                         # the server answers nobody
    # a proxy in front of it: 30 clients ask the proxy, the proxy asks the server, nobody answers
    for i in range(30):
        stuck += [seg(2 + i * 0.1, "10.0.0.3", 45000 + i, "10.0.0.5", 80, 250, "cli", 3),
                  seg(2.001 + i * 0.1, "10.0.0.5", 46000 + i, "10.0.0.9", 80, 250, "proxy", 5)]
    stuck.append(normal[-1])                          # the end of the slice
    out = "\n".join(report(read(stuck), 20, read(normal)))
    assert "SERVICE DOES NOT ANSWER: srv (pid_ns 9) at 10.0.0.9:80 has 71 connections with a request and no answer for 5 s or more, 0 answered, 0 silent in the baseline" in out, out
    assert "SLOW CLIENTS: 40 of them keep sending segments of 16 bytes or less, one about every 1.0 s, 40 from 10.0.0.1" in out, out
    assert out.count("VERDICT") == 1, out
    assert "ALSO NOT ANSWERING, as a caller: proxy (pid_ns 5) at 10.0.0.5:80 has 30 unanswered connections and 30 unanswered requests of its own" in out, out
    out = "\n".join(report(read(normal), 20, read(normal)))
    assert "NO SERVICE THAT DOES NOT ANSWER (most: 0 silent and 60 answered at 10.0.0.9:80" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: unanswered.py <slice.txt> <slice_seconds> [baseline_slice.txt]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        d = read(f)
    b = None
    if len(sys.argv) > 3:
        with open(sys.argv[3], errors="replace") as f:
            b = read(f)
    print("\n".join(report(d, float(sys.argv[2]), b)))
