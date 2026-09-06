#!/usr/bin/env python3
"""Regenerate the campaign's issue list from the run bundles.

WHY A SCRIPT AND NOT A HAND-KEPT LIST
-------------------------------------
CAMPAIGN-ISSUES.md started as prose and was out of date within two hours - the campaign kept
producing runs while it was being written. A list of what is wrong has to be derived from the
bundles, for the same reason the manifest does: anything maintained by hand drifts from what is
on disk, and the thing that drifts is the thing nobody re-checks.

This prints the current state, grouped so the eye lands on what matters:

    RE-COLLECT   the run does not contain the fault it claims  - costs a VM run
    RE-SCORE     fault fired and the trace is clean, verdict wrong - costs a re-run of scoring
    ACCEPTED     recorded deliberately, not a defect

Classification is deliberately conservative: anything it cannot prove is a data problem is
reported as needing a re-score, because that is the cheap remedy and the honest default.

    python3 campaign_issues.py [--roots DIR ...]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

# Faults registered as known negatives: the metric check is EXPECTED to fail, and that is the
# finding rather than a fault to chase.
KNOWN_NEGATIVE = {"dns_delay", "anomaly_net"}   # anomaly_net on Train Ticket only


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:                                                  # noqa: BLE001
        return None


def classify(run_dir, run_id):
    """What is wrong with this run, and what would it cost to put right?"""
    gt = read_json(os.path.join(run_dir, "ground_truth.json")) or {}
    fault = gt.get("fault", {})
    verif = read_json(os.path.join(run_dir, "verification.json")) or {}
    loss = read_json(os.path.join(run_dir, "meta", "event_loss.json"))
    status = verif.get("verification_status", "n/a")
    recipe = os.path.basename(os.path.dirname(run_dir))
    issues = []

    # THE ONLY THING THAT COSTS A RUN: the injection did not happen. Ground truth is the
    # authority here - it is written by the recipe at inject time, so a zero in it means the
    # recipe found nothing to act on.
    params = fault.get("parameters", {}) or {}
    for key in ("containers", "connections_held", "target_pid"):
        if key in params and not params[key]:
            issues.append(("RE-COLLECT", f"{key}={params[key]} - nothing was injected"))

    if loss is not None and not loss.get("clean"):
        n = loss.get("discarded_events", 0)
        # Loss is recorded, not fatal: the run is usable with a stated caveat. Only flag it as
        # a re-collect if it is large enough to distort rates.
        kind = "RE-COLLECT" if n > 20_000_000 else "ACCEPTED"
        issues.append((kind, f"event loss {n:,} discarded"))

    if recipe != "normal":
        if status == "no_targets":
            issues.append(("RE-SCORE", "no verification target registered for this family"))
        elif status in ("unconfirmed", "borderline") and recipe not in KNOWN_NEGATIVE:
            issues.append(("RE-SCORE", f"verdict {status}"))
    return issues


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", nargs="*", default=[os.path.expanduser("~/traces"),
                                                  "/mnt/archive/runs"])
    args = ap.parse_args()

    buckets = collections.defaultdict(lambda: collections.defaultdict(list))
    total = seen = 0
    done = set()
    for root in args.roots:
        if not os.path.isdir(root):
            continue
        for recipe in sorted(os.listdir(root)):
            rdir = os.path.join(root, recipe)
            if not os.path.isdir(rdir):
                continue
            for run_id in sorted(os.listdir(rdir)):
                run_dir = os.path.join(rdir, run_id)
                if not os.path.isfile(os.path.join(run_dir, "meta", "runinfo_end.txt")):
                    continue
                if run_id in done:
                    continue
                done.add(run_id)
                total += 1
                for kind, why in classify(run_dir, run_id):
                    buckets[kind][why.split(" - ")[0].split(" ")[0] + "|" + recipe].append(run_id)
                    seen += 1

    print(f"{total} completed runs")
    for kind in ("RE-COLLECT", "RE-SCORE", "ACCEPTED"):
        rows = buckets.get(kind)
        if not rows:
            continue
        n = sum(len(v) for v in rows.values())
        print(f"\n{kind}  ({n} runs)")
        for key, runs in sorted(rows.items()):
            why, recipe = key.split("|", 1)
            print(f"  {recipe:26s} {len(runs):>3}  {why}")
            for r in sorted(runs)[:4]:
                print(f"      {r}")
            if len(runs) > 4:
                print(f"      ... and {len(runs) - 4} more")
    if not buckets:
        print("\nnothing wrong.")


if __name__ == "__main__":
    main()
