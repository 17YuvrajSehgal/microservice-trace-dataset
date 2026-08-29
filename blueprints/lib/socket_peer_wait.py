#!/usr/bin/env python3
"""Who is each process talking to, and how long does that peer take to answer?

WHY THIS EXISTS (findings F2, F4)
---------------------------------
The datastore blueprint fires on anything that blocks a socket. Measured false fires:

    slow datastore      mysqld blocked in poll        36.8x   <- the real thing
    hung dependency     java blocked in poll          89.0x   <- wrong
    degraded network    node blocked in epoll_pwait  175.5x   <- wrong

The impostors give a STRONGER signal than the real fault, so no threshold separates them.
Syscall duration says a process is blocked; it cannot say blocked ON WHAT. That is the
missing question, and the trace can answer it: our kernel events carry full IP and TCP
headers, so every packet names its peer address and port.

WHAT THIS MEASURES
------------------
For each (process, peer) pair, the reply gap: the time from a packet sent to that peer until
the next packet received back from it. Reported per window, baseline against incident.

Three shapes should then be distinguishable, and this script exists to find out whether they
actually are - no rule is written here:

    slow datastore    ONE peer answers slowly; that peer is the datastore port
    degraded network  MANY peers answer slowly, or one interface degrades across peers
    hung dependency   packets go out to a peer and NOTHING comes back

    python3 socket_peer_wait.py --ctf <ctf> --gt <ground_truth> --out peers.json
"""
from __future__ import annotations
import argparse, collections, json, os, re, statistics, subprocess, sys

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/bt21.sh")

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
PROC = re.compile(r'procname = "([^"]*)"')
EVENT = re.compile(r"\] \([^)]+\) [^ ]+ (net_dev_queue|net_if_receive_skb):")
IFACE = re.compile(r'name = "([^"]*)"')
SADDR = re.compile(r"saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]")
DADDR = re.compile(r"daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]")
PORTS = re.compile(r"source_port = (\d+), dest_port = (\d+)")


def secs(m):
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            + int(m.group(4)) / 1e9)


def hhmmss(iso):
    return iso.split("T")[1].rstrip("Z")


def ip(m):
    return ".".join(m.group(i) for i in (1, 2, 3, 4)) if m else None


def scan(ctf, begin, end):
    """One window. Returns reply gaps per (proc, peer) and unanswered-request counts."""
    p1 = subprocess.Popen([BT2, ctf, "--begin", begin, "--end", end],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          env={**os.environ, "TZ": "UTC"})
    p2 = subprocess.Popen(["grep", "-E", "net_dev_queue|net_if_receive_skb"],
                          stdin=p1.stdout, stdout=subprocess.PIPE, text=True, errors="replace")
    p1.stdout.close()

    pending = {}                                   # (proc, peer) -> t_sent of oldest unanswered
    gaps = collections.defaultdict(list)           # (proc, peer) -> [reply gap seconds]
    sent = collections.Counter()
    recv = collections.Counter()
    ifaces = collections.defaultdict(collections.Counter)

    for line in p2.stdout:
        mt, me = TS.match(line), EVENT.search(line)
        if not (mt and me):
            continue
        t, ev = secs(mt), me.group(1)
        mp, mports = PROC.search(line), PORTS.search(line)
        if not (mp and mports):
            continue
        proc = mp.group(1)
        src, dst = ip(SADDR.search(line)), ip(DADDR.search(line))
        sport, dport = int(mports.group(1)), int(mports.group(2))
        mif = IFACE.search(line)

        if ev == "net_dev_queue":                  # outgoing: peer is the destination
            peer = (dst, dport)
            key = (proc, peer)
            sent[key] += 1
            pending.setdefault(key, t)             # oldest unanswered request wins
        else:                                      # incoming: peer is the source
            peer = (src, sport)
            key = (proc, peer)
            recv[key] += 1
            t0 = pending.pop(key, None)
            if t0 is not None and 0 <= t - t0 < 30.0:
                gaps[key].append(t - t0)
        if mif:
            ifaces[proc][mif.group(1)] += 1

    p2.stdout.close()
    for p in (p2, p1):
        try:
            p.terminate()
        except Exception:                                              # noqa: BLE001
            pass

    # requests still waiting when the window ended: the frozen-dependency shape
    unanswered = collections.Counter()
    for key in pending:
        unanswered[key] += 1
    return gaps, sent, recv, unanswered, ifaces


