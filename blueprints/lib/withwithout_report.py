#!/usr/bin/env python3
"""Score the with/without experiment: does a blueprint beat not having one?

Same model, same evidence, same incidents. The only difference between the two arms is
whether the blueprint library was available.

Field names come from evaluate.py: rows live under "results", correctness is nested in
score{service_hit,fault_hit,both,no_answer}, and effort is n_tool_calls/tokens/wall_s.
There is no per-run cost field, so effort is reported in tokens and calls.

Reports per application and per fault family, because a headline average can hide the thing
that matters - the whole point of the blueprints is that they encode what a fault looks like,
so any lift should be concentrated on the families a blueprint actually covers, and the
uncovered families are the check that an irrelevant library does not mislead.

    python3 withwithout_report.py --dir <results dir> --out withwithout.json
"""
from __future__ import annotations
import argparse, json, os, statistics, sys

# families a blueprint covers - see blueprint_decide.VERDICTS
COVERED = {"noisy_neighbor", "anomaly_cpu", "svc_cpu_cap", "slow_db", "db_latency",
           "anomaly_net", "svc_net", "anomaly_disk"}
ARMS = [("without", "no blueprint"), ("with", "blueprint available")]


def load(path):
    """evaluate.py results file -> flat per-incident rows."""
    if not os.path.exists(path):
        return []
    d = json.load(open(path, encoding="utf-8"))
    out = []
    for r in d.get("results", []):
        s = r.get("score") or {}
        out.append({
            "run_id": r.get("run_id"), "family": r.get("family"),
            "service_ok": bool(s.get("service_hit")), "fault_ok": bool(s.get("fault_hit")),
            "both_ok": bool(s.get("both")), "no_answer": bool(s.get("no_answer")),
            "pred_fault": s.get("pred_fault"), "pred_service": s.get("pred_service"),
            "seconds": r.get("wall_s"), "tokens": r.get("tokens"),
            "calls": r.get("n_tool_calls"), "error": r.get("error"),
            "skill": r.get("skill_selected"), "skill_ok": r.get("selection_correct"),
        })
    return out


def med(rows, field):
    v = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
    return round(statistics.median(v)) if v else None


def agg(rows, key=lambda r: True):
    sel = [r for r in rows if key(r)]
    if not sel:
        return None
    n = len(sel)
    tok = [r["tokens"] for r in sel if isinstance(r.get("tokens"), (int, float))]
    return {"n": n,
            "service": sum(r["service_ok"] for r in sel),
            "fault": sum(r["fault_ok"] for r in sel),
            "both": sum(r["both_ok"] for r in sel),
            "both_pct": round(100 * sum(r["both_ok"] for r in sel) / n),
            "no_answer": sum(r["no_answer"] for r in sel),
            "errors": sum(1 for r in sel if r.get("error")),
            "median_s": med(sel, "seconds"), "median_calls": med(sel, "calls"),
            "median_tokens": med(sel, "tokens"),
            "total_tokens": sum(tok) if tok else None}


HDR = (f"{'app':7s} {'arm':22s} {'n':>4s} {'service':>8s} {'fault':>6s} {'BOTH':>6s} "
       f"{'rate':>6s} {'silent':>7s} {'med s':>7s} {'calls':>6s} {'med tok':>8s}")


