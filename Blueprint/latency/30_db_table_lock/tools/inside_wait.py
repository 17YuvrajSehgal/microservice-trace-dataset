#!/usr/bin/env python3
# inside_wait.py - where do a service's requests spend their time: on a CPU, waiting for a CPU,
# waiting for a dependency, or waiting INSIDE the service for something the trace cannot name
# (a lock, a pool, an internal queue)?
#
# A lock held across a slow call leaves nothing busy: the service uses little CPU, its database
# answers quickly, nothing is lost. But requests pile up inside the service. This tool counts
# that pile.
#
# For one service (one address):
#   in flight   requests it has received and not yet answered, averaged over the slice
#   downstream  calls it has made to other services and not yet got an answer to
#   on CPU      cores its container used
#   CPU wait    its threads that were ready to run and waiting for a core
#   inside      in flight - downstream - on CPU - CPU wait  (never below 0)
# "inside" is requests that are neither running, nor waiting for a core, nor waiting for
# another service. In a healthy service it is near 0.
#
# It reads the transmit events (net_dev_queue: a call runs from the client's last data segment
# to the server's first answering segment, on one connection) and the scheduling events.
#
# WHERE A CALL IS TIMED. A packet is queued once on the sender's interface and once on the next
# interface. A call is timed AT THE SERVER: from the request's arrival on the server's side to
# the answer's queueing on the server's own interface. So a wait on the CLIENT's interface (a
# rate limit there) is not counted as time in the server; it shows as "inside" of the client,
# which is where it is. (Until 25-11-2026 the tool used whichever sighting it met first, and on
# the 5 net_bandwidth runs it named the database proxy for a limit on the catalogue.)
#
# WHAT IT CANNOT SEE.
# - A request that never gets an answer has no end and is not counted at all. A service that
#   has stopped answering is missing from the table (measured on the 5 slow_client runs). Use
#   unanswered.py for that.
# - A single-threaded service has a standing queue: the Node front-end here shows about 10
#   requests "inside" in every normal slice. So ALWAYS give a baseline slice with about the
#   same traffic. Without one the tool names the front-end. With a comparison slice that has
#   much less traffic for a service, that service is not judged (and the tool says so).
#
# Usage:
#   python3 inside_wait.py <slice.txt> <slice_seconds> [baseline_slice.txt]
#   python3 inside_wait.py --selftest
#
#   slices: 20 s or more, cut with
#     extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue|sched_switch|sched_waking|sched_wakeup'
import re
import sys
from collections import defaultdict
from statistics import median

MIN_CALLS = 200        # a service is judged only if it received this many requests in the slice
MIN_INSIDE = 1.0       # requests waiting inside, averaged over the slice
MIN_SHARE = 0.25       # ... and this share of its requests in flight
MIN_RISE = 3.0         # ... and this many times the baseline (when a baseline is given)
MIN_BASE_RATE = 0.25   # the baseline must have at least this share of the slice's request rate for
                       # that service, or the two slices are not like for like and it is not judged
# The first two bars were guessed at 2.0 and 50% and then LOWERED after the 5 labelled runs
# (24-11-2026): the locked service is at 2.07-2.65 requests and 34-39% of its requests in
# flight, with 0.00 in every baseline. Fitted to one defect in one service; the check on
# other fault families has not been run yet.
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_dev = re.compile(r' name = "([^"]*)"')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = \d+, ack_seq = \d+, data_offset = (\d+)'
                    r'(?:, .*?flags = 0x([0-9A-Fa-f]+))?')
