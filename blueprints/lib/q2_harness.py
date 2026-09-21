#!/usr/bin/env python3
"""Question 2: given the problem AND the blueprint, does the blueprint help?

THE ONE THING THAT MAKES THIS DIFFERENT FROM THE OLD EXPERIMENT
---------------------------------------------------------------
`withwithout.json` (2 Sept) let the agent CHOOSE its blueprint from the whole library. That
conflated two things, and the raw file shows it:

    "selection": { "n_with_a_pick": 57, "n_correct_pick": 19, "n_no_pick": 0 }

Selection was right 19 times in 57. Splitting by whether a blueprint even covers the fault:

    fault HAS a blueprint   36 runs   without 20 (56%)   with 20 (56%)   dead even
    fault has NONE          21 runs   without 12 (57%)   with  9 (43%)   -14 pts

The entire pooled loss came from the agent picking a blueprint written for a different fault.
That experiment measured `selection accuracy x usefulness` and reported it as usefulness.

Naser parked selection (16 Sept): "we can assume that they're giving the blueprint along with
the problem." So here the blueprint is HANDED OVER, never chosen, and the only thing that varies
between arms is whether it is present.

THE DESIGN
----------
  arm      none    : no blueprint
           given   : exactly ONE blueprint, injected directly, selector bypassed

  ask      nohint  : "diagnose this incident"
           hint    : the operator's SYMPTOM report - "requests are slow and the network path
                     looks degraded". Never the fault name, never the culprit service: a hint
                     that names the answer stops the arms comparing anything. Identical string
                     in both arms so it cannot advantage one.

  repeats  5 for EVERY cell. The model is stochastic; one run per cell measures nothing.

RANKED ANSWERS, so narrowing can be scored
------------------------------------------
`rank_k` turns on the `alternatives` field: the agent returns a primary verdict plus up to
rank_k-1 further candidates, best first, each needing its OWN cited evidence (the harness drops
a candidate that just restates the primary). Narrowing ~12 fault types to a ranked 4 is a real
result even when the top pick is wrong - Naser: "instead of many different reasons, you narrow
down, then the human analyst will go and check."

HOW WE KNOW THE ANSWER IS RIGHT
-------------------------------
We injected the fault. `ground_truth.json` records the family, the target service and the
injection window. Worth stating in the paper rather than leaving implied - Naser asked twice.

WHAT IS SCORED AUTOMATICALLY, AND WHAT IS NOT
---------------------------------------------
Automatic: service_hit, fault_hit, both, hit@k, MRR.
NOT automatic: whether the cited `evidence` is true and whether the reasoning is sound. Nothing
checks that a run scoring `both=True` did not fabricate its evidence. Yuvraj reviews those by
hand, which is why every run writes a self-contained folder.

    python3 q2_harness.py --plan
    python3 q2_harness.py --incidents 3 --repeats 5 --out-dir results/q2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

# The six problems testable today: a blueprint exists, both applications, 10+ runs.
# lock_contention / priority_inversion / conn_pool_exhaustion are latency problems too but have
# NO blueprint - see COVERAGE-which-blueprints-are-missing.md. Not in this matrix.
PROBLEMS = {
    "slow_db":         {"blueprint": "db-latency-dependency-wait",
                        "hint": "requests are slow and the slowness looks like it is coming from "
                                "a datastore or a dependency"},
    "anomaly_net":     {"blueprint": "network-path-degradation",
                        "hint": "requests are slow and the network path looks degraded"},
    "svc_net":         {"blueprint": "network-path-degradation",
                        "hint": "requests are slow and the network path looks degraded"},
    "noisy_neighbor":  {"blueprint": "cpu-contention-co-tenant",
                        "hint": "requests are slow and the host looks contended"},
    "svc_cpu_cap":     {"blueprint": "service-cpu-throttle",
                        "hint": "one service is slow while the host looks healthy"},
    "anomaly_cpu":     {"blueprint": "host-cpu-saturation",
                        "hint": "requests are slow across the board and the host looks busy"},
}

# anomaly_net and svc_net share one blueprint on purpose - does a single network blueprint serve
# both host-wide and single-container degradation? Kept as separate problems so the answer shows.
ARMS = ("none", "given")
ASKS = ("nohint", "hint")
RANK_K = 4          # primary + up to 3 alternatives


def incidents_for(family: str, data_root: str, limit: int) -> list:
    """Run dirs for one family, capped at `limit` - the SAME cap for every problem, so no
    problem gets more attempts than another.

    Reads the WORKING COPY, not the archives. Those two fell out of step once already
    (DATASET-v2-INVENTORY, "THE TRAP"): if a family returns nothing here, check its replacement
    was extracted before concluding the runs do not exist.
    """
    out = []
    for app in ("sockshop", "trainticket"):
        d = os.path.join(data_root, app, family)
        if not os.path.isdir(d):
            continue
        for run in sorted(os.listdir(d)):
            rd = os.path.join(d, run)
            if run.endswith("_metrics") or not os.path.isdir(rd):
                continue
            if not os.path.exists(os.path.join(rd, "meta", "runinfo_end.txt")):
                continue
            if not os.path.exists(os.path.join(rd, "ground_truth.json")):
                continue
            out.append({"app": app, "family": family, "run_id": run, "run_dir": rd})
    return out[:limit]


def cell_dir(out_dir: str, fam: str, run_id: str, ask: str, arm: str, rep: int) -> str:
    """One self-contained folder per agent run, so a human review needs nothing else open.

      <out>/<problem>/<run_id>/<ask>/<arm>/rep<N>/
          diagnosis.json     primary verdict + ranked alternatives + cited evidence
          score.json         service_hit / fault_hit / both / hit@k / MRR
          ground_truth.json  what we injected - the thing the answer is checked against
          transcript.jsonl   every prompt, tool call and response
          blueprint.md       the exact skill body given (given-arm only)
    """
    return os.path.join(out_dir, fam, run_id, ask, arm, "rep%d" % rep)


def build_matrix(problems, data_root, incidents, repeats, asks, out_dir) -> list:
    cells = []
    for fam in problems:
        for inc in incidents_for(fam, data_root, incidents):
            for ask in asks:
                for arm in ARMS:
                    for rep in range(1, repeats + 1):
                        cells.append({
                            **inc, "arm": arm, "ask": ask, "repeat": rep, "rank_k": RANK_K,
                            "blueprint": PROBLEMS[fam]["blueprint"] if arm == "given" else None,
                            "hint": PROBLEMS[fam]["hint"] if ask == "hint" else None,
                            "dir": cell_dir(out_dir, fam, inc["run_id"], ask, arm, rep),
                        })
    return cells


def summarise(rows) -> dict:
    """One number per problem per arm - the table Naser asked for, plus narrowing."""
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r["family"]][(r["ask"], r["arm"])].append(r)

    out = {}
    for fam, cells in sorted(by.items()):
        entry = {}
        for (ask, arm), rs in sorted(cells.items()):
            n = len(rs)
            def pct(f):
                return round(100 * sum(1 for r in rs if f(r)) / n) if n else None
            entry["%s|%s" % (ask, arm)] = {
                "n": n,
                "both_pct": pct(lambda r: r.get("both_ok")),
                "service_pct": pct(lambda r: r.get("service_ok")),
                "fault_pct": pct(lambda r: r.get("fault_ok")),
                # narrowing: right answer anywhere in the ranked list, and how far down
                "hit_at_k_pct": pct(lambda r: r.get("hit_at_k")),
                "mrr": (round(sum(r.get("mrr") or 0 for r in rs) / n, 3) if n else None),
                "median_candidates": _median([r.get("n_candidates") for r in rs]),
            }
        for ask in ASKS:
            a, b = entry.get("%s|none" % ask), entry.get("%s|given" % ask)
            if a and b and a["both_pct"] is not None and b["both_pct"] is not None:
                entry["%s|delta_pts" % ask] = b["both_pct"] - a["both_pct"]
        out[fam] = entry
    return out


def _median(vals):
    v = sorted(x for x in vals if isinstance(x, (int, float)))
    return v[len(v) // 2] if v else None


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    ap = argparse.ArgumentParser()
    ap.add_argument("--problems", default=",".join(PROBLEMS))
    ap.add_argument("--data-root", default="/scratch/yuvraj17/stratatrace/data/stratatrace-v2")
    ap.add_argument("--incidents", type=int, default=3,
                    help="incidents per problem - the same for every problem")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--asks", default="nohint,hint")
    ap.add_argument("--out-dir", default=os.path.join(root, "blueprints", "results", "q2"))
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()

    problems = [p for p in args.problems.split(",") if p]
    unknown = [p for p in problems if p not in PROBLEMS]
    if unknown:
        print("no blueprint for: %s" % ", ".join(unknown))
        print("see blueprints/docs/COVERAGE-which-blueprints-are-missing.md")
        return 2
    asks = [a for a in args.asks.split(",") if a]

    print("=== question 2 matrix ===")
    print("  the blueprint is GIVEN, never selected. ranked answers on: rank_k=%d" % RANK_K)
    print()
    print("  %-18s %-30s %8s %10s" % ("problem", "blueprint", "avail", "used"))
    print("  " + "-" * 70)
    total_inc = 0
    short = []
    for fam in problems:
        avail = len(incidents_for(fam, args.data_root, 10 ** 6))
        used = len(incidents_for(fam, args.data_root, args.incidents))
        total_inc += used
        if used < args.incidents:
            short.append((fam, used))
        print("  %-18s %-30s %8d %10d%s"
              % (fam, PROBLEMS[fam]["blueprint"], avail, used,
                 "   <-- SHORT" if used < args.incidents else ""))

    n = total_inc * len(ARMS) * len(asks) * args.repeats
    print()
    print("  incidents %d  x  arms %d  x  asks %d  x  repeats %d  =  %d agent runs"
          % (total_inc, len(ARMS), len(asks), args.repeats, n))
    if short:
        print("  WARNING: not equal across problems - %s" % ", ".join("%s=%d" % s for s in short))
    print()
    print("  results: %s/<problem>/<run_id>/<ask>/<arm>/rep<N>/" % args.out_dir)
    print("           diagnosis.json  score.json  ground_truth.json  transcript.jsonl  blueprint.md")

    cells = build_matrix(problems, args.data_root, args.incidents, args.repeats, asks,
                         args.out_dir)
    if args.plan:
        os.makedirs(args.out_dir, exist_ok=True)
        pl = os.path.join(args.out_dir, "plan.json")
        json.dump({"matrix": cells, "problems": {p: PROBLEMS[p] for p in problems},
                   "rank_k": RANK_K, "n_runs": len(cells)}, open(pl, "w"), indent=1)
        print("\n  wrote plan: %s" % pl)
        return 0

    if not cells:
        print("\nNothing to run - the working copy does not hold these families.")
        return 1

    sys.path.insert(0, os.path.join(root, "agentic-rca"))
    try:
        import agent                                                    # noqa: F401
    except Exception as e:                                              # noqa: BLE001
        print("\ncannot import the agent harness: %r" % (e,))
        return 1
    print("\nexecution not wired in this commit - use --plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