def line(tag, desc, r):
    return (f"{tag:7s} {desc:22s} {r['n']:4d} {r['service']:8d} {r['fault']:6d} "
            f"{r['both']:6d} {r['both_pct']:5d}% {r['no_answer']:7d} "
            f"{str(r['median_s']):>7s} {str(r['median_calls']):>6s} "
            f"{str(r['median_tokens']):>8s}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default="withwithout.json")
    a = ap.parse_args()

    data = {(arm, app): load(os.path.join(a.dir, f"{arm}_{app}.json"))
            for arm, _ in ARMS for app in ("ss", "tt")}
    have = {k: len(v) for k, v in data.items() if v}
    if not have:
        print("no results found - check the arm logs in", a.dir)
        return 1
    print("loaded:", ", ".join(f"{k[0]}_{k[1]}={n}" for k, n in have.items()))

    print("\n" + HDR + "\n" + "-" * len(HDR))
    summary = {}
    for app, label in (("ss", "sockshop"), ("tt", "traintkt")):
        for arm, desc in ARMS:
            r = agg(data[(arm, app)])
            if r:
                summary[f"{label}_{arm}"] = r
                print(line(label, desc, r))

    print()
    pooled = {}
    for arm, desc in ARMS:
        r = agg(data[(arm, "ss")] + data[(arm, "tt")])
        if r:
            pooled[arm] = r
            print(line("POOLED", desc, r))

    headline = None
    if "with" in pooled and "without" in pooled:
        wo, wi = pooled["without"], pooled["with"]
        headline = {"both_delta_pts": wi["both_pct"] - wo["both_pct"],
                    "both_without": wo["both"], "both_with": wi["both"],
                    "n_without": wo["n"], "n_with": wi["n"],
                    "service_delta": wi["service"] - wo["service"],
                    "fault_delta": wi["fault"] - wo["fault"],
                    "silent_delta": wi["no_answer"] - wo["no_answer"]}
        print(f"\nHEADLINE  fully correct {wo['both']}/{wo['n']} -> {wi['both']}/{wi['n']}  "
              f"({headline['both_delta_pts']:+d} points)")
        print(f"          right service {wo['service']} -> {wi['service']}   "
              f"right fault {wo['fault']} -> {wi['fault']}   "
              f"no answer {wo['no_answer']} -> {wi['no_answer']}")

    # where the lift lands. A blueprint should help on what it covers and not mislead elsewhere.
    print("\nsplit by whether a blueprint covers the family:")
    covsplit = {}
    for grp, keyf in (("covered by a blueprint", lambda r: r["family"] in COVERED),
                      ("not covered", lambda r: r["family"] not in COVERED)):
        for arm, desc in ARMS:
            r = agg(data[(arm, "ss")] + data[(arm, "tt")], keyf)
            if r:
                covsplit[f"{grp}|{arm}"] = r
                print(f"  {grp:24s} {desc:22s} {r['n']:3d} runs  "
                      f"{r['both']:3d} correct ({r['both_pct']:3d}%)  "
                      f"{r['no_answer']:2d} silent")

    print("\nper family (fully correct):")
    print(f"  {'family':20s} {'covered':>8s} {'without':>9s} {'with':>9s} {'change':>7s}")
    per_family = {}
    for f in sorted({r["family"] for rows in data.values() for r in rows if r["family"]}):
        wo = agg(data[("without", "ss")] + data[("without", "tt")], lambda r: r["family"] == f)
        wi = agg(data[("with", "ss")] + data[("with", "tt")], lambda r: r["family"] == f)
        if not (wo and wi):
            continue
        per_family[f] = {"without": wo, "with": wi, "change": wi["both"] - wo["both"],
                         "covered": f in COVERED}
        print(f"  {f:20s} {'yes' if f in COVERED else 'no':>8s} "
              f"{wo['both']:4d}/{wo['n']:<4d} {wi['both']:4d}/{wi['n']:<4d} "
              f"{wi['both'] - wo['both']:+7d}")

    # did the selector pick the right blueprint? it sees only the masked evidence survey.
    withrows = [r for r in data[("with", "ss")] + data[("with", "tt")]]
    picked = [r for r in withrows if r.get("skill")]
    sel = None
    if picked:
        ok = sum(1 for r in picked if r.get("skill_ok"))
        sel = {"n_with_a_pick": len(picked), "n_correct_pick": ok,
               "n_no_pick": len(withrows) - len(picked)}
        print(f"\nblueprint selection: picked one on {len(picked)}/{len(withrows)} runs, "
              f"right blueprint {ok} times; picked none on {len(withrows) - len(picked)}")
        byskill = {}
        for r in picked:
            b = byskill.setdefault(r["skill"], {"n": 0, "right": 0, "both": 0})
            b["n"] += 1
            b["right"] += bool(r.get("skill_ok"))
            b["both"] += r["both_ok"]
        for k, v in sorted(byskill.items(), key=lambda kv: -kv[1]["n"]):
            print(f"  {k:34s} chosen {v['n']:3d}  right family {v['right']:3d}  "
                  f"fully correct {v['both']:3d}")
        sel["by_blueprint"] = byskill

    json.dump({"headline": headline, "pooled": pooled, "by_app": summary,
               "covered_split": covsplit, "per_family": per_family, "selection": sel,
               "rows": {f"{k[0]}_{k[1]}": v for k, v in data.items()}},
              open(a.out, "w"), indent=2, default=str)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
