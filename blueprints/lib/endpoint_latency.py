#!/usr/bin/env python3
"""How long does each service endpoint take to answer? Measured from packet headers alone.

WHY THE FIRST ATTEMPT FAILED (finding F5)
-----------------------------------------
socket_peer_wait.py grouped packets by `procname` and got nonsense - it reported a slowed
peer on the no-fault run too. Two wrong assumptions, both now disproved by the trace:

  1. `procname` on a network event is NOT the socket owner. Receive processing happens in
     softirq context, so the field holds whatever was on-CPU at the time. Measured: both
     directions of one flow attributed to `python3`, and elsewhere to `ksoftirqd` and
     `cadvisor`.
  2. There is no "us". This host runs every container, so it sees BOTH sides of every
     conversation. Treating one event type as outgoing and the other as incoming is
     meaningless here.

The second point is really a gift: seeing both sides means we can measure a service's true
response time from the host alone.

WHAT THIS MEASURES
------------------
Identify each flow by its address/port 4-tuple and ignore process names entirely. The SERVER
is the endpoint holding the well-known port (the lower one - 80, 3306, 8080, 27017 rather
than an ephemeral 41762). Then:

    request   any packet whose destination is the server endpoint
    response  any packet whose source is the server endpoint
    latency   request -> next response on the same flow

Reported per server endpoint, baseline window against incident window. Requests with no
response inside the cap are counted separately, because that - not slowness - is what a hung
dependency looks like.

    python3 endpoint_latency.py --ctf <ctf> --gt <ground_truth> --out endpoints.json
"""
from __future__ import annotations
import argparse, collections, json, os, re, statistics, subprocess, sys

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/bt21.sh")

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
SADDR = re.compile(r"saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]")
DADDR = re.compile(r"daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]")
PORTS = re.compile(r"source_port = (\d+), dest_port = (\d+)")

EPHEMERAL = 32768          # above this a port is a client's, not a service's
MAX_GAP_S = 2.0            # beyond this it is idleness, not a reply. F5's baselines of
                           # 1-5 SECONDS on a healthy system came from not capping this.


def secs(m):
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            + int(m.group(4)) / 1e9)


def hhmmss(iso):
    return iso.split("T")[1].rstrip("Z")


def unwrapper():
    """Trace timestamps are time-of-day and wrap at midnight (finding F8)."""
    state = {"day": 0.0, "prev": None}

    def fix(t):
        if state["prev"] is not None and t < state["prev"] - 43200:
            state["day"] += 86400.0
        state["prev"] = t
        return t + state["day"]
    return fix


def ip(m):
    return ".".join(m.group(i) for i in (1, 2, 3, 4)) if m else None


def server_of(a, b):
    """Which end of the flow is the service? The one with the well-known port."""
    (ia, pa), (ib, pb) = a, b
    if pa < EPHEMERAL and pb >= EPHEMERAL:
        return a
    if pb < EPHEMERAL and pa >= EPHEMERAL:
        return b
    return a if pa <= pb else b          # both or neither well-known: take the lower port


def scan(ctf, begin, end):
    """One window -> per-endpoint reply latencies, request/response counts, unanswered."""
    p1 = subprocess.Popen([BT2, ctf, "--begin", begin, "--end", end],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          env={**os.environ, "TZ": "UTC"})
    p2 = subprocess.Popen(["grep", "net_if_receive_skb:"], stdin=p1.stdout,
                          stdout=subprocess.PIPE, text=True, errors="replace")
    p1.stdout.close()

    unwrap = unwrapper()
    open_req = {}                                   # flow -> t of the request awaiting a reply
    lat = collections.defaultdict(list)             # server endpoint -> [latency seconds]
    req = collections.Counter()
    resp = collections.Counter()
    dropped = collections.Counter()                 # request never answered inside the cap

    for line in p2.stdout:
        mt, mp = TS.match(line), PORTS.search(line)
        if not (mt and mp):
            continue
        src, dst = ip(SADDR.search(line)), ip(DADDR.search(line))
        if not (src and dst):
            continue
        t = unwrap(secs(mt))
        a, b = (src, int(mp.group(1))), (dst, int(mp.group(2)))
        flow = (a, b) if a <= b else (b, a)         # canonical, so both directions agree
        srv = server_of(a, b)

        if b == srv:                                # heading TO the service: a request
            req[srv] += 1
            open_req.setdefault(flow, t)
        else:                                       # coming FROM the service: a response
            resp[srv] += 1
            t0 = open_req.pop(flow, None)
            if t0 is not None:
                gap = t - t0
                if 0 <= gap <= MAX_GAP_S:
                    lat[srv].append(gap)
                else:
                    dropped[srv] += 1

    p2.stdout.close()
    for p in (p2, p1):
        try:
            p.terminate()
        except Exception:                                              # noqa: BLE001
            pass

    # requests still open when the window closed: the frozen-dependency shape
    for flow in open_req:
        dropped[server_of(*flow)] += 1
    return lat, req, resp, dropped


