#!/usr/bin/env python3
"""Find the component the slow call paths converge on.

A datastore that answers slowly has a distinctive shape in the call graph: its INCOMING
edges inflate while its own OUTGOING edges do not, because it is waiting on something
below the trace rather than on another traced service. Its callers are victims.

Reports every component with slow incoming edges, ranked, and marks which ones also have
slow outgoing edges (those are pass-through victims, not the cause — keep walking).

    python3 edge_convergence.py --run <run_dir> --app sockshop --out convergence.json
"""
from __future__ import annotations
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "agentic-rca"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--app", default="sockshop")
    ap.add_argument("--out", default="convergence.json")
    ap.add_argument("--slow-x", type=float, default=2.0,
                    help="an edge counts as slow at this baseline->incident p95 ratio")
    a = ap.parse_args()

    from stratatrace import load_run
    from tools import RunTools

    t = RunTools(load_run(a.run), app=a.app)
    topo, _ = t.topology(None)
    edges = topo.get("edges", []) if isinstance(topo, dict) else []
    if not edges:
        json.dump({"run": os.path.basename(a.run.rstrip("/")), "edges": [], "candidates": [],
                   "note": "no parent/child span links in this run - traces cannot locate a "
                           "convergence point here"}, open(a.out, "w"), indent=2)
        print("no trace edges in this run; wrote empty convergence")
        return 0

    incoming, outgoing = {}, {}
    for e in edges:
        x = e.get("slowdown_x")
        if x is None:
            continue
        incoming.setdefault(e.get("callee"), []).append((e.get("caller"), x))
        outgoing.setdefault(e.get("caller"), []).append((e.get("callee"), x))

    cands = []
    for comp, ins in incoming.items():
        slow_in = [(c, x) for c, x in ins if x >= a.slow_x]
        outs = outgoing.get(comp, [])
        slow_out = [(c, x) for c, x in outs if x >= a.slow_x]
        cands.append({
            "component": comp,
            "max_incoming_x": round(max(x for _, x in ins), 2),
            "n_slow_incoming": len(slow_in),
            "slow_callers": [c for c, _ in slow_in][:6],
            "emits_own_spans": bool(outs),
            "n_slow_outgoing": len(slow_out),
            "max_outgoing_x": round(max((x for _, x in outs), default=0), 2),
            # the cause is the DEEPEST component whose own dependencies are not also slow
            "is_terminal": len(slow_out) == 0,
        })
    cands.sort(key=lambda c: (-c["n_slow_incoming"], -c["max_incoming_x"]))
    terminal = [c for c in cands if c["is_terminal"] and c["n_slow_incoming"] > 0]

    out = {
        "run": os.path.basename(a.run.rstrip("/")),
        "slow_threshold_x": a.slow_x,
        "candidates": cands[:10],
        "converged_on": terminal[0]["component"] if terminal else None,
        "reasoning": (
            f"{terminal[0]['component']} has {terminal[0]['n_slow_incoming']} slow incoming "
            f"edge(s) (up to {terminal[0]['max_incoming_x']}x) and no slow outgoing edges, so "
            f"nothing it depends on explains its slowness"
            if terminal else
            "no component has slow incoming edges without also having slow outgoing edges - "
            "either the cause is not on the traced path, or every hop slowed together"),
    }
    json.dump(out, open(a.out, "w"), indent=2)
    print(f"wrote {a.out}")
    print(f"converged on: {out['converged_on']}")
    for c in cands[:6]:
        print(f"  {c['component']:22s} in={c['max_incoming_x']:7.1f}x "
              f"({c['n_slow_incoming']} slow) out={c['max_outgoing_x']:6.1f}x "
              f"terminal={c['is_terminal']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
