"""Whether a run actually contains the fault it is labelled with.

THE PROBLEM THIS SOLVES
-----------------------
283 of the 303 v2 runs carry a verdict from the campaign's `verify_injection.py`, written at
collection time. **No analysis script read it.** So 32 runs whose fault demonstrably did not
take were used as positives when deriving thresholds, and as labelled examples when measuring
separation. Every number produced that way is measured partly against runs that contain no
fault.

THE POLICY, AND WHY EACH PART OF IT
-----------------------------------
    confirmed            the fault moved its target metric.
                         -> positive: yes.  negative: yes.

    unconfirmed          the metric checks RAN and saw nothing.
                         -> positive: NO. We cannot claim a run demonstrates a fault when the
                            measurement says it does not.
                         -> negative: YES, and this matters. The run exists and nothing
                            happened in it, so a blueprint firing on it is a real false fire.
                            Dropping it would make every separation look better than it is.

    no_metric_signature  no metric target can see this fault AT ALL.
                         -> positive: yes, IF the kernel shows it. This is not a failed
                            injection: all 5 dns_delay runs read this way and 4 show the fault
                            plainly at 161-310 EMFILE/s. A fault invisible to metrics and
                            obvious in the kernel is the finding, not a defect.
                         -> negative: yes.

    borderline           the effect is weak.
                         -> positive: NO by default, because "weak" is not "present", but the
                            count is reported separately so it can be reconsidered per family
                            rather than silently dropped.
                         -> negative: yes.

    unknown              no verdict (the 20 healthy controls, plus anything unindexed).
                         -> treated as confirmed for controls, because a control has no fault
                            to verify. Anything else unknown is reported, never assumed good.

Build the index once, where the bundles are:

    python3 blueprints/lib/verification.py --v2 /scratch/.../stratatrace-v2 \
        --out blueprints/results/verification_index.json
"""
import argparse
import collections
import glob
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(os.path.dirname(HERE), "results", "verification_index.json")

CONFIRMED = "confirmed"
UNCONFIRMED = "unconfirmed"
BORDERLINE = "borderline"
BLIND = "no_metric_signature"
UNKNOWN = "unknown"

_CACHE = {}


def load(path=None):
    """run_id -> status. Empty dict if the index is missing, so a caller can still run - but
    `report()` will say the index was absent rather than pretend everything is confirmed."""
    p = path or INDEX
    if p not in _CACHE:
        try:
            with io.open(p, encoding="utf-8") as fh:
                _CACHE[p] = json.load(fh).get("runs", {})
        except (OSError, ValueError):
            _CACHE[p] = {}
    return _CACHE[p]


def status(run_id, index=None):
    return (index if index is not None else load()).get(run_id, UNKNOWN)


def usable_as_positive(run_id, index=None, family=None):
    """Can this run be used as evidence that its fault is present?"""
    st = status(run_id, index)
    if st == CONFIRMED:
        return True
    if st == BLIND:
        # metrics cannot see this fault; the kernel measurement decides, and the caller is the
        # one holding it. Allowed through, and counted separately so the reliance is visible.
        return True
    if st == UNKNOWN:
        # a control run has no fault to verify
        return bool(family) and family in ("normal", "control")
    return False


def usable_as_negative(run_id, index=None):
    """Almost always yes. A run where the fault did not take is still a real run of a real
    system, and a blueprint firing on it is still a false fire."""
    return True


def report(runs, index=None, label=""):
    """One line per status, for any script that filters on this. Printing it is the point -
    a filter nobody can see is how the previous silence happened."""
    idx = index if index is not None else load()
    c = collections.Counter(status(r, idx) for r in runs)
    if not idx:
        print("  VERIFICATION INDEX MISSING - nothing was filtered%s"
              % (" (%s)" % label if label else ""))
        return c
    parts = ", ".join("%s=%d" % (k, n) for k, n in c.most_common())
    print("  verification%s: %s" % (" (%s)" % label if label else "", parts))
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", required=True, help="root of the run bundles")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    runs, detail = {}, {}
    for f in sorted(glob.glob(os.path.join(a.v2, "*", "*", "*", "verification.json"))):
        run = os.path.basename(os.path.dirname(f))
        try:
            d = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            runs[run] = UNKNOWN
            continue
        runs[run] = d.get("verification_status", UNKNOWN)
        detail[run] = {"app": os.path.basename(os.path.dirname(os.path.dirname(
                           os.path.dirname(f)))),
                       "family": os.path.basename(os.path.dirname(os.path.dirname(f))),
                       "review": bool(d.get("operator_review_required"))}

    # runs with no verification.json at all - the controls, and anything that lost one
    for d in sorted(glob.glob(os.path.join(a.v2, "*", "*", "*"))):
        if not os.path.isdir(d) or d.endswith("_metrics"):
            continue
        run = os.path.basename(d)
        if run not in runs:
            runs[run] = UNKNOWN
            detail[run] = {"app": os.path.basename(os.path.dirname(os.path.dirname(d))),
                           "family": os.path.basename(os.path.dirname(d)), "review": False}

    out = {"source": a.v2, "n": len(runs), "runs": runs, "detail": detail}
    with io.open(a.out, "w", encoding="utf-8", newline=chr(10)) as fh:
        fh.write(json.dumps(out, indent=1, sort_keys=True) + chr(10))

    c = collections.Counter(runs.values())
    print("indexed %d runs" % len(runs))
    for k, n in c.most_common():
        print("  %-22s %d" % (k, n))
    print("wrote " + a.out)


if __name__ == "__main__":
    main()
