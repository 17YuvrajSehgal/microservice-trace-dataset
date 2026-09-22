#!/usr/bin/env python3
"""Find candidate kernel signatures for a fault family - and test them against the others.

WHY THIS EXISTS RATHER THAN A HAND-WRITTEN BLUEPRINT
----------------------------------------------------
Every discriminator in the existing blueprints carries a measured range and an `n`, and each
one records what was tested and FAILED in `unverified_do_not_claim`. That is the bar. Writing a
new blueprint from what a kernel trace ought to show would fail it on the first review.

The campaign already learned this the expensive way. Six verification targets were wrong, and
the flaw was the same every time: they measured *consequences* - throughput, CPU usage, byte
rates - which scale with offered load, instead of *mechanisms*, which do not. A signal that
moves because the workload moved is not a signature.

WHAT IT DOES
------------
For each run: rate of every event type inside the injection window against a baseline window
taken before it, read from the count index. Then the part that matters - the same measurement
across EVERY family, so a candidate signal is only reported if it moves in its own family and
stays put in the others. A signal that fires everywhere is a load detector wearing a costume.

Ground truth is read here because this is offline analysis, not a tool the agent can reach.

    python discover_signature.py --families lock_contention,deadlock,normal
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import sys
from collections import defaultdict

IDX = "/scratch/yuvraj17/stratatrace/dataset/index"
DATA = "/scratch/yuvraj17/stratatrace/dataset/runs"
TAB = chr(9)
# a rate below this is noise: a handful of events over two minutes says nothing
MIN_RATE = 0.5


def secs(iso):
    try:
        t = iso.split("T")[-1].rstrip("Z")
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return None


def run_dirs(family, app="sockshop"):
    d = os.path.join(DATA, app, family)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, r) for r in sorted(os.listdir(d))
            if os.path.isdir(os.path.join(d, r)) and not r.endswith("_metrics")]


def windows(run_dir):
    """(baseline_start, baseline_end, incident_start, incident_end) in seconds, or None.

    The baseline is the 60 s ending 10 s before injection. The gap matters: a recipe that arms
    itself (pulling an image, starting a container) does work just before the stamp, and
    letting that bleed into the baseline is how a fault gets compared against itself.
    """
    gp = os.path.join(run_dir, "ground_truth.json")
    if not os.path.exists(gp):
        return None
    f = (json.load(open(gp)).get("fault") or {})
    t0, t1 = secs(f.get("injection_start_utc") or ""), secs(f.get("injection_end_utc") or "")
    if t0 is None or t1 is None or t1 <= t0:
        return None
    return (t0 - 70, t0 - 10, t0, t1)


def rates(run_dir):
    """Per-event rate in the baseline window and in the injection window."""
    rid = os.path.basename(run_dir.rstrip("/"))
    p = os.path.join(IDX, rid + ".tsv.gz")
    if not os.path.exists(p):
        return None
    w = windows(run_dir)
    if not w:
        return None
    b0, b1, i0, i1 = w
    base, inc = defaultdict(int), defaultdict(int)
    with gzip.open(p, "rt") as fh:
        for line in fh:
            if line[0] == "#":
                continue
            parts = line.rstrip().split(TAB)
            if len(parts) != 5:
                continue
            try:
                bt, n = float(parts[0]), int(parts[4])
            except ValueError:
                continue
            ev = parts[1]
            if b0 <= bt < b1:
                base[ev] += n
            elif i0 <= bt < i1:
                inc[ev] += n
    db, di = (b1 - b0), (i1 - i0)
    return {"run": rid,
            "base": {e: v / db for e, v in base.items()},
            "inc": {e: v / di for e, v in inc.items()}}


def ratios(r):
    """log2 ratio per event. A new event is +inf and is reported separately, not as a number."""
    out = {}
    for e in set(r["base"]) | set(r["inc"]):
        b, i = r["base"].get(e, 0.0), r["inc"].get(e, 0.0)
        if max(b, i) < MIN_RATE:
            continue
        if b == 0:
            out[e] = ("appeared", i)
        elif i == 0:
            out[e] = ("vanished", b)
        else:
            out[e] = ("ratio", math.log2(i / b))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", required=True)
    ap.add_argument("--app", default="sockshop")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    fams = [f.strip() for f in a.families.split(",") if f.strip()]

    per_fam = {}
    for fam in fams:
        rs = []
        for rd in run_dirs(fam, a.app):
            r = rates(rd)
            if r:
                rs.append((r, ratios(r)))
        if rs:
            per_fam[fam] = rs
        print("%-24s %d run(s) with an index" % (fam, len(rs)))
    print()

    if not per_fam:
        print("nothing indexed yet")
        return 1

    # --- per family: what moved ---
    for fam, rs in per_fam.items():
        print("=" * 96)
        print("%s   (%d runs)" % (fam, len(rs)))
        print("=" * 96)
        agg = defaultdict(list)
        for _, rat in rs:
            for e, (kind, v) in rat.items():
                agg[e].append((kind, v))
        # keep events that behaved the same way in EVERY run of the family
        stable = []
        for e, vs in agg.items():
            if len(vs) < len(rs):
                continue
            kinds = {k for k, _ in vs}
            if kinds == {"ratio"}:
                xs = [v for _, v in vs]
                if min(xs) * max(xs) > 0 and min(abs(x) for x in xs) > 0.7:
                    stable.append((e, "ratio", min(xs), max(xs)))
            elif kinds == {"appeared"}:
                stable.append((e, "appeared", min(v for _, v in vs), max(v for _, v in vs)))
            elif kinds == {"vanished"}:
                stable.append((e, "vanished", min(v for _, v in vs), max(v for _, v in vs)))
        stable.sort(key=lambda t: -abs(t[2]))
        if not stable:
            print("  nothing moved consistently in every run")
        for e, kind, lo, hi in stable[:a.top]:
            if kind == "ratio":
                print("  %-46s x%.2f to x%.2f" % (e, 2 ** lo, 2 ** hi))
            else:
                print("  %-46s %s  (%.1f to %.1f /s)" % (e, kind.upper(), lo, hi))
        print()

    # --- the part that decides: does it fire anywhere else? ---
    print("=" * 96)
    print("SPECIFICITY - the same event across every family")
    print("=" * 96)
    print("A signal that moves everywhere is a load detector, not a signature.")
    print()
    cand = set()
    for fam, rs in per_fam.items():
        if fam == "normal":
            continue
        agg = defaultdict(list)
        for _, rat in rs:
            for e, (kind, v) in rat.items():
                agg[e].append((kind, v))
        for e, vs in agg.items():
            if len(vs) == len(rs):
                cand.add(e)

    hdr = "  %-40s" % "event" + "".join("%>12s".replace(">", "") % f[:11] for f in per_fam)
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    rows = []
    for e in sorted(cand):
        cells, spread = [], []
        for fam, rs in per_fam.items():
            vs = [rat.get(e) for _, rat in rs]
            vs = [v for v in vs if v]
            if not vs:
                cells.append("-")
                continue
            kinds = {k for k, _ in vs}
            if kinds == {"ratio"}:
                m = sum(v for _, v in vs) / len(vs)
                cells.append("x%.1f" % (2 ** m))
                spread.append(abs(m))
            elif "appeared" in kinds:
                cells.append("NEW")
                spread.append(9.9)
            else:
                cells.append("gone")
                spread.append(9.9)
        rows.append((max(spread) if spread else 0, e, cells))
    rows.sort(reverse=True)
    for _, e, cells in rows[:40]:
        print("  %-40s" % e[:40] + "".join("%12s" % c for c in cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
