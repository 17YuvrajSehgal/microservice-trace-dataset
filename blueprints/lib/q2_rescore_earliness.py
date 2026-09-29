#!/usr/bin/env python3
"""Score HOW EARLY the agent noticed, on runs that are already finished.

WHY. The published evaluation asks whether a claimed window overlaps the real one, and reports
IoU. That cannot express the thing an operator cares about most: two answers with identical IoU
can differ by a minute in when they noticed, and IoU calls them equal. Measured on our own runs,
IoU moved 0.543 -> 0.776 between agent versions while onset error moved 121 s -> 7 s at p90 -
the metric we publish was hiding most of the difference.

This reads `window_claimed` and `window_true`, which every score.json already carries, so every
run ever done can be rescored with no model calls and no re-running.

THE FOUR NUMBERS, and why not one.

  onset_error_s    claimed start minus true start. Signed: negative means it named a start
                   before the fault began, positive means it noticed late. Raw diagnostic.

  detect_delay_s   max(0, onset_error_s). Lateness only. Being early is not a virtue to reward
                   without limit - past a point it is just an over-wide claim - so the delay
                   clock starts at the true onset.

  earliness        1 - delay/duration, clamped. 1.0 caught it as it began, 0.5 halfway through,
                   0.0 not until it was over. Normalised by the incident's own duration so
                   faults of different lengths compare.

  earliness_gated  earliness x IoU. THE HEADLINE. Earliness alone is trivially gamed - claim the
                   whole recording and the delay is zero by construction. IoU punishes an
                   over-wide claim through its precision term, so the product is high only for a
                   window that is both early AND tight.

ABSTENTIONS SCORE None, NOT ZERO. The agent's schema says a wrong window is worse than an
admitted gap. Scoring an abstention as maximum lateness would contradict that and make honesty
cost more than guessing. They are counted and reported separately.

    python q2_rescore_earliness.py results/q2-ss results/q2-tt
    python q2_rescore_earliness.py --write results/q2-ss      # add the fields to score.json
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import re
import statistics
import sys

_T = re.compile(r"(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)")


def _ends(text):
    """Both timestamps out of 'HH:MM:SS - HH:MM:SS' or an ISO range. None if not two."""
    t = _T.findall(str(text) or "")
    if len(t) < 2:
        return None, None
    v = [int(h) * 3600 + int(m) * 60 + float(s) for h, m, s in t[:2]]
    return v[0], v[1]


def earliness_for(claimed, true_window):
    """The four numbers for one run, or None when there is nothing to score."""
    c0, c1 = _ends(claimed)
    t0, t1 = _ends(true_window)
    if t0 is None or t1 is None or t1 <= t0:
        return None
    if c0 is None or c1 is None or c1 <= c0:
        return None                      # abstained or unparseable: scored separately
    dur = t1 - t0
    inter = max(0.0, min(t1, c1) - max(t0, c0))
    union = max(t1, c1) - min(t0, c0)
    iou = inter / union if union > 0 else 0.0
    onset = c0 - t0
    delay = max(0.0, onset)
    early = max(0.0, min(1.0, 1.0 - delay / dur))
    return {"onset_error_s": round(onset, 1),
            "detect_delay_s": round(delay, 1),
            "earliness": round(early, 3),
            "earliness_gated": round(early * iou, 3),
            "iou": round(iou, 3),
            "claimed_width_ratio": round((c1 - c0) / dur, 2)}


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * (len(v) - 1)))] if v else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--write", action="store_true",
                    help="add the fields to each score.json in place")
    ap.add_argument("--by", default="problem", help="group rows by this score.json field")
    a = ap.parse_args()

    groups = {}
    n_files = n_abstain = 0
    for root in a.dirs:
        for sp in glob.glob(os.path.join(root, "*", "*", "*", "*", "*", "score.json")):
            try:
                r = json.load(open(sp, encoding="utf-8"))
            except Exception:
                continue
            n_files += 1
            e = earliness_for(r.get("window_claimed"), r.get("window_true"))
            key = (os.path.basename(root.rstrip("/")), str(r.get(a.by)))
            g = groups.setdefault(key, {"n": 0, "abstain": 0, "rows": []})
            g["n"] += 1
            if e is None:
                g["abstain"] += 1
                n_abstain += 1
                continue
            g["rows"].append(e)
            if a.write:
                r.update({k: e[k] for k in ("onset_error_s", "detect_delay_s",
                                            "earliness", "earliness_gated")})
                tmp = sp + ".tmp"
                json.dump(r, open(tmp, "w", encoding="utf-8"), indent=1)
                os.replace(tmp, sp)

    if not n_files:
        print("no score.json found under %s" % ", ".join(a.dirs))
        return 1

    print("%-14s %-22s %5s %7s %9s %9s %9s %9s %8s"
          % ("dir", a.by, "n", "abst", "onset med", "onset p90", "earliness",
             "gated", "width"))
    print("-" * 104)
    for (d, k), g in sorted(groups.items()):
        rows = g["rows"]
        if not rows:
            print("%-14s %-22s %5d %7d   (nothing scoreable)" % (d, k, g["n"], g["abstain"]))
            continue
        on = [x["onset_error_s"] for x in rows]
        ea = [x["earliness"] for x in rows]
        ga = [x["earliness_gated"] for x in rows]
        wr = [x["claimed_width_ratio"] for x in rows]
        print("%-14s %-22s %5d %7d %+9.1f %+9.1f %9.3f %9.3f %7.1fx"
              % (d, k, g["n"], g["abstain"], statistics.median(on), q(on, 0.9),
                 statistics.mean(ea), statistics.mean(ga), statistics.median(wr)))

    allrows = [x for g in groups.values() for x in g["rows"]]
    print()
    print("%d runs, %d abstained (scored as None, not 0)" % (n_files, n_abstain))
    if allrows:
        wide = [x for x in allrows if x["claimed_width_ratio"] > 2]
        gamed = [x for x in wide if x["earliness"] > 0.9 and x["earliness_gated"] < 0.5]
        print("claimed windows more than 2x the true width: %d of %d (%.0f%%)"
              % (len(wide), len(allrows), 100.0 * len(wide) / len(allrows)))
        print("  of those, how many the IoU gate demotes: %d - this is what the gate is for"
              % len(gamed))
    if a.write:
        print()
        print("wrote the four fields into every score.json scanned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
