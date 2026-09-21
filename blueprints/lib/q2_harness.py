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

RANK_K = 5          # primary + up to 4 alternatives, 5 candidates in total
NARROW_AT = 2       # "narrowed" = the true answer is in the TOP 2

# Narrowing is scored at top-2 rather than top-5 on purpose. The point of a blueprint is that a
# human analyst then goes and checks - "instead of many different reasons, you narrow down, then
# the human analyst will go and check" - and handing someone 5 candidates out of ~12 fault types
# is barely a narrowing. Two is a shortlist they can actually work through. hit@5 and MRR are
# recorded as well, so a different bar can be applied later without re-running anything.


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
                # narrowing, the thing a ranked answer buys us
                "narrowed_pct": pct(lambda r: (r.get("rank") or 99) <= NARROW_AT),
                "hit_at_k_pct": pct(lambda r: r.get("hit_at_k")),
                "mrr": (round(sum(r.get("mrr") or 0 for r in rs) / n, 3) if n else None),
                "median_candidates": _median([r.get("n_candidates") for r in rs]),
                # F1, two ways, because they answer different questions
                "set_f1": (round(sum(set_f1(bool(r.get("hit_at_k")),
                                            r.get("n_candidates") or 0) for r in rs) / n, 3)
                           if n else None),
                "macro_f1": macro_f1(rs)["macro_f1"],
                # COST. A blueprint that buys accuracy by taking three times as long is a
                # different trade from one that is faster, and only the numbers show which.
                "median_seconds": _median([r.get("seconds") for r in rs]),
                "median_tool_calls": _median([r.get("calls") for r in rs]),
                "median_tokens": _median([r.get("tokens") for r in rs]),
            }
        for ask in ASKS:
            a, b = entry.get("%s|none" % ask), entry.get("%s|given" % ask)
            if not (a and b):
                continue
            if a["both_pct"] is not None and b["both_pct"] is not None:
                entry["%s|delta_pts" % ask] = b["both_pct"] - a["both_pct"]
            if a["narrowed_pct"] is not None and b["narrowed_pct"] is not None:
                entry["%s|narrowed_delta_pts" % ask] = b["narrowed_pct"] - a["narrowed_pct"]
            if a["median_seconds"] and b["median_seconds"]:
                entry["%s|seconds_ratio" % ask] = round(
                    b["median_seconds"] / a["median_seconds"], 2)
            if a["set_f1"] is not None and b["set_f1"] is not None:
                entry["%s|set_f1_delta" % ask] = round(b["set_f1"] - a["set_f1"], 3)
        out[fam] = entry
    return out


def _median(vals):
    v = sorted(x for x in vals if isinstance(x, (int, float)))
    return v[len(v) // 2] if v else None


def set_f1(hit: bool, n_candidates: int) -> float:
    """F1 of the returned candidate SET against the single true answer.

    There is exactly one ground truth, so with a ranked list of size k:
        precision = 1/k if the truth is in the list, else 0
        recall    = 1   if the truth is in the list, else 0
        F1        = 2PR/(P+R)

    This is the metric that actually prices narrowing. Returning the right answer alone scores
    1.00; right answer buried in 5 candidates scores 0.33; a confident wrong answer scores 0.
    An agent cannot game it by listing everything - padding the list drives precision down - and
    it separates "found it" from "found it and said so cleanly", which `both_ok` cannot.
    """
    if not hit or not n_candidates:
        return 0.0
    p, r = 1.0 / n_candidates, 1.0
    return round(2 * p * r / (p + r), 3)


def macro_f1(rows, field="pred_fault", truth="true_fault") -> dict:
    """Macro-F1 over fault types across a set of runs - the classification view.

    Per class: precision = TP/(TP+FP), recall = TP/(TP+FN), then averaged over classes that
    appear as either truth or prediction. Macro rather than micro so a rare fault counts as much
    as a common one; with 3 incidents per problem the support is small either way, so read it
    alongside the counts rather than on its own.
    """
    tp, fp, fn = {}, {}, {}
    classes = set()
    for r in rows:
        t, p = r.get(truth), r.get(field)
        classes.update(x for x in (t, p) if x)
        if t == p and t:
            tp[t] = tp.get(t, 0) + 1
        else:
            if p:
                fp[p] = fp.get(p, 0) + 1
            if t:
                fn[t] = fn.get(t, 0) + 1
    if not classes:
        return {"macro_f1": None, "per_class": {}}
    per = {}
    for c in sorted(classes):
        t_, f_, n_ = tp.get(c, 0), fp.get(c, 0), fn.get(c, 0)
        p = t_ / (t_ + f_) if (t_ + f_) else 0.0
        rc = t_ / (t_ + n_) if (t_ + n_) else 0.0
        per[c] = {"precision": round(p, 3), "recall": round(rc, 3),
                  "f1": round(2 * p * rc / (p + rc), 3) if (p + rc) else 0.0,
                  "support": t_ + n_}
    return {"macro_f1": round(sum(v["f1"] for v in per.values()) / len(per), 3),
            "per_class": per}


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    ap = argparse.ArgumentParser()
    # FIRST RUN IS ONE PROBLEM. noisy_neighbor, for two reasons that point the same way:
    #   * it is where the agent most needs help - in the 2 Sept data it got this right
    #     0 times out of 6 unaided, the only family it could not do at all
    #   * its blueprint has the most threshold work behind it. BIG_THIEF_SHARE was re-derived
    #     to 0.297 (geometric midpoint, 1.78x margin each way) after the original 0.167 turned
    #     out to be a separation cut misused as a ceiling, which cost 1 of 16 runs.
    # Maximum headroom and the blueprint I trust most - if it shows nothing here, the whole
    # approach needs rethinking before spending 360 runs on it.
    ap.add_argument("--problems", default="noisy_neighbor")
    ap.add_argument("--data-root", default="/scratch/yuvraj17/stratatrace/data/stratatrace-v2")
    ap.add_argument("--incidents", type=int, default=3,
                    help="incidents per problem - the same for every problem")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--asks", default="nohint,hint")
    ap.add_argument("--out-dir", default=os.path.join(root, "blueprints", "results", "q2"))
    # Cheapest of the GPT family. The arms are both on the same model so the with/without
    # comparison is valid - but this is NOT comparable to the 2 Sept baseline of 56%, which ran
    # on full gpt-5.4. Do not put a nano number next to that one in a table.
    ap.add_argument("--model", default="gpt-5.4-nano")
    ap.add_argument("--provider", default="azure")
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("RCA_PROVIDER", args.provider)
    os.environ.setdefault("RCA_MODEL", args.model)

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
