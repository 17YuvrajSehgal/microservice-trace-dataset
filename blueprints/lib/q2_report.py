#!/usr/bin/env python3
"""Collect every score.json the matrix wrote and print the with/without table.

Reads results only. Ground truth was already applied per cell by q2_run_one; nothing here
re-scores, so the table cannot disagree with the individual cells it came from.

    python q2_report.py --out-dir /scratch/yuvraj17/stratatrace/results/q2
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import q2_harness as Q  # noqa: E402


def load_rows(out_dir: str) -> list:
    rows = []
    for p in sorted(glob.glob(os.path.join(out_dir, "*", "*", "*", "*", "*", "score.json"))):
        try:
            r = json.load(open(p, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # summarise() groups on "family"; the cells write "problem". Same thing, one name.
        r.setdefault("family", r.get("problem"))
        r["_path"] = p
        rows.append(r)
    return rows


def window_stats(rows) -> dict:
    """How well the agent found WHEN, which the ranked metrics do not cover at all.

    Abstentions are counted, not scored. The submit_diagnosis schema tells the agent an
    invented window is worse than an admitted gap, so folding "unknown" in as a zero would
    contradict the instruction it was given.
    """
    ious = [r["window_iou"] for r in rows if isinstance(r.get("window_iou"), (int, float))]
    n = len(rows)
    v = [r.get("window_verdict") for r in rows]
    return {
        "n": n,
        "abstained": v.count("abstained"),
        "miss": v.count("miss"),
        "partial": v.count("partial"),
        "hit": v.count("hit"),
        "median_iou": Q._median(ious),
        "mean_iou": round(sum(ious) / len(ious), 3) if ious else None,
    }


def fmt_pct(x):
    return "  -  " if x is None else "%4d%%" % x


def fmt_num(x, w=6, dp=2):
    return " " * w if x is None else ("%*.*f" % (w, dp, x))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="/scratch/yuvraj17/stratatrace/results/q2")
    ap.add_argument("--json", default="", help="also write the summary here")
    a = ap.parse_args()

    rows = load_rows(a.out_dir)
    if not rows:
        print("no score.json under %s" % a.out_dir)
        return 1
    print("%d scored cells under %s\n" % (len(rows), a.out_dir))

    summ = Q.summarise(rows)
    for fam, entry in summ.items():
        print("=" * 78)
        print("PROBLEM: %s" % fam)
        print("=" * 78)
        hdr = ("  %-14s %3s  %6s %6s %6s  %6s %6s  %6s %6s  %6s %5s %7s"
               % ("ask | arm", "n", "both", "svc", "fault", "narr@2", "hit@5",
                  "setF1", "macF1", "sec", "calls", "tokens"))
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for ask in Q.ASKS:
            for arm in ("none", "given"):
                k = "%s|%s" % (ask, arm)
                e = entry.get(k)
                if not e:
                    continue
                print("  %-14s %3d  %6s %6s %6s  %6s %6s  %6s %6s  %6s %5s %7s"
                      % (k, e["n"], fmt_pct(e["both_pct"]), fmt_pct(e["service_pct"]),
                         fmt_pct(e["fault_pct"]), fmt_pct(e["narrowed_pct"]),
                         fmt_pct(e["hit_at_k_pct"]),
                         fmt_num(e["set_f1"], 6, 3), fmt_num(e["macro_f1"], 6, 3),
                         e["median_seconds"], e["median_tool_calls"], e["median_tokens"]))
            d = entry.get("%s|delta_pts" % ask)
            nd = entry.get("%s|narrowed_delta_pts" % ask)
            fd = entry.get("%s|set_f1_delta" % ask)
            sr = entry.get("%s|seconds_ratio" % ask)
            if d is not None:
                print("  %-14s      %+5d pts both      %+5s pts narrowed   setF1 %+0.3f   "
                      "time x%s" % ("  -> blueprint", d,
                                    "%+d" % nd if nd is not None else " - ",
                                    fd if fd is not None else 0.0, sr))
            print()

    # The fairer marking. Kept separate from the table above because it answers different
    # questions: not "did it pick the right label" but "did it find the thing, describe the
    # mechanism, and how did it get there". See q2_judge.py.
    print("=" * 78)
    print("WHERE, WHAT, HOW - the fairer marking")
    print("=" * 78)
    print("  %-14s %3s  %6s %6s %6s %6s  %8s  %9s %6s"
          % ("ask | arm", "n", "named", "scope", "ambig", "wrong", "described",
             "who-tools", "calls"))
    print("  " + "-" * 80)
    for ask in Q.ASKS:
        for arm in ("none", "given"):
            rs = [r for r in rows if r.get("ask") == ask and r.get("arm") == arm]
            if not rs:
                continue
            n = len(rs)
            w = [r.get("where") for r in rs]
            ws = [r["what_score"] for r in rs
                  if isinstance(r.get("what_score"), (int, float))]
            who = sum(1 for r in rs if r.get("used_who_tools"))
            print("  %-14s %3d  %6d %6d %6d %6d  %8s  %9s %6s"
                  % ("%s|%s" % (ask, arm), n, w.count("named"), w.count("scope"),
                     w.count("ambiguous"), w.count("wrong") + w.count("none"),
                     ("%.0f%%" % (100 * sum(ws) / len(ws))) if ws else "  -  ",
                     "%d/%d" % (who, n),
                     Q._median([r.get("calls") for r in rs])))
    print()
    print("  named = identified the injected thing. scope = right level only (e.g. 'host').")
    print("  ambig = a shared runtime (java, node, dockerd) that maps to several services.")
    print("  described = average share of the mechanism the agent's own words covered.")
    print("  who-tools = runs that used ctf_procdiff or ctf_proclife at all.")
    print()

    # Does reaching for the WHO tools go with finding the right window? This is the question
    # the two new tools exist to answer, so it gets its own line rather than being inferred.
    with_who = [r for r in rows if r.get("used_who_tools")]
    without = [r for r in rows if not r.get("used_who_tools")]
    if with_who and without:
        def _iou(rs):
            v = [r["window_iou"] for r in rs if isinstance(r.get("window_iou"), (int, float))]
            return Q._median(v)

        def _named(rs):
            return "%d/%d" % (sum(1 for r in rs if r.get("named_culprit")), len(rs))
        print("  used who-tools:     %2d runs   median window IoU %-6s   named culprit %s"
              % (len(with_who), _iou(with_who), _named(with_who)))
        print("  did not use them:   %2d runs   median window IoU %-6s   named culprit %s"
              % (len(without), _iou(without), _named(without)))
        print()

    # WHEN. Not in summarise() because the ranked metrics say nothing about it, and finding
    # the window is half the task once the agent is no longer told where to look.
    print("=" * 78)
    print("WINDOW - did it find WHEN? (never told; abstain counted, not scored as wrong)")
    print("=" * 78)
    print("  %-14s %3s  %9s %5s %7s %4s  %8s %8s"
          % ("ask | arm", "n", "abstained", "miss", "partial", "hit", "med IoU", "mean IoU"))
    print("  " + "-" * 70)
    for ask in Q.ASKS:
        for arm in ("none", "given"):
            rs = [r for r in rows if r.get("ask") == ask and r.get("arm") == arm]
            if not rs:
                continue
            w = window_stats(rs)
            print("  %-14s %3d  %9d %5d %7d %4d  %8s %8s"
                  % ("%s|%s" % (ask, arm), w["n"], w["abstained"], w["miss"],
                     w["partial"], w["hit"],
                     fmt_num(w["median_iou"], 8, 3), fmt_num(w["mean_iou"], 8, 3)))
    print()

    if a.json:
        payload = {"n_cells": len(rows), "summary": summ,
                   "window": {"%s|%s" % (ask, arm): window_stats(
                       [r for r in rows if r.get("ask") == ask and r.get("arm") == arm])
                       for ask in Q.ASKS for arm in ("none", "given")}}
        json.dump(payload, open(a.json, "w"), indent=1)
        print("wrote %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
