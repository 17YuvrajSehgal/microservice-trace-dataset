#!/usr/bin/env python3
"""Which conversations died, and which kept going? Per network flow.

WHY THIS EXISTS
---------------
The queue-backlog fault pauses the sole consumer of a message queue. Orders keep succeeding,
nothing errors, and `fault_catalog.md` calls it the hardest detection case in the catalogue -
"a silent degradation fault with NO user-visible error". Its pre-registered kernel signature
is a PAIR: the consumer falls silent while the broker keeps working.

That pairing is the thing worth testing, because it is what should separate it from the other
`docker pause` fault. Both freeze a container. The difference is where the container sits:

    queue backlog     the paused service is OFF the request path. The broker keeps talking to
                      everyone else; it just loses ONE peer.
    hung dependency   the paused service is ON the request path. Its callers stall, so its
                      peers degrade too.

So: count packets per flow in both windows, then ask - for each endpoint, how many of its
conversation partners went silent, and how many carried on? An endpoint that loses exactly one
peer while keeping the rest is a different shape from one that loses all of them.

Earlier attempts to see a frozen container through the SCHEDULER failed (findings F11, F12):
process names are shared between containers, healthy runs also have threads stopping, and the
freezer does not stop the kernel waking a task. Flows do not have that problem - a paused
container's connections simply stop carrying traffic.

    python3 flow_activity.py --ctf <ctf> --gt <ground_truth> --out flows.json
"""
from __future__ import annotations
import argparse, collections, json, os, re, subprocess, sys

# Shared reader: with CTF_CACHE_DIR set this reads a pre-extracted family file
# instead of decoding the trace again. Our own grep still runs on top either way,
# so this script sees exactly the lines it always did. See ctf_stream.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctf_stream                                                      # noqa: E402

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/bt21.sh")

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
SADDR = re.compile(r"saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]")
DADDR = re.compile(r"daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]")
PORTS = re.compile(r"source_port = (\d+), dest_port = (\d+)")
TOTLEN = re.compile(r"tot_len = (\d+)")

EPHEMERAL = 32768
# A "conversation partner" is an address pair, not a socket. One service opens many short
# connections to another; those are the same partner, and counting sockets would drown the
# signal in ordinary connection churn.


def secs(m):
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            + int(m.group(4)) / 1e9)


def hhmmss(iso):
    return iso.split("T")[1].rstrip("Z")


def ip(m):
    return ".".join(m.group(i) for i in (1, 2, 3, 4)) if m else None


