#!/usr/bin/env python3
"""Evaluation runner — (run × [condition] × method) → prediction → score vs ground truth.

For now: the **P2 sanity gate** — run the LLM agent at 100% telemetry over a sample of incidents,
score Top-1 (root-cause service, fault type, both), and report per-family. This is the go/no-go
before any degradation: if the agent can't diagnose full telemetry, degradation results are moot.

Later this same runner gains the degradation axis (a `condition` from degrade.py applied to the Run
before diagnose) and the statistical / CARE methods — the scoring + aggregation stay identical.

    RCA_PROVIDER=claude ANTHROPIC_API_KEY=…  python evaluate.py --app trainticket --n 10
    python evaluate.py --app both --per-family 1 --out results/sanity.json
"""
from __future__ import annotations
import argparse, json, os, sys, time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stratatrace import load_run
import runs as R


def _sample(app, per_family, n, families):
    recs = list(R.iter_runs(app))
    if families:
        recs = [r for r in recs if r.fault_family in families]
    if per_family:  # first `per_family` of each family — a broad, deterministic spread
        seen, out = defaultdict(int), []
        for r in sorted(recs, key=lambda x: x.run_id):
            if seen[r.fault_family] < per_family:
                out.append(r); seen[r.fault_family] += 1
        recs = out
    if n:
        recs = recs[:n]
    return recs


def run(app, per_family, n, families, out_path, method="agent"):
    if method == "agent":
        import agent as _m
        label = __import__("config").model_id()
    elif method == "stat":
        import baseline_stat as _m
        label = "statistical-baseline"
    else:
        raise SystemExit(f"unknown method {method!r} (agent|stat)")
    recs = _sample(app, per_family, n, families)
    print(f"== {method} over {len(recs)} incidents ({app}), model={label} ==")
    results, t0 = [], time.time()
    for i, rec in enumerate(recs, 1):
        try:
            out = _m.diagnose(load_run(rec.dir), app=rec.app)
        except Exception as e:
            out = {"diagnosis": None, "error": str(e), "trajectory": [], "n_tool_calls": 0,
                   "bytes_touched": 0, "tokens": {"in": 0, "out": 0}}
        sc = R.score(out.get("diagnosis"), rec.ground_truth, rec.fault_family)
        row = {"app": rec.app, "run_id": rec.run_id, "family": rec.fault_family,
               "target": rec.target_service, "expected_modality": rec.expected_winning_modality,
               "diagnosis": out.get("diagnosis"), "score": sc,
               "n_tool_calls": out.get("n_tool_calls"), "tokens": out.get("tokens"),
               "bytes_touched": out.get("bytes_touched"), "trajectory": out.get("trajectory"),
               "error": out.get("error")}
        results.append(row)
        d = out.get("diagnosis") or {}
        mark = "OK " if sc["both"] else ("svc" if sc["service_hit"] else ("flt" if sc["fault_hit"] else "MISS"))
        print(f"  [{i}/{len(recs)}] {mark:4s} {rec.run_id:46s} pred={d.get('root_cause_service','-')}/"
              f"{d.get('fault_type','-')} tgt={rec.target_service}/{rec.fault_family} "
              f"calls={out.get('n_tool_calls')} tok={out.get('tokens',{}).get('out')}")
    _summarize(results)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        json.dump({"meta": {"app": app, "n": len(results), "wall_s": round(time.time() - t0, 1)},
                   "results": results}, open(out_path, "w"), indent=2, default=str)
        print(f"\nwrote {out_path}")
    return results


def _summarize(results):
    n = len(results) or 1
    svc = sum(r["score"]["service_hit"] for r in results)
    flt = sum(r["score"]["fault_hit"] for r in results)
    both = sum(r["score"]["both"] for r in results)
    noans = sum(r["score"].get("no_answer") for r in results)
    print(f"\n== Top-1: service {svc}/{n} ({svc/n:.0%}) | fault {flt}/{n} ({flt/n:.0%}) | "
          f"both {both}/{n} ({both/n:.0%}) | no-answer {noans} ==")
    byfam = defaultdict(lambda: [0, 0])
    for r in results:
        byfam[r["family"]][0] += r["score"]["both"]; byfam[r["family"]][1] += 1
    print("by family (both-hit / n):")
    for fam in sorted(byfam):
        h, t = byfam[fam]
        print(f"    {fam:18s} {h}/{t}")
    avg = lambda k: sum((r.get(k) or 0) for r in results) / n
    print(f"avg tool-calls {avg('n_tool_calls'):.1f} | avg out-tokens "
          f"{sum((r['tokens'] or {}).get('out', 0) for r in results)/n:.0f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="trainticket", choices=["trainticket", "sockshop", "both"])
    ap.add_argument("--per-family", type=int, default=0, help="take the first K runs of each family")
    ap.add_argument("--n", type=int, default=0, help="cap total incidents")
    ap.add_argument("--families", default="", help="comma list to restrict to")
    ap.add_argument("--method", default="agent", choices=["agent", "stat"])
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    fams = [x for x in a.families.split(",") if x]
    apps = ["trainticket", "sockshop"] if a.app == "both" else [a.app]
    allres = []
    for app in apps:
        allres += run(app, a.per_family, a.n, fams, a.out or "", method=a.method)
    if a.app == "both":
        print("\n==== COMBINED ===="); _summarize(allres)
