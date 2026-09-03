#!/usr/bin/env python3
"""Decode a kernel trace ONCE and split it into the event families our scripts read.

WHY
---
Measured on a real StrataTrace L0 trace (14 GB decompressed, 258M events):

    full pass, decode + format text      361 s
    full pass, decode ONLY (-o dummy)    101 s     <- text formatting is 72% of the cost
    one 60 s window                      111 s

A full blueprint battery runs seven scripts over two windows each: 14 decodes of one file,
~26 min per run, nearly all of it re-decoding. This replaces that with 2 decodes - one per
window - fanned out to per-family files that every script then reads.

The fan-out runs in `tee` + `grep` + `zstd`, i.e. in C on separate cores, so it rides along
with the decode instead of adding to it.

WHAT IT DOES NOT DO
-------------------
It does not change any script's filtering. Each family file is a SUPERSET (all `sched_*`, all
`net_*`, ...) and every script still applies its own grep on top, so it sees exactly the lines
it saw before. That is what makes the speedup verifiable by diffing output JSON rather than
by trusting it.

    python3 ctf_extract.py --ctf <trace> --gt <ground_truth> --out <cache dir>
    CTF_CACHE_DIR=<cache dir> python3 oncpu_share.py --ctf <trace> ...   # now reads the cache
"""
from __future__ import annotations
import argparse, json, os, shlex, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ctf_stream import BT2, FAMILIES, cache_path, windows          # noqa: E402


def fanout_cmd(ctf, begin, end, out_dir, families):
    """One decode, tee'd into one (grep | zstd) pipeline per family."""
    subs = []
    for fam in families:
        path = cache_path(fam, begin, end, out_dir)
        subs.append(f">(grep -E {shlex.quote(FAMILIES[fam])} "
                    f"| zstd -1 -q -T4 -o {shlex.quote(path + '.part')})")
    return (f"{shlex.quote(BT2)} {shlex.quote(ctf)} "
            f"--begin {begin} --end {end} 2>/dev/null | tee {' '.join(subs)} > /dev/null")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", required=True, help="cache dir; pass it back as CTF_CACHE_DIR")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    ap.add_argument("--families", default=",".join(FAMILIES),
                    help="comma list; drop the ones no blueprint in this run needs")
    ap.add_argument("--force", action="store_true", help="rebuild even if files exist")
    a = ap.parse_args()

    fams = [f for f in a.families.split(",") if f]
    bad = [f for f in fams if f not in FAMILIES]
    if bad:
        print(f"unknown families: {bad}; known: {list(FAMILIES)}")
        return 2

    t0 = json.load(open(a.gt))["fault"]["injection_start_utc"].split("T")[1].rstrip("Z")
    wins = windows(t0, a.baseline_s, a.incident_s)
    os.makedirs(a.out, exist_ok=True)

    total = time.time()
    for name, (b, e) in wins.items():
        want = [f for f in fams
                if a.force or not os.path.exists(cache_path(f, b, e, a.out))]
        if not want:
            print(f"{name:9s} {b}->{e}  cached, skipping")
            continue
        print(f"{name:9s} {b}->{e}  extracting {','.join(want)} ...", flush=True)
        t = time.time()
        r = subprocess.run(["bash", "-c", fanout_cmd(a.ctf, b, e, a.out, want)])
        if r.returncode != 0:
            print(f"  FAILED (exit {r.returncode}) - leaving .part files, cache not published")
            return 1
        # publish atomically, so an interrupted extract never looks like a complete cache
        for f in want:
            p = cache_path(f, b, e, a.out)
            if os.path.exists(p + ".part"):
                os.replace(p + ".part", p)
        print(f"  {time.time() - t:.0f}s", flush=True)

    print(f"\ncache: {a.out}")
    grand = 0
    for name, (b, e) in wins.items():
        for f in fams:
            p = cache_path(f, b, e, a.out)
            if os.path.exists(p):
                mb = os.path.getsize(p) / 1e6
                grand += mb
                print(f"  {name:9s} {f:8s} {mb:9.1f} MB")
    print(f"  {'total':19s} {grand:9.1f} MB   in {time.time() - total:.0f}s")
    print(f"\nnow run the scripts with:  CTF_CACHE_DIR={a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
