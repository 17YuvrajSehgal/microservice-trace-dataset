#!/usr/bin/env python3
"""What does the injected container DO? And is that unique to its fault?

WHY THIS IS THE RIGHT QUESTION
------------------------------
Every one of these faults is injected as a sidecar container - lock-contention, deadlock,
priority-inversion, conn-pool-exhaustion, nagle-delayed-ack, anomaly-mem-stress. So "a new
container appeared" is true of all of them and separates nothing. It is also how the existing
noisy_neighbor blueprint already finds its culprit.

What separates them is what the newcomer SPENDS ITS SYSCALLS ON. A futex storm is not a poll
storm is not a connect storm. That fingerprint is the thing worth writing into a blueprint,
and - unlike "a new container appeared" - it still means something when the same bug happens
inside an existing service in production.

HARNESS, CORRECTED
------------------
The first pass called containerised `python3` harness and nearly threw away every signature.
The collection scripts run in the HOST namespace; anything in a container namespace is either
an application service or the injected fault. Namespace, not process name, is the test.

    python fault_fingerprint.py --families lock_contention,deadlock,...
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
HOST_NS = "4026531836"          # the host's own pid namespace: collection lives here


def secs(iso):
    try:
        t = iso.split("T")[-1].rstrip("Z")
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return None


def newcomer_fingerprint(run_dir):
    """The container that is absent before injection and busy during it, and what it does."""
    rid = os.path.basename(run_dir.rstrip("/"))
    ip = os.path.join(IDX, rid + ".tsv.gz")
    gp = os.path.join(run_dir, "ground_truth.json")
    if not (os.path.exists(ip) and os.path.exists(gp)):
        return None
    f = json.load(open(gp)).get("fault") or {}
    t0, t1 = secs(f.get("injection_start_utc")), secs(f.get("injection_end_utc"))
    if t0 is None or t1 is None:
        return None
    b0, b1 = t0 - 70, t0 - 10

    base_ns, inc = defaultdict(int), defaultdict(lambda: defaultdict(int))
    inc_ns = defaultdict(int)
    procs = defaultdict(set)
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
            if ns == HOST_NS or ns == "0":
                continue                       # collection harness, not the system under test
            if b0 <= bt < b1:
                base_ns[ns] += n
            elif t0 <= bt < t1:
                inc_ns[ns] += n
                inc[ns][ev] += n
                procs[ns].add(proc)

    # the newcomer: a container namespace with real traffic during, none before
    cands = [(v, ns) for ns, v in inc_ns.items() if base_ns.get(ns, 0) == 0 and v > 5000]
    if not cands:
        return {"run": rid, "newcomer": None, "target": f.get("target_service")}
    cands.sort(reverse=True)
    tot, ns = cands[0]
    dur = t1 - t0
    top = sorted(inc[ns].items(), key=lambda kv: -kv[1])[:10]
    return {"run": rid, "target": f.get("target_service"), "pid_ns": ns,
            "procs": sorted(procs[ns]), "events_per_s": tot / dur,
            "top": [(e, n / dur) for e, n in top],
            "n_other_newcomers": len(cands) - 1}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", required=True)
    ap.add_argument("--app", default="sockshop")
    a = ap.parse_args()

    shares = {}
    for fam in [f.strip() for f in a.families.split(",") if f.strip()]:
        d = os.path.join(DATA, a.app, fam)
        if not os.path.isdir(d):
            continue
        print("=" * 92)
        print(fam)
        print("=" * 92)
        for rid in sorted(os.listdir(d)):
            rd = os.path.join(d, rid)
            if not os.path.isdir(rd) or rid.endswith("_metrics"):
                continue
            r = newcomer_fingerprint(rd)
            if not r:
                continue
            if not r.get("newcomer", True) and not r.get("pid_ns"):
                print("  %-44s no newcomer container found" % r["run"])
                continue
            print("  %s" % r["run"])
            print("     container ns=%s  procs=%s  %.0f events/s  (%d other newcomers)"
                  % (r["pid_ns"], ",".join(r["procs"][:4]), r["events_per_s"],
                     r["n_other_newcomers"]))
            tot = sum(n for _, n in r["top"]) or 1
            frac = {}
            for e, n in r["top"]:
                print("        %-42s %9.0f/s   %4.1f%%" % (e, n, 100 * n / tot))
                frac[e] = n / tot
            shares.setdefault(fam, []).append(frac)
        print()

    # what fraction of the newcomer's syscalls is each family's top event - the fingerprint
    print("=" * 92)
    print("FINGERPRINT - what the injected container spends its events on")
    print("=" * 92)
    keys = ["syscall_entry_futex", "syscall_entry_poll", "syscall_entry_epoll_pwait",
            "syscall_entry_sendto", "syscall_entry_recvfrom", "syscall_entry_connect",
            "syscall_entry_mmap", "syscall_entry_madvise", "sched_switch",
            "syscall_entry_nanosleep", "syscall_entry_sched_yield"]
    print("  %-22s" % "family" + "".join("%11s" % k.replace("syscall_entry_", "")[:10]
                                         for k in keys))
    print("  " + "-" * (22 + 11 * len(keys)))
    for fam, fr in shares.items():
        cells = []
        for k in keys:
            vals = [f.get(k, 0.0) for f in fr]
            m = sum(vals) / len(vals) if vals else 0.0
            cells.append("%10.0f%%" % (100 * m) if m >= 0.005 else "         .")
        print("  %-22s" % fam + "".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
