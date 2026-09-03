#!/usr/bin/env python3
"""Build ONE L0 evidence pack per run, shared by every method in the comparison.

Fairness rule: if the blueprint reads the raw kernel trace, every other method must be
offered the same thing. So the expensive decoding happens ONCE here, and the resulting
measurements are handed identically to:

  * the blueprint decision rules (no model involved)
  * the tool-using LLM agent
  * the model-only LLM control

Each method then differs only in what it DOES with the same evidence, which is the thing we
actually want to compare.

The pack deliberately contains measurements, not conclusions: per-process runqueue delay,
per-(process, syscall) blocking duration, and call-graph convergence. Nothing in it names a
fault or a culprit.

    python3 l0_evidence.py --run-id slow_db_aggressive_steady_r1 --app sockshop \
        --out /scratch/yuvraj17/stratatrace/data/packs/evidence_packs
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time

REPO = "/scratch/yuvraj17/stratatrace/repo"
L0ROOT = "/scratch/yuvraj17/stratatrace/data/l0"
RUNS = "/scratch/yuvraj17/stratatrace/data/agentic-runs"

RQ = f"{REPO}/blueprints/problems/cpu-contention-co-tenant/scripts/runqueue_delay.py"
BLK = f"{REPO}/blueprints/problems/db-latency-dependency-wait/scripts/blocking_syscall.py"
CONV = f"{REPO}/blueprints/problems/db-latency-dependency-wait/scripts/edge_convergence.py"


def sh(cmd):
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, round(time.time() - t0, 1), (r.stderr or "")[-400:]


def find_run_dir(app, run_id):
    for fam in os.listdir(os.path.join(RUNS, app)):
        d = os.path.join(RUNS, app, fam, run_id)
        if os.path.isdir(d):
            return d, fam
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--app", default="sockshop")
    ap.add_argument("--out", default="/scratch/yuvraj17/stratatrace/data/packs/evidence_packs")
    ap.add_argument("--comms", default="",
                    help="processes to profile for blocking duration; empty = per-app default")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--kernel-only", action="store_true",
                    help="phase-1 mode: kernel trace only. Skips call-graph convergence and "
                         "does not require an extracted working set, so a run can be judged "
                         "from its staged CTF alone. Neither blueprint's FIRE decision uses "
                         "convergence, so the verdict is unaffected.")
    a = ap.parse_args()

    # Per-app process set. Train Ticket reports EVERY Java service as `java`, so that one
    # comm covers ~39 services; the datastore is still distinguishable as `mysqld`.
    if not a.comms:
        a.comms = {"sockshop": "mysqld,app,node,java",
                   "trainticket": "mysqld,java,node,redis-server"}.get(a.app, "mysqld,java")

    run_dir, fam = find_run_dir(a.app, a.run_id)
    if not run_dir and not a.kernel_only:
        sys.exit(f"run not found: {a.run_id}")
    fam = fam or "unstaged"
    ctf = os.path.join(L0ROOT, a.app, a.run_id, "ctf")
    gt_l0 = os.path.join(L0ROOT, a.app, a.run_id, "ground_truth.json")
    gt = gt_l0 if os.path.exists(gt_l0) else os.path.join(run_dir or "", "ground_truth.json")
    if not os.path.exists(gt):
        sys.exit(f"no ground_truth.json for {a.run_id} (looked in L0 stage and run dir)")

    os.makedirs(a.out, exist_ok=True)
    pack_path = os.path.join(a.out, f"{a.run_id}.json")
    if os.path.exists(pack_path) and not a.force:
        print(f"SKIP {a.run_id} (pack exists)")
        return 0
    if not os.path.isdir(ctf):
        sys.exit(f"L0 not staged for {a.run_id}: {ctf}")

    tmp = os.path.join(a.out, "_tmp", a.run_id)
    os.makedirs(tmp, exist_ok=True)
    timing = {}

    rc, secs, err = sh([sys.executable, RQ, "--ctf", ctf, "--gt", gt,
                        "--out", f"{tmp}/rq.json"])
    timing["runqueue_delay_s"] = secs
    if rc:
        print(f"  runqueue FAILED: {err}")

    rc, secs, err = sh([sys.executable, BLK, "--ctf", ctf, "--gt", gt,
                        "--comms", a.comms, "--out", f"{tmp}/blocking.json"])
    timing["blocking_syscall_s"] = secs
    if rc:
        print(f"  blocking FAILED: {err}")

    if a.kernel_only or not run_dir:
        timing["convergence_s"] = 0.0          # phase 1: kernel trace only, no spans read
    else:
        rc, secs, err = sh([sys.executable, CONV, "--run", run_dir, "--app", a.app,
                            "--out", f"{tmp}/convergence.json"])
        timing["convergence_s"] = secs
        if rc:
            print(f"  convergence FAILED: {err}")

    def load(n):
        p = os.path.join(tmp, n)
        try:
            return json.load(open(p))
        except Exception:                                              # noqa: BLE001
            return None

    rq, blk, conv = load("rq.json"), load("blocking.json"), load("convergence.json")

    # keep only what a method could legitimately reason from - measurements, no verdicts
    def top_rq(d, k=12):
        if not d:
            return []
        rows = [r for r in d.get("comparison", []) if r.get("n_incident", 0) >= 500]
        return rows[:k]

    def top_blk(d, k=14):
        return (d or {}).get("comparison", [])[:k]

    pack = {
        "run_id": a.run_id, "app": a.app, "family_dir": fam,
        "kernel_only": bool(a.kernel_only),
        "source": ("raw LTTng kernel trace (L0) read with babeltrace2" if a.kernel_only else
                   "raw LTTng kernel trace (L0) read with babeltrace2, plus OTLP spans"),
        "timing_s": timing,
        "total_analysis_s": round(sum(timing.values()), 1),
        "runqueue_delay": {
            "what": "per-wakeup delay between becoming runnable and getting a CPU; p95 "
                    "baseline vs incident, per process",
            "top_by_inflation": top_rq(rq),
        },
        "blocking_syscall": {
            "what": "time spent inside each syscall between entry and exit; p95 baseline vs "
                    "incident, per (process, syscall)",
            "top_by_inflation": top_blk(blk),
        },
        "call_graph": {
            "what": "caller->callee p95 slowdown and where slow edges converge",
            "candidates": (conv or {}).get("candidates", [])[:8],
            "converged_on": (conv or {}).get("converged_on"),
        },
    }
    json.dump(pack, open(pack_path, "w"), indent=2)
    print(f"OK   {a.run_id}  analysis {pack['total_analysis_s']}s  -> {pack_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
