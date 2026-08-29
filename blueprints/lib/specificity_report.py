#!/usr/bin/env python3
"""Turn E1 verdicts into a specificity matrix and a threshold-margin table.

Two questions, and the second matters as much as the first:

  1. Does a blueprint stay quiet on families that are not its problem?
  2. By how much? A family that declines at 4.9x against a 5x threshold is not safe,
     it is lucky. Margins are what tell us whether a threshold survives new data.

Every run carries a ground-truth family. `noisy_neighbor` is the cpu-contention blueprint's
target and `slow_db` is the datastore blueprint's; everything else, including `normal`, is
a negative for both.

    python3 specificity_report.py --verdicts <dir> --tasks <task_file> --out specificity.json
"""
from __future__ import annotations
import argparse, collections, json, os, sys

TARGET_OF = {"noisy_neighbor": "cpu-contention", "slow_db": "datastore-wait"}
# thresholds the rules use, repeated here only to report distance from them
RQ_X, BLOCK_X = 2.0, 5.0


def load_tasks(path):
    fam = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 3:
            fam[parts[2]] = (parts[0], parts[1])
    return fam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", default="specificity.json")
    a = ap.parse_args()

    truth = load_tasks(a.tasks)
    rows = []
    for run_id, (app, fam) in sorted(truth.items()):
        p = os.path.join(a.verdicts, f"{run_id}.json")
        if not os.path.exists(p):
            continue
        v = json.load(open(p, encoding="utf-8"))
        cpu, db = v.get("cpu_contention", {}), v.get("datastore_wait", {})
        expected = TARGET_OF.get(fam)                       # None = should stay quiet
        selected = v.get("selected")
        if expected is None:
            outcome = "correct_decline" if selected is None else "FALSE_FIRE"
        elif selected == expected:
            outcome = "correct_fire"
        elif selected is None:
            outcome = "missed"
        else:
            outcome = "WRONG_BLUEPRINT"
        rows.append({
            "run_id": run_id, "app": app, "truth_family": fam,
            "expected": expected, "selected": selected,
            "fired": v.get("blueprints_fired", []),
            "outcome": outcome,
            # the measured numbers, so thresholds can be revisited without decoding again
            "max_runqueue_x": cpu.get("max_runqueue_x"),
            "median_runqueue_x": cpu.get("median_runqueue_x"),
            "n_processes_inflated": cpu.get("n_processes_inflated"),
            "max_socket_wait_x": cpu.get("max_socket_wait_x"),
            "max_any_syscall_x": cpu.get("max_any_syscall_x"),
            "db_blocking_x": db.get("blocking_x"),
            "db_blocked_process": db.get("blocked_process"),
            "db_blocking_call": db.get("blocking_call"),
            "analysis_seconds": v.get("analysis_seconds"),
        })

    # ---- specificity matrix ----
    by_fam = collections.defaultdict(list)
    for r in rows:
        by_fam[(r["app"], r["truth_family"])].append(r)

    print(f"\n{'app':12s} {'truth family':20s} {'n':>3s}  "
          f"{'quiet':>5s} {'cpu':>4s} {'db':>4s}  outcome")
    print("-" * 78)
    matrix = []
    for (app, fam), rs in sorted(by_fam.items()):
        quiet = sum(1 for r in rs if not r["selected"])
        c = sum(1 for r in rs if r["selected"] == "cpu-contention")
        d = sum(1 for r in rs if r["selected"] == "datastore-wait")
        bad = [r["outcome"] for r in rs if r["outcome"] in ("FALSE_FIRE", "WRONG_BLUEPRINT")]
        note = f"{len(bad)} bad" if bad else ("target" if fam in TARGET_OF else "clean")
        matrix.append({"app": app, "family": fam, "n": len(rs), "quiet": quiet,
                       "fired_cpu": c, "fired_db": d, "bad": len(bad)})
        print(f"{app:12s} {fam:20s} {len(rs):3d}  {quiet:5d} {c:4d} {d:4d}  {note}")

    neg = [r for r in rows if r["expected"] is None]
    pos = [r for r in rows if r["expected"] is not None]
    false_fires = [r for r in neg if r["outcome"] == "FALSE_FIRE"]

    print(f"\nnegatives: {len(neg)} runs, {len(false_fires)} false fires "
          f"({100 * len(false_fires) / len(neg):.0f}%)" if neg else "\nnegatives: none")
    if pos:
        ok = sum(1 for r in pos if r["outcome"] == "correct_fire")
        print(f"positives: {len(pos)} runs, {ok} correct fires")

    # ---- threshold margins on the negative class ----
    if neg:
        print(f"\nhow close the negatives came to firing "
              f"(runqueue threshold {RQ_X}x, socket-block threshold {BLOCK_X}x):")
        print(f"  {'run':44s} {'rq_max':>7s} {'n_infl':>6s} {'sock':>7s}")
        for r in sorted(neg, key=lambda r: -(r["max_runqueue_x"] or 0))[:20]:
            print(f"  {r['run_id']:44s} {str(r['max_runqueue_x']):>7s} "
                  f"{str(r['n_processes_inflated']):>6s} {str(r['max_socket_wait_x']):>7s}")

    out = {"rows": rows, "matrix": matrix,
           "n_negative": len(neg), "n_false_fire": len(false_fires),
           "n_positive": len(pos),
           "thresholds": {"runqueue_x": RQ_X, "socket_block_x": BLOCK_X}}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