def summarise(gaps, sent, recv, unanswered, min_n=20):
    rows = []
    for key, g in gaps.items():
        if len(g) < min_n:
            continue
        g = sorted(g)
        proc, (peer_ip, peer_port) = key
        rows.append({
            "process": proc, "peer_ip": peer_ip, "peer_port": peer_port,
            "n": len(g),
            "p50_ms": round(g[len(g) // 2] * 1e3, 3),
            "p95_ms": round(g[min(len(g) - 1, int(0.95 * len(g)))] * 1e3, 3),
            "mean_ms": round(statistics.fmean(g) * 1e3, 3),
            "sent": sent.get(key, 0), "received": recv.get(key, 0),
            "reply_ratio": round(recv.get(key, 0) / max(sent.get(key, 1), 1), 3),
        })
    rows.sort(key=lambda r: -r["p95_ms"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", default="peers.json")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    a = ap.parse_args()

    gt = json.load(open(a.gt))["fault"]
    t0 = hhmmss(gt["injection_start_utc"])

    def shift(hms, d):
        h, m, s = (int(x) for x in hms.split(":"))
        v = max(0, h * 3600 + m * 60 + s + d)
        return f"{v//3600:02d}:{(v%3600)//60:02d}:{v%60:02d}"

    windows = {"baseline": (shift(t0, -a.baseline_s), t0),
               "incident": (t0, shift(t0, a.incident_s))}

    result = {"ctf": a.ctf, "windows": {}}
    for name, (b, e) in windows.items():
        print(f"decoding {name}: {b} -> {e} ...", flush=True)
        gaps, sent, recv, unans, ifaces = scan(a.ctf, b, e)
        rows = summarise(gaps, sent, recv, unans)
        result["windows"][name] = {
            "range": [b, e],
            "peers": rows[:40],
            "n_peer_pairs": len(rows),
            "total_sent": sum(sent.values()), "total_received": sum(recv.values()),
        }
        print(f"  {len(rows)} (process,peer) pairs with enough samples")

    base = {(r["process"], r["peer_ip"], r["peer_port"]): r
            for r in result["windows"]["baseline"]["peers"]}
    inc = {(r["process"], r["peer_ip"], r["peer_port"]): r
           for r in result["windows"]["incident"]["peers"]}

    comparison = []
    for k in sorted(set(base) | set(inc), key=str):
        b, i = base.get(k), inc.get(k)
        if not b or not i:
            continue
        comparison.append({
            "process": k[0], "peer_ip": k[1], "peer_port": k[2],
            "p95_baseline_ms": b["p95_ms"], "p95_incident_ms": i["p95_ms"],
            "p95_x": round(i["p95_ms"] / b["p95_ms"], 2) if b["p95_ms"] else None,
            "reply_ratio_baseline": b["reply_ratio"],
            "reply_ratio_incident": i["reply_ratio"],
            "n_incident": i["n"],
        })
    comparison.sort(key=lambda r: -(r["p95_x"] or 0))
    result["comparison"] = comparison

    slow = [r for r in comparison if (r["p95_x"] or 0) >= 2.0]
    result["signature"] = {
        "n_peers_compared": len(comparison),
        "n_peers_slowed_2x": len(slow),
        # ONE slow peer = something specific is slow. MANY = the path itself is degraded.
        "slowest_peer": slow[0] if slow else None,
        "slow_peer_ports": sorted({r["peer_port"] for r in slow}),
        "worst_reply_ratio": min([r["reply_ratio_incident"] for r in comparison], default=None),
    }

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}\n")
    print(f"{'process':16s} {'peer':24s} {'base ms':>9s} {'inc ms':>9s} {'x':>7s} {'reply':>6s}")
    for r in comparison[:14]:
        print(f"{r['process'][:16]:16s} {r['peer_ip']}:{r['peer_port']:<10} "
              f"{r['p95_baseline_ms']:9.3f} {r['p95_incident_ms']:9.3f} "
              f"{str(r['p95_x']):>7s} {r['reply_ratio_incident']:6.2f}")
    s = result["signature"]
    print(f"\n{s['n_peers_slowed_2x']} of {s['n_peers_compared']} peers slowed 2x or more; "
          f"ports affected: {s['slow_peer_ports']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
