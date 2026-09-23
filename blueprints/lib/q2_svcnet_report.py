#!/usr/bin/env python3
"""Score the svc_net re-run against the published 0/60, at the same n.

The point of this run is one question: is "2 of 6" real? The earlier comparison was n=6 per
cell, where a single run is 17 points, so it could establish the mechanism and not the size.
This uses the published design - 3 incidents x 2 arms x 2 asks x 5 repeats - so the number
sits beside the 0/60 it replaces without a caveat about sample size.

Every WHERE outcome is printed, not just the pass count. "named the wrong container" and
"answered host" both fail, and they mean completely different things about whether the agent
is looking in the right place.

    python q2_svcnet_report.py [--new DIR] [--old-ss DIR] [--old-tt DIR]
"""
from __future__ import annotations
import argparse, collections, glob, json, os

S = "/scratch/yuvraj17/stratatrace/results"
ORDER = ["named", "container", "container_wrong", "container_unverified",
         "scope", "ambiguous", "wrong", "none"]
PASS = {"named", "container"}       # matches q2_rescore.where_ok for a service-scoped fault


def load(root, pre, arm=None, ask=None):
    out = []
    for sp in glob.glob("%s/svc_net/*/*/*/*/score.json" % root):
        try:
            r = json.load(open(sp))
        except Exception:
            continue
        if (r.get("run_id") or "").startswith("tt_") != (pre == "tt"):
            continue
        if arm and r.get("arm") != arm:
            continue
        if ask and r.get("ask") != ask:
            continue
        if int(r.get("repeat") or 0) > 10:
            continue
        out.append(r)
    return out


def line(label, rows):
    if not rows:
        return "  %-26s %5s  (no cells)" % (label, "-")
    n = len(rows)
    c = collections.Counter(r.get("where") for r in rows)
    ok = sum(c[k] for k in PASS)
    hit = sum(1 for r in rows if r.get("window_verdict") == "hit")
    bits = "  ".join("%s=%d" % (k, c[k]) for k in ORDER if c[k])
    return ("  %-26s %5d   WHERE %2d/%-3d (%3.0f%%)   window %2d/%-3d   %s"
            % (label, n, ok, n, 100.0 * ok / n, hit, n, bits))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", default=os.path.join(S, "svcnet-n30"))
    ap.add_argument("--old-ss", default=os.path.join(S, "q2-ss"))
    ap.add_argument("--old-tt", default=os.path.join(S, "q2-tt"))
    a = ap.parse_args()

    for pre, label, old in (("ss", "SOCK SHOP", a.old_ss), ("tt", "TRAIN TICKET", a.old_tt)):
        print("=" * 104)
        print("%s   svc_net" % label)
        print("=" * 104)
        print(line("published (v1, old tools)", load(old, pre)))
        print(line("re-run (v2, blueprint v4)", load(a.new, pre)))
        print()
        for arm in ("given", "none"):
            print(line("  re-run, arm=%s" % arm, load(a.new, pre, arm=arm)))
        for ask in ("hint", "nohint"):
            print(line("  re-run, ask=%s" % ask, load(a.new, pre, ask=ask)))
        print()

    print("=" * 104)
    print("WHICH container it named, when it named one")
    print("=" * 104)
    for pre, label in (("ss", "SOCK SHOP"), ("tt", "TRAIN TICKET")):
        rows = [r for r in load(a.new, pre)
                if str(r.get("where", "")).startswith("container")]
        if not rows:
            print("  %-14s none" % label)
            continue
        right = sum(1 for r in rows if r.get("container_correct") is True)
        wrong = sum(1 for r in rows if r.get("container_correct") is False)
        unk = sum(1 for r in rows if r.get("container_correct") is None)
        print("  %-14s %d named a container: %d right, %d wrong, %d unresolvable"
              % (label, len(rows), right, wrong, unk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
