#!/usr/bin/env python3
"""Second half of the audit: is each run's BASELINE window actually a healthy reference?

`audit_dataset.py` reads the bundle. It cannot see inside the trace, so it cannot tell whether
the baseline window was quiet - and a loud baseline is how 25 code-defect runs became unusable
without anyone noticing for months. That needs the analysis packs, which already carry
per-interface retransmission split by window.

Three things make a baseline untrustworthy:

  retransmission in the baseline   a healthy baseline measures 0.00%. The code-defect runs
                                   measure 28-80%, because the injection restarted the
                                   container inside the window.
  endpoints vanishing              MEASURED AND DROPPED AS A CRITERION. It looked clean -
                                   3-7 gone in every contaminated run against 1-2 in a clean
                                   one - until it was checked against every family.
                                   anomaly_mem, fd_exhaustion, fork_storm and nagle_delayed_ack
                                   all reach 5 with perfectly quiet baselines. Still reported,
                                   but it no longer decides anything.
  a newcomer already present       a process that "arrives" in the incident window but was
                                   already consuming in the baseline means the fault started
                                   early.

    python3 audit_baselines.py --packs <dir> --out baselines.json
"""
import argparse
import collections
import glob
import io
import json
import os

RETRANS_MAX_PCT = 10.0
GONE_MAX = 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    rows, by_fam = [], collections.defaultdict(lambda: [0, 0])
    for f in sorted(glob.glob(os.path.join(a.packs, "*.json"))):
        try:
            p = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if not p.get("run_id"):
            continue
        fam = p.get("family_dir") or ""
        fam = fam[3:] if fam.startswith("tt_") else fam
        worst = 0.0
        for r in (p.get("netloss") or {}).get("worst") or []:
            worst = max(worst, r.get("retrans_pct_baseline") or 0.0)
        gone = (((p.get("endpoints") or {}).get("signature") or {}).get("n_gone")) or 0
        bad = []
        if worst > RETRANS_MAX_PCT:
            bad.append("baseline retransmission %.3g%%" % worst)
        # `gone > GONE_MAX` was a criterion until it was measured across every family and
        # found to fire on four families whose baselines are quiet. Reported, not decisive.
        rows.append({"run": p["run_id"], "app": p.get("app"), "family": fam,
                     "baseline_retrans_pct": round(worst, 3), "endpoints_gone": gone,
                     "problems": bad})
        by_fam[(p.get("app"), fam)][0] += 1
        if bad:
            by_fam[(p.get("app"), fam)][1] += 1

    bad = [r for r in rows if r["problems"]]
    print("packs checked            : %d" % len(rows))
    print("baselines NOT usable     : %d" % len(bad))
    print()
    print("--- per family: runs / contaminated baselines ---")
    for (app, fam), (t, b) in sorted(by_fam.items()):
        if b:
            print("  %-12s %-24s %3d   %3d   <--" % (app, fam, t, b))
    print()
    print("  (families with zero contaminated baselines omitted)")
    print()
    print("--- every run with a bad baseline ---")
    for r in sorted(bad, key=lambda r: (r["app"], r["family"], r["run"])):
        print("  %-12s %-24s %-42s %s"
              % (r["app"], r["family"], r["run"][:42], "; ".join(r["problems"])))

    if a.out:
        with io.open(a.out, "w", encoding="utf-8", newline=chr(10)) as fh:
            fh.write(json.dumps(rows, indent=1) + chr(10))
        print()
        print("wrote " + a.out)


if __name__ == "__main__":
    main()
