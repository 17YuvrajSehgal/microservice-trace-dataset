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
Counts. `bucket_start_s, event, procname, pid_ns, count` at a fixed bucket width.
Nothing else. pid_ns is the container: one number per container, and it is the only thing in
a kernel trace that tells `java` in one container from `java` in another.

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
# Every event carries the namespaces of the task that produced it. pid_ns is one
# number per container, so it is what tells `java` in carts from `java` in orders -
# measured on svc_cpu_cap r1, `java` appears under FOUR distinct pid_ns values. The
# first index kept only procname and threw this away, and the agent could then do
# nothing but answer "host" for every per-service fault.
_PIDNS_RE = re.compile(r'pid_ns\s*=\s*(\d+)')

BUCKET_MS = 100

# Raw lines are kept up to this many characters. It was 400, which silently cut the field that
# mattered: measured over 400k decoded events, net_if_receive_skb / net_dev_queue / net_if_rx
# average 913 chars and carry `transport_header = { source_port, dest_port, seq, ack_seq }`
# starting around char 660 - so the TCP sequence numbers, the one thing that identifies a
# retransmission, were past the cut on every single line. sched_switch (mean 407, max 440) lost
# its tail too. 1200 carries every event type measured except a rare epoll_pwait variant whose
# tail is a long event array, and costs about 25% more bytes before gzip.
LINE_CAP = 1200

TAB = chr(9)
SCHEMA = TAB.join(["# bucket_start_s", "event", "procname", "pid_ns", "count",
                   "value_sum"]) + chr(10)

# A COUNT IS NOT A QUANTITY, and for three of our fault families the quantity is the answer.
#
# svc_cpu_cap caps a container's CPU. What identifies it is CPU TIME CONSUMED, which lives in
# sched_stat_runtime's `runtime` field in nanoseconds. Counting sched_stat_runtime events
# instead measures how often the scheduler accounted, not how much CPU was used - a throttled
# container can be accounted just as often while getting far less time. The same argument
# applies to bytes on the wire and sectors to disk.
#
# These cannot be recovered from the line sample either: it keeps ONE line per (bucket, event),
# so summing `runtime` from it would sum one arbitrary task per 100 ms. The sum has to happen
# here, during the single decode that already reads every event.
#
# Everything else gets 0 - the column is only meaningful where a payload is worth adding up.
_VALUE_FIELD = {
    "sched_stat_runtime": "runtime",     # nanoseconds of CPU actually consumed
    "net_dev_xmit": "len",               # bytes out
    "net_if_receive_skb": "len",         # bytes in
    "block_rq_issue": "nr_sector",       # sectors requested
    "block_rq_complete": "nr_sector",    # sectors completed
}
_VALUE_RE = {ev: re.compile(f + r"\s*=\s*(\d+)") for ev, f in _VALUE_FIELD.items()}


