#!/usr/bin/env python3
"""Drive the whole question-2 matrix: one subprocess per cell, a few at a time.

Each cell is q2_run_one.py, unchanged, so a cell that is interesting can be re-run on its own
and reproduce exactly. The driver only decides WHICH cells run and how many at once, and keeps
going when one of them fails.

Parallelism is safe now that counts come from the index: a cell spends its wall clock waiting
on the API, not decoding a trace. Before the index a cell was ~500 s of babeltrace CPU and
running several at once on a shared login node would have been antisocial.

Resumable. A cell whose score.json already exists is skipped, so an interrupted matrix picks
up where it stopped instead of paying for the completed cells again.

    python q2_run_matrix.py --problem noisy_neighbor --incidents 3 --repeats 5 --jobs 4
    python q2_run_matrix.py --dry-run          # print the plan, run nothing
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import q2_harness as Q  # noqa: E402

ONE = os.path.join(HERE, "q2_run_one.py")


def cells(problem: str, incidents: int, repeats: int, asks, arms):
    for i in range(incidents):
        for ask in asks:
            for arm in arms:
                for rep in range(1, repeats + 1):
                    yield {"problem": problem, "incident": i, "ask": ask,
                           "arm": arm, "repeat": rep}


def done_path(out_dir: str, problem: str, run_id: str, ask: str, arm: str, rep: int) -> str:
    return os.path.join(Q.cell_dir(out_dir, problem, run_id, ask, arm, rep), "score.json")


def run_cell(c: dict, a, log_dir: str) -> dict:
    tag = "%s_i%d_%s_%s_r%d" % (c["problem"], c["incident"], c["ask"], c["arm"], c["repeat"])
    log = os.path.join(log_dir, tag + ".log")
    cmd = [a.python, "-u", ONE,
           "--problem", c["problem"], "--incident", str(c["incident"]),
           "--ask", c["ask"], "--arm", c["arm"], "--repeat", str(c["repeat"]),
           "--data-root", a.data_root, "--out-dir", a.out_dir,
           "--skills-dir", a.skills_dir, "--max-steps", str(a.max_steps)]
    t0 = time.time()
    with open(log, "w") as fh:
        rc = subprocess.call(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return {"tag": tag, "rc": rc, "s": round(time.time() - t0, 1), "log": log, **c}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="noisy_neighbor")
    ap.add_argument("--incidents", type=int, default=3)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--asks", default="hint,nohint")
    ap.add_argument("--arms", default="given,none")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--python", default=os.path.expanduser("~/q2venv/bin/python"))
    ap.add_argument("--data-root", default="/scratch/yuvraj17/stratatrace/dataset/runs")
    ap.add_argument("--out-dir", default="/scratch/yuvraj17/stratatrace/results/q2")
    ap.add_argument("--packs-root", default="/scratch/yuvraj17/stratatrace/data/packs")
    ap.add_argument("--skills-dir", default=os.path.join(ROOT, "blueprints", "skills-kernel-only"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-run cells that already have a score")
    a = ap.parse_args()

    asks = [x for x in a.asks.split(",") if x]
    arms = [x for x in a.arms.split(",") if x]
    incs = Q.incidents_for(a.problem, a.data_root, a.incidents)
    if len(incs) < a.incidents:
        print("WARNING: asked for %d incidents of %s, found %d"
              % (a.incidents, a.problem, len(incs)))

    todo, skipped = [], 0
    for c in cells(a.problem, min(a.incidents, len(incs)), a.repeats, asks, arms):
        rid = incs[c["incident"]]["run_id"]
        if not a.force and os.path.exists(done_path(a.out_dir, c["problem"], rid,
                                                    c["ask"], c["arm"], c["repeat"])):
            skipped += 1
            continue
        todo.append(c)

    print("matrix: %s | %d incident(s) x %d ask x %d arm x %d repeat = %d cells"
          % (a.problem, min(a.incidents, len(incs)), len(asks), len(arms), a.repeats,
             min(a.incidents, len(incs)) * len(asks) * len(arms) * a.repeats))
    print("  already scored: %d      to run: %d      at %d in parallel"
          % (skipped, len(todo), a.jobs))
    for i, c in enumerate(incs[:a.incidents]):
        print("  incident %d: %s (%s)" % (i, c["run_id"], c["app"]))
    if a.dry_run:
        for c in todo:
            print("  would run i%d %s/%s rep%d" % (c["incident"], c["ask"], c["arm"], c["repeat"]))
        return 0
    if not todo:
        print("nothing to do")
        return 0

    log_dir = os.path.join(a.out_dir, "logs", "cells")
    os.makedirs(log_dir, exist_ok=True)

    t0 = time.time()
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(run_cell, c, a, log_dir): c for c in todo}
        for n, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r["rc"] == 0:
                ok += 1
            else:
                fail += 1
            print("  [%d/%d] %-42s rc=%d  %6.1fs   (ok %d, fail %d, %.0f min elapsed)"
                  % (n, len(todo), r["tag"], r["rc"], r["s"], ok, fail,
                     (time.time() - t0) / 60), flush=True)

    print("done: %d ok, %d failed, %.1f min" % (ok, fail, (time.time() - t0) / 60))
    if fail:
        print("failed cell logs are under %s" % log_dir)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
