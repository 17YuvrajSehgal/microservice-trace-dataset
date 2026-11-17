#!/usr/bin/env python3
# tcp_conns.py - what happens to TCP connections: opened, refused, reset, or held open.
#
# Three things leave no CPU, disk or loss signal and show only here:
#   - a server side that accepts a connection and then RESETS it (a broken proxy or database
#     path): the clients connect, get a RST, and try again
#   - a server port that REFUSES connections (nothing listens there: the service is down)
#   - a client that HOLDS many connections open to one server and does nothing with them
#     (a connection leak, or a holder that fills the server's connection limit)
#
# It reads the transmit events (net_dev_queue), which carry the TCP header with its flags.
#
# Usage:
#   python3 tcp_conns.py <net_slice.txt> <slice_seconds> [baseline_slice.txt]
#   python3 tcp_conns.py --selftest
#
#   <net_slice.txt>  20 s or more, cut with:
#        extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'net_dev_queue'
#   [baseline_slice.txt]  the same cut from before the suspect window. A connection pool also
#        holds idle connections; with a baseline the tool can say whether the holder is NEW.
import re
import sys
from collections import defaultdict

MIN_RESETS = 5         # new connections to one server that were accepted and then reset by it
                       # (clients that are reset every time back off: measured 12 attempts in
                       # 20 s where the same client made 922 before)
MIN_RESET_SHARE = 0.5  # ... and this share of all connections opened to that server
MIN_HELD = 50          # connections of one client to one server that stay open all slice
MIN_HELD_SHARE = 0.9   # ... and this share of that client's connections to it
MAX_HELD_BYTES = 1024  # ... each carrying at most this much payload (both ways): held, not used
NEW_SHARE = 0.1        # "new" = the baseline has under this share of the held count for that pair
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")
SYN, FIN, RST, ACK = 0x02, 0x01, 0x04, 0x10

re_ctx = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_dev = re.compile(r' name = "([^"]*)"')
re_ip = re.compile(r'ihl = (\d+), .*?tot_len = (\d+), .*?'
                   r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = \d+, ack_seq = \d+, '
                    r'data_offset = (\d+), .*?flags = 0x([0-9A-Fa-f]+)')


def read(lines):
    # conn (client ip, client port, server ip, server port) -> what was seen
    conns = defaultdict(lambda: {"syn": False, "synack": False, "end": False, "rst_s": False,
                                 "pay": defaultdict(lambda: [0, 0]), "who": defaultdict(int)})
    for line in lines:
        if ' net_dev_queue:' not in line:
            continue
        ip, tcp = re_ip.search(line), re_tcp.search(line)
        if not ip or not tcp:
            continue
        src, dst = ".".join(ip.groups()[2:6]), ".".join(ip.groups()[6:10])
        sp, dp, fl = int(tcp.group(1)), int(tcp.group(2)), int(tcp.group(4), 16)
        # The server is the side with the fixed port: below the ephemeral range, or the smaller one.
        from_client = (dp < 32768 <= sp) or (not (sp < 32768 <= dp) and dp < sp)
        c = conns[(src, sp, dst, dp) if from_client else (dst, dp, src, sp)]
        if fl & SYN:
            c["syn" if from_client else "synack"] = True
        if fl & (FIN | RST):
            c["end"] = True
        if fl & RST and not from_client:
            c["rst_s"] = True
        payload = int(ip.group(2)) - int(ip.group(1)) * 4 - int(tcp.group(3)) * 4
        if payload > 0:
            # one packet fires once per device it crosses: add up per device, take the largest
            d = re_dev.search(line)
            c["pay"][d.group(1) if d else "?"][0 if from_client else 1] += payload
        if from_client and (payload > 0 or fl & SYN):
            # the context of a transmit is whoever is on the CPU; only the client's data and
            # its SYN (sent from inside connect()) vote
            cx = re_ctx.search(line)
            if cx and not cx.group(2).startswith(KERNEL_CTX):
                pn = re_pidns.search(line)
                c["who"][(cx.group(2), pn.group(1) if pn else "?")] += 1
    return conns


def who(votes):
    if not votes:
        return "?"
    nm, ns = max(votes, key=votes.get)
    return f"{nm} (pid_ns {ns})"


