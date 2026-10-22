#!/usr/bin/env python3
"""Where the 5 blueprints live, and how to find the runs that match a problem.

Blueprints are the Blueprint/latency folders. A run "matches" a problem when its ground truth
says so (score.load_truth), which works across both dataset shapes without hard-coding paths.
A run is only runnable when its index (<run_id>.tsv.gz) exists under the given index root.
"""
from __future__ import annotations
import os

import score as S

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BP_ROOT = os.path.join(ROOT, "Blueprint", "latency")

# problem -> blueprint folder under Blueprint/latency
BLUEPRINTS = {
    "svc_cpu_cap":    "1_svc_cpu_cap",
    "noisy_neighbor": "2_noisy_neighbor",
    "slow_db":        "3_slow_db",
    "svc_mem_cap":    "4_svc_mem_cap",
    "svc_net":        "5_svc_net",
    # agentic experiments map onto the same blueprints
    "io_cap":         None,          # no blueprint yet
    "threads":        None,          # no blueprint yet
}


def blueprint_path(problem: str):
    folder = BLUEPRINTS.get(problem)
    if not folder:
        return None
    md = os.path.join(BP_ROOT, folder, "README_v1.md")
    return md if os.path.exists(md) else None


def has_index(run_dir: str, index_root: str) -> bool:
    rid = os.path.basename(run_dir.rstrip("/\\"))
    return os.path.exists(os.path.join(index_root, rid + ".tsv.gz"))


def iter_run_dirs(runs_root: str):
    """Every directory under runs_root that carries ground truth (either dataset shape)."""
    for dirpath, dirnames, filenames in os.walk(runs_root):
        if "ground_truth.json" in filenames or \
           os.path.exists(os.path.join(dirpath, "meta", "ground_truth.json")):
            yield dirpath
            dirnames[:] = []          # a run dir has no nested runs


def discover(problem: str, runs_root: str, index_root: str, include_controls=True):
    """Run dirs that match `problem` by ground truth AND have an index to read. Sorted."""
    out = []
    for rd in iter_run_dirs(runs_root):
        truth = S.load_truth(rd)
        if truth["family"] != problem:
            continue
        if not include_controls and truth["present"] is False:
            continue
        if has_index(rd, index_root):
            out.append(rd)
    return sorted(out)


if __name__ == "__main__":
    import sys
    prob = sys.argv[1] if len(sys.argv) > 1 else "svc_cpu_cap"
    print("blueprint for %s: %s" % (prob, blueprint_path(prob)))
    if len(sys.argv) > 3:
        runs = discover(prob, sys.argv[2], sys.argv[3])
        print("%d runnable runs under %s" % (len(runs), sys.argv[2]))
        for r in runs[:10]:
            print("  ", r)
