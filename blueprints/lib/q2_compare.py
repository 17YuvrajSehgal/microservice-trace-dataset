#!/usr/bin/env python3
"""Compare two result directories on the same problems.

Built for before/after on a single change. The per-service re-run differs from the full matrix
in exactly one way - whether the count index carried pid_ns, so whether the agent could tell
one container's `java` from another's - and everything else was held fixed: same model, same
blueprints, same prompt, same runs, same repeats.

    python q2_compare.py --before .../results/q2-full --after .../results/q2-ns
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import q2_rescore as RS  # noqa: E402


def load(out_dir: str):
    rows = []
    for sp in sorted(glob.glob(os.path.join(out_dir, "*", "*", "*", "*", "*", "score.json"))):
        try:
            rows.append(json.load(open(sp, encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def stats(rs, prob):
    n = len(rs)
    if not n:
        return None
    w = Counter(r.get("where") for r in rs)
    return {
        "n": n,
        "where_ok": sum(1 for r in rs if RS.where_ok(r.get("where", ""), prob)),
        "named": w["named"], "container": w["container"], "scope": w["scope"],
        "ambiguous": w["ambiguous"], "wrong": w["wrong"] + w["none"],
        "window_hits": sum(1 for r in rs if r.get("window_verdict") == "hit"),
        "said_host": sum(1 for r in rs
                         if str(r.get("pred_service", "")).strip().lower() == "host"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    a = ap.parse_args()

    before, after = load(a.before), load(a.after)
    if not after:
        print("nothing under %s" % a.after)
        return 1
    problems = sorted({r.get("problem") for r in after})

    print("before: %s  (%d runs)" % (a.before, len(before)))
    print("after : %s  (%d runs)" % (a.after, len(after)))
    print()
    for prob in problems:
        b = stats([r for r in before if r.get("problem") == prob], prob)
        f = stats([r for r in after if r.get("problem") == prob], prob)
        if not (b and f):
            continue
        tgt = next((r.get("true_service") for r in after if r.get("problem") == prob), "?")
        print("=" * 72)
        print("%s   (target: %s)" % (prob, tgt))
        print("=" * 72)
        print("  %-18s %10s %10s %10s" % ("", "before", "after", "change"))
        print("  " + "-" * 52)
        for key, label in (("where_ok", "WHERE right"), ("named", "  named it"),
                           ("container", "  named container"), ("scope", "  scope only"),
                           ("ambiguous", "  ambiguous"), ("wrong", "  wrong"),
                           ("said_host", 'answered "host"'),
                           ("window_hits", "window hits")):
            print("  %-18s %6d/%-3d %6d/%-3d %10s"
                  % (label, b[key], b["n"], f[key], f["n"], "%+d" % (f[key] - b[key])))
        print()

    # Also per arm, because the whole point is whether the blueprint helps once the agent can
    # actually see containers - which it could not before.
    print("=" * 72)
    print("WHERE right, per arm")
    print("=" * 72)
    print("  %-16s %-14s %10s %10s %8s" % ("problem", "ask | arm", "before", "after", "change"))
    print("  " + "-" * 62)
    for prob in problems:
        for ask in ("nohint", "hint"):
            for arm in ("none", "given"):
                bs = [r for r in before if r.get("problem") == prob
                      and r.get("ask") == ask and r.get("arm") == arm]
                fs = [r for r in after if r.get("problem") == prob
                      and r.get("ask") == ask and r.get("arm") == arm]
                if not (bs and fs):
                    continue
                bo = sum(1 for r in bs if RS.where_ok(r.get("where", ""), prob))
                fo = sum(1 for r in fs if RS.where_ok(r.get("where", ""), prob))
                print("  %-16s %-14s %6d/%-3d %6d/%-3d %8s"
                      % (prob, "%s|%s" % (ask, arm), bo, len(bs), fo, len(fs),
                         "%+d" % (fo - bo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
