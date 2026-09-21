#!/usr/bin/env python3
"""Print every answer in the agent's own words, so a human can mark them.

The automatic scores sort and flag. They do not decide. This dumps all 60 answers in one
readable file, grouped by arm, so the real question - did it actually understand what it was
looking at - can be answered by reading rather than by trusting a keyword match.

Each block shows what the agent said, where it pointed, when it thought it happened, how it
got there, and what the rubric thought. Disagreeing with the rubric is the point: if a run
reads correct and scored low, the rubric is wrong, not the run.

    python q2_review.py --out-dir .../results/q2 > review.md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def load(out_dir: str):
    rows = []
    for sp in sorted(glob.glob(os.path.join(out_dir, "*", "*", "*", "*", "*", "score.json"))):
        try:
            r = json.load(open(sp, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        cell = os.path.dirname(sp)
        dp = os.path.join(cell, "diagnosis.json")
        r["_diagnosis"] = {}
        if os.path.exists(dp):
            try:
                r["_diagnosis"] = json.load(open(dp, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        r["_cell"] = cell
        rows.append(r)
    return rows


def wrap(text: str, width: int = 92, indent: str = "    ") -> str:
    words, line, out = str(text or "").split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(indent + line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(indent + line)
    return "\n".join(out) or (indent + "(nothing said)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="/scratch/yuvraj17/stratatrace/results/q2")
    ap.add_argument("--problem", default="")
    ap.add_argument("--only", default="", help="filter, e.g. 'hint|given'")
    a = ap.parse_args()

    rows = load(a.out_dir)
    if a.problem:
        rows = [r for r in rows if r.get("problem") == a.problem]
    if not rows:
        print("no runs found under %s" % a.out_dir)
        return 1

    print("# Review sheet - %d runs" % len(rows))
    print()
    print("Automatic scores are a first pass. Read the words and mark it yourself.")
    print("If a run reads correct but scored low, the rubric is wrong - say so and it changes.")
    print()

    for ask in ("nohint", "hint"):
        for arm in ("none", "given"):
            key = "%s|%s" % (ask, arm)
            if a.only and a.only != key:
                continue
            rs = [r for r in rows if r.get("ask") == ask and r.get("arm") == arm]
            if not rs:
                continue
            named = sum(1 for r in rs if r.get("named_culprit"))
            whotool = sum(1 for r in rs if r.get("used_who_tools"))
            print("=" * 96)
            print("## %s   (%d runs)   named the culprit: %d   used who-tools: %d"
                  % (key, len(rs), named, whotool))
            print("=" * 96)
            print()
            for r in sorted(rs, key=lambda x: (x.get("run_id", ""), x.get("repeat", 0))):
                d = r["_diagnosis"]
                print("### %s rep%s" % (r.get("run_id"), r.get("repeat")))
                print()
                print("  WHAT IT SAID:")
                print(wrap(d.get("what_is_wrong") or "(field not present - older run)"))
                print()
                print("  WHERE: %s  (kind: %s)   [rubric: %s]"
                      % (d.get("root_cause_service"), d.get("culprit_kind"),
                         (r.get("where") or "?").upper()))
                print("  WHEN:  %s   [true %s, IoU %s]"
                      % (r.get("window_claimed"), r.get("window_true"), r.get("window_iou")))
                print("  LABEL: %s   [true %s]" % (r.get("pred_fault"), r.get("true_fault")))
                print("  TOOLS: %s" % ", ".join(r.get("distinct_tools") or []))
                ws = r.get("what_score")
                print("  RUBRIC: described %s%s"
                      % ("%.0f%%" % (100 * ws) if ws is not None else "n/a",
                         ("  |  missed: " + "; ".join(r.get("what_missed") or []))
                         if r.get("what_missed") else ""))
                print()
                print("  HOW IT SAYS IT FOUND IT:")
                print(wrap(d.get("evidence")))
                print()
                print("  WHY THAT WINDOW:")
                print(wrap(d.get("window_evidence")))
                alts = d.get("alternatives") or []
                if alts:
                    print()
                    print("  ALTERNATIVES IT LEFT OPEN:")
                    for i, alt in enumerate(alts, 2):
                        print("    %d. %s / %s" % (i, alt.get("service"), alt.get("fault_type")))
                print()
                print("  files: %s" % r.get("_cell"))
                print()
                print("-" * 96)
                print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