def report(conns, secs, base=None):
    pairs = defaultdict(lambda: {"n": 0, "opened": 0, "ended": 0, "held": 0, "idle": 0, "bytes": 0,
                                 "who": defaultdict(int)})
    servers = defaultdict(lambda: {"opened": 0, "reset": 0, "refused": 0, "down": 0,
                                   "clients": defaultdict(lambda: defaultdict(int))})
    for (cip, cport, sip, sport), c in conns.items():
        up, down = max(c["pay"].values(), key=sum, default=(0, 0))
        p = pairs[(cip, sip, sport)]
        p["n"] += 1
        p["opened"] += c["syn"]
        p["ended"] += c["end"]
        p["bytes"] += up + down
        if not c["syn"] and not c["end"]:
            p["held"] += 1
            p["idle"] += up + down <= MAX_HELD_BYTES
        for k, v in c["who"].items():
            p["who"][k] += v
        if c["syn"]:
            s = servers[(sip, sport)]
            s["opened"] += 1
            s["down"] += down
            bad = c["rst_s"] and ("reset" if c["synack"] else "refused")
            if bad:
                s[bad] += 1
                for k, v in c["who"].items() or [(("?", "?"), 1)]:
                    s["clients"][cip][k] += v
    out = [f"TCP connections in this {secs:.0f} s slice: {len(conns)} connections, {len(pairs)} client-server pairs",
           "", "Servers that ended new connections with a RST",
           f"  {'server':<21} {'opened':>7} {'accepted, then reset':>21} {'refused':>8} {'clients':>8} {'kB back':>8}"]
    srows = sorted(servers.items(), key=lambda kv: -(kv[1]["reset"] + kv[1]["refused"]))
    srows = [r for r in srows if r[1]["reset"] + r[1]["refused"]]
    for (sip, sport), s in srows[:8]:
        out.append(f"  {sip + ':' + str(sport):<21} {s['opened']:>7} {s['reset']:>21} {s['refused']:>8} "
                   f"{len(s['clients']):>8} {s['down'] / 1e3:>8.1f}")
    if not srows:
        out.append("  none")
    out.append("  accepted, then reset = the server answered the SYN, then sent a RST; refused = RST with no answer to the SYN")
    out += ["", "Clients that hold connections open (not opened and not ended in the slice)",
            f"  {'client':<15} {'server':<21} {'conns':>6} {'opened':>7} {'ended':>6} {'held':>5} {'idle':>5} "
            f"{'before':>7}  client program"]
    prows = sorted(pairs.items(), key=lambda kv: -kv[1]["idle"])
    before = {}
    if base is not None:
        for (cip, cport, sip, sport) in base:
            before[(cip, sip, sport)] = before.get((cip, sip, sport), 0) + 1
    for k, p in prows[:8]:
        b = "-" if base is None else str(before.get(k, 0))
        out.append(f"  {k[0]:<15} {k[1] + ':' + str(k[2]):<21} {p['n']:>6} {p['opened']:>7} {p['ended']:>6} "
                   f"{p['held']:>5} {p['idle']:>5} {b:>7}  {who(p['who'])}")
    out.append(f"  idle = held with {MAX_HELD_BYTES} bytes of payload or less; before = connections of that pair in the baseline slice")
    hits = 0
    for (sip, sport), s in srows:
        cl = max(s["clients"].items(), key=lambda kv: sum(kv[1].values()))
        tail = f"{len(s['clients'])} clients, most from {who(cl[1])} at {cl[0]}"
        if s["reset"] >= MIN_RESETS and s["reset"] >= MIN_RESET_SHARE * s["opened"]:
            out.append(f"VERDICT: SERVER ACCEPTS AND THEN RESETS CONNECTIONS: {sip}:{sport} reset {s['reset']} of the "
                       f"{s['opened']} connections opened to it ({s['reset'] / s['opened']:.0%}); {tail}; "
                       f"{s['down'] / 1e3:.1f} kB came back")
            hits += 1
        elif s["refused"] >= MIN_RESETS and s["refused"] >= MIN_RESET_SHARE * s["opened"]:
            out.append(f"VERDICT: SERVER PORT REFUSES CONNECTIONS: {sip}:{sport} refused {s['refused']} of the "
                       f"{s['opened']} connections opened to it ({s['refused'] / s['opened']:.0%}), nothing listens there; {tail}")
            hits += 1
    for k, p in prows:
        if p["idle"] >= MIN_HELD and p["idle"] >= MIN_HELD_SHARE * p["n"]:
            what = (f"{who(p['who'])} at {k[0]} holds {p['idle']} connections to {k[1]}:{k[2]}; it opened {p['opened']} "
                    f"and ended {p['ended']} in the slice, {p['bytes'] / p['n']:.0f} bytes per connection")
            if base is None:
                out.append(f"VERDICT: CONNECTIONS HELD OPEN AND IDLE (no baseline given, so not known to be new): {what}")
            elif before.get(k, 0) < NEW_SHARE * p["idle"]:
                out.append(f"VERDICT: NEW CLIENT HOLDS CONNECTIONS OPEN AND IDLE: {what}; {before.get(k, 0)} in the baseline")
            else:
                out.append(f"NOTE: a standing pool, not new: {what}; {before.get(k, 0)} in the baseline")
                continue
            hits += 1
    if not hits:
        r = max(servers.values(), key=lambda s: s["reset"], default=None)
        h = max(pairs.values(), key=lambda p: p["idle"], default=None)
        out.append(f"VERDICT: NO RESET STORM, NO NEW HELD CONNECTIONS (most accepted-then-reset by one server: "
                   f"{r['reset'] if r else 0} of {r['opened'] if r else 0}; most idle held connections of one client: "
                   f"{h['idle'] if h else 0} of {h['n'] if h else 0}; the bars are {MIN_RESETS} and {MIN_HELD})")
    return out


