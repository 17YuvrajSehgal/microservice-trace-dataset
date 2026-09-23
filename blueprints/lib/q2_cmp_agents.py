#!/usr/bin/env python3
"""Compare agent v1 and v2 on the network problems, separating two changes that landed together.

Three arms, and the point of the middle one is that without it "v2 is better" is unattributable:

  A  v1 agent, OLD tools     the published cells in q2-ss / q2-tt
  B  v1 agent, FIXED tools   isolates the tool fixes (reply cap, LINE_CAP, value_sum, timespan)
  C  v2 agent, FIXED tools   isolates the architecture (planner/workers, scratchpad, run_python)

A->B is what we fixed underneath the agent. B->C is what the new agent adds on top.

Arm A carries both asks and 5 repeats; B and C are hint-only with 2. Rates are comparable, n is
not, so n is printed beside every number.

    python q2_cmp_agents.py
"""
from __future__ import annotations
import argparse, collections, glob, json, os

S = "/scratch/yuvraj17/stratatrace/results"
PROBLEMS = ["svc_net", "anomaly_net"]

# The best honest answer differs by problem. svc_net degrades ONE service, so naming it (or its
# container) is the target. anomaly_net degrades the host's network with no culprit workload,
# so "the whole host / every container" is the ceiling - demanding a service name there would
# score an honest answer wrong. Same rule as q2_rescore.WHERE_CEILING.
WHERE_OK = {"svc_net": {"named", "container"},
            "anomaly_net": {"named", "container", "scope"}}


def load(root, app_prefix, problem, ask="hint"):
    out = []
    for sp in glob.glob("%s/%s/*/*/*/*/score.json" % (root, problem)):
        try:
            r = json.load(open(sp))
        except Exception:
            continue
        rid = r.get("run_id") or ""
        is_tt = rid.startswith("tt_")
        if (app_prefix == "tt") != is_tt:
            continue
        if ask and r.get("ask") != ask:
            continue
        # the v2 cells carry a rep99 smoke row in some dirs; keep the real repeats only
        if int(r.get("repeat") or 0) > 10:
            continue
        out.append(r)
    return out


def summarise(rows, problem):
    n = len(rows)
    if not n:
        return None
    ok = WHERE_OK[problem]
    v = collections.Counter(r.get("window_verdict") for r in rows)
    return {
        "n": n,
        "where": sum(1 for r in rows if r.get("where") in ok),
        "hit": v["hit"], "partial": v["partial"], "abstained": v["abstained"], "miss": v["miss"],
        "fault": sum(1 for r in rows if r.get("fault_ok")),
        "iou": sum(r.get("window_iou") or 0 for r in rows) / n,
        "calls": sum(r.get("calls") or r.get("n_tool_calls") or 0 for r in rows) / n,
        "secs": sum(r.get("seconds") or r.get("wall_s") or 0 for r in rows) / n,
        "tok": sum(r.get("tokens") or 0 for r in rows) / n,
    }


def pct(a, b):
    return "%d/%d (%.0f%%)" % (a, b, 100.0 * a / b) if b else "-"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="A,B,C")
    a = ap.parse_args()

    ARMS = [
        ("A  v1 + old tools", {"ss": os.path.join(S, "q2-ss"), "tt": os.path.join(S, "q2-tt")}),
        ("B  v1 + fixed tools", {"ss": os.path.join(S, "v2cmp-v1"),
                                 "tt": os.path.join(S, "v2cmp-v1")}),
        ("C  v2 + fixed tools", {"ss": os.path.join(S, "v2cmp-v2"),
                                 "tt": os.path.join(S, "v2cmp-v2")}),
    ]
    want = set(a.arms.split(","))
    ARMS = [x for x in ARMS if x[0][0] in want]

    for app, pre, label in (("sockshop", "ss", "SOCK SHOP"), ("trainticket", "tt", "TRAIN TICKET")):
        print()
        print("=" * 100)
        print(label)
        print("=" * 100)
        for problem in PROBLEMS:
            print()
            print("  %s" % problem)
            print("  %-22s %5s %-16s %-16s %-16s %8s %7s" %
                  ("arm", "n", "WHERE right", "window hit", "abstained", "mean IoU", "calls"))
            print("  " + "-" * 96)
            for name, roots in ARMS:
                rows = load(roots[pre], pre, problem)
                s = summarise(rows, problem)
                if not s:
                    print("  %-22s %5s  (no cells yet)" % (name, "-"))
                    continue
                print("  %-22s %5d %-16s %-16s %-16s %8.3f %7.1f"
                      % (name, s["n"], pct(s["where"], s["n"]), pct(s["hit"], s["n"]),
                         pct(s["abstained"], s["n"]), s["iou"], s["calls"]))
    print()
    print("=" * 100)
    print("cost per cell")
    print("=" * 100)
    print("  %-22s %10s %10s" % ("arm", "mean secs", "mean tokens"))
    for name, roots in ARMS:
        rows = []
        for pre in ("ss", "tt"):
            for problem in PROBLEMS:
                rows += load(roots[pre], pre, problem)
        if rows:
            s = summarise(rows, "svc_net")
            print("  %-22s %10.0f %10.0f" % (name, s["secs"], s["tok"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
