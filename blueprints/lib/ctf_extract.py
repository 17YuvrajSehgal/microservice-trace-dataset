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
    """One decode, fanned out to one (grep | zstd) pipeline per family.

    Uses explicit FIFOs and `wait` rather than `tee >(...)` process substitution. That is not
    style: **bash does not wait for process substitutions to finish.** With `tee >(a) >(b)`
    the shell returns as soon as tee exits, so the caller renames .part into place while grep
    and zstd are still flushing, and the cache silently ends up TRUNCATED. That produced a
    complete-looking cache whose results disagreed with the per-script path.

    TZ=UTC is equally non-optional: babeltrace prints AND interprets --begin/--end in the
    local zone, while the collector wrote these traces in UTC. Without it a 22:43:58 UTC
    window is read as 22:43:58 EDT, lands outside the trace, and every family file comes out
    as a valid but EMPTY 13-byte zstd frame.
    """
    lines = ["set -uo pipefail",
             'FIFO=$(mktemp -d)',
             'trap \'rm -rf "$FIFO"\' EXIT',
             "pids=()"]
    fifos = []
    for fam in families:
        path = cache_path(fam, begin, end, out_dir)
        f = f'"$FIFO"/{fam}'
        fifos.append(f)
        lines.append(f"mkfifo {f}")
        lines.append(f"( grep -E {shlex.quote(FAMILIES[fam])} < {f} "
                     f"| zstd -1 -q -T4 -o {shlex.quote(path + '.part')} ) & pids+=($!)")
    lines.append(f"TZ=UTC {shlex.quote(BT2)} {shlex.quote(ctf)} "
                 f"--begin {begin} --end {end} 2>/dev/null "
                 f"| tee {' '.join(fifos)} > /dev/null")
    lines.append("rc=$?")
    # the point of the whole exercise: do not return until every writer has finished
    lines.append('for p in "${pids[@]}"; do wait "$p" || rc=1; done')
    lines.append("exit $rc")
    return "\n".join(lines)


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
        # An empty zstd frame is 13 bytes and is perfectly valid, so a cache built against the
        # wrong timezone or a window outside the trace looks FINE and yields nothing - the
        # scripts then "succeed" in 0.08 s with empty results. Check before publishing.
        # A single empty family can be real (a run with no disk I/O has no block_rq_* events),
        # but ALL of them empty means the window never matched.
        sizes = {f: os.path.getsize(cache_path(f, b, e, a.out) + ".part")
                 for f in want if os.path.exists(cache_path(f, b, e, a.out) + ".part")}
        if sizes and max(sizes.values()) < 1024:
            print(f"  REFUSING to publish: every family is empty {sizes}.\n"
                  f"  The window {b}->{e} matched no events. Almost always a timezone "
                  f"mismatch - the traces are UTC and babeltrace reads --begin/--end in the "
                  f"local zone.")
            return 1
        for f, n in sorted(sizes.items()):
            if n < 1024:
                print(f"  note: {f} family is empty ({n} B) - real for some runs, "
                      f"but check if you expected events")

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