def selftest():
    def addr(a):
        return ", ".join(f"[{i}] = {x}" for i, x in enumerate(a.split(".")))

    def q(t, nm, ns, src, sport, dst, dport, payload, flags):
        return (f'[10:00:{t:012.9f}] (+0.0) h net_dev_queue: {{ cpu_id = 1 }}, {{ pid = 7, tid = 7, procname = "{nm}", '
                f'pid_ns = {ns} }}, {{ skbaddr = 0x1, len = {payload + 40}, name = "eth0", network_header_type = 1, '
                f'network_header = {{ ipv4 = {{ version = 4, ihl = 5, tos = 0, tot_len = {payload + 40}, id = 0x1, frag_off = 0, '
                f'ttl = 64, protocol = 6, checksum = 0x0, saddr = [ {addr(src)} ], daddr = [ {addr(dst)} ], '
                f'transport_header_type = 1, transport_header = {{ tcp = {{ source_port = {sport}, dest_port = {dport}, '
                f'seq = 1, ack_seq = 1, data_offset = 5, reserved = 0, flags = 0x{flags:02x}, window_size = 64 }} }} }} }} }}')

    ls = []
    for i in range(30):                 # two apps -> proxy: accepted, then reset
        cl = "10.0.0.5" if i % 3 else "10.0.0.3"
        ls += [q(i * 0.1, "app", 5, cl, 40000 + i, "10.0.0.9", 3306, 0, 0x02),
               q(i * 0.1 + 0.001, "swapper/1", 1, "10.0.0.9", 3306, cl, 40000 + i, 0, 0x12),
               q(i * 0.1 + 0.002, "swapper/1", 1, "10.0.0.9", 3306, cl, 40000 + i, 0, 0x14)]
    for i in range(10):                 # a dead port: refused
        ls += [q(i * 0.1, "web", 4, "10.0.0.4", 41000 + i, "10.0.0.2", 5672, 0, 0x02),
               q(i * 0.1 + 0.001, "swapper/1", 1, "10.0.0.2", 5672, "10.0.0.4", 41000 + i, 0, 0x14)]
    hold = []
    for i in range(60):                 # holder -> db: 60 open connections, one ping each
        hold += [q(5 + i * 0.01, "python3", 8, "10.0.0.7", 50000 + i, "10.0.0.6", 3306, 5, 0x18),
                 q(5 + i * 0.01 + 0.001, "mysqld", 6, "10.0.0.6", 3306, "10.0.0.7", 50000 + i, 11, 0x18)]
    healthy = []
    for i in range(40):                 # a healthy client: open, talk, close
        healthy += [q(i * 0.2, "web", 4, "10.0.0.4", 42000 + i, "10.0.0.5", 80, 0, 0x02),
                    q(i * 0.2 + 0.0005, "app", 5, "10.0.0.5", 80, "10.0.0.4", 42000 + i, 0, 0x12),
                    q(i * 0.2 + 0.001, "web", 4, "10.0.0.4", 42000 + i, "10.0.0.5", 80, 300, 0x18),
                    q(i * 0.2 + 0.002, "app", 5, "10.0.0.5", 80, "10.0.0.4", 42000 + i, 900, 0x18),
                    q(i * 0.2 + 0.003, "web", 4, "10.0.0.4", 42000 + i, "10.0.0.5", 80, 0, 0x11)]
    out = "\n".join(report(read(ls + hold + healthy), 20, read(healthy)))
    assert "ACCEPTS AND THEN RESETS CONNECTIONS: 10.0.0.9:3306 reset 30 of the 30 connections opened to it (100%); 2 clients, most from app (pid_ns 5) at 10.0.0.5" in out, out
    assert "PORT REFUSES CONNECTIONS: 10.0.0.2:5672 refused 10 of the 10" in out, out
    assert "NEW CLIENT HOLDS CONNECTIONS OPEN AND IDLE: python3 (pid_ns 8) at 10.0.0.7 holds 60 connections to 10.0.0.6:3306; it opened 0 and ended 0" in out, out
    assert out.count("VERDICT") == 3, out
    out = "\n".join(report(read(hold + healthy), 20, read(hold)))
    assert "NOTE: a standing pool, not new" in out and "NO RESET STORM, NO NEW HELD CONNECTIONS (most accepted-then-reset by one server: 0 of 40" in out, out
    assert "no baseline given" in "\n".join(report(read(hold), 20)), out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: tcp_conns.py <net_slice.txt> <slice_seconds> [baseline_slice.txt]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        res = read(f)
    b = None
    if len(sys.argv) > 3:
        with open(sys.argv[3], errors="replace") as f:
            b = read(f)
    print("\n".join(report(res, float(sys.argv[2]), b)))
