#!/usr/bin/env python3
"""Score the CPU blueprints against v2 ground truth, using the thresholds that actually ship.

The constants and rule functions are IMPORTED from blueprint_decide.py rather than copied. A
scorer with its own copy of the numbers can pass while the shipped rule fails, which is the
one result that would be worse than no scorer at all.

Ground truth is the family name in the task file, which comes from the directory the run was
collected into - so it is the label the campaign assigned, not a re-derivation.

    host-cpu-saturation   should fire on anomaly_cpu and nothing else
    cpu-contention        should fire on noisy_neighbor and nothing else
    service-cpu-throttle  should fire on svc_cpu_cap and nothing else
    (normal fires nothing)

    python3 score_v2_cpu.py --oncpu <dir> --tasks <task_file> [--rq <dir>] [--out scored.json]

--rq is optional. The cgroup-cap rule needs runqueue delay for its `waiting_for_cpu` clause;
without it that rule is reported as UNSCORABLE rather than silently counted as a miss.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_decide as BD                                          # noqa: E402

# Which family each rule is supposed to fire on. Everything else is a false positive.
OWNS = {
    "host-cpu-saturation": "anomaly_cpu",
    "cpu-contention": "noisy_neighbor",
    "service-cpu-throttle": "svc_cpu_cap",
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


def rq_for(rq_dir, run):
    """The shape blueprint_decide's rules expect. Absent rq is None, not a zero - a zero would
    quietly make `waiting_for_cpu` false and turn 'we did not measure it' into 'it did not
    happen'."""
    if not rq_dir:
        return None
    p = os.path.join(rq_dir, f"{run}.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p))
    rows = d.get("services") or d.get("rows") or []
    xs = [r.get("p95_x") for r in rows if isinstance(r.get("p95_x"), (int, float))]
    return {"max": max(xs) if xs else 0.0, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oncpu", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--rq", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    truth = load_tasks(a.tasks)
    # rule name -> {family -> [ (run, fired) ]}
    fired = collections.defaultdict(lambda: collections.defaultdict(list))
    per_app = collections.defaultdict(lambda: collections.defaultdict(list))
    rows = []
    unscorable = collections.Counter()

    for run, (app, fam) in sorted(truth.items()):
        p = os.path.join(a.oncpu, f"{run}.json")
        if not os.path.exists(p):
            unscorable["no oncpu measurement"] += 1
            continue
        pack = {"oncpu": json.load(open(p))}
        cpu = BD._cpu(pack)
        rq = rq_for(a.rq, run)
        rq_in = rq or {"max": 0.0, "rows": []}

        sat = BD.host_saturation_rule(cpu, rq_in)
        cot = BD.co_tenant_rule(cpu, rq_in, {})
        thr = BD.cpu_throttle_rule(cpu, rq_in) if rq else None
        if thr is None:
            unscorable["service-cpu-throttle needs runqueue delay"] += 1

        # The clause-by-clause breakdown for the co-tenant rule, because when it fails we need
        # to know WHICH clause, not just that it did.
        ui, ur, tc = cpu["util_incident"], cpu["util_ratio"], cpu["thief_cores"]
        clauses = {
            "has_thief": tc >= BD.THIEF_CORES and not BD.is_infra(cpu["thief_comm"]),
            "bounded": tc < BD.BIG_THIEF,
            "busy": ui is not None and ui >= BD.CONTENDED,
            "headroom": ui is not None and ui < BD.SATURATED,
            "rising": ur is not None and ur > 1.0,
        }
        # The counterfactual: the thief test alone, dropping the absolute-utilisation clause.
        thief_only = clauses["has_thief"] and clauses["bounded"] and clauses["rising"]

        for name, res in (("host-cpu-saturation", sat), ("cpu-contention", cot),
                          ("service-cpu-throttle", thr)):
            if res is None:
                continue
            fired[name][fam].append((run, res["fires"]))
            per_app[(name, app)][fam].append(res["fires"])
        fired["cpu-contention[thief-only]"][fam].append((run, thief_only))
        per_app[("cpu-contention[thief-only]", app)][fam].append(thief_only)

        rows.append({"run": run, "app": app, "family": fam,
                     "util_baseline": cpu["util_baseline"], "util_incident": ui,
                     "util_ratio": ur, "thief_comm": cpu["thief_comm"], "thief_cores": tc,
                     "loser_cores": cpu["loser_cores"],
                     "saturation_fires": sat["fires"], "co_tenant_fires": cot["fires"],
                     "co_tenant_clauses": clauses, "thief_only_fires": thief_only,
                     "throttle_fires": (thr or {}).get("fires")})

    def report(name):
        owns = OWNS.get(name.split("[")[0], "?")
        fams = fired[name]
        tp = sum(1 for r, f in fams.get(owns, []) if f)
        pos = len(fams.get(owns, []))
        fp = sum(1 for fam, lst in fams.items() if fam != owns for r, f in lst if f)
        neg = sum(len(lst) for fam, lst in fams.items() if fam != owns)
        print(f"\n  {name}   (should fire on {owns})")
        print(f"    recall     {tp}/{pos}" + (f"  = {tp/pos:.0%}" if pos else ""))
        print(f"    false fires {fp}/{neg}" + (f"  = {fp/neg:.0%}" if neg else ""))
        for fam in sorted(fams):
            n = sum(1 for r, f in fams[fam] if f)
            flag = "  <-- should be 0" if (fam != owns and n) else \
                   ("  <-- should be all" if (fam == owns and n < len(fams[fam])) else "")
            print(f"      {fam:16s} {n:2d}/{len(fams[fam]):2d} fire{flag}")
        for app in ("sockshop", "trainticket"):
            key = (name, app)
            if key not in per_app:
                continue
            t = sum(1 for v in per_app[key].get(owns, []) if v)
            p_ = len(per_app[key].get(owns, []))
            f_ = sum(1 for fam, lst in per_app[key].items() if fam != owns for v in lst if v)
            print(f"      [{app:11s}] recall {t}/{p_}, false fires {f_}")

    print("=" * 66)
    print(f" BLUEPRINT SCORING on v2  -  {len(rows)} runs")
    print(f" thresholds imported from blueprint_decide: SATURATED={BD.SATURATED} "
          f"CONTENDED={BD.CONTENDED} THIEF_CORES={BD.THIEF_CORES} BIG_THIEF={BD.BIG_THIEF}")
    print("=" * 66)
    for name in ("host-cpu-saturation", "cpu-contention", "cpu-contention[thief-only]",
                 "service-cpu-throttle"):
        if fired.get(name):
            report(name)
    if unscorable:
        print("\n  unscorable:")
        for why, n in unscorable.items():
            print(f"    {n:3d}  {why}")

    if a.out:
        json.dump({"rows": rows,
                   "thresholds": {"SATURATED": BD.SATURATED, "CONTENDED": BD.CONTENDED,
                                  "THIEF_CORES": BD.THIEF_CORES, "BIG_THIEF": BD.BIG_THIEF,
                                  "COLLAPSE_RATIO": BD.COLLAPSE_RATIO,
                                  "LOSER_CORES": BD.LOSER_CORES}},
                  open(a.out, "w"), indent=2)
        print(f"\n  wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
