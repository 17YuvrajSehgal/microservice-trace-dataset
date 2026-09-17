#!/usr/bin/env python3
"""Re-score a run from its archived metric sidecar, with no live Prometheus.

WHY THIS EXISTS
---------------
verify_injection.py queries Prometheus. The collection VM is deleted, so for anything already
collected there is no Prometheus to query - but every run bundle ships `<run>_metrics/*.json.gz`,
the same series the verdict was computed from. This re-scores from those.

It was written for one concrete job: `fd_exhaustion` carried a target that measured an artifact.
`container_file_descriptors{name=~".*front-end_1$"}` looks like one series and is eleven, because
cAdvisor mints a new series on every container restart (they differ only in
`container_label_restartcount`). Summing them gave injection 446 against baseline 98, a
`decrease` target failed, and five perfectly good runs read `unconfirmed`.

What the fault does is restart-loop the front-end. So the thing to count is RESTART GENERATIONS
THAT BEGIN INSIDE THE INJECTION WINDOW.

    python3 rescore_from_sidecar.py --work <dir> --family fd_exhaustion

MEASURED 2026-09-16 over the five re-collected runs:

    fd_exhaustion     9, 9, 9, 9, 9 new generations in injection
    lock_contention   0, 0, 0, 0, 0   (restartcount frozen at 76 - the control)
    dns_delay         9, 0, 8, 0, 0   (not unique to fd_exhaustion, still decisive for it)

Do NOT score this against the baseline. The loop outlives the injection because of Docker's
restart backoff, so each run's baseline inherits the previous run's tail (1, 6, 7, 11, 12 across
the five). A baseline-relative ratio measures the last run, not this one.
"""
from __future__ import annotations

import argparse
import calendar
import gzip
import json
import os
import time

# One restart is a blip; two inside a 120 s window is a loop. The measured separation is wide
# (9 against 0), so the exact cut does not matter - it only has to sit between them.
MIN_NEW_GENERATIONS = 2
SERIES_METRIC = "container_file_descriptors"
GENERATION_LABEL = "container_label_restartcount"


def _ts(s: str) -> int:
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def generations(sidecar_dir: str, name_suffix: str) -> dict:
    """First-sample time per restart generation of the matching container."""
    path = os.path.join(sidecar_dir, SERIES_METRIC + ".json.gz")
    if not os.path.exists(path):
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    out = {}
    for entry in doc.get("data", {}).get("result", []):
        labels = entry.get("metric", {})
        if not labels.get("name", "").endswith(name_suffix):
            continue
        stamps = [int(t) for t, _ in entry.get("values", [])]
        if stamps:
            out[labels.get(GENERATION_LABEL)] = min(stamps)
    return out


def score_run(run_dir: str, sidecar_dir: str, name_suffix: str = "front-end_1") -> dict:
    ground = json.load(open(os.path.join(run_dir, "ground_truth.json")))["fault"]
    start, end = _ts(ground["injection_start_utc"]), _ts(ground["injection_end_utc"])
    gens = generations(sidecar_dir, name_suffix)
    new_in_injection = sum(1 for first in gens.values() if start <= first <= end)
    # Recorded, never scored on - see the module docstring.
    inherited = sum(1 for first in gens.values() if first < start)
    nums = sorted(int(g) for g in gens if str(g).isdigit())
    passed = new_in_injection >= MIN_NEW_GENERATIONS
    return {
        "run": os.path.basename(run_dir.rstrip("/")),
        "new_generations_in_injection": new_in_injection,
        "generations_inherited_from_previous_run": inherited,
        "restartcount_range": [nums[0], nums[-1]] if nums else None,
        "threshold": MIN_NEW_GENERATIONS,
        "passed": bool(passed),
        "verification_status": "confirmed" if passed else "unconfirmed",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="dir holding <family>/<run>/ and <run>_metrics/")
    ap.add_argument("--family", required=True)
    ap.add_argument("--suffix", default="front-end_1")
    ap.add_argument("--out")
    args = ap.parse_args()

    base = os.path.join(args.work, args.family)
    runs = sorted(d for d in os.listdir(base)
                  if not d.endswith("_metrics") and os.path.isdir(os.path.join(base, d)))
    rows = []
    for run in runs:
        sidecar = os.path.join(base, run + "_metrics")
        if not os.path.isdir(sidecar):
            continue
        rows.append(score_run(os.path.join(base, run), sidecar, args.suffix))

    print("%-44s %6s %10s %12s  %s" % ("run", "new", "inherited", "restartcount", "verdict"))
    print("-" * 92)
    for r in rows:
        rng = r["restartcount_range"]
        print("%-44s %6d %10d %12s  %s" % (
            r["run"][:44], r["new_generations_in_injection"],
            r["generations_inherited_from_previous_run"],
            "%s->%s" % (rng[0], rng[1]) if rng else "?", r["verification_status"]))
    ok = sum(1 for r in rows if r["passed"])
    print("\n  %d of %d confirmed (threshold: >= %d new generations inside the injection window)"
          % (ok, len(rows), MIN_NEW_GENERATIONS))
    if args.out:
        json.dump(rows, open(args.out, "w"), indent=1)
        print("  wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
