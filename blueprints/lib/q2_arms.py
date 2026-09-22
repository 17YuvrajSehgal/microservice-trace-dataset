#!/usr/bin/env python3
"""Does the blueprint help? Per problem, not pooled.

The pooled table said the blueprint was worth +0 points, which is an artefact of averaging six
problems that behave nothing alike: three sit near the ceiling, two sit on the floor at 0/60,
and an average over that says nothing about any of them. This splits every axis by problem and
by arm so a real effect is not cancelled by an unrelated one.

Reads score.json and rescored.json. Computes nothing new - it only groups.

    python q2_arms.py --out-dir /scratch/yuvraj17/stratatrace/results/q2-full
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import q2_rescore as RS  # noqa: E402


def load(out_dir: str):
    rows = []
    for sp in sorted(glob.glob(os.path.join(out_dir, "*", "*", "*", "*", "*", "score.json"))):
        try:
            r = json.load(open(sp, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rp = os.path.join(os.path.dirname(sp), "rescored.json")
        if os.path.exists(rp):
            try:
                r["_v2"] = json.load(open(rp, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                r["_v2"] = {}
        else:
            r["_v2"] = {}
        rows.append(r)
    return rows


def pct(n, d):
    return "  -  " if not d else "%3d%%" % round(100 * n / d)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="/scratch/yuvraj17/stratatrace/results/q2-full")
    a = ap.parse_args()

    rows = load(a.out_dir)
    if not rows:
        print("no runs under %s" % a.out_dir)
        return 1
    print("%d runs\n" % len(rows))

    by = defaultdict(list)
    for r in rows:
        by[(r.get("problem"), r.get("ask"), r.get("arm"))].append(r)
    problems = sorted({r.get("problem") for r in rows})

    hdr = ("  %-14s %3s  %7s %7s %8s %8s %7s %7s"
           % ("ask | arm", "n", "WHERE", "window", "describe", "fault", "calls", "tokens"))
    for prob in problems:
        ceiling = RS.WHERE_CEILING.get(prob, "named")
        print("=" * 78)
        print("%s   (best possible WHERE answer: %s)" % (prob, ceiling))
        print("=" * 78)
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        cache = {}
        for ask in ("nohint", "hint"):
            for arm in ("none", "given"):
                rs = by.get((prob, ask, arm)) or []
                if not rs:
                    continue
                n = len(rs)
                where = sum(1 for r in rs if RS.where_ok(r.get("where", ""), prob))
                win = sum(1 for r in rs if r.get("window_verdict") == "hit")
                v2 = [r["_v2"].get("what_score_v2") for r in rs
                      if isinstance(r["_v2"].get("what_score_v2"), (int, float))]
                fault = sum(1 for r in rs if r.get("fault_ok"))
                cache[(ask, arm)] = (where / n, win / n,
                                     (sum(v2) / len(v2)) if v2 else 0.0, fault / n)
                print("  %-14s %3d  %7s %7s %8s %8s %7s %7s"
                      % ("%s|%s" % (ask, arm), n, pct(where, n), pct(win, n),
                         "%3d%%" % round(100 * sum(v2) / len(v2)) if v2 else "  - ",
                         pct(fault, n),
                         _med([r.get("calls") for r in rs]),
                         _med([r.get("tokens") for r in rs])))
        for ask in ("nohint", "hint"):
            none_, given = cache.get((ask, "none")), cache.get((ask, "given"))
            if not (none_ and given):
                continue
            print("  %-14s      %+4d    %+4d     %+4d     %+4d   <- blueprint effect"
                  % ("  " + ask,
                     round(100 * (given[0] - none_[0])), round(100 * (given[1] - none_[1])),
                     round(100 * (given[2] - none_[2])), round(100 * (given[3] - none_[3]))))
        print()

    # One line per problem, pooling the two asks, because that is the number that goes in a
    # paper and it must not be the pooled-over-problems one that came out as +0.
    print("=" * 78)
    print("BLUEPRINT EFFECT, per problem (both asks pooled, in percentage points)")
    print("=" * 78)
    print("  %-16s %8s %8s %10s %8s" % ("problem", "WHERE", "window", "describe", "fault"))
    print("  " + "-" * 56)
    for prob in problems:
        out = []
        for axis in range(4):
            vals = {}
            for arm in ("none", "given"):
                rs = [r for ask in ("nohint", "hint")
                      for r in (by.get((prob, ask, arm)) or [])]
                if not rs:
                    continue
                n = len(rs)
                if axis == 0:
                    v = sum(1 for r in rs if RS.where_ok(r.get("where", ""), prob)) / n
                elif axis == 1:
                    v = sum(1 for r in rs if r.get("window_verdict") == "hit") / n
                elif axis == 2:
                    xs = [r["_v2"].get("what_score_v2") for r in rs
                          if isinstance(r["_v2"].get("what_score_v2"), (int, float))]
                    v = (sum(xs) / len(xs)) if xs else 0.0
                else:
                    v = sum(1 for r in rs if r.get("fault_ok")) / n
                vals[arm] = v
            out.append(round(100 * (vals.get("given", 0) - vals.get("none", 0)))
                       if len(vals) == 2 else None)
        print("  %-16s %+8s %+8s %+10s %+8s"
              % (prob, *[("%d" % o) if o is not None else " -" for o in out]))
    print()
    print("  WHERE is judged against the best answer each fault allows (see q2_rescore.py).")
    return 0


def _med(vals):
    v = sorted(x for x in vals if isinstance(x, (int, float)))
    return v[len(v) // 2] if v else "-"


if __name__ == "__main__":
    sys.exit(main())