re_sw = re.compile(r'prev_tid = (\d+), prev_prio = -?\d+, prev_state = (\d+), next_comm = "[^"]*", next_tid = (\d+)')
re_wk = re.compile(r'\{ comm = "[^"]*", tid = (\d+), prio')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    segs = defaultdict(lambda: defaultdict(list))        # conn -> device -> [(t, from_client)]
    votes = defaultdict(lambda: defaultdict(int))        # ip -> (comm, pid_ns) -> data segments sent
    last = {}                                            # cpu -> time of the last switch
    oncpu = defaultdict(float)                           # pid_ns -> seconds on a CPU
    tid_ns = {}                                          # tid -> pid_ns (learned at switch-out)
    ready = {}                                           # tid -> since when it is ready and not running
    wait_tid = defaultdict(float)                        # tid -> seconds waiting for a CPU
    start = None
    for line in lines:
        if ' net_dev_queue:' in line:
            ip, tcp = re_ip.search(line), re_tcp.search(line)
            if not ip or not tcp:
                continue
            payload = int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(3)) * 4
            # SYN, FIN and RST mark the edges of a connection even when they carry no data
            edge = bool(tcp.group(4)) and int(tcp.group(4), 16) & 0x07
            if payload <= 0 and not edge:
                continue
            t = tsec(line)
            if t is None:
                continue
            src, dst = ".".join(ip.groups()[2:6]), ".".join(ip.groups()[6:10])
            sp, dp = int(tcp.group(1)), int(tcp.group(2))
            # the server is the side with the fixed port: below the ephemeral range, or the smaller
            from_client = (dp < 32768 <= sp) or (not (sp < 32768 <= dp) and dp < sp)
            d = re_dev.search(line)
            # one packet fires once per device it crosses: keep them apart, use the fullest
            segs[(src, sp, dst, dp) if from_client else (dst, dp, src, sp)][d.group(1) if d else "?"].append(
                (t, None if edge else from_client))
            if payload <= 0:
                continue
            cx = re_ctx.search(line)
            # data leaves in the context of the process that wrote it, so it names the owner
            if cx and not cx.group(3).startswith(KERNEL_CTX):
                pn = re_pidns.search(line)
                votes[src][(cx.group(3), pn.group(1) if pn else "?")] += 1
        elif ' sched_switch:' in line:
            t, cm, sw = tsec(line), re_cpu.search(line), re_sw.search(line)
            if t is None or not cm or not sw:
                continue
            start = t if start is None else start
            cpu = cm.group(1)
            since = last.get(cpu, start)
            last[cpu] = t
            prev_tid, prev_state, next_tid = sw.groups()
            pn = re_pidns.search(line)
            if prev_tid != '0' and pn:
                tid_ns[prev_tid] = pn.group(1)
                oncpu[pn.group(1)] += t - since       # the context of a switch is the thread going out
                if prev_state == '0':                  # still runnable: it was pushed off the core
                    ready[prev_tid] = t
            if next_tid in ready:
                wait_tid[next_tid] += t - ready.pop(next_tid)
        elif ' sched_waking:' in line or ' sched_wakeup:' in line:
            t, wk = tsec(line), re_wk.search(line)
            if t is not None and wk:
                ready.setdefault(wk.group(1), t)
    cpuwait = defaultdict(float)
    for tid, s in wait_tid.items():
        if tid in tid_ns:
            cpuwait[tid_ns[tid]] += s
    calls = defaultdict(list)                             # (client ip, server ip, port) -> [(t0, t1)]
    for (cip, cport, sip, sport), devs in segs.items():
        t0 = None
        for t, fc in at_server(devs):
            if fc is None:
                # a connection opened or closed here. A client port is reused by a later
                # connection: measured, a MySQL "quit" (no answer) followed 12 s later by the
                # greeting of a NEW connection on the same port read as one 12 s call.
                t0 = None
            elif fc:
                # measured from the client's LAST data segment. Some commands get no answer at
                # all (a MySQL statement close): counted from the first segment, such a command
                # looked like a call in flight until the next query came (measured: 27 calls
                # "in flight" at an idle database).
                t0 = t
            elif t0 is not None:
                calls[(cip, sip, sport)].append((t0, t))
                t0 = None
    who = {ip: max(v, key=v.get) for ip, v in votes.items()}
    return calls, who, oncpu, cpuwait


def at_server(devs):
    # One connection, seen on several interfaces. Take the client's segments where they are
    # LATEST (arriving at the server) and the server's segments where they are EARLIEST (leaving
    # the server), so that a queue on either sender's interface is not counted in the call.
    def pick(want, latest):
        best, key = [], None
        full = max((sum(1 for _, fc in v if fc is want) for v in devs.values()), default=0)
        for v in devs.values():
            x = [t for t, fc in v if fc is want]
            # a device that saw only part of the connection (cut by the slice) is not compared
            if not x or len(x) < 0.9 * full:
                continue
            k = sum(x) / len(x)
            if key is None or (k > key if latest else k < key):
                best, key = x, k
        return best
    edges = max(([t for t, fc in v if fc is None] for v in devs.values()), key=len, default=[])
    return sorted([(t, True) for t in pick(True, True)] + [(t, False) for t in pick(False, False)]
                  + [(t, None) for t in edges])


