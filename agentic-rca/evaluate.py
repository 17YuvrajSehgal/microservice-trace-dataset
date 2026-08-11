#!/usr/bin/env python3
"""Evaluation runner — (run × condition × method) → prediction → score vs ground truth.

Two modes, same scoring/aggregation:
  * grid=full  → the P2 sanity gate (100% telemetry) — is the method solid before degrading?
  * grid=…     → RQ1 degradation sweep: apply each DegradeSpec to the run (offline, seeded) and
                 re-diagnose. The run is loaded ONCE and every condition wraps the cached frames
                 (loading dominates), so a whole grid costs ~one load per incident.

The agent is HELD FIXED across conditions (Mahsa's guardrail): only the data the tools see changes.

    python evaluate.py --app both --per-family 1 --method stat                 # sanity gate
    python evaluate.py --app trainticket --per-family 1 --method stat --grid trace --out results/rq1_trace.json
"""
from __future__ import annotations
import argparse, json, os, sys, time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stratatrace import load_run
import runs as R
from degrade import DegradeSpec, FULL, degrade

# named degradation grids (research-agentic-rca.md §5). Condition labels carry an axis prefix so
# analyze.py can group them; "full" is the shared reference point for every axis.
GRIDS = {
    "full":   [("full", FULL)],
    "trace":  [(f"trace{int(k*100):03d}", DegradeSpec(trace_keep=k)) for k in (1.0, 0.5, 0.25, 0.1, 0.05)],
    "metric": [(f"metric{s or 5}s", DegradeSpec(metric_step_s=s)) for s in (0, 10, 30, 60)],
    "log":    [("logALL", FULL), ("logWARN", DegradeSpec(log_level="WARN")), ("logERROR", DegradeSpec(log_level="ERROR"))],
    "kernel": [("kAll", FULL), ("kL1", DegradeSpec(kernel_tier="L1")), ("kL3", DegradeSpec(kernel_tier="L3")), ("kNone", DegradeSpec(kernel_tier="none"))],
    "compensate": [("MLTK_full", FULL), ("MLT_noK", DegradeSpec(drop_modalities=("kernel",)))],
    # one-pass union of every axis — load each run ONCE, evaluate all conditions
    "all": [
        ("full", FULL),
        ("trace050", DegradeSpec(trace_keep=0.5)), ("trace025", DegradeSpec(trace_keep=0.25)),
        ("trace010", DegradeSpec(trace_keep=0.1)), ("trace005", DegradeSpec(trace_keep=0.05)),
        ("metric10s", DegradeSpec(metric_step_s=10)), ("metric30s", DegradeSpec(metric_step_s=30)),
        ("metric60s", DegradeSpec(metric_step_s=60)),
        ("logWARN", DegradeSpec(log_level="WARN")), ("logERROR", DegradeSpec(log_level="ERROR")),
        ("kL1", DegradeSpec(kernel_tier="L1")), ("kL3", DegradeSpec(kernel_tier="L3")),
        ("kNone", DegradeSpec(kernel_tier="none")),
        ("MLT_noK", DegradeSpec(drop_modalities=("kernel",))),
        ("MLK_noT", DegradeSpec(drop_modalities=("traces",))),
    ],
}


class _MemoRun:
    """Cache a base Run's modality reads so a whole degradation grid costs ONE parse per modality
    (loader.spans/logs/metrics re-read from disk every call; SS spans are 2.4M rows = ~65s each)."""
    def __init__(self, run):
        self._run = run
        self.run_dir = run.run_dir
        self.ground_truth = run.ground_truth
        self.verification = getattr(run, "verification", {})
        self.clock_anchors = getattr(run, "clock_anchors", {})
        self._c = {}

    def _get(self, name):
        if name not in self._c:
            self._c[name] = getattr(self._run, name)()
        return self._c[name]

    def spans(self):       return self._get("spans")
    def logs(self):        return self._get("logs")
    def metrics(self):     return self._get("metrics")
    def kernel_l1(self):   return self._get("kernel_l1")
    def kernel_l2(self):   return self._get("kernel_l2")
    def kernel_l3(self):   return self._get("kernel_l3")
    def load(self):        return self._get("load")
    def has_kernel_l0(self): return self._run.has_kernel_l0()


