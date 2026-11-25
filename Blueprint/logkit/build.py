"""Build the log index of one or more runs.

    python -m logkit.build <run_dir> [<run_dir> ...] --out-dir DIR [--profile docker_compose]
    python -m logkit.build <run_dir> --out FILE

Writes <run_id>.logidx.json.gz. It never writes into a run directory. A run whose index
already exists is skipped unless --force, so a sweep can be resumed.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from logkit.index import build_index, write_index
from logkit.profile import ProfileError, load_profile


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m logkit.build", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="run directories")
    ap.add_argument("--profile", default="docker_compose", help="profile id or path")
    dest = ap.add_mutually_exclusive_group(required=True)
    dest.add_argument("--out", help="output file (one run only)")
    dest.add_argument("--out-dir", help="output folder; one <run_id>.logidx.json.gz per run")
    ap.add_argument("--force", action="store_true", help="rebuild an existing index")
    a = ap.parse_args(argv)
    if a.out and len(a.runs) > 1:
        ap.error("--out takes one run; use --out-dir for several")
    try:
        profile = load_profile(a.profile)
    except ProfileError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    failed = 0
    for run in a.runs:
        run_dir = Path(run).resolve()
        out = Path(a.out) if a.out else Path(a.out_dir) / f"{run_dir.name}.logidx.json.gz"
        if run_dir in out.resolve().parents:
            print(f"error: refusing to write inside the run directory: {out}", file=sys.stderr)
            return 2
        if out.exists() and not a.force:
            print(f"skip {run_dir.name}: {out} exists")
            continue
        t = time.time()
        try:
            idx = build_index(run_dir, profile)
        except (OSError, ProfileError) as e:
            print(f"FAILED {run_dir.name}: {e}", file=sys.stderr)
            failed += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        write_index(idx, out)
        lines = sum(e["lines"] for e in idx["entities"].values())
        print(f"built {run_dir.name}: {len(idx['entities'])} entities, {lines} lines, "
              f"{time.time() - t:.1f} s -> {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