def table(data, secs):
    calls, who, oncpu, cpuwait = data
    rows = {}
    for ip in {k[1] for k in calls}:
        inb = [iv for (c, s, p), ivs in calls.items() if s == ip for iv in ivs]
        if len(inb) < MIN_CALLS:
            continue
        out = [iv for (c, s, p), ivs in calls.items() if c == ip for iv in ivs]
        ns = who.get(ip, ("?", "?"))[1]
        lin = sum(b - a for a, b in inb) / secs
        lout = sum(b - a for a, b in out) / secs
        cpu, cw = oncpu.get(ns, 0.0) / secs, cpuwait.get(ns, 0.0) / secs
        rows[ip] = {"rate": len(inb) / secs, "ms": median(b - a for a, b in inb) * 1000, "lin": lin, "lout": lout,
                    "cpu": cpu, "cw": cw, "inside": max(0.0, lin - lout - cpu - cw)}
    return rows


def report(cur, secs, base=None):
    rows, brow = table(cur, secs), (table(base, secs) if base else {})
    who = cur[1]

    def name(ip):
        return f"{who[ip][0]} (pid_ns {who[ip][1]})" if ip in who else "?"

    out = [f"Where requests wait, per service, in this {secs:.0f} s slice (services that received {MIN_CALLS} requests or more)",
           f"  {'service':<15} {'req/s':>7} {'answer ms':>10} {'in flight':>10} {'downstream':>11} {'on CPU':>7} {'CPU wait':>9} "
           f"{'inside':>7} {'before':>7}  program"]
    for ip, r in sorted(rows.items(), key=lambda kv: -kv[1]["inside"])[:12]:
        b = "%.2f" % brow[ip]["inside"] if ip in brow else "-"
        out.append(f"  {ip:<15} {r['rate']:>7.0f} {r['ms']:>10.2f} {r['lin']:>10.2f} {r['lout']:>11.2f} {r['cpu']:>7.2f} "
                   f"{r['cw']:>9.2f} {r['inside']:>7.2f} {b:>7}  {name(ip)}")
    out.append("  in flight = requests received and not yet answered; downstream = its own calls not yet answered; "
               "on CPU and CPU wait = its container's threads; all averaged over the slice")
    out.append("  inside = in flight - downstream - on CPU - CPU wait: requests waiting in the service for something "
               "the trace cannot name (a lock, a pool, an internal queue); before = the baseline slice")
    hits = 0
    for ip, r in sorted(rows.items(), key=lambda kv: -kv[1]["inside"]):
        b = brow.get(ip)
        if base and r["inside"] >= MIN_INSIDE and r["inside"] >= MIN_SHARE * r["lin"] and (not b or b["rate"] < MIN_BASE_RATE * r["rate"]):
            out.append(f"NOT JUDGED: {name(ip)} at {ip} has {r['inside']:.1f} requests waiting inside it, but the baseline slice has "
                       f"{b['rate'] if b else 0:.0f} requests/s for it against {r['rate']:.0f} here: the two slices are not like for like")
            continue
        if r["inside"] >= MIN_INSIDE and r["inside"] >= MIN_SHARE * r["lin"] and (not base or (b and r["inside"] >= MIN_RISE * b["inside"])):
            was = f", {b['inside']:.2f} in the baseline" if b else " (NO BASELINE GIVEN: a single-threaded service always has a standing queue)"
            out.append(f"VERDICT: REQUESTS WAIT INSIDE THE SERVICE: {name(ip)} at {ip} has {r['lin']:.1f} requests in flight, "
                       f"{r['inside']:.1f} of them wait inside it{was}: it uses {r['cpu']:.2f} cores, {r['cw']:.2f} threads wait "
                       f"for a core, {r['lout']:.2f} of its calls are waiting for a dependency; answers take {r['ms']:.1f} ms")
            hits += 1
    if not hits:
        top = max(rows.items(), key=lambda kv: kv[1]["inside"], default=None)
        why = (f"most: {top[1]['inside']:.2f} of {top[1]['lin']:.2f} in flight at {top[0]}" if top else "no service received enough requests")
        out.append(f"VERDICT: NO REQUESTS WAITING INSIDE A SERVICE ({why}; the bars are {MIN_INSIDE} requests, "
                   f"{MIN_SHARE:.0%} of those in flight, {MIN_RISE}x the baseline)")
    return out


