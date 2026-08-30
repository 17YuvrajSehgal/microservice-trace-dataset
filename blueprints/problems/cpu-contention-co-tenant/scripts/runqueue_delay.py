#!/usr/bin/env python3
"""Runqueue delay per service, straight from the raw LTTng trace (L0) via babeltrace2.

This is the textbook CPU-contention metric and it is NOT what the derived L2 record
reports. L2's `runnable_wait` is a share of a service's total wall time, which is dominated
by ordinary idle waiting, so it stays near 1-4% no matter what is wrong. Runqueue delay is a
per-wakeup latency: how long a thread sat READY before a CPU actually ran it. Contention
shows up here even when it is invisible in the share.

Definition, measured from two tracepoints only:
    sched_waking  payload tid = T  at t_wake     ->  thread T becomes runnable
    sched_switch  next_tid  = T    at t_run      ->  thread T actually gets a CPU
    runqueue delay = t_run - t_wake

Baseline and incident windows are decoded separately so the comparison is like-for-like.

    python3 runqueue_delay.py --ctf <ctf_dir> --gt <ground_truth.json> --out rq.json
"""
from __future__ import annotations
import argparse, collections, json, os, re, statistics, subprocess, sys

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/bt21.sh")

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
# sched_waking payload: { comm = "X", tid = N, prio = P, target_cpu = C }
WAKING = re.compile(r'sched_waking:.*?\{ comm = "([^"]*)", tid = (\d+)')
# sched_switch payload: { prev_comm = ..., next_comm = "X", next_tid = N }
SWITCH = re.compile(r'sched_switch:.*?next_comm = "([^"]*)", next_tid = (\d+)')


def secs(m):
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1e9


def hhmmss(iso):
    """'2026-07-28T22:04:49Z' -> '22:04:49' (trace timestamps are wall-clock, forced to UTC)."""
    return iso.split("T")[1].rstrip("Z")


def unwrapper():
    """Trace timestamps are wall-clock time-of-day, so they wrap to zero at midnight. This
    returns a function that adds a day each time it sees the clock jump backwards, so a
    window crossing midnight still has monotonic time and a positive span."""
    state = {"day": 0.0, "prev": None}

    def fix(t):
        if state["prev"] is not None and t < state["prev"] - 43200:
            state["day"] += 86400.0
        state["prev"] = t
        return t + state["day"]
    return fix


def scan(ctf, begin, end, cap_events=0):
    """Decode ONE window and return {tid: [delay_seconds, ...]} plus tid->comm."""
    cmd = [BT2, ctf, "--begin", begin, "--end", end]
    env = {**os.environ, "TZ": "UTC"}
    p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    p2 = subprocess.Popen(["grep", "-E", "sched_waking|sched_switch"], stdin=p1.stdout,
                          stdout=subprocess.PIPE, text=True, errors="replace")
    p1.stdout.close()

    unwrap = unwrapper()   # window may cross midnight

    wake = {}                                   # tid -> t_wake (most recent)
    delays = collections.defaultdict(list)      # tid -> [delay]
    comm = {}                                   # tid -> comm
    n = 0
    for line in p2.stdout:
        m = TS.match(line)
        if not m:
            continue
        t = unwrap(secs(m))
        w = WAKING.search(line)
        if w:
            c, tid = w.group(1), int(w.group(2))
            comm[tid] = c
            wake[tid] = t                        # last wake wins (re-wake before running)
            continue
        s = SWITCH.search(line)
        if s:
            c, tid = s.group(1), int(s.group(2))
            comm[tid] = c
            t0 = wake.pop(tid, None)
            if t0 is not None and t >= t0:
                d = t - t0
                if d < 10.0:                     # guard against window-edge artifacts
                    delays[tid].append(d)
            n += 1
            if cap_events and n >= cap_events:
                break
    p2.stdout.close()
    for p in (p2, p1):
        try:
            p.terminate()
        except Exception:                                              # noqa: BLE001
            pass
    return delays, comm


def by_service(delays, comm, svc_of):
    out = collections.defaultdict(list)
    for tid, ds in delays.items():
        out[svc_of(comm.get(tid, ""))].extend(ds)
    return out


