#!/usr/bin/env python3
"""Score the with/without experiment: does a blueprint beat not having one?

Same model, same evidence, same incidents. The only difference between the two arms is
whether the blueprint library was available.

Reports per application and per fault family, because a headline average can hide the thing
that matters - the whole point of the blueprints is that they encode what a fault looks like,
so any lift should be concentrated on the families a blueprint actually covers.

Also reports cost and time, since the supervisor asked for both: "compare with and without
those blueprints" and Yuvraj added the speed axis in the same conversation.

    python3 withwithout_report.py --dir <results dir> --out withwithout.json
"""
from __future__ import annotations
import argparse, collections, json, os, sys

# families a blueprint covers - lift should appear here, and NOT firing wrongly elsewhere
COVERED = {"noisy_neighbor", "anomaly_cpu", "svc_cpu_cap", "slow_db", "anomaly_net",
           "svc_net", "anomaly_disk"}
ARMS = [("without", "no blueprint"), ("with", "blueprint available")]


def load(path):
    """evaluate.py results -> per-incident rows."""
    if not os.path.exists(path):
        return []
    d = json.load(open(path, encoding="utf-8"))
    rows = d.get("rows") or d.get("results") or []
    out = []
    for r in rows:
        out.append({
            "run_id": r.get("run_id"),
            "family": r.get("fault_family") or r.get("family"),
            "service_ok": bool(r.get("service_correct") or r.get("service_hit")),
            "fault_ok": bool(r.get("fault_correct") or r.get("fault_hit")),
            "both_ok": bool(r.get("both_correct") or
                            (r.get("service_correct") and r.get("fault_correct"))),
            "seconds": r.get("seconds") or r.get("elapsed_s"),
            "tokens": r.get("tokens") or r.get("total_tokens"),
            "usd": r.get("usd") or r.get("cost_usd"),
            "calls": r.get("tool_calls") or r.get("calls"),
            "selected_skill": r.get("selected_skill") or r.get("skill_selected"),
            "skill_ok": r.get("selection_correct"),
        })
    return out


def agg(rows, key=lambda r: True):
    sel = [r for r in rows if key(r)]
    if not sel:
        return None
    n = len(sel)
    num = lambda f: [r[f] for r in sel if isinstance(r.get(f), (int, float))]
    return {
        "n": n,
        "service": sum(r["service_ok"] for r in sel),
        "fault": sum(r["fault_ok"] for r in sel),
        "both": sum(r["both_ok"] for r in sel),
        "both_pct": round(100 * sum(r["both_ok"] for r in sel) / n),
        "median_s": (sorted(num("seconds"))[len(num("seconds")) // 2]
                     if num("seconds") else None),
        "total_usd": round(sum(num("usd")), 4) if num("usd") else None,
        "median_calls": (sorted(num("calls"))[len(num("calls")) // 2]
                         if num("calls") else None),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default="withwithout.json")
    a = ap.parse_args()

    data = {}
    for arm, _ in ARMS:
        for app in ("ss", "tt"):
            data[(arm, app)] = load(os.path.join(a.dir, f"{arm}_{app}.json"))

    if not any(data.values()):
        print("no results found - check the arm logs")
        return 1

    print(f"\n{'app':6s} {'arm':22s} {'n':>4s} {'service':>8s} {'fault':>7s} "
          f"{'BOTH':>7s} {'rate':>6s} {'med s':>7s} {'calls':>6s} {'usd':>8s}")
    print("-" * 92)
    summary = {}
    for app, label in (("ss", "sockshop"), ("tt", "trainticket")):
        for arm, desc in ARMS:
            r = agg(data[(arm, app)])
            if not r:
                continue
            summary[f"{label}_{arm}"] = r
            print(f"{label[:6]:6s} {desc:22s} {r['n']:4d} {r['service']:8d} {r['fault']:7d} "
                  f"{r['both']:7d} {r['both_pct']:5d}% {str(r['median_s']):>7s} "
                  f"{str(r['median_calls']):>6s} {str(r['total_usd']):>8s}")

    # the headline: both arms pooled
    print()
    pooled = {}
    for arm, desc in ARMS:
        rows = data[(arm, "ss")] + data[(arm, "tt")]
        r = agg(rows)
        if r:
            pooled[arm] = r
            print(f"POOLED {desc:22s} {r['n']:4d} {r['service']:8d} {r['fault']:7d} "
                  f"{r['both']:7d} {r['both_pct']:5d}% {str(r['median_s']):>7s} "
                  f"{str(r['median_calls']):>6s} {str(r['total_usd']):>8s}")
    if "with" in pooled and "without" in pooled:
        d = pooled["with"]["both_pct"] - pooled["without"]["both_pct"]
        print(f"\nDIFFERENCE: {d:+d} points fully correct "
              f"({pooled['without']['both']} -> {pooled['with']['both']} of "
              f"{pooled['without']['n']})")

    # where the lift lands - covered families vs everything else
    print("\nsplit by whether a blueprint covers the family:")
    print(f"{'group':28s} {'arm':22s} {'n':>4s} {'BOTH':>6s} {'rate':>6s}")
    for grp, keyf in (("a blueprint covers it", lambda r: r["family"] in COVERED),
                      ("no blueprint for it", lambda r: r["family"] not in COVERED)):
        for arm, desc in ARMS:
            rows = data[(arm, "ss")] + data[(arm, "tt")]
            r = agg(rows, keyf)
            if r:
                print(f"{grp:28s} {desc:22s} {r['n']:4d} {r['both']:6d} {r['both_pct']:5d}%")

    # per family, both arms side by side
    print("\nper family (fully correct):")
    fams = sorted({r["family"] for rows in data.values() for r in rows if r["family"]})
    print(f"{'family':20s} {'covered':>8s} {'without':>9s} {'with':>7s} {'change':>7s}")
    per_family = {}
    for f in fams:
        wo = agg(data[("without", "ss")] + data[("without", "tt")], lambda r: r["family"] == f)
        wi = agg(data[("with", "ss")] + data[("with", "tt")], lambda r: r["family"] == f)
        if not (wo and wi):
            continue
        chg = wi["both"] - wo["both"]
        per_family[f] = {"without": wo, "with": wi, "change": chg}
        print(f"{f:20s} {'yes' if f in COVERED else 'no':>8s} "
              f"{wo['both']:4d}/{wo['n']:<4d} {wi['both']:3d}/{wi['n']:<3d} {chg:+7d}")

    json.dump({"summary": summary, "pooled": pooled, "per_family": per_family,
               "rows": {f"{k[0]}_{k[1]}": v for k, v in data.items()}},
              open(a.out, "w"), indent=2, default=str)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
