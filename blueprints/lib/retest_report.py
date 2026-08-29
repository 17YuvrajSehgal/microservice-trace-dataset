#!/usr/bin/env python3
"""Score the re-test: did the new rules cut the false-positive rate, and on both apps?

Two classes of run:
  positives  a family some blueprint SHOULD claim  -> did the right one fire?
  negatives  everything else, including no-fault   -> did every blueprint stay quiet?

Reported per application, because the whole point of the exercise is whether a rule measured
on one system survives on another.

    python3 retest_report.py --verdicts <dir> --tasks <task_file> --out retest.json
"""
from __future__ import annotations
import argparse, collections, json, os, sys

# family -> the blueprint that should claim it
TARGET_OF = {
    "noisy_neighbor": "cpu-contention-co-tenant",
    "anomaly_cpu": "host-cpu-saturation",
    "svc_cpu_cap": "service-cpu-throttle",
    "slow_db": "datastore-wait",
}


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
    ap.add_argument("--out", default="retest.json")
    a = ap.parse_args()

    truth = load_tasks(a.tasks)
    rows = []
    for run_id, (app, fam) in sorted(truth.items()):
        p = os.path.join(a.verdicts, f"{run_id}.json")
        if not os.path.exists(p):
            continue
        v = json.load(open(p, encoding="utf-8"))
        expected = TARGET_OF.get(fam)
        sel = v.get("selected")
        if expected is None:
            outcome = "correct_decline" if sel is None else "FALSE_FIRE"
        elif sel == expected:
            outcome = "correct_fire"
        elif sel is None:
            outcome = "missed"
        else:
            outcome = "WRONG_BLUEPRINT"
        cc = v.get("cpu_contention_co_tenant", {})
        rows.append({
            "run_id": run_id, "app": app, "family": fam,
            "expected": expected, "selected": sel, "outcome": outcome,
            "oncpu_available": v.get("oncpu_available"),
            "util_baseline": cc.get("host_util_baseline"),
            "util_incident": cc.get("host_util_incident"),
            "util_ratio": cc.get("host_util_ratio"),
            "thief_cores": cc.get("thief_cores"),
            "loser_cores": cc.get("biggest_loser_cores"),
            "runqueue_max_x": cc.get("corroboration_runqueue_max_x"),
            "blocking_x": v.get("datastore_wait", {}).get("blocking_x"),
        })

    if not rows:
        print("no verdicts found")
        return 1

    print(f"\n{'run':42s} {'app':12s} {'truth':18s} {'verdict':26s} outcome")
    print("-" * 118)
    for r in sorted(rows, key=lambda r: (r["app"], r["family"], r["run_id"])):
        mark = {"correct_fire": "OK", "correct_decline": "OK",
                "FALSE_FIRE": "**FALSE FIRE**", "missed": "missed",
                "WRONG_BLUEPRINT": "**WRONG**"}[r["outcome"]]
        print(f"{r['run_id'][:42]:42s} {r['app']:12s} {r['family']:18s} "
              f"{str(r['selected'])[:26]:26s} {mark}")

    summary = {}
    print(f"\n{'app':12s} {'class':10s} {'n':>3s} {'correct':>8s} {'rate':>7s}")
    print("-" * 46)
    for app in sorted({r["app"] for r in rows}):
        ar = [r for r in rows if r["app"] == app]
        pos = [r for r in ar if r["expected"]]
        neg = [r for r in ar if not r["expected"]]
        pos_ok = sum(1 for r in pos if r["outcome"] == "correct_fire")
        neg_ok = sum(1 for r in neg if r["outcome"] == "correct_decline")
        summary[app] = {"positives": len(pos), "positives_correct": pos_ok,
                        "negatives": len(neg), "negatives_correct": neg_ok,
                        "false_fires": len(neg) - neg_ok}
        if pos:
            print(f"{app:12s} {'positive':10s} {len(pos):3d} {pos_ok:8d} "
                  f"{100*pos_ok/len(pos):6.0f}%")
        if neg:
            print(f"{app:12s} {'negative':10s} {len(neg):3d} {neg_ok:8d} "
                  f"{100*neg_ok/len(neg):6.0f}%")

    bad = [r for r in rows if r["outcome"] in ("FALSE_FIRE", "WRONG_BLUEPRINT")]
    if bad:
        print(f"\n{len(bad)} wrong answers remain:")
        for r in bad:
            print(f"  {r['run_id'][:40]:40s} {r['family']:18s} -> {r['selected']}")

    missed = [r for r in rows if r["outcome"] == "missed"]
    if missed:
        print(f"\n{len(missed)} missed (target family, nothing fired):")
        for r in missed:
            print(f"  {r['run_id'][:40]:40s} {r['family']:18s} util "
                  f"{r['util_baseline']}->{r['util_incident']} thief {r['thief_cores']}")

    # per-family utilisation ranges, so cross-app drift is visible immediately
    print("\nhost utilisation by app and family (the deciding signal):")
    by = collections.defaultdict(list)
    for r in rows:
        if r["util_incident"] is not None:
            by[(r["app"], r["family"])].append(r["util_incident"])
    for (app, fam), vs in sorted(by.items()):
        print(f"  {app:12s} {fam:18s} n={len(vs):2d}  {min(vs):.3f}-{max(vs):.3f}")

    json.dump({"rows": rows, "summary": summary}, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
