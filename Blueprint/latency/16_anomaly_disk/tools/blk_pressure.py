#!/usr/bin/env python3
"""
blk_pressure.py - who is using the disk, how slow did it get, and who is stuck waiting for it?

Usage:
    python3 blk_pressure.py <slice.txt> <secs> [--baseline <base.txt> <base_secs>] [--top 8]

Input:
    Slices cut with extract_slice.sh and the pattern
      'block_rq_issue|block_rq_complete|sched_switch'
    Works with or without the pid_ns context.

What it measures:
    per issuer (pid_ns, comm of the block_rq_issue): requests/s, MB/s, and the latency of its
    requests (issue -> complete, matched on dev + sector);
    per thread comm: time in D state (switched out with prev_state = 2, uninterruptible, until
    switched back in) - the time processes spent waiting for the disk.
    Kernel helpers (kworker, jbd2, ksoftirqd) and the tracer (lttng-*) are shown but never named
    the culprit: they write on behalf of others.

Verdict:
    VERDICT: DISK HOG: <comm> (ns N) issued P% of block requests (R req/s, B MB/s; baseline r/s);
             D-state of that process D s/s; other writers' latency p50 a ms -> b ms; newly in
             D state: ...
        - top user-space issuer >= 50% of USER-SPACE requests (kernel writeback and the tracer
          are left out of the total), >= 200 requests/s, >= 10x its baseline rate (or absent before)
    NO DISK PRESSURE (top user-space issuer ...)
"""
import re
import sys
from collections import Counter, defaultdict

SHARE_MIN = 0.5
REQ_MIN = 200.0       # requests/s: measured, a Prometheus compaction (25/s) passed the share bar alone; the hog ran 1,800-2,200/s
RATIO_MIN = 10.0
KERNEL = ("kworker", "jbd2", "ksoftirqd", "lttng", "kswapd", "migration")

re_ts = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ev = re.compile(r'\] \(\+[^)]*\) \S+ (block_rq_issue|block_rq_complete|sched_switch):')
re_ns = re.compile(r'\bpid_ns = (\d+)')
re_proc = re.compile(r'procname = "([^"]*)"')
re_dev = re.compile(r'\bdev = (\d+)')
re_sec = re.compile(r'\bsector = (\d+)')
re_bytes = re.compile(r'\bbytes = (\d+)')
re_sw = re.compile(r'prev_comm = "([^"]*)", prev_tid = (\d+), prev_prio = -?\d+, prev_state = (\d+), '
                   r'next_comm = "([^"]*)", next_tid = (\d+)')


def ts(line):
    h, mi, s, f = re_ts.match(line).groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(f.ljust(9, "0")) / 1e9


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


