#!/usr/bin/env python3
"""Aggregate sweep result JSONs into RQ1 degradation curves + the RQ3 kernel-dependence table.

    python analyze.py agentic-rca/results/sweep/*.json
Reads the {meta, results:[...]} files evaluate.py writes and prints, per condition:
  Top-1 service / fault / both, split overall · by app · by expected_winning_modality (kernel vs
  other) · by family. The trace/metric/log axes vs 'full' are the RQ1 curves; 'full' vs 'kNone' /
  'MLT_noK' on the kernel-decisive faults is the RQ3 "kernel as safety net" signal.
"""
from __future__ import annotations
import glob, json, os, sys
from collections import defaultdict

AXES = {
    "trace":  ["full", "trace050", "trace025", "trace010", "trace005"],
    "metric": ["full", "metric10s", "metric30s", "metric60s"],
    "log":    ["full", "logWARN", "logERROR"],
    "kernel": ["full", "kL1", "kL3", "kNone"],
    "compensate(RQ3)": ["full", "MLT_noK", "MLK_noT"],
}


def load(paths):
    rows = []
    for p in paths:
        for pp in glob.glob(p):
            rows += json.load(open(pp)).get("results", [])
    return rows


def _rate(rows, key):
    n = len(rows) or 1
    return sum(r["score"].get(key) for r in rows) / n


METRIC = os.environ.get("ANALYZE_METRIC", "service_hit")  # Top-1 service localization (= AC@1),
#          the metric comparable across ALL methods (RCAEval localizes only). Set 'both' for
#          statistical/agent service+fault. 'fault_hit' for fault-only.


def _cell(rows, cond):
    rs = [r for r in rows if r["condition"] == cond]
    if not rs:
        return "  -  "
    return f"{_rate(rs, METRIC):4.0%}"


def table(rows, title, subsets):
    print(f"\n{'='*70}\n{title}   (cell = {METRIC} rate; service_hit = Top-1 localization = AC@1)\n{'='*70}")
    for axis, conds in AXES.items():
        print(f"\n  [{axis}]")
        header = "    " + f"{'subset':22s}" + "".join(f"{c:>10}" for c in conds)
        print(header)
        for label, sub in subsets:
            line = "    " + f"{label:22s}" + "".join(f"{_cell(sub, c):>10}" for c in conds)
            print(line)


def main(paths):
    rows = load(paths)
    if not rows:
        print("no results found:", paths); return
    apps = sorted(set(r["app"] for r in rows))
    kern = [r for r in rows if (r.get("expected_modality") or "").lower() == "kernel"]
    other = [r for r in rows if (r.get("expected_modality") or "").lower() != "kernel"]
    subsets = [("ALL", rows)] + [(a, [r for r in rows if r["app"] == a]) for a in apps] + \
              [("kernel-decisive", kern), ("other-modality", other)]
    n_inc = len(set((r["app"], r["run_id"]) for r in rows))
    print(f"loaded {len(rows)} rows over {n_inc} incidents, {len(set(r['condition'] for r in rows))} conditions")
    table(rows, f"Degradation sweep — {n_inc} incidents [metric={METRIC}]", subsets)

    # per-family at 'full' vs kernel-removed (the RQ3 headline)
    print(f"\n{'='*70}\nRQ3 per-family: full vs kernel-removed [{METRIC}]\n{'='*70}")
    fams = sorted(set(r["family"] for r in rows))
    print(f"    {'family':20s}{'full':>8}{'kNone':>8}{'MLT_noK':>10}{'expect':>9}")
    for fam in fams:
        fr = [r for r in rows if r["family"] == fam]
        em = (fr[0].get("expected_modality") or "?") if fr else "?"
        g = lambda c: _cell(fr, c)
        print(f"    {fam:20s}{g('full'):>8}{g('kNone'):>8}{g('MLT_noK'):>10}{em:>9}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["agentic-rca/results/sweep/*.json"])