def selftest():
    def addr(a):
        return ", ".join(f"[{i}] = {x}" for i, x in enumerate(a.split(".")))

    def q(t, nm, ns, src, sport, dst, dport, dev="eth0"):
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 7, tid = 7, procname = "{nm}", '
                f'pid_ns = {ns} }}, {{ skbaddr = 0x1, len = 90, name = "{dev}", network_header_type = 1, '
                f'network_header = {{ ipv4 = {{ version = 4, ihl = 5, tos = 0, tot_len = 90, id = 0x1, frag_off = 0, '
                f'ttl = 64, protocol = 6, checksum = 0x0, saddr = [ {addr(src)} ], daddr = [ {addr(dst)} ], '
                f'transport_header_type = 1, transport_header = {{ tcp = {{ source_port = {sport}, dest_port = {dport}, '
                f'seq = 1, ack_seq = 1, data_offset = 5, reserved = 0, flags = 0x18, window_size = 64 }} }} }} }} }}')

    def slice_(hold):
        # 10 clients each send one request every 100 ms; the app answers after `hold` seconds,
        # of which 2 ms is one database call. So hold - 2 ms is spent inside the app.
        ls = []
        for i in range(100):
            for c in range(10):
                t = i * 0.1 + c * 0.001
                ls += [q(t, "web", 4, "10.0.0.4", 40000 + c, "10.0.0.5", 80),
                       q(t + 0.001, "app", 5, "10.0.0.5", 41000 + c, "10.0.0.6", 3306),
                       q(t + 0.003, "mysqld", 6, "10.0.0.6", 3306, "10.0.0.5", 41000 + c),
                       q(t + hold, "app", 5, "10.0.0.5", 80, "10.0.0.4", 40000 + c)]
        return sorted(ls, key=tsec)

    base = read(slice_(0.004))
    out = "\n".join(report(read(slice_(0.090)), 10, base))
    assert "REQUESTS WAIT INSIDE THE SERVICE: app (pid_ns 5) at 10.0.0.5 has 9.0 requests in flight, 8.8 of them wait inside it, 0.20 in the baseline" in out, out
    out = "\n".join(report(base, 10, base))
    assert "NO REQUESTS WAITING INSIDE A SERVICE (most: 0.20 of 0.40 in flight at 10.0.0.5" in out, out

    def capped(wait):
        # the same service with a rate limit on its OWN interface: each query to the database
        # waits `wait` seconds there before it reaches the database's side (second sighting)
        ls = []
        for i in range(100):
            for c in range(10):
                t = i * 0.1 + c * 0.001
                ls += [q(t, "web", 4, "10.0.0.4", 40000 + c, "10.0.0.5", 80),
                       q(t + 0.000005, "swapper/1", 0, "10.0.0.4", 40000 + c, "10.0.0.5", 80, "vethapp"),
                       q(t + 0.001, "app", 5, "10.0.0.5", 41000 + c, "10.0.0.6", 3306),
                       q(t + 0.001 + wait, "swapper/1", 0, "10.0.0.5", 41000 + c, "10.0.0.6", 3306, "vethdb"),
                       q(t + 0.003 + wait, "mysqld", 6, "10.0.0.6", 3306, "10.0.0.5", 41000 + c),
                       q(t + 0.003005 + wait, "swapper/1", 0, "10.0.0.6", 3306, "10.0.0.5", 41000 + c, "vethapp"),
                       q(t + 0.004 + wait, "app", 5, "10.0.0.5", 80, "10.0.0.4", 40000 + c)]
        return sorted(ls, key=tsec)

    out = "\n".join(report(read(capped(0.060)), 10, read(capped(0.0))))
    assert out.count("VERDICT") == 1 and "REQUESTS WAIT INSIDE THE SERVICE: app (pid_ns 5) at 10.0.0.5" in out, out
    assert "  10.0.0.6            100       2.00       0.20" in out, out          # the database: 2 ms, not 62 ms
    # a comparison slice with almost no traffic is not a baseline
    thin = [l for l in slice_(0.004) if int(tsec(l) * 10) % 10 == 0 and tsec(l) < 36002.5]
    out = "\n".join(report(read(slice_(0.090)), 10, read(thin)))
    assert "NOT JUDGED: app (pid_ns 5) at 10.0.0.5" in out and "NO REQUESTS WAITING INSIDE A SERVICE" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: inside_wait.py <slice.txt> <slice_seconds> [baseline_slice.txt]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        cur = read(f)
    b = None
    if len(sys.argv) > 3:
        with open(sys.argv[3], errors="replace") as f:
            b = read(f)
    print("\n".join(report(cur, float(sys.argv[2]), b)))
