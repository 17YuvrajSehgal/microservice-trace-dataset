#!/usr/bin/env python3
"""How long a component blocks inside each syscall, straight from the raw LTTng trace (L0).

The complement of runqueue delay. Runqueue delay answers "was it waiting for a CPU?".
This answers "when it was off-CPU, what was it blocked IN, and for how long?".

Measured from the syscall boundary only:
    syscall_entry_<name>  tid = T  at t0
    syscall_exit_<name>   tid = T  at t1        ->  blocked duration = t1 - t0

A datastore that is being slowed from outside spends its time in network-read syscalls
(recvfrom / read / epoll_wait on its client socket) with durations that inflate against the
baseline, while its CPU stays idle. A service pinned by its own CPU limit does not: its
syscall durations stay flat and its runqueue delay is what moves.

Reported per (comm, syscall): count and duration percentiles, baseline vs incident.

    python3 blocking_syscall.py --ctf <ctf_dir> --gt <ground_truth.json> \
        --comms mysqld,app --out blocking.json
"""
from __future__ import annotations
import argparse, collections, json, os, re, statistics, subprocess, sys

# Shared reader: with CTF_CACHE_DIR set this reads a pre-extracted family file
# instead of decoding the trace again. Our own grep still runs on top either way,
# so this script sees exactly the lines it always did. See ctf_stream.py.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "lib"))
import ctf_stream                                                      # noqa: E402

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/bt21.sh")

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
EV = re.compile(r"\] \([^)]*\) \S+ syscall_(entry|exit)_([a-z0-9_]+):")
CTX = re.compile(r'\{ cpu_id = \d+ \}, \{ pid = (\d+), tid = (\d+), procname = "([^"]*)"')


def secs(m):
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1e9


def hhmmss(iso):
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


def shift(hms, delta):
    h, m, s = (int(x) for x in hms.split(":"))
    # MEASURED against babeltrace: an end of "24:00:21" is accepted and read as the
    # next day, but wrapping it to "00:00:21" against a begin of "23:59:21" makes the
    # trimmer reject the window and return nothing. So an end that runs past midnight
    # must stay past 24. The midnight problem is handled in unwrapper(), not here.
    v = max(0, h * 3600 + m * 60 + s + delta)
    return f"{v//3600:02d}:{(v%3600)//60:02d}:{v%60:02d}"


def scan(ctf, begin, end, comms):
    """-> {(comm, syscall): [durations]}"""
    p2out, _bt = ctf_stream.open_lines(ctf, begin, end,
                                      'syscall_entry_|syscall_exit_', family="syscall")

    unwrap = unwrapper()   # window may cross midnight

    open_call = {}                                   # tid -> (syscall, t0)
    durs = collections.defaultdict(list)
    want = set(comms) if comms else None
    for line in p2out:
        ts = TS.match(line)
        ev = EV.search(line)
        if not ts or not ev:
            continue
        ctx = CTX.search(line)
        if not ctx:
            continue
        comm = ctx.group(3)
        if want and comm not in want:
            continue
        kind, name, t = ev.group(1), ev.group(2), unwrap(secs(ts))
        tid = int(ctx.group(2))
        if kind == "entry":
            open_call[tid] = (name, t)
        else:
            prev = open_call.pop(tid, None)
            if prev and prev[0] == name and t >= prev[1]:
                d = t - prev[1]
                if d < 30.0:
                    durs[(comm, name)].append(d)
    ctf_stream.close_lines(_bt)
    return durs


def stats(ds):
    ds = sorted(ds)
    q = lambda p: ds[min(len(ds) - 1, int(p * len(ds)))]
    return {"n": len(ds), "p50_ms": round(q(.5) * 1e3, 3), "p95_ms": round(q(.95) * 1e3, 3),
            "p99_ms": round(q(.99) * 1e3, 3), "total_s": round(sum(ds), 2),
            "mean_ms": round(statistics.fmean(ds) * 1e3, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--comms", default="", help="comma-separated procnames; empty = all")
    ap.add_argument("--out", default="blocking.json")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    a = ap.parse_args()

    gt = json.load(open(a.gt))["fault"]
    t0 = hhmmss(gt["injection_start_utc"])
    comms = [c for c in a.comms.split(",") if c]
    windows = {"baseline": (shift(t0, -a.baseline_s), t0),
               "incident": (t0, shift(t0, a.incident_s))}

    res = {"ctf": a.ctf, "target_service": gt.get("target_service"),
           "fault_window_utc": [gt["injection_start_utc"], gt["injection_end_utc"]],
           "comms_filter": comms or "all", "windows": {}}
    for name, (b, e) in windows.items():
        print(f"decoding {name}: {b} -> {e} ...", flush=True)
        d = scan(a.ctf, b, e, comms)
        res["windows"][name] = {"range": [b, e],
                                "per_call": {f"{c}|{s}": stats(v) for (c, s), v in d.items() if v}}
        print(f"  {sum(len(v) for v in d.values())} completed syscalls, {len(d)} (comm,syscall) pairs")

    base = res["windows"]["baseline"]["per_call"]
    inc = res["windows"]["incident"]["per_call"]
    cmp_rows = []
    for k in sorted(set(base) | set(inc)):
        b, i = base.get(k), inc.get(k)
        if not b or not i or i["n"] < 20:
            continue
        cmp_rows.append({"comm_syscall": k, "n_incident": i["n"],
                         "p95_baseline_ms": b["p95_ms"], "p95_incident_ms": i["p95_ms"],
                         "p95_x": round(i["p95_ms"] / b["p95_ms"], 2) if b["p95_ms"] else None,
                         "total_s_baseline": b["total_s"], "total_s_incident": i["total_s"]})
    cmp_rows.sort(key=lambda r: (-(r["p95_x"] or 0), r["comm_syscall"]))
    res["comparison"] = cmp_rows

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}\n")
    print(f"{'comm | syscall':34s} {'p95 base':>10s} {'p95 inc':>10s} {'x':>7s} {'n':>7s}")
    for r in cmp_rows[:14]:
        print(f"{r['comm_syscall']:34s} {r['p95_baseline_ms']:9.3f}ms "
              f"{r['p95_incident_ms']:9.3f}ms {str(r['p95_x']):>7s} {r['n_incident']:7d}")


if __name__ == "__main__":
    sys.exit(main())
