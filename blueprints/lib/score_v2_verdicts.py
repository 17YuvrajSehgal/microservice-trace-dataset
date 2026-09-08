#!/usr/bin/env python3
"""Score every blueprint against v2 ground truth, from blueprint_decide verdicts.

One row per run, one column per blueprint. Recall is "did the blueprint that owns this family
fire on it"; a false fire is any other blueprint firing on it.

    python3 score_v2_verdicts.py --verdicts <dir> --tasks <task_file> [--out scored.json]

WHICH FAMILY EACH BLUEPRINT OWNS
--------------------------------
blueprint_decide's own VERDICTS table maps a blueprint to the fault label it claims, but two
of those labels do not match a v2 family name and would silently score as zero:

    datastore-wait -> "db_latency"    the v2 family is `slow_db`
    network-path-degradation -> "anomaly_net"   `svc_net` is the same fault, per service

So the mapping is stated here, in v2's vocabulary, rather than inferred.

`normal` owns nothing: any blueprint firing on it is a false fire, which is the strictest and
most useful control we have.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

# blueprint -> the v2 families it is SUPPOSED to fire on
OWNS = {
    "host-cpu-saturation": {"anomaly_cpu"},
    "service-cpu-throttle": {"svc_cpu_cap"},
    "cpu-contention-co-tenant": {"noisy_neighbor"},
    "datastore-wait": {"slow_db"},
    "network-path-degradation": {"anomaly_net", "svc_net"},
    "host-disk-saturation": {"anomaly_disk"},
    "service-memory-cap": {"svc_mem_cap"},
}
ALL_BP = list(OWNS)


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
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    truth = load_tasks(a.tasks)
    rows, missing = [], []
    # blueprint -> family -> [fired?]
    grid = collections.defaultdict(lambda: collections.defaultdict(list))
    per_app = collections.defaultdict(lambda: collections.defaultdict(list))
    fired_count = collections.Counter()

    for run, (app, fam) in sorted(truth.items()):
        p = os.path.join(a.verdicts, f"{run}.json")
        if not os.path.exists(p):
            missing.append(run)
            continue
        v = json.load(open(p))
        fired = set(v.get("blueprints_fired") or [])
        fired_count[len(fired)] += 1
        for bp in ALL_BP:
            grid[bp][fam].append(bp in fired)
            per_app[(bp, app)][fam].append(bp in fired)
        rows.append({"run": run, "app": app, "family": fam,
                     "fired": sorted(fired), "n_fired": len(fired),
                     "oncpu": v.get("oncpu_available"),
                     "blockio": v.get("blockio_available"),
                     "irq": v.get("irq_available"),
                     "retrans": v.get("retrans_available"),
                     "endpoint": v.get("endpoint_available")})

    print("=" * 78)
    print(f" ALL BLUEPRINTS on v2, kernel traces only  -  {len(rows)} runs")
    print("=" * 78)

    summary = {}
    for bp in ALL_BP:
        owns = OWNS[bp]
        pos = [f for fam in owns for f in grid[bp].get(fam, [])]
        neg = [f for fam, lst in grid[bp].items() if fam not in owns for f in lst]
        tp, fp = sum(pos), sum(neg)
        summary[bp] = {"recall": [tp, len(pos)], "false_fires": [fp, len(neg)]}
        print(f"\n  {bp}   (owns: {', '.join(sorted(owns))})")
        print(f"    recall      {tp}/{len(pos)}" + (f"  = {tp/len(pos):.0%}" if pos else ""))
        print(f"    false fires {fp}/{len(neg)}" + (f"  = {fp/len(neg):.0%}" if neg else ""))
        for fam in sorted(grid[bp]):
            n, tot = sum(grid[bp][fam]), len(grid[bp][fam])
            if fam in owns:
                flag = "" if n == tot else "   <-- misses"
            else:
                flag = "" if n == 0 else "   <-- FALSE FIRE"
            if n or fam in owns:
                print(f"      {fam:18s} {n:2d}/{tot:2d}{flag}")
        for app in ("sockshop", "trainticket"):
            k = (bp, app)
            if k not in per_app:
                continue
            t = sum(f for fam in owns for f in per_app[k].get(fam, []))
            n = len([f for fam in owns for f in per_app[k].get(fam, [])])
            fpa = sum(f for fam, lst in per_app[k].items() if fam not in owns for f in lst)
            print(f"      [{app:11s}] recall {t}/{n}, false fires {fpa}")

    print("\n  how many blueprints fired per run:")
    for n in sorted(fired_count):
        label = {0: "none - no verdict", 1: "exactly one"}.get(n, f"{n} - ambiguous")
        print(f"    {fired_count[n]:3d} runs  {label}")

    if missing:
        print(f"\n  {len(missing)} runs had no verdict file:")
        for r in missing[:8]:
            print(f"    {r}")

    if a.out:
        json.dump({"summary": summary, "rows": rows}, open(a.out, "w"), indent=2)
        print(f"\n  wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
