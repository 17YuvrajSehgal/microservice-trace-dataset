#!/usr/bin/env python3
"""Do lock waits or interrupt time move for any fault we inject?

This is a SPECIFICITY test, run before any blueprint is written rather than after. We have no
lock-contention fault, so the useful result is the negative one: if futex wait is flat across
all 13 families, then a future rise in it means lock contention and not something else.

Finding F17 is why this comes first. We built a packet-loss signal, checked it against 8 of 13
families, and the one we skipped (svc_mem_cap) retransmitted harder than any network fault.

    python3 futexirq_report.py --dir <results dir> --out report.json
"""
from __future__ import annotations
import argparse, glob, json, os, statistics, sys

FAMILIES = ["anomaly_cpu", "anomaly_disk", "anomaly_mem", "anomaly_net",
            "dependency_outage", "error_storm", "noisy_neighbor", "normal",
            "queue_backlog", "slow_db", "svc_cpu_cap", "svc_mem_cap", "svc_net"]

SIGNALS = [("futex_long_waits_per_s", "futex blocks/s"),
           ("futex_short_waits_per_s", "futex SHORT waits/s"),
           ("futex_wait_s_per_s",     "futex wait s/s"),
           ("futex_p95_ms",           "futex p95 ms"),
           ("softirq_s_per_s",        "softirq s/s"),
           ("softirq_NET_RX_s_per_s", "softirq NET_RX s/s"),
           ("hardirq_s_per_s",        "hardirq s/s")]


def family_of(name):
    for f in sorted(FAMILIES, key=len, reverse=True):
        if f in name:
            return f
    return "?"


def med(v):
    v = [x for x in v if isinstance(x, (int, float))]
    return round(statistics.median(v), 3) if v else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default="report.json")
    a = ap.parse_args()

    rows = []
    for p in sorted(glob.glob(os.path.join(a.dir, "*.json"))):
        if os.path.basename(p) == os.path.basename(a.out):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:                                              # noqa: BLE001
            continue
        if "summary" not in d:
            continue
        rows.append({"run": os.path.basename(p)[:-5],
                     "family": family_of(os.path.basename(p)),
                     "s": d["summary"], "d": d})
    if not rows:
        print("no probe outputs found in", a.dir)
        return 1
    print(f"{len(rows)} runs, {len(set(r['family'] for r in rows))} families\n")

    per_family = {}
    for key, label in SIGNALS:
        print(f"=== {label} ===")
        print(f"  {'family':20s} {'n':>3s} {'baseline':>10s} {'incident':>10s} {'x':>7s}")
        for fam in FAMILIES:
            rs = [r for r in rows if r["family"] == fam]
            if not rs:
                continue
            b = med([r["s"].get(key, {}).get("baseline") for r in rs])
            i = med([r["s"].get(key, {}).get("incident") for r in rs])
            x = med([r["s"].get(key, {}).get("x") for r in rs])
            per_family.setdefault(fam, {})[key] = {"n": len(rs), "baseline": b,
                                                   "incident": i, "x": x}
            flag = ""
            if isinstance(x, (int, float)):
                flag = "  <<<" if (x >= 2.0 or x <= 0.5) else ""
            print(f"  {fam:20s} {len(rs):3d} {str(b):>10s} {str(i):>10s} {str(x):>7s}{flag}")
        print()

    # the verdict we actually came for
    print("=== is each signal quiet enough to mean something on its own? ===")
    verdict = {}
    for key, label in SIGNALS:
        xs = [(f, v[key]["x"]) for f, v in per_family.items()
              if isinstance(v.get(key, {}).get("x"), (int, float))]
        movers = [(f, x) for f, x in xs if x >= 2.0 or x <= 0.5]
        biggest = max((abs_x for _, x in xs for abs_x in [max(x, 1 / x if x else 0)]),
                      default=None)
        verdict[key] = {"families_measured": len(xs),
                        "families_that_move": [{"family": f, "x": x} for f, x in movers],
                        "largest_move_x": round(biggest, 2) if biggest else None}
        if not xs:
            print(f"  {label:22s} no data")
        elif not movers:
            print(f"  {label:22s} FLAT across all {len(xs)} families "
                  f"(largest move {biggest:.2f}x) - usable as a specific signal")
        else:
            names = ", ".join(f"{f} {x}x" for f, x in sorted(movers, key=lambda r: -r[1])[:5])
            print(f"  {label:22s} moves on {len(movers)}/{len(xs)}: {names}")

    json.dump({"n_runs": len(rows), "per_family": per_family, "verdict": verdict,
               "runs": [{"run": r["run"], "family": r["family"], "summary": r["s"]}
                        for r in rows]},
              open(a.out, "w"), indent=2, default=str)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
