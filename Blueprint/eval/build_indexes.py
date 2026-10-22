#!/usr/bin/env python3
"""Build a count index for every run under a runs-root that has a CTF trace.

Run this inside WSL (it needs babeltrace2):

    BT2=babeltrace2 python3 build_indexes.py <runs_root> <index_root> [--with-lines]

For each <run>/trace/kernel (the CTF dir holding `metadata`) it writes
<index_root>/<run_basename>.tsv.gz (+ .lines.gz). Skips a run whose index already exists, so
it is resumable. The run basename is the id the evaluator and ctf_tool key on, so it must be
unique within one index root — scope each agent/experiment to its own root if basenames clash.
"""
from __future__ import annotations
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_ctf_index as B


def find_runs(runs_root):
    for dirpath, dirnames, filenames in os.walk(runs_root):
        if dirpath.endswith(os.path.join("trace", "kernel")) and "metadata" in filenames:
            run = os.path.dirname(os.path.dirname(dirpath))   # <run>/trace/kernel -> <run>
            yield os.path.basename(run), dirpath


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs_root")
    ap.add_argument("index_root")
    ap.add_argument("--with-lines", action="store_true", default=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.index_root, exist_ok=True)

    runs = sorted(find_runs(a.runs_root))
    print("found %d runs with a CTF under %s" % (len(runs), a.runs_root), flush=True)
    built = skipped = failed = 0
    for i, (rid, ctf) in enumerate(runs, 1):
        out = os.path.join(a.index_root, rid + ".tsv.gz")
        if os.path.exists(out) and not a.force:
            skipped += 1
            continue
        lines = os.path.join(a.index_root, rid + ".lines.gz") if a.with_lines else None
        r = B.build(ctf, out, ctf_subdir="", lines_path=lines)
        if isinstance(r, dict) and r.get("error"):
            print("  [%d/%d] %-34s FAILED %s" % (i, len(runs), rid, r["error"]), flush=True)
            failed += 1
        else:
            print("  [%d/%d] %-34s %s rows, %s events" % (
                i, len(runs), rid, r.get("rows"), r.get("events_decoded")), flush=True)
            built += 1
    print("built %d, skipped %d (existing), failed %d" % (built, skipped, failed), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
