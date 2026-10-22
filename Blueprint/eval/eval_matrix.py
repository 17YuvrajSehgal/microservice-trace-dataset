#!/usr/bin/env python3
"""Matched-blueprint evaluation: run one blueprint on all its matching runs, score, scoreboard.

Answers the question "how often does the agent detect the fault when handed the correct
blueprint." One cell = one run; parallel, resumable (a run whose result.json exists is skipped),
budget-capped. Everything runs from the Blueprint tree.

    python eval_matrix.py --problem svc_mem_cap \
        --runs-root /path/to/runs --index-root /path/to/indexes \
        --out results/svc_mem_cap --jobs 4

    python eval_matrix.py --problem svc_mem_cap --runs-root ... --index-root ... --dry-run
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import datasets as D          # noqa: E402
import eval_one as E          # noqa: E402

# GPT-6 Luna standard pricing, for a running cost estimate (confirm against your account).
PRICE_IN = float(os.environ.get("PRICE_IN_PER_M", "0.10")) / 1e6
PRICE_OUT = float(os.environ.get("PRICE_OUT_PER_M", "0.50")) / 1e6


def _cell_done(out_dir, rid):
    return os.path.exists(os.path.join(out_dir, rid, "result.json"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", required=True)
    ap.add_argument("--runs-root", required=True, help="dir to search for matching run dirs")
    ap.add_argument("--index-root", required=True, help="where <run_id>.tsv.gz live")
    ap.add_argument("--out", required=True)
    ap.add_argument("--blueprint", default=None, help="override; default is the problem's own")
    ap.add_argument("--arm", default="given", choices=["given", "none"],
                    help="given = hand over the correct blueprint; none = control")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="cap the number of runs (0 = all)")
    ap.add_argument("--no-controls", action="store_true", help="skip uncapped baseline runs")
    ap.add_argument("--budget-usd", type=float, default=0.0, help="stop before exceeding (0=off)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    bp = a.blueprint or (D.blueprint_path(a.problem) if a.arm == "given" else None)
    if a.arm == "given" and not bp:
        print("no blueprint for problem %r (Blueprint/latency). arms=given needs one." % a.problem)
        return 2

    runs = D.discover(a.problem, a.runs_root, a.index_root,
                      include_controls=not a.no_controls)
    if a.limit:
        runs = runs[:a.limit]
    os.makedirs(a.out, exist_ok=True)

    todo = [r for r in runs if not _cell_done(a.out, os.path.basename(r.rstrip("/\\")))]
    print("problem %s | blueprint %s | arm %s" % (a.problem, os.path.basename(
        os.path.dirname(bp)) if bp else "(none)", a.arm))
    print("%d matching runs, %d already scored, %d to run (jobs=%d)"
          % (len(runs), len(runs) - len(todo), len(todo), a.jobs))
    if a.dry_run:
        for r in runs:
            print("   %s%s" % (os.path.basename(r.rstrip("/\\")),
                               "" if r in todo else "  [done]"))
        return 0
    if not todo:
        print("nothing to run.")
        return _report(a.out, a.problem)

    t0 = time.time()

    def one(rd):
        rid = os.path.basename(rd.rstrip("/\\"))
        try:
            return E.run(rd, bp, a.problem, a.index_root, os.path.join(a.out, rid),
                         transcript=os.path.join(a.out, rid, "transcript.json"))
        except Exception as e:                                          # noqa: BLE001
            return {"run_id": rid, "error": "%s: %s" % (type(e).__name__, e)}

    spent = 0.0
    done = 0
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(one, r): r for r in todo}
        for f in as_completed(futs):
            row = f.result()
            done += 1
            if row.get("error"):
                print("  [%d/%d] %-34s ERROR %s" % (done, len(todo), row["run_id"], row["error"]))
                continue
            sc = row.get("score") or {}
            cost = row.get("tokens_in", 0) * PRICE_IN + row.get("tokens_out", 0) * PRICE_OUT
            spent += cost
            print("  [%d/%d] %-34s detected=%s where=%s %4.0fs $%.3f"
                  % (done, len(todo), row["run_id"], sc.get("detected"),
                     sc.get("where", "-"), row.get("seconds", 0), cost))
            if a.budget_usd and spent >= a.budget_usd:
                print("  budget $%.2f reached; stopping (resumable)." % a.budget_usd)
                break
    print("ran %d in %.0fs, ~$%.2f" % (done, time.time() - t0, spent))
    return _report(a.out, a.problem)


def _report(out_dir, problem) -> int:
    rows = []
    for d in sorted(os.listdir(out_dir)):
        p = os.path.join(out_dir, d, "result.json")
        if os.path.exists(p):
            try:
                rows.append(json.load(open(p, encoding="utf-8")))
            except (OSError, ValueError):
                pass
    if not rows:
        return 0
    faults = [r for r in rows if not (r.get("score") or {}).get("control")]
    ctrls = [r for r in rows if (r.get("score") or {}).get("control")]
    det_f = sum(1 for r in faults if (r.get("score") or {}).get("detected"))
    det_c = sum(1 for r in ctrls if (r.get("score") or {}).get("detected"))
    tin = sum(r.get("tokens_in", 0) for r in rows)
    tout = sum(r.get("tokens_out", 0) for r in rows)
    print("\n==== %s ====" % problem)
    print("fault runs   : detected %d / %d" % (det_f, len(faults)))
    if ctrls:
        print("control runs : correct  %d / %d (did not cry wolf)" % (det_c, len(ctrls)))
    print("cost         : %s in + %s out tokens = $%.2f"
          % (f"{tin:,}", f"{tout:,}", tin * PRICE_IN + tout * PRICE_OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
