#!/usr/bin/env python3
"""The portable part of a fingerprint: what SHARE of its events the culprit spends on each thing.

WHY SHARES AND NOT RATES
------------------------
The absolute rates separate these families perfectly - 70/s for a deadlock against 63,000/s for
lock contention - but they are not a discriminator anyone else can use. They encode our
injector's parameters: 16 threads holding for 200 us is what makes 63,000/s. Change the
parameters and the number moves.

What survives a change of parameters is the SHAPE. A contended lock spends a fifth of its
events on futex whatever its thread count. A deadlocked one barely uses futex at all, because
parked threads make no calls. That ratio is what belongs in a blueprint; the rate belongs
beside it as "measured here, at these settings".

Prints mean and range over every indexed run of each family, so a discriminator can be written
with an n and a spread rather than a single number.

    python fingerprint_table.py --families lock_contention,deadlock,...
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
HOST_NS = "4026531836"

# Grouped by what an engineer would call them, not by syscall family.
GROUPS = {
    "futex": ["syscall_entry_futex", "syscall_exit_futex"],
    "sched churn": ["sched_switch", "sched_waking", "sched_wakeup"],
    "migrate": ["sched_migrate_task"],
    "on-CPU": ["sched_stat_runtime"],
    "softirq": ["irq_softirq_raise", "irq_softirq_entry", "irq_softirq_exit"],
    "network": ["net_dev_queue", "net_dev_xmit", "net_if_receive_skb", "net_if_rx",
                "net_if_rx_entry", "net_if_rx_exit"],
    "ioctl": ["syscall_entry_ioctl", "syscall_exit_ioctl"],
    "file ops": ["syscall_entry_close", "syscall_exit_close", "syscall_entry_fcntl",
                 "syscall_exit_fcntl", "syscall_entry_openat2", "syscall_exit_openat2"],
    "sleep": ["syscall_entry_nanosleep", "syscall_exit_nanosleep",
              "syscall_entry_clock_nanosleep", "syscall_exit_clock_nanosleep"],
    "socket io": ["syscall_entry_sendto", "syscall_exit_sendto",
                  "syscall_entry_recvfrom", "syscall_exit_recvfrom"],
}


def secs(iso):
    try:
        t = iso.split("T")[-1].rstrip("Z")
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return None


def one_run(run_dir):
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
    base_ns, inc_ns = defaultdict(int), defaultdict(int)
    ev_by_ns = defaultdict(lambda: defaultdict(int))
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
            ev, ns = p[1], p[3]
            if ns in (HOST_NS, "0"):
                continue
            if b0 <= bt < b1:
                base_ns[ns] += n
            elif t0 <= bt < t1:
                inc_ns[ns] += n
                ev_by_ns[ns][ev] += n
    cands = [(v, ns) for ns, v in inc_ns.items() if base_ns.get(ns, 0) == 0 and v > 3000]
    if not cands:
        return {"rid": rid, "rate": None}
    tot, ns = max(cands)
    evs = ev_by_ns[ns]
    shares = {}
    for label, names in GROUPS.items():
        shares[label] = sum(evs.get(n, 0) for n in names) / max(1, tot)
    return {"rid": rid, "rate": tot / (t1 - t0), "shares": shares}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", required=True)
    ap.add_argument("--app", default="sockshop")
    a = ap.parse_args()

    labels = list(GROUPS)
    print("%-22s %3s %16s  " % ("family", "n", "events/s (culprit)")
          + "".join("%11s" % l[:10] for l in labels))
    print("-" * (45 + 11 * len(labels)))
    for fam in [f.strip() for f in a.families.split(",") if f.strip()]:
        d = os.path.join(DATA, a.app, fam)
        if not os.path.isdir(d):
            continue
        rows = []
        for rid in sorted(os.listdir(d)):
            rd = os.path.join(d, rid)
            if not os.path.isdir(rd) or rid.endswith("_metrics"):
                continue
            r = one_run(rd)
            if r and r.get("rate"):
                rows.append(r)
        if not rows:
            print("%-22s  -   no culprit container found in any run" % fam)
            continue
        rates = [r["rate"] for r in rows]
        cells = []
        for l in labels:
            vs = [100 * r["shares"][l] for r in rows]
            m = sum(vs) / len(vs)
            cells.append("%10.1f%%" % m if m >= 0.05 else "         .")
        print("%-22s %3d %7.0f-%-8.0f  " % (fam, len(rows), min(rates), max(rates))
              + "".join(cells))

    print()
    print("Shares are of the culprit container's OWN events, so they do not move when the")
    print("machine gets busier. The rate beside them is what our injector produced at its")
    print("settings and is NOT a portable threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
