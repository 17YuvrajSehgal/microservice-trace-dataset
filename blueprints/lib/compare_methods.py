#!/usr/bin/env python3
"""Score every method on the same incidents, with one scorer, and report accuracy AND time.

Arms compared:
  blueprint      deterministic rules over the shared L0 evidence pack; no model
  agent+L0       tool-using LLM, given the same pack
  agent          tool-using LLM, pack withheld (isolates what the pack is worth)
  llmonly+L0     one model call, no tools, same pack
  stat / mmbaro  published non-LLM methods; they cannot consume kernel data at all

Scoring is deliberately the same function the main campaign uses, so these numbers sit
beside the existing results rather than being a private scale.

    python3 compare_methods.py --results-dir <dir> --packs <dir> --out comparison.json
"""
from __future__ import annotations
import argparse, glob, json, os, statistics, sys

REPO = "/scratch/yuvraj17/microservice-trace-dataset"
sys.path.insert(0, os.path.join(REPO, "agentic-rca"))
sys.path.insert(0, REPO)


def ground_truth(run_dir):
    p = os.path.join(run_dir, "ground_truth.json")
    return json.load(open(p))["fault"] if os.path.exists(p) else {}


def load_blueprint(d, runs_index):
    """blueprint_decide verdicts -> rows"""
    out = []
    for p in sorted(glob.glob(os.path.join(d, "*.json"))):
        v = json.load(open(p, encoding="utf-8"))
        rid = v.get("run_id")
        if rid not in runs_index:
            continue
        out.append({"run_id": rid, "method": "blueprint",
                    "pred_service": v.get("root_cause_service"),
                    "pred_fault": v.get("fault_type"),
                    "seconds": v.get("analysis_seconds"),
                    "tokens": 0, "usd": 0.0,
                    "note": v.get("selected") or "ambiguous"})
    return out


def _transcript_seconds(doc, row):
    """Older result files did not persist per-incident wall time; recover it from the
    transcript that was written alongside."""
    tdir = (doc.get("meta") or {}).get("transcripts_dir")
    rel = row.get("transcript")
    if not tdir or not rel:
        return None
    try:
        t = json.load(open(os.path.join(tdir, rel), encoding="utf-8"))
        return (t.get("meta") or {}).get("wall_s") or (t.get("summary") or {}).get("wall_s")
    except Exception:                                                  # noqa: BLE001
        return None


def load_eval(path, method_label):
    """evaluate.py result file -> rows"""
    if not os.path.exists(path):
        return []
    d = json.load(open(path, encoding="utf-8"))
    rows = []
    for r in d.get("results", []):
        dg = r.get("diagnosis") or {}
        tk = r.get("tokens") or {}
        tin, tout = tk.get("in", 0), tk.get("out", 0)
        rows.append({"run_id": r["run_id"], "method": method_label,
                     "pred_service": dg.get("root_cause_service"),
                     "pred_fault": dg.get("fault_type"),
                     "seconds": r.get("wall_s") or _transcript_seconds(d, r),
                     "tokens": tin + tout,
                     "usd": round(tin / 1e6 * 1.25 + tout / 1e6 * 10, 4),
                     "note": r.get("error") or ""})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blueprint-dir", default="/scratch/yuvraj17/comparison/blueprint")
    ap.add_argument("--results-dir", default="/scratch/yuvraj17/comparison")
    ap.add_argument("--runs-root", default="/scratch/yuvraj17/agentic-runs/sockshop")
    ap.add_argument("--families", default="noisy_neighbor,slow_db")
    ap.add_argument("--out", default="/scratch/yuvraj17/comparison/comparison.json")
    a = ap.parse_args()

    import runs as R

    fams = a.families.split(",")
    index = {}
    for fam in fams:
        for d in sorted(glob.glob(os.path.join(a.runs_root, fam, "*/"))):
            rid = os.path.basename(d.rstrip("/"))
            index[rid] = {"dir": d.rstrip("/"), "family": fam, "gt": ground_truth(d)}
    print(f"incidents under test: {len(index)}")

    rows = load_blueprint(a.blueprint_dir, index)
    for label, fname in (("agent+L0", "agent_l0.json"), ("agent", "agent_nol0.json"),
                         ("llmonly+L0", "llmonly_l0.json"), ("stat", "stat.json"),
                         ("mmbaro", "mmbaro.json")):
        rows += load_eval(os.path.join(a.results_dir, fname), label)

    if not rows:
        sys.exit("no results found yet")

    # one scorer for everyone
    for r in rows:
        meta = index.get(r["run_id"])
        if not meta:
            r["score"] = None
            continue
        sc = R.score({"root_cause_service": r["pred_service"] or "",
                      "fault_type": r["pred_fault"] or ""},
                     meta["gt"], meta["family"])
        r["score"] = sc
        r["family"] = meta["family"]

    methods, summary = {}, []
    for r in rows:
        methods.setdefault(r["method"], []).append(r)
    for m, rs in methods.items():
        graded = [r for r in rs if r.get("score")]
        n = len(graded)
        if not n:
            continue
        svc = sum(r["score"]["service_hit"] for r in graded)
        # RCAEval-family methods localize only - they emit a ranked service list and no fault
        # type. Scoring them 0% on fault typing would misreport them, so it is marked n/a.
        types_faults = any(r.get("pred_fault") for r in graded)
        both = sum(r["score"]["both"] for r in graded) if types_faults else None
        answered = sum(1 for r in graded if r["pred_service"])
        # A method that abstains is not the same as one that answers wrongly. Precision is
        # scored over the answers actually given; recall over every incident.
        precision = (round(100 * svc / answered) if answered else None)
        secs = [r["seconds"] for r in graded if r.get("seconds")]
        summary.append({
            "method": m, "n": n,
            "component_pct": round(svc / n * 100),
            "fully_correct_pct": (round(both / n * 100) if both is not None else None),
            "does_fault_typing": types_faults,
            "answered_pct": round(answered / n * 100),
            "precision_when_answered_pct": precision,
            "median_seconds": round(statistics.median(secs), 1) if secs else None,
            "usd_per_incident": round(sum(r["usd"] for r in graded) / n, 4),
            "per_family": {f: {
                "n": len([r for r in graded if r.get("family") == f]),
                "component_pct": round(100 * sum(r["score"]["service_hit"] for r in graded
                                                 if r.get("family") == f)
                                       / max(1, len([r for r in graded if r.get("family") == f]))),
            } for f in fams},
        })
    order = {"blueprint": 0, "agent+L0": 1, "agent": 2, "llmonly+L0": 3, "stat": 4, "mmbaro": 5}
    summary.sort(key=lambda s: order.get(s["method"], 9))

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"summary": summary, "rows": rows}, open(a.out, "w"), indent=2, default=str)

    print(f"\n{'method':13s} {'n':>3s} {'component':>10s} {'fully':>7s} {'answered':>9s} "
          f"{'median s':>9s} {'$/incident':>11s}")
    for s in summary:
        fc = f"{s['fully_correct_pct']:6d}%" if s["fully_correct_pct"] is not None else "   n/a"
        pr = (f"{s['precision_when_answered_pct']:9d}%"
              if s.get("precision_when_answered_pct") is not None else "      n/a")
        print(f"{s['method']:13s} {s['n']:3d} {s['component_pct']:9d}% {fc} "
              f"{s['answered_pct']:8d}% {pr} {str(s['median_seconds']):>9s} "
              f"{s['usd_per_incident']:11.4f}")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
