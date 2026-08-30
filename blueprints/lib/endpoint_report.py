#!/usr/bin/env python3
"""Compare endpoint signatures across the families that get mistaken for a slow datastore.

The question this answers, before any rule is written: does the endpoint view actually
separate a slow datastore from a degraded network path, a frozen dependency and a healthy
system? Prints per-family ranges and an explicit overlap check, so an honest "these are not
separable" outcome is as visible as a clean split.

    python3 endpoint_report.py --dir <endpoints_dir> --tasks <task_file> --out summary.json
"""
from __future__ import annotations
import argparse, collections, json, os, sys

FIELDS = [("n_slowed_2x", "endpoints slowed"),
          ("top_p95_x", "worst slowdown"),
          ("median_tail_ratio_of_slowed", "tail vs shift"),
          ("n_hung", "stopped answering"),
          ("n_gone", "vanished"),
          ("worst_response_ratio", "min reply ratio")]


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
    ap.add_argument("--out", default="endpoint_summary.json")
    a = ap.parse_args()

    truth = load_tasks(a.tasks)
    rows = []
    for run_id, (app, fam) in sorted(truth.items()):
        p = os.path.join(a.dir, f"{run_id}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        s = d.get("signature", {})
        comp = d.get("comparison", [])
        top = comp[0] if comp else {}
        rows.append({
            "run_id": run_id, "app": app, "family": fam,
            "n_slowed_2x": s.get("n_slowed_2x"),
            "n_endpoints": s.get("n_endpoints"),
            "top_p95_x": top.get("p95_x"),
            "top_p50_x": top.get("p50_x"),
            "top_endpoint": top.get("endpoint"),
            "median_tail_ratio_of_slowed": s.get("median_tail_ratio_of_slowed"),
            "n_hung": s.get("n_hung"),
            "n_gone": s.get("n_gone"),
            "endpoints_gone": s.get("endpoints_gone"),
            "worst_response_ratio": s.get("worst_response_ratio"),
            "slow_ports": s.get("slow_ports"),
        })

    if not rows:
        print("no endpoint results found")
        return 1

    print(f"\n{'run':40s} {'family':18s} {'slow':>7s} {'topx':>7s} {'p50x':>6s} "
          f"{'tail':>6s} {'hung':>5s} {'gone':>5s} {'resp':>6s}")
    print("-" * 108)
    for r in sorted(rows, key=lambda r: (r["app"], r["family"], r["run_id"])):
        f = lambda v, w=6: f"{v:{w}.2f}" if isinstance(v, (int, float)) else f"{str(v):>{w}s}"
        print(f"{r['run_id'][:40]:40s} {r['family']:18s} "
              f"{str(r['n_slowed_2x']) + '/' + str(r['n_endpoints']):>7s} "
              f"{f(r['top_p95_x'], 7)} {f(r['top_p50_x'])} "
              f"{f(r['median_tail_ratio_of_slowed'])} "
              f"{str(r['n_hung']):>5s} {str(r['n_gone']):>5s} {f(r['worst_response_ratio'])}")

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

    print("\nseparation check per app (overlapping ranges mean the signal alone cannot decide):")
    for app in sorted({r["app"] for r in rows}):
        print(f"  {app}:")
        fams = [s for s in summary if s["app"] == app]
        for k, lbl in FIELDS:
            pairs = []
            for i in range(len(fams)):
                for j in range(i + 1, len(fams)):
                    x, y = fams[i]["ranges"].get(k), fams[j]["ranges"].get(k)
                    if not x or not y:
                        continue
                    if x[0] <= y[1] and y[0] <= x[1]:
                        pairs.append(f"{fams[i]['family']}~{fams[j]['family']}")
            print(f"    {lbl:20s} {'overlaps: ' + ', '.join(pairs) if pairs else 'CLEAN SPLIT'}")

    json.dump({"rows": rows, "summary": summary}, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
