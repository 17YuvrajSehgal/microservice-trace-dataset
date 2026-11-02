#!/usr/bin/env python3
"""Per-arm usage/cost report from eval transcripts.

Answers "what did this experiment cost" in tokens, cache hits, wall time and dollars.
Cost is read from the provider when it reports one (OpenRouter puts `cost` in usage);
otherwise pass --price to apply a rate yourself. Never invents a price.

    python usage_report.py <arm_dir> [<arm_dir> ...] [--price IN_PER_M,OUT_PER_M] [--cached-discount 0.1]

Doubles as the "cost + latency per diagnosis" number the ICSE plan asks for (§5 Metrics).
"""
import argparse
import glob
import json
import os


def walk(arm):
    """Yield (usage_dict, seconds, model, provider) per cell in one arm directory."""
    for res in sorted(glob.glob(os.path.join(arm, "*", "*", "result.json"))):
        try:
            r = json.load(open(res))
        except Exception:
            continue
        usages = []
        tj = os.path.join(os.path.dirname(res), "t.json")
        if os.path.exists(tj):
            try:
                d = json.load(open(tj))
                ev = d.get("events", d if isinstance(d, list) else [])
                for e in ev:
                    if e.get("type") != "api_response":
                        continue
                    resp = e.get("response") or {}
                    u = resp.get("usage") if isinstance(resp, dict) else None
                    if isinstance(u, dict):
                        usages.append(u)
            except Exception:
                pass
        yield usages, r.get("seconds", 0), r.get("model", "?"), r.get("provider", "?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arms", nargs="+")
    ap.add_argument("--price", help="IN_PER_M,OUT_PER_M in dollars per million tokens")
    ap.add_argument("--cached-discount", type=float, default=0.1,
                    help="fraction of input price charged for cached tokens (default 0.1)")
    a = ap.parse_args()
    rate = None
    if a.price:
        pin, pout = (float(x) for x in a.price.split(","))
        rate = (pin, pout)

    for arm in a.arms:
        cells = calls = pt = ct = cached = 0
        cost = 0.0
        secs = 0.0
        models, provs = set(), set()
        for usages, s, model, prov in walk(arm):
            cells += 1
            secs += s or 0
            models.add(model)
            provs.add(prov)
            for u in usages:
                calls += 1
                pt += u.get("prompt_tokens") or 0
                ct += u.get("completion_tokens") or 0
                cost += float(u.get("cost") or 0)
                cached += (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0

        print(f"\n=== {os.path.basename(arm.rstrip('/'))} ===")
        print(f"  model/provider : {','.join(sorted(models))} / {','.join(sorted(provs))}")
        print(f"  cells          : {cells}")
        print(f"  api calls      : {calls:,}" + (f"  ({calls/cells:.0f} per cell)" if cells else ""))
        print(f"  prompt tokens  : {pt:,}  (cached {cached:,} = {100*cached/max(pt,1):.0f}%)")
        print(f"  output tokens  : {ct:,}")
        print(f"  wall time      : {secs/60:.0f} min total"
              + (f", {secs/cells/60:.1f} min per diagnosis" if cells else ""))
        if cost > 0:
            print(f"  provider cost  : ${cost:.4f}"
                  + (f"  (${cost/cells:.4f} per diagnosis)" if cells else ""))
        else:
            print("  provider cost  : $0.00 reported "
                  "(BYOK or free endpoint — real spend sits on the upstream account)")
        if rate:
            billable_in = (pt - cached) + cached * a.cached_discount
            est = billable_in / 1e6 * rate[0] + ct / 1e6 * rate[1]
            print(f"  est. at {rate[0]}/{rate[1]} per M: ${est:.2f}"
                  + (f"  (${est/cells:.3f} per diagnosis)" if cells else "")
                  + f"   [cached charged at {a.cached_discount:.0%}]")


if __name__ == "__main__":
    main()