def _sample(app, per_family, n, families):
    recs = list(R.iter_runs(app))
    if families:
        recs = [r for r in recs if r.fault_family in families]
    if per_family:
        seen, out = defaultdict(int), []
        for r in sorted(recs, key=lambda x: x.run_id):
            if seen[r.fault_family] < per_family:
                out.append(r); seen[r.fault_family] += 1
        recs = out
    if n:
        recs = recs[:n]
    return recs


def run(app, per_family, n, families, out_path, method, grid):
    RCAEVAL = {"mmbaro", "microrank", "tracerca", "baro"}
    if method == "agent":
        import agent as _m; label = __import__("config").model_id()
    elif method == "stat":
        import baseline_stat as _m; label = "statistical-baseline"
    elif method in RCAEVAL:
        import rcaeval_adapter as _m; label = f"rcaeval:{method}"   # run in .venv-rca (py3.12)
    else:
        raise SystemExit(f"unknown method {method!r}")
    conditions = GRIDS[grid]
    recs = _sample(app, per_family, n, families)
    print(f"== {method} ({label}) × grid '{grid}' ({len(conditions)} conds) over {len(recs)} incidents ({app}) ==")
    results, t0 = [], time.time()
    for i, rec in enumerate(recs, 1):
        base = _MemoRun(load_run(rec.dir))             # load ONCE; conditions wrap the cached frames
        for cname, spec in conditions:
            try:
                kw = {"method": method} if method in RCAEVAL else {}
                out = _m.diagnose(degrade(base, spec), app=rec.app, **kw)
            except Exception as e:
                out = {"diagnosis": None, "error": str(e), "n_tool_calls": 0,
                       "bytes_touched": 0, "tokens": {"in": 0, "out": 0}}
            sc = R.score(out.get("diagnosis"), rec.ground_truth, rec.fault_family, out.get("ranked_services"))
            results.append({"app": rec.app, "run_id": rec.run_id, "family": rec.fault_family,
                            "condition": cname, "target": rec.target_service,
                            "expected_modality": rec.expected_winning_modality,
                            "diagnosis": out.get("diagnosis"), "ranked_services": out.get("ranked_services"),
                            "score": sc, "n_tool_calls": out.get("n_tool_calls"), "tokens": out.get("tokens"),
                            "bytes_touched": out.get("bytes_touched"), "trajectory": out.get("trajectory"),  # RQ2
                            "error": out.get("error")})
        d0 = results[-len(conditions)]
        print(f"  [{i}/{len(recs)}] {rec.run_id:44s} ({rec.fault_family})")
    _summarize(results, conditions)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        json.dump({"meta": {"app": app, "method": method, "grid": grid, "model": label,
                            "n_incidents": len(recs), "wall_s": round(time.time() - t0, 1)},
                   "results": results}, open(out_path, "w"), indent=2, default=str)
        print(f"\nwrote {out_path}")
    return results


def _summarize(results, conditions):
    order = [c[0] for c in conditions]
    by = defaultdict(list)
    for r in results:
        by[r["condition"]].append(r)
    print(f"\n{'condition':16s} {'svc':>7} {'fault':>7} {'both':>7}   (Top-1, n per condition)")
    for c in order:
        rs = by.get(c, [])
        n = len(rs) or 1
        svc = sum(x["score"]["service_hit"] for x in rs)
        flt = sum(x["score"]["fault_hit"] for x in rs)
        both = sum(x["score"]["both"] for x in rs)
        print(f"{c:16s} {svc/n:6.0%} {flt/n:6.0%} {both/n:6.0%}   (n={len(rs)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="trainticket", choices=["trainticket", "sockshop", "both"])
    ap.add_argument("--per-family", type=int, default=0)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--families", default="")
    ap.add_argument("--method", default="agent", choices=["agent", "stat", "mmbaro", "microrank", "tracerca", "baro"])
    ap.add_argument("--grid", default="full", choices=list(GRIDS))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    fams = [x for x in a.families.split(",") if x]
    apps = ["trainticket", "sockshop"] if a.app == "both" else [a.app]
    allres = []
    for app in apps:
        allres += run(app, a.per_family, a.n, fams, a.out or "", a.method, a.grid)
    if a.app == "both":
        print("\n==== COMBINED ===="); _summarize(allres, GRIDS[a.grid])
