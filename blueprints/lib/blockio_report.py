#!/usr/bin/env python3
"""Does anything in the block layer separate the disk fault from every other family?

Retransmissions are the one thing specific to a network fault - nothing else in the catalogue
drops packets. The first probe was decisive on four runs (host-wide 12/16 interfaces impaired,
single-container 1/18 at 52.6%, healthy 0/18 at 0%, baseline 0% everywhere). This checks it at
scale, and in particular whether the NON-network families stay quiet, which is the check that
A3 and A4 failed on latency.

    python3 netloss_report.py --dir <netloss_dir> --tasks <task_file> --out summary.json
"""
from __future__ import annotations
import argparse, collections, json, os, sys

FIELDS = [("io_newcomer_iops_gained", "disk newcomer req/s"),
          ("worst_device_p95_x", "device p95 slowdown"),
          ("total_iops_x", "total I/O change"),
          ("queue_depth_x", "queue depth change")]
NETWORK_FAMILIES = {"anomaly_disk"}


def load_tasks(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split()
        if len(p) >= 3:
            out[p[2]] = (p[0], p[1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", default="blockio_summary.json")
    a = ap.parse_args()

    truth = load_tasks(a.tasks)
    rows = []
    for run_id, (app, fam) in sorted(truth.items()):
        p = os.path.join(a.dir, f"{run_id}.json")
        if not os.path.exists(p):
            continue
        s = json.load(open(p, encoding="utf-8")).get("signature", {})
        rows.append({"run_id": run_id, "app": app, "family": fam,
                     "is_network": fam in NETWORK_FAMILIES, **s})

    if not rows:
        print("no results found")
        return 1

    print(f"\n{'run':42s} {'family':18s} {'impaired':>10s} {'worst%':>8s} "
          f"{'base%':>7s} {'drop%':>7s}")
    print("-" * 96)
    for r in sorted(rows, key=lambda r: (r["app"], r["family"], r["run_id"])):
        f = lambda v, w=7: f"{v:{w}.2f}" if isinstance(v, (int, float)) else f"{str(v):>{w}s}"
        print(f"{r['run_id'][:42]:42s} {r['family']:18s} "
              f"{str(r.get('io_newcomer_iops_gained')) + '/' + str(r.get('n_interfaces')):>10s} "
              f"{f(r.get('worst_device_p95_x'), 8)} {f(r.get('total_iops_x'))} "
              f"{f(r.get('queue_depth_x'))}")

    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        for k, _ in FIELDS:
            if isinstance(r.get(k), (int, float)):
                by[(r["app"], r["family"])][k].append(r[k])

    print("\nranges per app and family:")
    summary = []
    for key in sorted(by):
        s = by[key]
        parts = [f"{lbl}={min(s[k]):.2f}-{max(s[k]):.2f}" for k, lbl in FIELDS if s.get(k)]
        summary.append({"app": key[0], "family": key[1],
                        "ranges": {k: [min(v), max(v)] for k, v in s.items()}})
        print(f"  {key[0]:12s} {key[1]:18s} " + "  ".join(parts))

    # the decisive question: do network and non-network families overlap?
    print("\nnetwork against non-network, per app:")
    for app in sorted({r["app"] for r in rows}):
        ar = [r for r in rows if r["app"] == app]
        net = [r for r in ar if r["is_network"] and isinstance(r.get("worst_device_p95_x"), float)]
        other = [r for r in ar
                 if not r["is_network"] and isinstance(r.get("worst_device_p95_x"), float)]
        if not (net and other):
            continue
        nlo = min(r["worst_device_p95_x"] for r in net)
        ohi = max(r["worst_device_p95_x"] for r in other)
        worst_other = max(other, key=lambda r: r["worst_device_p95_x"])
        verdict = "CLEAN SPLIT" if nlo > ohi else "OVERLAP"
        print(f"  {app:12s} disk-fault device-p95 floor {nlo:.2f}%  "
              f"other-family ceiling {ohi:.2f}% ({worst_other['family']})  -> {verdict}")
        nimp = [r["io_newcomer_iops_gained"] for r in net if isinstance(r.get("io_newcomer_iops_gained"), int)]
        oimp = [r["io_newcomer_iops_gained"] for r in other if isinstance(r.get("io_newcomer_iops_gained"), int)]
        if nimp and oimp:
            print(f"  {'':12s} newcomer req/s: disk {min(nimp)}-{max(nimp)}, "
                  f"others {min(oimp)}-{max(oimp)}")

    json.dump({"rows": rows, "summary": summary}, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
