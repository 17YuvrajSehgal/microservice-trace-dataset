#!/usr/bin/env python3
"""Measure the kernel wait signature of every fault family, from derived L2 records.

Fast: reads kernel_l2.jsonl directly, no span/metric loading. Run this BEFORE writing any
wait-based discriminator into a blueprint.

Two things it reports, and the second is the one that matters:

  1. the coarse 4-bucket shares (on_cpu / runnable_wait / disk_wait / off_cpu_io_wait)
  2. the `family_seconds` breakdown, which splits off_cpu_io_wait into WHY the thread was
     off-CPU (idle in epoll, blocked on a futex, blocked reading a socket, ...)

The coarse buckets are dominated by idle waiting and are near-identical across families, so
they cannot discriminate. Any claim that they can must be checked against this output.

    python3 measure_wait_signature.py --out evidence/wait_signature.json
"""
from __future__ import annotations
import argparse, collections, glob, json, os, statistics, sys

DEFAULT_ROOT = os.environ.get("RUNS_ROOT", "/scratch/yuvraj17/agentic-runs")


def scan(root):
    rows = []
    for app in ("sockshop", "trainticket"):
        for p in glob.glob(os.path.join(root, app, "*", "*", "kernel_l2.jsonl")):
            fam = p.split(os.sep)[-3]
            run_id = p.split(os.sep)[-2]
            tgt = ""
            gt = os.path.join(os.path.dirname(p), "ground_truth.json")
            if os.path.exists(gt):
                try:
                    tgt = json.load(open(gt))["fault"].get("target_service", "")
                except Exception:                                       # noqa: BLE001
                    pass
            for line in open(p):
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                svc = r.get("service", "")
                rows.append({
                    "app": app, "family": fam, "run_id": run_id, "service": svc,
                    "target_service": tgt,
                    "is_target": bool(tgt) and (tgt in svc or svc in tgt),
                    "shares_pct": r.get("rule_out_pct") or {},
                    "family_seconds": r.get("family_seconds") or {},
                    "verdict_hint": r.get("verdict_hint"),
                })
    return rows


def norm(d):
    tot = sum(v for v in d.values() if isinstance(v, (int, float)))
    return {k: 100.0 * v / tot for k, v in d.items()} if tot > 0 else {}


def summarise(rows, target_only=True):
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    runs = collections.defaultdict(set)
    for r in rows:
        if target_only and not r["is_target"]:
            continue
        n = norm(r["family_seconds"])
        if not n:
            continue
        runs[r["family"]].add(r["run_id"])
        for k, v in n.items():
            by[r["family"]][k].append(v)
    out = {}
    for fam, d in by.items():
        out[fam] = {"n_records": len(next(iter(d.values()))) if d else 0,
                    "n_runs": len(runs[fam]),
                    "mean_pct": {k: round(statistics.fmean(v), 2) for k, v in d.items()},
                    "stdev_pct": {k: (round(statistics.stdev(v), 2) if len(v) > 1 else 0.0)
                                  for k, v in d.items()}}
    return out


def discriminative(summary, min_gap=15.0):
    """A signal is discriminative for a family only if that family's mean is separated from
    every other family's mean by more than `min_gap` points. Anything else is a symptom."""
    keys = sorted({k for f in summary.values() for k in f["mean_pct"]})
    found = []
    for k in keys:
        vals = {f: s["mean_pct"].get(k) for f, s in summary.items() if k in s["mean_pct"]}
        if len(vals) < 2:
            continue
        for fam, v in vals.items():
            others = [x for f, x in vals.items() if f != fam]
            if not others:
                continue
            gap_hi = v - max(others)
            gap_lo = min(others) - v
            if gap_hi >= min_gap:
                found.append({"signal": k, "family": fam, "direction": "HIGHEST",
                              "value_pct": v, "next_best_pct": max(others),
                              "gap_points": round(gap_hi, 1)})
            elif gap_lo >= min_gap:
                found.append({"signal": k, "family": fam, "direction": "LOWEST",
                              "value_pct": v, "next_lowest_pct": min(others),
                              "gap_points": round(gap_lo, 1)})
    return sorted(found, key=lambda d: -d["gap_points"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--out", default="")
    ap.add_argument("--min-gap", type=float, default=15.0)
    a = ap.parse_args()

    rows = scan(a.root)
    if not rows:
        sys.exit(f"no kernel_l2.jsonl found under {a.root}")
    summary = summarise(rows, target_only=True)
    disc = discriminative(summary, a.min_gap)

    fams_with_l2 = set(summary)
    all_fams = {r["family"] for r in rows}
    missing = sorted(all_fams - fams_with_l2)

    print(f"scanned {len(rows)} L2 records across {len({r['run_id'] for r in rows})} runs\n")
    keys = sorted({k for f in summary.values() for k in f["mean_pct"]})
    print("family_seconds of the LABELLED CULPRIT (mean %, +-stdev):\n")
    print(f"{'family':20s} {'runs':>4s} " + " ".join(f"{k[:13]:>14s}" for k in keys))
    for fam in sorted(summary):
        s = summary[fam]
        cells = []
        for k in keys:
            m = s["mean_pct"].get(k)
            cells.append(f"{m:8.1f}+-{s['stdev_pct'].get(k,0):4.1f}" if m is not None else f"{'-':>14s}")
        print(f"{fam:20s} {s['n_runs']:4d} " + " ".join(cells))

    if missing:
        print(f"\nNO culprit-side L2 record for: {', '.join(missing)}")
        print("  (their labelled target is the host, and there is no 'host' L2 record — so no")
        print("   wait-based claim can be made about the culprit for these families)")

    print(f"\nDiscriminative signals (mean separated by >= {a.min_gap} points from every other family):")
    if disc:
        for d in disc:
            print(f"  {d['signal']:18s} {d['direction']:8s} for {d['family']:20s} "
                  f"{d['value_pct']:6.1f}%  (gap {d['gap_points']} pts)")
    else:
        print("  NONE. No wait signal separates any family by that margin — do not write one")
        print("  into a blueprint as a discriminator.")

    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump({"summary": summary, "discriminative": disc,
                   "families_without_culprit_l2": missing,
                   "min_gap_points": a.min_gap,
                   "n_records": len(rows)}, open(a.out, "w"), indent=2)
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    sys.exit(main())