def stats(ds):
    if not ds:
        return None
    ds = sorted(ds)
    q = lambda p: ds[min(len(ds) - 1, int(p * len(ds)))]
    return {"n": len(ds),
            "p50_ms": round(q(0.50) * 1e3, 3),
            "p95_ms": round(q(0.95) * 1e3, 3),
            "p99_ms": round(q(0.99) * 1e3, 3),
            "max_ms": round(ds[-1] * 1e3, 3),
            "mean_ms": round(statistics.fmean(ds) * 1e3, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True, help="ground_truth.json (for the fault window)")
    ap.add_argument("--out", default="rq.json")
    ap.add_argument("--baseline-s", type=int, default=55,
                    help="seconds of baseline to read, ending at the fault start")
    ap.add_argument("--incident-s", type=int, default=60,
                    help="seconds of the fault window to read")
    ap.add_argument("--app", default="sockshop")
    a = ap.parse_args()

    gt = json.load(open(a.gt))["fault"]
    t0, t1 = hhmmss(gt["injection_start_utc"]), hhmmss(gt["injection_end_utc"])

    def shift(hms, delta):
        h, m, s = (int(x) for x in hms.split(":"))
        # MEASURED against babeltrace: an end of "24:00:21" is accepted and read as the
        # next day, but wrapping it to "00:00:21" against a begin of "23:59:21" makes the
        # trimmer reject the window and return nothing. So an end that runs past midnight
        # must stay past 24. The midnight problem is handled in unwrapper(), not here.
        v = max(0, h * 3600 + m * 60 + s + delta)
        return f"{v//3600:02d}:{(v%3600)//60:02d}:{v%60:02d}"

    windows = {
        "baseline": (shift(t0, -a.baseline_s), t0),
        "incident": (t0, shift(t0, a.incident_s)),
    }

    sys.path.insert(0, "/scratch/yuvraj17/microservice-trace-dataset/stratatrace")
    try:
        os.environ.setdefault("STRATATRACE_APP", a.app)
        from service_map import COMM_SERVICE, SVC_COMM
        comm2svc = dict(COMM_SERVICE)
        for svc, c in (SVC_COMM or {}).items():
            comm2svc.setdefault(c, svc)
    except Exception:                                                  # noqa: BLE001
        comm2svc = {"stress-ng": "aggressor", "stress-ng-cpu": "aggressor"}

    def svc_of(c):
        return comm2svc.get(c, c or "?")

    result = {"ctf": a.ctf, "fault_window_utc": [gt["injection_start_utc"], gt["injection_end_utc"]],
              "target_service": gt.get("target_service"), "windows": {}}
    for name, (b, e) in windows.items():
        print(f"decoding {name}: {b} -> {e} ...", flush=True)
        delays, comm = scan(a.ctf, b, e)
        svc = by_service(delays, comm, svc_of)
        result["windows"][name] = {"range": [b, e],
                                   "per_service": {k: stats(v) for k, v in svc.items() if v}}
        print(f"  {sum(len(v) for v in svc.values())} wake->run pairs across {len(svc)} comms")

    base = result["windows"]["baseline"]["per_service"]
    inc = result["windows"]["incident"]["per_service"]
    comparison = []
    for s in sorted(set(base) | set(inc)):
        b, i = base.get(s), inc.get(s)
        if not b or not i or b["n"] < 20 or i["n"] < 20:
            continue
        comparison.append({
            "service": s,
            "p95_baseline_ms": b["p95_ms"], "p95_incident_ms": i["p95_ms"],
            "p95_x": round(i["p95_ms"] / b["p95_ms"], 2) if b["p95_ms"] else None,
            "p99_baseline_ms": b["p99_ms"], "p99_incident_ms": i["p99_ms"],
            "n_baseline": b["n"], "n_incident": i["n"],
        })
    comparison.sort(key=lambda r: -(r["p95_x"] or 0))
    result["comparison"] = comparison

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}\n")
    print(f"{'service':22s} {'p95 base':>10s} {'p95 inc':>10s} {'x':>7s} {'n_inc':>8s}")
    for r in comparison[:14]:
        print(f"{r['service']:22s} {r['p95_baseline_ms']:9.3f}ms {r['p95_incident_ms']:9.3f}ms "
              f"{str(r['p95_x']):>7s} {r['n_incident']:8d}")


if __name__ == "__main__":
    sys.exit(main())
