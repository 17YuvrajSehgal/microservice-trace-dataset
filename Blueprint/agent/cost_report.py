#!/usr/bin/env python3
"""Per-incident dollar cost from transcripts (post-hoc — no agent changes).

    python cost_report.py results/campaign/s1 [more dirs...] [--rate-in 1.25 --rate-cached 0.125 --rate-out 10]

Reads every transcript's api_response usage (prompt / cached / completion tokens) plus the
skill-selector call (skill_selection event; its input counted as uncached — conservative).
Rates are $ per 1M tokens; defaults are the GPT-5-family price structure as a PROXY — set
the real Azure gpt-5.4 rates via flags or env (RCA_PRICE_IN / RCA_PRICE_CACHED / RCA_PRICE_OUT).
"""
from __future__ import annotations
import argparse
import glob
import json
import os


def incident_tokens(path):
    d = json.load(open(path, encoding="utf-8"))
    pin = cached = pout = 0
    for e in d.get("events", []):
        if e["type"] == "api_response":
            u = (e.get("response") or {}).get("usage") or {}
            pin += u.get("prompt_tokens", 0) or u.get("input_tokens", 0) or 0
            pout += u.get("completion_tokens", 0) or u.get("output_tokens", 0) or 0
            det = u.get("prompt_tokens_details") or {}
            cached += det.get("cached_tokens", 0) or 0
        elif e["type"] == "skill_selection":
            t = e.get("tokens") or {}
            pin += t.get("in", 0) or 0
            pout += t.get("out", 0) or 0
    meta = d.get("meta") or {}
    return {"run_id": meta.get("run_id"), "condition": meta.get("condition"),
            "in": pin, "cached": cached, "out": pout}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", help="results dirs (transcripts found recursively)")
    ap.add_argument("--rate-in", type=float,
                    default=float(os.environ.get("RCA_PRICE_IN", "1.25")))
    ap.add_argument("--rate-cached", type=float,
                    default=float(os.environ.get("RCA_PRICE_CACHED", "0.125")))
    ap.add_argument("--rate-out", type=float,
                    default=float(os.environ.get("RCA_PRICE_OUT", "10")))
    ap.add_argument("--per-incident", action="store_true", help="print every incident line")
    a = ap.parse_args()
    print(f"rates $/1M: in={a.rate_in} cached={a.rate_cached} out={a.rate_out} "
          f"(PROXY unless overridden — set real gpt-5.4 rates)")
    grand = {"in": 0, "cached": 0, "out": 0, "n": 0, "cost": 0.0}
    for d in a.dirs:
        files = sorted(glob.glob(os.path.join(d, "**", "*.json"), recursive=True))
        files = [f for f in files if os.sep + "transcripts" in f or "/transcripts" in f]
        rows = []
        for f in files:
            try:
                t = incident_tokens(f)
            except Exception:
                continue
            fresh = t["in"] - t["cached"]
            t["cost"] = (fresh * a.rate_in + t["cached"] * a.rate_cached
                         + t["out"] * a.rate_out) / 1e6
            rows.append(t)
        if not rows:
            continue
        tot_in = sum(r["in"] for r in rows)
        tot_c = sum(r["cached"] for r in rows)
        tot_o = sum(r["out"] for r in rows)
        cost = sum(r["cost"] for r in rows)
        print(f"\n== {d}: {len(rows)} incidents ==")
        if a.per_incident:
            for r in sorted(rows, key=lambda x: -x["cost"]):
                print(f"  {str(r['run_id'])[:44]:46s} {r['condition'] or '':8s} "
                      f"in={r['in']:>7,} (cached {100 * r['cached'] // max(r['in'], 1):>2}%) "
                      f"out={r['out']:>6,}  ${r['cost']:.4f}")
        print(f"  tokens: in={tot_in:,} cached={tot_c:,} ({100 * tot_c // max(tot_in, 1)}%) "
              f"out={tot_o:,}")
        print(f"  cost: ${cost:.2f} total, ${cost / len(rows):.4f}/incident avg")
        grand["in"] += tot_in; grand["cached"] += tot_c; grand["out"] += tot_o
        grand["n"] += len(rows); grand["cost"] += cost
    if grand["n"]:
        print(f"\n==== GRAND TOTAL: {grand['n']} incidents | in={grand['in']:,} "
              f"(cached {100 * grand['cached'] // max(grand['in'], 1)}%) out={grand['out']:,} "
              f"| ${grand['cost']:.2f} (${grand['cost'] / grand['n']:.4f}/incident) ====")


if __name__ == "__main__":
    main()
