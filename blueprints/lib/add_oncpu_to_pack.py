#!/usr/bin/env python3
"""Measure on-CPU attribution for a run and merge it into that run's evidence pack.

The packs built before finding F3 carry runqueue delay, syscall blocking and call-graph
convergence, but not on-CPU attribution - which is now the deciding evidence for the whole
CPU family. Re-decoding a 20 GB trace for the other three measurements would be wasteful, so
this adds the missing one in place.

Idempotent: skips a run whose pack already has an `oncpu` section unless --force.

    python3 add_oncpu_to_pack.py --run-id <id> --app <app> --pack-dir <dir>
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time

REPO = "/scratch/yuvraj17/stratatrace/repo"
L0ROOT = "/scratch/yuvraj17/stratatrace/data/l0"
ONCPU = f"{REPO}/blueprints/problems/cpu-contention-co-tenant/scripts/oncpu_share.py"
SYNTH = f"{REPO}/blueprints/lib/synthesize_gt.py"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--app", default="sockshop")
    ap.add_argument("--pack-dir", required=True)
    ap.add_argument("--cache", default="/scratch/yuvraj17/stratatrace/results/cpucluster/oncpu",
                    help="reuse a measurement already made for this run")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    pack_path = os.path.join(a.pack_dir, f"{a.run_id}.json")
    if not os.path.exists(pack_path):
        sys.exit(f"no pack for {a.run_id} in {a.pack_dir}")
    pack = json.load(open(pack_path, encoding="utf-8"))
    if pack.get("oncpu") and not a.force:
        print(f"SKIP {a.run_id} (pack already has on-CPU evidence)")
        return 0

    l0 = os.path.join(L0ROOT, a.app, a.run_id)
    ctf, gt = os.path.join(l0, "ctf"), os.path.join(l0, "ground_truth.json")
    if not os.path.isdir(ctf):
        sys.exit(f"L0 not staged for {a.run_id}: {ctf}")

    os.makedirs(a.cache, exist_ok=True)
    cached = os.path.join(a.cache, f"{a.run_id}.json")

    t0 = time.time()
    if not os.path.exists(cached) or a.force:
        if not os.path.exists(gt):
            subprocess.run([sys.executable, SYNTH, "--ctf", ctf, "--out", gt],
                           capture_output=True, text=True)
        r = subprocess.run([sys.executable, ONCPU, "--ctf", ctf, "--gt", gt, "--out", cached],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"on-CPU measurement failed for {a.run_id}: {(r.stderr or '')[-300:]}")
    else:
        print(f"  reusing cached measurement for {a.run_id}")
    secs = round(time.time() - t0, 1)

    d = json.load(open(cached, encoding="utf-8"))
    # Keep measurements, not conclusions - same rule as the rest of the pack. The top movers
    # are enough for any method to reason from; the full per-process table stays on disk.
    pack["oncpu"] = {
        "what": "on-CPU time per process from sched_switch, baseline window vs incident window: "
                "host utilisation, and the cores each process gained or lost",
        "signature": d.get("signature", {}),
        "top_gainers": d.get("cores_delta", [])[:8],
        "top_losers": sorted(d.get("cores_delta", []),
                             key=lambda r: r.get("cores_gained", 0))[:8],
    }
    pack.setdefault("timing_s", {})["oncpu_share_s"] = secs
    pack["total_analysis_s"] = round(sum(pack["timing_s"].values()), 1)

    json.dump(pack, open(pack_path, "w"), indent=2)
    s = pack["oncpu"]["signature"]
    print(f"OK   {a.run_id:44s} util {s.get('host_util_baseline')}->{s.get('host_util_incident')} "
          f"thief={s.get('thief_comm')} +{s.get('thief_cores_gained')} ({secs}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
