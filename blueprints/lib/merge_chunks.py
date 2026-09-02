#!/usr/bin/env python3
"""Merge per-family evaluate.py chunk files into one results file.

Agent runs have to be chunked (one fresh python per family) because the login node's watchdog
kills long cumulative processes - see RESULTS-agent-sanitygate.md. That leaves one JSON per
family; the scorer wants one JSON per arm.

    python3 merge_chunks.py --glob 'dir/without_ss/*.json' --out dir/without_ss.json
"""
from __future__ import annotations
import argparse, glob, json, os, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    files = sorted(f for f in glob.glob(a.glob) if not f.endswith(os.path.basename(a.out)))
    results, metas, bad = [], [], []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception as e:                                             # noqa: BLE001
            bad.append(f"{os.path.basename(f)}: {e}")
            continue
        rs = d.get("results") or []
        if not rs:
            bad.append(f"{os.path.basename(f)}: no results")
            continue
        results += rs
        metas.append(d.get("meta"))

    # a chunk whose every run timed out is not a result, it is a failed chunk. Say so loudly
    # rather than letting zeros average into the headline.
    dead = sum(1 for r in results if r.get("error"))
    seen, uniq = set(), []
    for r in results:                                       # resume can re-run a chunk
        k = (r.get("run_id"), r.get("condition"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"meta": {"merged_from": len(metas), "chunks": [os.path.basename(f) for f in files],
                        "n_incidents": len(uniq), "n_errored": dead, "bad_chunks": bad},
               "results": uniq}, open(a.out, "w"), indent=2, default=str)
    print(f"{os.path.basename(a.out)}: {len(uniq)} incidents from {len(metas)} chunks"
          + (f", {dead} errored" if dead else "")
          + (f", {len(bad)} bad chunks" if bad else ""))
    for b in bad:
        print(f"  BAD {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
