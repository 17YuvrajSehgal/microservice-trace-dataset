#!/usr/bin/env python3
"""Run every blueprint's decision rule over every evidence pack and score the result.

This is the rule-engine scoreboard: no model, just the thresholds the blueprints declare.
It answers the two questions E1 exists for -

    does a blueprint fire on the fault it was written for?
    does it stay quiet on the twelve it was not?

A fault with no blueprint SHOULD produce silence. Silence there is a correct answer, not a
gap, so it is counted as one.

    python3 decide_report.py --packs <dir> [--packs <dir>] --out report.json
"""
from __future__ import annotations
import argparse, collections, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_decide as BD                                          # noqa: E402

# families a blueprint claims; anything else should get silence
COVERED = {v[1] for v in BD.VERDICTS.values()}

FAMILIES = ["anomaly_cpu", "anomaly_disk", "anomaly_mem", "anomaly_net", "dependency_outage",
            "error_storm", "noisy_neighbor", "normal", "queue_backlog", "slow_db",
            "svc_cpu_cap", "svc_mem_cap", "svc_net"]


def family_of(run_id):
    """Longest family name that prefixes the run id, after any tt_ prefix."""
    r = re.sub(r"^tt_", "", run_id)
    hits = [f for f in FAMILIES if r.startswith(f)]
    return max(hits, key=len) if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", action="append", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    rows = []
    for d in a.packs:
        app = os.path.basename(d.rstrip("/"))
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            rid = os.path.basename(f)[:-5]
            fam = family_of(rid)
            if not fam:
                continue
            pack = json.load(open(f, encoding="utf-8"))
            v = BD.decide(pack)
            said = v.get("fault_type")
            rows.append({"app": app, "run": rid, "family": fam,
                         "selected": v.get("selected"), "said": said,
                         "fired": v.get("blueprints_fired") or [],
                         "correct": (said == fam) if said else (fam not in COVERED),
                         "silent": said is None,
                         "why": v.get("evidence")})

    n = len(rows)
    right = sum(r["correct"] for r in rows)
    wrong = [r for r in rows if not r["correct"] and not r["silent"]]
    quiet_miss = [r for r in rows if r["silent"] and r["family"] in COVERED]
    print(f"\n{n} runs: {right} correct ({100 * right // max(n, 1)}%), "
          f"{len(wrong)} wrong, {len(quiet_miss)} covered-but-silent")

    print("\n=== per family ===")
    print(f"{'family':20s} {'covered':>7s} {'n':>3s} {'named right':>11s} "
          f"{'named wrong':>11s} {'silent':>6s}")
    per = collections.defaultdict(list)
    for r in rows:
        per[r["family"]].append(r)
    for fam in sorted(per):
        rs = per[fam]
        ok = sum(1 for r in rs if r["said"] == fam)
        bad = sum(1 for r in rs if r["said"] and r["said"] != fam)
        sil = sum(1 for r in rs if r["silent"])
        cov = "yes" if fam in COVERED else "no"
        flag = "  <-- WRONG" if bad else ""
        print(f"{fam:20s} {cov:>7s} {len(rs):3d} {ok:11d} {bad:11d} {sil:6d}{flag}")

    if wrong:
        print("\n=== wrong answers ===")
        for r in wrong:
            print(f"  {r['app']:12s} {r['run']:42s} {r['family']} -> said {r['said']}")

    print("\n=== which blueprint fired, and was it right? ===")
    byb = collections.defaultdict(lambda: {"n": 0, "right": 0})
    for r in rows:
        if r["selected"]:
            b = byb[r["selected"]]
            b["n"] += 1
            b["right"] += r["correct"]
    for name in sorted(byb, key=lambda k: -byb[k]["n"]):
        b = byb[name]
        print(f"  {name:28s} fired {b['n']:3d}  right {b['right']:3d}")
    silent_bp = [v[0] for k, v in [(k, (k,)) for k in BD.VERDICTS] if k not in byb]
    if silent_bp:
        print(f"  never fired: {', '.join(silent_bp)}")

    if a.out:
        json.dump({"n": n, "correct": right, "rows": rows},
                  open(a.out, "w", encoding="utf-8"), indent=2, default=str)
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
