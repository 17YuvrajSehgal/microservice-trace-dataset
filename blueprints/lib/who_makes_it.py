#!/usr/bin/env python3
"""For a candidate signal: WHICH process produces it, and is that the app or the injector?

THE TRAP THIS EXISTS TO CATCH
-----------------------------
A signal can pass a specificity check and still be worthless. If `fchmod` appears only in
lock_contention and deadlock because the fault RECIPE chmods a lock file, then a blueprint
keyed on it detects our own injector and nothing else. It would score beautifully on this
dataset and fire never in production.

So every candidate gets asked: who emitted it? If the answer is dockerd, docker, runc,
containerd-shim, stress-ng or a shell, the signal is the harness. If it is the application's
own processes - java, node, mysqld, the connection threads - it is the mechanism.

That distinction cannot be made from event counts alone, which is why it is a separate pass.

    python who_makes_it.py --family dependency_outage --events getrusage,bind
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from collections import defaultdict

IDX = "/scratch/yuvraj17/stratatrace/dataset/index"
DATA = "/scratch/yuvraj17/stratatrace/dataset/runs"
TAB = chr(9)

# Anything here is the experiment looking at itself, not the system under test.
HARNESS = ("dockerd", "docker", "containerd", "containerd-shim", "runc", "docker-proxy",
           "stress-ng", "stress", "tc", "iptables", "bash", "sh", "sudo", "python3",
           "collect_trace.s", "lttng", "lttng-consumerd", "lttng-sessiond", "cadvisor",
           "otelcol-contrib", "node_exporter", "ps", "sed", "date", "stat", "uname",
           "chronyc", "hostname", "networkctl", "systemd-udevd", "(udev-worker)")


def is_harness(proc):
    p = (proc or "").strip()
    return any(p == h or p.startswith(h) for h in HARNESS)


def secs(iso):
    try:
        t = iso.split("T")[-1].rstrip("Z")
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", required=True)
    ap.add_argument("--events", required=True, help="comma-separated, matched as substrings")
    ap.add_argument("--app", default="sockshop")
    a = ap.parse_args()
    want = [e.strip() for e in a.events.split(",") if e.strip()]

    d = os.path.join(DATA, a.app, a.family)
    runs = [r for r in sorted(os.listdir(d))
            if os.path.isdir(os.path.join(d, r)) and not r.endswith("_metrics")]

    for rid in runs:
        ip = os.path.join(IDX, rid + ".tsv.gz")
        if not os.path.exists(ip):
            continue
        gp = os.path.join(d, rid, "ground_truth.json")
        if not os.path.exists(gp):
            continue
        f = json.load(open(gp)).get("fault") or {}
        t0, t1 = secs(f.get("injection_start_utc")), secs(f.get("injection_end_utc"))
        if t0 is None or t1 is None:
            continue
        b0, b1 = t0 - 70, t0 - 10

        base = defaultdict(lambda: defaultdict(int))
        inc = defaultdict(lambda: defaultdict(int))
        with gzip.open(ip, "rt") as fh:
            for line in fh:
                if line[0] == "#":
                    continue
                p = line.rstrip().split(TAB)
                if len(p) != 5:
                    continue
                try:
                    bt, n = float(p[0]), int(p[4])
                except ValueError:
                    continue
                ev, proc, ns = p[1], p[2], p[3]
                if not any(w in ev for w in want):
                    continue
                key = next(w for w in want if w in ev)
                if b0 <= bt < b1:
                    base[key][(proc, ns)] += n
                elif t0 <= bt < t1:
                    inc[key][(proc, ns)] += n

        print("=" * 92)
        print("%s   target=%s" % (rid, f.get("target_service")))
        print("=" * 92)
        for w in want:
            db, di = (b1 - b0), (t1 - t0)
            rows = []
            for k in set(base[w]) | set(inc[w]):
                rb, ri = base[w][k] / db, inc[w][k] / di
                rows.append((ri - rb, k, rb, ri))
            rows.sort(reverse=True)
            print("  %s" % w)
            if not rows:
                print("      (none)")
            for delta, (proc, ns), rb, ri in rows[:8]:
                tag = "HARNESS" if is_harness(proc) else "app"
                print("      %-18s ns=%-11s %8.1f/s -> %8.1f/s   %+8.1f   %s"
                      % (proc[:18], ns, rb, ri, delta, tag))
            app_delta = sum(d for d, (p, _), _, _ in rows if not is_harness(p))
            har_delta = sum(d for d, (p, _), _, _ in rows if is_harness(p))
            tot = abs(app_delta) + abs(har_delta)
            if tot > 0:
                print("      --> %.0f%% of the change is the APPLICATION, %.0f%% is the harness"
                      % (100 * abs(app_delta) / tot, 100 * abs(har_delta) / tot))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
