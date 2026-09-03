#!/usr/bin/env python3
"""Who is using the disk, and how long are requests taking? From the block layer.

WHY THIS EXISTS
---------------
The disk fault has never been attempted. It is only ever tested as something to decline, yet
the events needed are in every trace we hold: block_rq_issue carries the device, sector, byte
count AND the process that issued the request, and block_rq_complete closes it. Matching the
two gives a real service time.

`fault_catalog.md` pre-registers the shape: "the KERNEL disambiguates - block_rq_* dominated
by the stressor, DB threads in D-state waits". So this measures both halves:

    WHO       requests and bytes per process, baseline vs incident. A disk stressor should
              appear the way a CPU stressor does - lots of work it was not doing before.
    HOW LONG  issue -> complete latency per device. If the device is saturated, everyone
              else's requests queue behind the stressor's.
    DEPTH     how many requests are in flight at once, which is what saturation looks like
              from the device's side.

Deliberately mirrors oncpu_share.py: "who took the resource" plus "how much did everyone else
wait". That pairing is what made the CPU cluster separable.

    python3 block_io_signature.py --ctf <ctf> --gt <ground_truth> --out blockio.json
"""
from __future__ import annotations
import argparse, collections, json, os, re, statistics, subprocess, sys

# Shared reader: with CTF_CACHE_DIR set this reads a pre-extracted family file
# instead of decoding the trace again. Our own grep still runs on top either way,
# so this script sees exactly the lines it always did. See ctf_stream.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctf_stream                                                      # noqa: E402

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/bt21.sh")

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
EVENT = re.compile(r"\] \([^)]+\) [^ ]+ (block_rq_issue|block_rq_complete):")
DEV = re.compile(r"dev = (\d+)")
SECTOR = re.compile(r"sector = (\d+)")
NRSEC = re.compile(r"nr_sector = (\d+)")
# `comm` is the LAST field of block_rq_issue and is the process that issued the request -
# unlike the network events, where procname is only whatever was on-CPU at the time.
COMM = re.compile(r'comm = "([^"]*)"')
MAX_LATENCY_S = 5.0        # beyond this the match is almost certainly a reused sector


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


def scan(ctf, begin, end):
    p2out, _bt = ctf_stream.open_lines(ctf, begin, end,
                                      'block_rq_issue|block_rq_complete', family="block")

    unwrap = unwrapper()
    inflight = {}                                   # (dev, sector) -> (t_issue, comm)
    lat = collections.defaultdict(list)             # dev -> [service time seconds]
    reqs = collections.Counter()                    # comm -> requests issued
    sectors = collections.Counter()                 # comm -> sectors written/read
    depth_peak = 0
    depth_sum = depth_n = 0
    t_first = t_last = None

    for line in p2out:
        mt, me = TS.match(line), EVENT.search(line)
        if not (mt and me):
            continue
        md, msec = DEV.search(line), SECTOR.search(line)
        if not (md and msec):
            continue
        t = unwrap(secs(mt))
        if t_first is None:
            t_first = t
        t_last = t
        key = (md.group(1), msec.group(1))

        if me.group(1) == "block_rq_issue":
            mc, mn = COMM.search(line), NRSEC.search(line)
            comm = mc.group(1) if mc else "?"
            reqs[comm] += 1
            sectors[comm] += int(mn.group(1)) if mn else 0
            inflight[key] = (t, comm)
            depth_peak = max(depth_peak, len(inflight))
            depth_sum += len(inflight)
            depth_n += 1
        else:
            prior = inflight.pop(key, None)
            if prior is not None:
                d = t - prior[0]
                if 0 <= d <= MAX_LATENCY_S:
                    lat[md.group(1)].append(d)

    ctf_stream.close_lines(_bt)
    span = (t_last - t_first) if (t_first is not None and t_last is not None) else 0.0
    return {"lat": dict(lat), "reqs": reqs, "sectors": sectors, "span": span,
            "depth_peak": depth_peak,
            "depth_mean": round(depth_sum / depth_n, 2) if depth_n else 0.0}


