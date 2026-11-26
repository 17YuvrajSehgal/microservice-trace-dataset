"""Build the call graph of one or more runs from their request traces.

    python -m spankit.build <run_dir> [<run_dir> ...] --out-dir DIR [--force]

Writes <run_id>.callgraph.json. Never writes into a run directory; skips a run whose graph
exists unless --force, so a sweep can be resumed. A run without otlp/spans.jsonl still gets a
graph, with no edges and `source: null`, so "no traces" is never read as "no calls".
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from spankit.graph import build_graph, write_graph


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m spankit.build", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="run directories")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    failed = 0
    for run in a.runs:
        run_dir = Path(run).resolve()
        out = Path(a.out_dir) / f"{run_dir.name}.callgraph.json"
        if run_dir in out.resolve().parents:
            print(f"error: refusing to write inside the run directory: {out}", file=sys.stderr)
            return 2
        if out.exists() and not a.force:
            print(f"skip {run_dir.name}: {out} exists")
            continue
        t = time.time()
        try:
            g = build_graph(run_dir)
        except OSError as e:
            print(f"FAILED {run_dir.name}: {e}", file=sys.stderr)
            failed += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        write_graph(g, out)
        print(f"built {run_dir.name}: {len(g['services'])} services, {len(g['edges'])} edges, "
              f"{g['read']['spans']} spans, {g['read']['bad_lines']} bad lines, "
              f"{time.time() - t:.1f} s")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