def scan(ctf, begin, end):
    """One window -> packets and bytes per (service endpoint, peer address)."""
    p2out, _bt = ctf_stream.open_lines(ctf, begin, end,
                                      'net_if_receive_skb:', family="net")

    pkts = collections.Counter()          # (endpoint, peer_ip) -> packets
    byts = collections.Counter()
    for line in p2out:
        mp = PORTS.search(line)
        if not (mp and TS.match(line)):
            continue
        src, dst = ip(SADDR.search(line)), ip(DADDR.search(line))
        if not (src and dst):
            continue
        sp, dp = int(mp.group(1)), int(mp.group(2))
        # the service side of the conversation is the well-known port
        if sp < EPHEMERAL and dp >= EPHEMERAL:
            endpoint, peer = (src, sp), dst
        elif dp < EPHEMERAL and sp >= EPHEMERAL:
            endpoint, peer = (dst, dp), src
        elif sp <= dp:
            endpoint, peer = (src, sp), dst
        else:
            endpoint, peer = (dst, dp), src
        ml = TOTLEN.search(line)
        pkts[(endpoint, peer)] += 1
        byts[(endpoint, peer)] += int(ml.group(1)) if ml else 0

    ctf_stream.close_lines(_bt)
    return pkts, byts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", default="flows.json")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    ap.add_argument("--min-packets", type=int, default=100,
                    help="a partner must have carried at least this many packets in the "
                         "baseline to count as a real conversation")
    ap.add_argument("--silent-frac", type=float, default=0.05,
                    help="a partner counts as gone if its packet rate falls to this fraction")
    a = ap.parse_args()

    gt = json.load(open(a.gt))["fault"]
    t0 = hhmmss(gt["injection_start_utc"])

    def shift(hms, d):
        h, m, s = (int(x) for x in hms.split(":"))
        v = max(0, h * 3600 + m * 60 + s + d)       # F8: keep hour>=24, never wrap
        return f"{v//3600:02d}:{(v%3600)//60:02d}:{v%60:02d}"

    wins = {"baseline": (shift(t0, -a.baseline_s), t0),
            "incident": (t0, shift(t0, a.incident_s))}

    got = {}
    for name, (b, e) in wins.items():
        print(f"decoding {name}: {b} -> {e} ...", flush=True)
        got[name] = scan(a.ctf, b, e)
        print(f"  {len(got[name][0])} endpoint-peer conversations")

    bp, bb = got["baseline"]
    ip_, ib = got["incident"]
    # per-second, so the two windows are comparable even at different lengths
    bs, isec = max(a.baseline_s, 1), max(a.incident_s, 1)

    per_endpoint = collections.defaultdict(lambda: {"kept": 0, "gone": 0, "grew": 0,
                                                    "gone_peers": [], "pkts_b": 0, "pkts_i": 0})
    conversations = []
    for key, n in bp.items():
        if n < a.min_packets:
            continue
        endpoint, peer = key
        rb, ri = n / bs, ip_.get(key, 0) / isec
        ep = f"{endpoint[0]}:{endpoint[1]}"
        e = per_endpoint[ep]
        e["pkts_b"] += n
        e["pkts_i"] += ip_.get(key, 0)
        if ri <= rb * a.silent_frac:
            e["gone"] += 1
            e["gone_peers"].append(peer)
        else:
            e["kept"] += 1
            if ri >= rb * 1.5:
                e["grew"] += 1
        conversations.append({"endpoint": ep, "peer": peer,
                              "pkts_per_s_baseline": round(rb, 1),
                              "pkts_per_s_incident": round(ri, 1),
                              "ratio": round(ri / rb, 3) if rb else None,
                              "bytes_baseline": bb.get(key, 0),
                              "bytes_incident": ib.get(key, 0)})
    conversations.sort(key=lambda r: r["ratio"] if r["ratio"] is not None else 9e9)

    rows = []
    for ep, e in per_endpoint.items():
        total = e["kept"] + e["gone"]
        rows.append({"endpoint": ep, "peers": total, "peers_gone": e["gone"],
                     "peers_kept": e["kept"], "peers_grew": e["grew"],
                     "gone_peers": e["gone_peers"][:5],
                     "packets_baseline": e["pkts_b"], "packets_incident": e["pkts_i"],
                     "packet_ratio": (round((e["pkts_i"] / isec) / (e["pkts_b"] / bs), 3)
                                      if e["pkts_b"] else None)})
    rows.sort(key=lambda r: (-r["peers_gone"], r["endpoint"]))

    # THE SHAPE. An endpoint that loses SOME partners while keeping others is a broker whose
    # consumer stopped. An endpoint that loses ALL of them is a service that was itself frozen.
    partial = [r for r in rows if r["peers_gone"] >= 1 and r["peers_kept"] >= 1]
    total_loss = [r for r in rows if r["peers_gone"] >= 1 and r["peers_kept"] == 0]
    result = {
        "ctf": a.ctf, "windows": {k: list(v) for k, v in wins.items()},
        "endpoints": rows[:30], "conversations": conversations[:40],
        "signature": {
            "n_endpoints": len(rows),
            "n_endpoints_losing_some_peers": len(partial),
            "n_endpoints_losing_all_peers": len(total_loss),
            "worst_partial": partial[0] if partial else None,
            "worst_total_loss": total_loss[0] if total_loss else None,
            "total_peers_gone": sum(r["peers_gone"] for r in rows),
            "n_endpoints_that_grew": sum(1 for r in rows if r["peers_grew"] > 0),
        },
    }

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}\n")
    print(f"{'endpoint':24s} {'peers':>6s} {'gone':>5s} {'kept':>5s} {'grew':>5s} {'pkt ratio':>10s}")
    for r in rows[:12]:
        print(f"{r['endpoint']:24s} {r['peers']:6d} {r['peers_gone']:5d} {r['peers_kept']:5d} "
              f"{r['peers_grew']:5d} {str(r['packet_ratio']):>10s}")
    s = result["signature"]
    print(f"\n{s['n_endpoints_losing_some_peers']} endpoint(s) lost SOME peers but kept others; "
          f"{s['n_endpoints_losing_all_peers']} lost ALL; "
          f"{s['total_peers_gone']} conversations went silent overall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
