#!/usr/bin/env python3
"""Re-score finished cells from what they already saved, without re-running the agent.

WHY THIS EXISTS, given we normally prefer re-running. A re-run costs about five hours and five
dollars per matrix, and it would change nothing: the agent's answer is already on disk in
`diagnosis.json` and ground truth in `ground_truth.json`. What was wrong was the SCORER, not the
run. The deadlock matrix scored its first ten cells before `nsmap.ns_for_workload` existed, so
every correct answer there reads `container_unverified`. Re-scoring makes all sixty consistent;
re-running would only burn the budget to reach the same answers.

It never touches the agent, never calls a model, and reads only files the run already wrote.

    python q2_rescore_where.py <results-dir> [--data-root ...] [--dry-run]

Writes score.json in place and prints what changed. `--dry-run` prints and writes nothing.
"""
from __future__ import annotations
import argparse
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import q2_judge as J                                                    # noqa: E402
import q2_run_one as R                                                  # noqa: E402

DATA_ROOT = "/scratch/yuvraj17/stratatrace/data/stratatrace-v2"


def run_dir_for(run_id: str, problem: str, data_root: str) -> str:
    """Where the trace for this cell lives. Needed because nsmap reads the cgroup snapshots."""
    app = "trainticket" if run_id.startswith("tt_") else "sockshop"
    # the family directory is the run_id minus its `_<intensity>_<pattern>_r<N>` suffix, but the
    # problem name is the family for every problem we run except svc_net, so try both
    for fam in (problem, run_id.split("_aggressive")[0].split("_subtle")[0]):
        d = os.path.join(data_root, app, fam, run_id)
        if os.path.isdir(d):
            return d
    return ""


def resolve_ns(run_dir: str, gt: dict):
    """Exactly what q2_run_one does, kept in one place so the two cannot drift apart."""
    try:
        import nsmap
        ns = nsmap.ns_for_service(run_dir, (gt.get("fault") or {}).get("target_service", "")) or ""
        via = "service" if ns else ""
        tsvc = ((gt.get("fault") or {}).get("target_service") or "").strip().lower()
        if not ns and tsvc in ("", "host"):
            ns = nsmap.ns_for_workload(run_dir, gt) or ""
            via = "workload" if ns else "unresolved"
        return ns, via
    except Exception:                                                   # noqa: BLE001
        return "", "error"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--data-root", default=DATA_ROOT)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cells = sorted(glob.glob(os.path.join(a.results, "*", "*", "*", "*", "*", "score.json")))
    if not cells:
        print("no score.json under %s" % a.results)
        return 1

    changed = unchanged = skipped = 0
    moves = {}
    for sp in cells:
        d = os.path.dirname(sp)
        try:
            sc = json.load(io.open(sp, encoding="utf-8"))
            dx = json.load(io.open(os.path.join(d, "diagnosis.json"), encoding="utf-8"))
            gt = json.load(io.open(os.path.join(d, "ground_truth.json"), encoding="utf-8"))
        except Exception as e:                                          # noqa: BLE001
            print("skip %s (%s)" % (d, e))
            skipped += 1
            continue

        rd = run_dir_for(sc.get("run_id") or "", sc.get("problem") or "", a.data_root)
        if not rd:
            print("skip %s (no run dir for %s)" % (d, sc.get("run_id")))
            skipped += 1
            continue

        ns, via = resolve_ns(rd, gt)
        f = gt.get("fault") or {}
        jd = J.judge(dx.get("diagnosis") or {}, dx.get("trajectory"), sc.get("problem") or "",
                     true_service=f.get("target_service", ""), scope=f.get("scope", ""),
                     true_ns=ns)
        # the window scoring is unchanged, so carry it rather than recomputing and risking drift
        before = (sc.get("where"), sc.get("container_correct"))
        sc["where"] = jd.get("where")
        sc["container_correct"] = jd.get("container_correct")
        sc["true_ns"], sc["true_ns_via"] = ns, via
        after = (sc["where"], sc["container_correct"])

        if before != after:
            changed += 1
            moves["%s -> %s" % (before[0], after[0])] = moves.get(
                "%s -> %s" % (before[0], after[0]), 0) + 1
        else:
            unchanged += 1
        if not a.dry_run:
            json.dump(sc, io.open(sp, "w", encoding="utf-8"), indent=1)

    print("%d cells: %d changed, %d unchanged, %d skipped%s"
          % (len(cells), changed, unchanged, skipped, "  (dry run)" if a.dry_run else ""))
    for k, v in sorted(moves.items(), key=lambda kv: -kv[1]):
        print("   %-46s %d" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
