#!/usr/bin/env python3
"""One full decode of a run's kernel trace -> a small count table the agent can actually read.

WHY THIS EXISTS
---------------
Measured on noisy_neighbor_aggressive_steady_r1, babeltrace2 does not seek. `--begin/--end`
decodes from the start of the trace and discards what falls outside:

    1 s range   3 s into the trace  ->  1,220,291 events   9.6 s
    1 s range 213 s into the trace  ->      14,317 events 133.3 s

So the cost of a query tracks how deep the range sits, not how much comes back, and the scan
cap that keeps a single call bounded was buying the agent 0.3 s of a 20 s window - 1.6%. It
then compared two 0.3 s slices as though they were the 20 s windows it asked for. That is not
a coverage inconvenience; the conclusions drawn from it are not about the data.

A whole pass costs about the same as the deepest single query (~140 s here). Fourteen partial
queries in the last pilot cost 524 s. So one pass, cached, is both cheaper AND complete.

WHAT IT DOES AND DOES NOT CONTAIN
---------------------------------
Counts. `bucket_start_s, event, procname, count` at a fixed bucket width. Nothing else.

It does NOT read ground_truth.json - the rule at the top of ctf_tool.py applies here too. It
holds no notion of a baseline window, an incident window, a fault, or a culprit. It cannot,
because it is built before anyone asks a question of it, and identically for every run. An
engineer opening this trace in Trace Compass gets the same histogram for free.

What is lost: per-event fields (prev_state, latency between wakeup and switch, byte counts).
Those still come from the raw trace through query_ctf's sample path, over a narrow range.

    python build_ctf_index.py RUN_DIR [RUN_DIR ...] --out-root /path/to/ctf-index
"""
from __future__ import annotations

import argparse
import gzip
import os
import re
import subprocess
import sys
import time

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/stratatrace/tools/bt21.sh")
GMT = ["--clock-gmt"]

_TIME_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d+)\]")
_EVENT_RE = re.compile(r"\]\s+(?:\(\+[^)]*\)\s+)?\S+\s+([a-zA-Z0-9_]+):")
_PROC_RE = re.compile(r'procname\s*=\s*"([^"]*)"')

BUCKET_MS = 100

SCHEMA = "# bucket_start_s\tevent\tprocname\tcount\n"


def build(run_dir: str, out_path: str, ctf_subdir: str = "kernel/kernel",
          bucket_ms: int = BUCKET_MS, verbose: bool = True) -> dict:
    """Stream one decode into a bucketed count table.

    Streamed, not accumulated. babeltrace emits in time order, so a bucket is finished the
    moment the clock crosses into the next one - flush it and drop it. Holding every
    (bucket, event, procname) key in memory would be tens of millions of entries on a trace
    this dense; this way the footprint is one bucket.
    """
    ctf = os.path.join(run_dir, ctf_subdir)
    if not os.path.isdir(ctf):
        return {"error": "no CTF at %s" % ctf}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    bw = bucket_ms / 1000.0
    t0 = time.time()
    n_lines = n_rows = 0
    cur_bucket = None
    cur: dict[tuple[str, str], int] = {}
    first_t = last_t = None
    events: set[str] = set()
    procs: set[str] = set()

    tmp = out_path + ".partial"
    p = subprocess.Popen([BT2] + GMT + [ctf], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, bufsize=1 << 22)
    with gzip.open(tmp, "wt", compresslevel=6) as out:
        out.write(SCHEMA)
        with p:
            for line in p.stdout:
                n_lines += 1
                tm = _TIME_RE.match(line)
                if not tm:
                    continue
                t = (int(tm.group(1)) * 3600 + int(tm.group(2)) * 60 + int(tm.group(3))
                     + float("0." + tm.group(4)))
                if first_t is None:
                    first_t = t
                last_t = t
                b = int(t / bw)
                if cur_bucket is not None and b != cur_bucket:
                    n_rows += _flush(out, cur_bucket * bw, cur)
                    cur = {}
                cur_bucket = b
                em = _EVENT_RE.search(line)
                if not em:
                    continue
                ev = em.group(1)
                pm = _PROC_RE.search(line)
                proc = pm.group(1) if pm else "?"
                events.add(ev)
                procs.add(proc)
                k = (ev, proc)
                cur[k] = cur.get(k, 0) + 1
                if verbose and n_lines % 5_000_000 == 0:
                    print("    %d M events, t=%.1fs, %.0fs elapsed"
                          % (n_lines // 1_000_000, t - (first_t or t), time.time() - t0),
                          flush=True)
        if cur_bucket is not None:
            n_rows += _flush(out, cur_bucket * bw, cur)

    rc = p.returncode
    if rc not in (0, None) and n_lines == 0:
        os.unlink(tmp)
        return {"error": "babeltrace2 exited %s with no output" % rc}
    os.replace(tmp, out_path)
    return {
        "run_dir": run_dir,
        "index": out_path,
        "events_decoded": n_lines,
        "rows": n_rows,
        "bucket_ms": bucket_ms,
        "trace_begin": first_t,
        "trace_end": last_t,
        "n_event_types": len(events),
        "n_procnames": len(procs),
        "build_s": round(time.time() - t0, 1),
        "size_bytes": os.path.getsize(out_path),
    }


def _flush(out, bucket_start: float, counts: dict) -> int:
    for (ev, proc), n in counts.items():
        out.write("%.3f\t%s\t%s\t%d\n" % (bucket_start, ev, proc, n))
    return len(counts)


def index_path(out_root: str, run_dir: str) -> str:
    run_id = os.path.basename(run_dir.rstrip("/"))
    return os.path.join(out_root, run_id + ".tsv.gz")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--out-root", default="/scratch/yuvraj17/stratatrace/data/ctf-index")
    ap.add_argument("--bucket-ms", type=int, default=BUCKET_MS)
    ap.add_argument("--force", action="store_true", help="rebuild even if the index exists")
    a = ap.parse_args()

    rc = 0
    for rd in a.run_dirs:
        op = index_path(a.out_root, rd)
        if os.path.exists(op) and not a.force:
            print("SKIP %s (index exists, %d bytes)" % (os.path.basename(op),
                                                        os.path.getsize(op)), flush=True)
            continue
        print("BUILD %s" % rd, flush=True)
        r = build(rd, op)
        if "error" in r:
            print("  FAILED: %s" % r["error"], flush=True)
            rc = 1
            continue
        print("  %d events -> %d rows, %.1f MB, %s event types, %s procnames, %.0fs"
              % (r["events_decoded"], r["rows"], r["size_bytes"] / 1e6,
                 r["n_event_types"], r["n_procnames"], r["build_s"]), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