def analyse(path):
    reqs, nbytes, lat = Counter(), Counter(), defaultdict(list)
    pending, d_in, d_time = {}, {}, Counter()
    with open(path, errors="replace") as f:
        for line in f:
            m = re_ev.search(line)
            if not m:
                continue
            ev = m.group(1)
            t = ts(line)
            if ev == "sched_switch":
                s = re_sw.search(line)
                if not s:
                    continue
                pcomm, ptid, pstate, ncomm, ntid = s.groups()
                if pstate == "2":
                    d_in[ptid] = (t, pcomm)
                if ntid in d_in:
                    t0, c = d_in.pop(ntid)
                    d_time[c] += t - t0
                continue
            dv, sc = re_dev.search(line), re_sec.search(line)
            key = (dv.group(1) if dv else "?", sc.group(1) if sc else "?")
            if ev == "block_rq_issue":
                nm, pr, b = re_ns.search(line), re_proc.search(line), re_bytes.search(line)
                who = (nm.group(1) if nm else "-", pr.group(1) if pr else "?")
                reqs[who] += 1
                nbytes[who] += int(b.group(1)) if b else 0
                pending[key] = (t, who)
            elif key in pending:
                t0, who = pending.pop(key)
                lat[who].append((t - t0) * 1000)
    return reqs, nbytes, lat, d_time


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    path, secs = a[0], float(a[1])
    top = int(a[a.index("--top") + 1]) if "--top" in a else 8
    base = None
    if "--baseline" in a:
        i = a.index("--baseline")
        base = (analyse(a[i + 1]), float(a[i + 2]))
    reqs, nbytes, lat, d_time = analyse(path)
    breqs, _, blat, bd = base[0] if base else (Counter(), None, defaultdict(list), Counter())
    bsecs = base[1] if base else 1.0
    total = sum(reqs.values()) or 1

    print("block requests per issuer (slice %.0f s)" % secs)
    print("%12s %-18s %9s %8s %8s %8s %9s %9s" % ("ns", "comm", "req/s", "share", "MB/s", "base/s", "lat_p50", "lat_p99"))
    for who, n in reqs.most_common(top):
        print("%12s %-18s %9.1f %7.0f%% %8.1f %8.1f %9.1f %9.1f" % (
            who[0], who[1][:18], n / secs, 100 * n / total, nbytes[who] / secs / 1e6, breqs.get(who, 0) / bsecs,
            pct(lat[who], .5), pct(lat[who], .99)))
    print()
    print("time in D state (waiting on I/O), seconds per second of slice:")
    for c, d in d_time.most_common(top):
        print("   %-20s %6.2f   (baseline %.2f)" % (c[:20], d / secs, bd.get(c, 0) / bsecs))
    print()

    user = [w for w in reqs if not w[1].startswith(KERNEL)]
    if not user:
        print("NO DISK PRESSURE (no user-space process issued block requests)")
        return
    w = max(user, key=lambda w: reqs[w])
    utotal = sum(reqs[u] for u in user)       # share among user-space issuers: the tracer and kernel writeback do not dilute it
    share, rate, brate = reqs[w] / utotal, reqs[w] / secs, breqs.get(w, 0) / bsecs
    others = [x for who, xs in lat.items() if who != w for x in xs]
    bothers = [x for who, xs in blat.items() if who != w for x in xs]
    newly_d = [c for c, d in d_time.most_common(12) if not c.startswith(KERNEL) and c != w[1]
               and d / secs >= 0.05 and d / secs >= 3 * bd.get(c, 0) / bsecs][:5]
    detail = ("%s (ns %s) issued %.0f%% of user-space block requests (%.0f req/s, %.1f MB/s; baseline %.1f req/s); its D-state "
              "%.2f s/s; other issuers' latency p50 %s ms -> %.1f ms%s"
              % (w[1], w[0], 100 * share, rate, nbytes[w] / secs / 1e6, brate, d_time.get(w[1], 0) / secs,
                 "%.1f" % pct(bothers, .5) if bothers else "?", pct(others, .5),
                 "; newly in D state: %s" % ", ".join(newly_d) if newly_d else ""))
    if base is None:
        print("NOTE: no --baseline given; top user-space issuer %s. Cut a quiet slice and run again." % detail)
    elif share >= SHARE_MIN and rate >= REQ_MIN and (brate == 0 or rate / brate >= RATIO_MIN):
        print("VERDICT: DISK HOG: %s. One process floods the disk; everyone else's I/O waits behind it." % detail)
    else:
        print("NO DISK PRESSURE (top user-space issuer %s; bar: >= %.0f%% of user-space requests, >= %.0f req/s "
              "and >= %.0fx baseline)" % (detail, 100 * SHARE_MIN, REQ_MIN, RATIO_MIN))


def _selftest():
    import os
    import tempfile
    L = []
    ctx = '{ cpu_id = 1 }, { pid = 5, tid = %d, procname = "%s", pid_ns = %s }'
    for i in range(100):
        t = "[10:00:00.%09d] (+0.1) h" % (i * 1000000)
        t2 = "[10:00:00.%09d] (+0.1) h" % (i * 1000000 + 500000)
        L.append('%s block_rq_issue: %s, { dev = 8, sector = %d, nr_sector = 8, bytes = 65536, tid = 7, rwbs = 1, comm = "hog" }' % (t, ctx % (7, "hog", "99"), i))
        L.append('%s block_rq_complete: %s, { dev = 8, sector = %d, nr_sector = 8, error = 0, rwbs = 1 }' % (t2, ctx % (3, "x", "1"), i))
    L.append('[10:00:00.100000000] (+0.1) h sched_switch: { cpu_id = 1 }, { }, { prev_comm = "db", prev_tid = 40, prev_prio = 20, prev_state = 2, next_comm = "swapper", next_tid = 0, next_prio = 20 }')
    L.append('[10:00:00.400000000] (+0.1) h sched_switch: { cpu_id = 1 }, { }, { prev_comm = "swapper", prev_tid = 0, prev_prio = 20, prev_state = 0, next_comm = "db", next_tid = 40, next_prio = 20 }')
    fd, p = tempfile.mkstemp(suffix=".txt")
    os.write(fd, ("\n".join(L) + "\n").encode())
    os.close(fd)
    try:
        reqs, nbytes, lat, d = analyse(p)
        assert reqs[("99", "hog")] == 100 and abs(pct(lat[("99", "hog")], .5) - 0.5) < 1e-6
        assert abs(d["db"] - 0.3) < 1e-6
    finally:
        os.unlink(p)
    print("blk_pressure selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