def build(run_dir: str, out_path: str, ctf_subdir: str = "kernel/kernel",
          bucket_ms: int = BUCKET_MS, verbose: bool = True,
          lines_path: str | None = None) -> dict:
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
    cur: dict[tuple[str, str, str], int] = {}
    first_t = last_t = None
    events: set[str] = set()
    procs: set[str] = set()
    nss: set[str] = set()

    # Optional second output: ONE raw line per (bucket, event). Measured on 22-09, ctf_lines
    # was 80% of an agent run's wall clock - 56-90 s a call - because babeltrace cannot seek and
    # re-decodes the whole trace from the start to reach a range. This pass already decodes
    # every event once, so keeping a line costs nothing extra here and makes that tool a file
    # read.
    #
    # It is a DIFFERENT sample, and that has to be said rather than hidden: ctf_lines returns
    # the first n matching lines in a range, which can all land inside a few milliseconds.
    # Served from this file it returns one line per bucket, spread across the range.
    tmp = out_path + ".partial"
    lines_fh = None
    lines_seen: set = set()
    n_lines_kept = 0
    if lines_path:
        os.makedirs(os.path.dirname(lines_path) or ".", exist_ok=True)
        lines_fh = gzip.open(lines_path + ".partial", "wt", compresslevel=6)
        lines_fh.write(TAB.join(["# bucket_start_s", "event", "procname", "pid_ns",
                                 "raw_line"]) + chr(10))
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
                    lines_seen.clear()      # one line per event PER BUCKET
                cur_bucket = b
                em = _EVENT_RE.search(line)
                if not em:
                    continue
                ev = em.group(1)
                pm = _PROC_RE.search(line)
                proc = pm.group(1) if pm else "?"
                nm = _PIDNS_RE.search(line)
                ns = nm.group(1) if nm else "0"
                events.add(ev)
                procs.add(proc)
                nss.add(ns)
                k = (ev, proc, ns)
                if lines_fh is not None:
                    lk = (cur_bucket, ev)
                    if lk not in lines_seen:
                        lines_seen.add(lk)
                        lines_fh.write(TAB.join([
                            "%.3f" % (cur_bucket * bw), ev, proc, ns,
                            line.rstrip()[:LINE_CAP].replace(TAB, " ")]) + chr(10))
                        n_lines_kept += 1
                v = 0
                vre = _VALUE_RE.get(ev)
                if vre is not None:
                    vm = vre.search(line)
                    if vm:
                        v = int(vm.group(1))
                c0, v0 = cur.get(k, (0, 0))
                cur[k] = (c0 + 1, v0 + v)
                if verbose and n_lines % 5_000_000 == 0:
                    print("    %d M events, t=%.1fs, %.0fs elapsed"
                          % (n_lines // 1_000_000, t - (first_t or t), time.time() - t0),
                          flush=True)
        if cur_bucket is not None:
            n_rows += _flush(out, cur_bucket * bw, cur)

    if lines_fh is not None:
        lines_fh.close()
        os.replace(lines_path + ".partial", lines_path)

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
        "n_pid_ns": len(nss),
        "build_s": round(time.time() - t0, 1),
        "size_bytes": os.path.getsize(out_path),
        "lines_kept": n_lines_kept,
        "lines_path": lines_path if lines_path else None,
        "lines_bytes": os.path.getsize(lines_path) if lines_path and
        os.path.exists(lines_path) else 0,
    }


def _flush(out, bucket_start: float, counts: dict) -> int:
    for (ev, proc, ns), (n, v) in counts.items():
        out.write(TAB.join(["%.3f" % bucket_start, ev, proc, ns, str(n), str(v)]) + chr(10))
    return len(counts)


def index_path(out_root: str, run_dir: str) -> str:
    run_id = os.path.basename(run_dir.rstrip("/"))
    return os.path.join(out_root, run_id + ".tsv.gz")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--out-root", default="/scratch/yuvraj17/stratatrace/dataset/index")
    ap.add_argument("--bucket-ms", type=int, default=BUCKET_MS)
    ap.add_argument("--force", action="store_true", help="rebuild even if the index exists")
    ap.add_argument("--with-lines", action="store_true",
                    help="also keep one raw event line per (bucket, event), so ctf_lines reads "
                         "a file instead of re-decoding the trace. Off by default: it changes "
                         "WHICH lines that tool returns, and a live experiment must not have "
                         "its tools altered underneath it.")
    a = ap.parse_args()

    rc = 0
    for rd in a.run_dirs:
        op = index_path(a.out_root, rd)
        if os.path.exists(op) and not a.force:
            print("SKIP %s (index exists, %d bytes)" % (os.path.basename(op),
                                                        os.path.getsize(op)), flush=True)
            continue
        print("BUILD %s" % rd, flush=True)
        lp = (os.path.join(a.out_root, os.path.basename(rd.rstrip("/")) + ".lines.gz")
              if a.with_lines else None)
        r = build(rd, op, lines_path=lp)
        if "error" in r:
            print("  FAILED: %s" % r["error"], flush=True)
            rc = 1
            continue
        print("  %d events -> %d rows, %.1f MB, %s event types, %s procnames, %.0fs"
              % (r["events_decoded"], r["rows"], r["size_bytes"] / 1e6,
                 r["n_event_types"], r["n_procnames"], r["build_s"]), flush=True)
        print("     %d pid namespaces (containers)" % r.get("n_pid_ns", 0), flush=True)
        if r.get("lines_path"):
            print("     %d raw lines kept, %.1f MB"
                  % (r["lines_kept"], r["lines_bytes"] / 1e6), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