def summarise(s, min_n=50):
    span = s["span"] or 1e-9
    devs = []
    for dev, g in s["lat"].items():
        if len(g) < min_n:
            continue
        g = sorted(g)
        devs.append({
            "dev": dev, "n": len(g),
            "p50_ms": round(g[len(g) // 2] * 1e3, 3),
            "p95_ms": round(g[min(len(g) - 1, int(0.95 * len(g)))] * 1e3, 3),
            "mean_ms": round(statistics.fmean(g) * 1e3, 3),
            "iops": round(len(g) / span, 1),
        })
    devs.sort(key=lambda r: -r["p95_ms"])
    total = sum(s["reqs"].values()) or 1
    procs = [{"comm": c, "requests": n, "share": round(n / total, 4),
              "sectors": s["sectors"].get(c, 0),
              "iops": round(n / span, 1)}
             for c, n in s["reqs"].most_common(15)]
    return {"window_span_s": round(span, 3), "devices": devs, "top_processes": procs,
            "total_requests": total, "total_iops": round(total / span, 1),
            "queue_depth_peak": s["depth_peak"], "queue_depth_mean": s["depth_mean"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", default="blockio.json")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    ap.add_argument("--newcomer-iops", type=float, default=20.0,
                    help="a process must gain at least this many requests per second to count "
                         "as having arrived on the disk")
    a = ap.parse_args()

    gt = json.load(open(a.gt))["fault"]
    t0 = hhmmss(gt["injection_start_utc"])

    def shift(hms, d):
        h, m, s = (int(x) for x in hms.split(":"))
        v = max(0, h * 3600 + m * 60 + s + d)       # F8: keep hour>=24, never wrap
        return f"{v//3600:02d}:{(v%3600)//60:02d}:{v%60:02d}"

    windows = {"baseline": (shift(t0, -a.baseline_s), t0),
               "incident": (t0, shift(t0, a.incident_s))}

    result = {"ctf": a.ctf, "windows": {}}
    for name, (b, e) in windows.items():
        print(f"decoding {name}: {b} -> {e} ...", flush=True)
        w = summarise(scan(a.ctf, b, e))
        result["windows"][name] = {"range": [b, e], **w}
        print(f"  {w['total_requests']} requests ({w['total_iops']}/s), "
              f"{len(w['devices'])} devices, queue depth mean {w['queue_depth_mean']} "
              f"peak {w['queue_depth_peak']}")

    wb, wi = result["windows"]["baseline"], result["windows"]["incident"]
    bp = {p["comm"]: p for p in wb["top_processes"]}
    ip = {p["comm"]: p for p in wi["top_processes"]}
    gained = []
    for comm in sorted(set(bp) | set(ip)):
        b_iops = bp.get(comm, {}).get("iops", 0.0)
        i_iops = ip.get(comm, {}).get("iops", 0.0)
        gained.append({"comm": comm, "iops_baseline": b_iops, "iops_incident": i_iops,
                       "iops_gained": round(i_iops - b_iops, 1),
                       "share_incident": ip.get(comm, {}).get("share", 0.0)})
    gained.sort(key=lambda r: -r["iops_gained"])
    result["iops_delta"] = gained

    bd = {d["dev"]: d for d in wb["devices"]}
    dev_cmp = []
    for d in wi["devices"]:
        b = bd.get(d["dev"])
        if not b:
            continue
        dev_cmp.append({"dev": d["dev"],
                        "p95_baseline_ms": b["p95_ms"], "p95_incident_ms": d["p95_ms"],
                        "p95_x": round(d["p95_ms"] / b["p95_ms"], 2) if b["p95_ms"] else None,
                        "iops_baseline": b["iops"], "iops_incident": d["iops"]})
    dev_cmp.sort(key=lambda r: -(r["p95_x"] or 0))
    result["device_comparison"] = dev_cmp

    newcomer = next((g for g in gained if g["iops_gained"] >= a.newcomer_iops), None)
    result["signature"] = {
        "io_newcomer": newcomer["comm"] if newcomer else None,
        "io_newcomer_iops_gained": newcomer["iops_gained"] if newcomer else 0.0,
        "io_newcomer_share": newcomer["share_incident"] if newcomer else 0.0,
        "total_iops_baseline": wb["total_iops"], "total_iops_incident": wi["total_iops"],
        "total_iops_x": (round(wi["total_iops"] / wb["total_iops"], 2)
                         if wb["total_iops"] else None),
        "worst_device_p95_x": dev_cmp[0]["p95_x"] if dev_cmp else None,
        "worst_device_p95_ms": dev_cmp[0]["p95_incident_ms"] if dev_cmp else None,
        "queue_depth_baseline": wb["queue_depth_mean"],
        "queue_depth_incident": wi["queue_depth_mean"],
        "queue_depth_x": (round(wi["queue_depth_mean"] / wb["queue_depth_mean"], 2)
                          if wb["queue_depth_mean"] else None),
    }

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}\n")
    print(f"{'process':22s} {'iops base':>10s} {'iops inc':>10s} {'gained':>9s} {'share':>7s}")
    for g in gained[:10]:
        print(f"{g['comm'][:22]:22s} {g['iops_baseline']:10.1f} {g['iops_incident']:10.1f} "
              f"{g['iops_gained']:9.1f} {g['share_incident']:7.3f}")
    s = result["signature"]
    print(f"\nnewcomer on disk: {s['io_newcomer']} (+{s['io_newcomer_iops_gained']} req/s, "
          f"{100*s['io_newcomer_share']:.0f}% of all I/O)")
    print(f"total I/O {s['total_iops_baseline']} -> {s['total_iops_incident']} req/s "
          f"({s['total_iops_x']}x); device p95 {s['worst_device_p95_x']}x "
          f"({s['worst_device_p95_ms']} ms); queue depth "
          f"{s['queue_depth_baseline']} -> {s['queue_depth_incident']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