def summarise(lat, req, resp, dropped, min_n=30):
    rows = []
    for srv in set(req) | set(resp):
        g = sorted(lat.get(srv, []))
        n_req = req.get(srv, 0)
        if n_req < min_n:
            continue
        rows.append({
            "endpoint": f"{srv[0]}:{srv[1]}", "port": srv[1],
            "requests": n_req, "responses": resp.get(srv, 0),
            "answered": len(g), "unanswered": dropped.get(srv, 0),
            "unanswered_ratio": round(dropped.get(srv, 0) / max(n_req, 1), 4),
            "p50_ms": round(g[len(g) // 2] * 1e3, 3) if g else None,
            "p95_ms": round(g[min(len(g) - 1, int(0.95 * len(g)))] * 1e3, 3) if g else None,
            "mean_ms": round(statistics.fmean(g) * 1e3, 3) if g else None,
        })
    rows.sort(key=lambda r: -(r["p95_ms"] or 0))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", default="endpoints.json")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    a = ap.parse_args()

    gt = json.load(open(a.gt))["fault"]
    t0 = hhmmss(gt["injection_start_utc"])

    def shift(hms, d):
        h, m, s = (int(x) for x in hms.split(":"))
        # F8: babeltrace reads an hour past 24 as the next day but rejects end<begin.
        v = max(0, h * 3600 + m * 60 + s + d)
        return f"{v//3600:02d}:{(v%3600)//60:02d}:{v%60:02d}"

    windows = {"baseline": (shift(t0, -a.baseline_s), t0),
               "incident": (t0, shift(t0, a.incident_s))}

    result = {"ctf": a.ctf, "windows": {}}
    for name, (b, e) in windows.items():
        print(f"decoding {name}: {b} -> {e} ...", flush=True)
        rows = summarise(*scan(a.ctf, b, e))
        result["windows"][name] = {"range": [b, e], "endpoints": rows}
        print(f"  {len(rows)} service endpoints with enough requests")

    base = {r["endpoint"]: r for r in result["windows"]["baseline"]["endpoints"]}
    inc = {r["endpoint"]: r for r in result["windows"]["incident"]["endpoints"]}

    comparison = []
    for ep in sorted(set(base) & set(inc)):
        bb, ii = base[ep], inc[ep]
        comparison.append({
            "endpoint": ep, "port": ii["port"],
            "p95_baseline_ms": bb["p95_ms"], "p95_incident_ms": ii["p95_ms"],
            "p95_x": (round(ii["p95_ms"] / bb["p95_ms"], 2)
                      if (bb["p95_ms"] and ii["p95_ms"]) else None),
            "unanswered_baseline": bb["unanswered_ratio"],
            "unanswered_incident": ii["unanswered_ratio"],
            "requests_incident": ii["requests"],
        })
    comparison.sort(key=lambda r: -(r["p95_x"] or 0))
    result["comparison"] = comparison

    slow = [r for r in comparison if (r["p95_x"] or 0) >= 2.0]
    # a hung dependency stops answering rather than answering slowly
    hung = [r for r in comparison
            if r["unanswered_incident"] >= 0.5 and r["unanswered_baseline"] < 0.2]
    result["signature"] = {
        "n_endpoints": len(comparison),
        "n_slowed_2x": len(slow),
        "slowest": slow[0] if slow else None,
        "slow_ports": sorted({r["port"] for r in slow}),
        "n_hung": len(hung),
        "hung_endpoints": [r["endpoint"] for r in hung][:5],
        "worst_unanswered_ratio": max([r["unanswered_incident"] for r in comparison],
                                      default=None),
    }

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}\n")
    print(f"{'endpoint':26s} {'base ms':>9s} {'inc ms':>9s} {'x':>7s} "
          f"{'unans b':>8s} {'unans i':>8s} {'reqs':>7s}")
    for r in comparison[:14]:
        print(f"{r['endpoint']:26s} {str(r['p95_baseline_ms']):>9s} "
              f"{str(r['p95_incident_ms']):>9s} {str(r['p95_x']):>7s} "
              f"{r['unanswered_baseline']:8.3f} {r['unanswered_incident']:8.3f} "
              f"{r['requests_incident']:7d}")
    s = result["signature"]
    print(f"\n{s['n_slowed_2x']} of {s['n_endpoints']} endpoints slowed 2x "
          f"(ports {s['slow_ports']}); {s['n_hung']} stopped answering {s['hung_endpoints']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
