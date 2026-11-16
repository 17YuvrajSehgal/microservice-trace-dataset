#!/usr/bin/env python3
"""
loop_block.py - does one thread compute for a long time without ever entering the kernel?

Usage:
    python3 loop_block.py <slice.txt> <secs> --baseline <base.txt> <secs> [--top N]

Input:
    Slices made by extract_slice.sh with the events 'sched_switch|syscall_entry_'.

What it measures, per thread:
    A healthy request-serving thread (an event loop, a worker) alternates: a little CPU, then a
    system call (read, write, epoll_wait, futex). The CPU time between two system calls is a
    SYSCALL-FREE RUN. It is normally well under a millisecond.
    A thread that is stuck computing - a synchronous hash, a busy wait, a tight loop - stays on
    a CPU for tens or hundreds of milliseconds with no system call at all. Being switched out
    and back in (preemption) does not end a run; a system call or going to sleep does.

    cpu%        share of the slice the thread was on a CPU
    sys/s       system calls per second
    long%       share of the slice spent in runs of at least LONG_MS (default 20 ms)
    p50 / max   median and longest such run, in ms
    base ...    the same thread (same tid) in the baseline slice

Verdict:
    BLOCKED LOOP  a thread spends >= SHARE_MIN of the slice in long runs, AND the same thread
                  in the baseline spent almost none there and made >= DROP_MIN times more
                  system calls per second. It was serving requests; now it only computes.
    A thread that computes without system calls but has no baseline (a new process) or was the
    same in the baseline is a CPU-bound job, not a blocked service loop: reported as a NOTE.

Self-test:  python3 loop_block.py --selftest
"""
import re
import sys
from collections import defaultdict

LONG_MS = 20.0      # a syscall-free run this long is "long"
SHARE_MIN = 0.40    # verdict: this share of the slice in long runs
BASE_MAX = 0.05     # ... and at most this share in the baseline
DROP_MIN = 3.0      # ... and system calls per second fell at least this many times.
                    # Was 5: code_serial_awaits falls only 5-7x, so one run passed by a hair.
                    # None of the 47 quiet runs depends on this bar (they fail on the two above).
SHAPE_MS = 60.0     # median long run: above = one long computation, below = short repeats.
                    # Set between the two labelled families (107 ms and 33 ms medians); it
                    # reflects those two injected defects, not a law. Report the numbers.

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_ctx = re.compile(r'\bpid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_ns = re.compile(r'\bpid_ns = (\d+)')
re_sw = re.compile(r'prev_tid = (\d+), prev_prio = -?\d+, prev_state = (?:\([^()]*?container = )?(\d+)'
                   r'\s*\)?, next_comm = "[^"]*", next_tid = (\d+)')


def analyse(path):
    """tid -> {comm, pid, ns, cpu (ns on CPU), nsys, runs: [ns of each closed syscall-free run]}"""
    th = defaultdict(lambda: {"comm": "?", "pid": 0, "ns": "?", "cpu": 0, "nsys": 0, "runs": [],
                              "cur": 0})
    on = {}                                    # cpu -> [tid, since]
    last = 0

    def charge(cpu, t):
        cur = on.get(cpu)
        if cur and cur[0]:
            d = t - cur[1]
            if d > 0:
                th[cur[0]]["cpu"] += d
                th[cur[0]]["cur"] += d
            cur[1] = t

    def close(tid):
        r = th[tid]
        if r["cur"] > 0:
            r["runs"].append(r["cur"])
        r["cur"] = 0

    with open(path, errors="replace") as fh:
        for line in fh:
            m = re_time.match(line)
            c = re_cpu.search(line)
            if not m or not c:
                continue
            h, mi, s, frac = m.groups()
            t = (int(h) * 3600 + int(mi) * 60 + int(s)) * 1_000_000_000 + int(frac.ljust(9, "0")[:9])
            if t < last - 43_200_000_000_000:  # the slice crossed midnight
                t += 86_400_000_000_000
            last = max(last, t)
            cpu = int(c.group(1))
            ctx = re_ctx.search(line)
            if ctx:
                tid = int(ctx.group(2))
                if tid:
                    r = th[tid]
                    r["comm"], r["pid"] = ctx.group(3), int(ctx.group(1))
                    n = re_ns.search(line)
                    if n:
                        r["ns"] = n.group(1)
                    if cpu not in on:          # first event on this CPU: its thread starts now
                        on[cpu] = [tid, t]
            if " sched_switch: " in line:
                sw = re_sw.search(line)
                if not sw:
                    continue
                prev, state, nxt = int(sw.group(1)), int(sw.group(2)), int(sw.group(3))
                if cpu in on and on[cpu][0] != prev:
                    on[cpu] = [prev, on[cpu][1]]
                charge(cpu, t)
                if prev and state & 0xff:      # went to sleep: the run is over. 0 / 256 = still
                    close(prev)                # runnable, only preempted - the run goes on
                on[cpu] = [nxt, t]
            elif " syscall_entry_" in line and ctx:
                tid = int(ctx.group(2))
                if cpu in on and on[cpu][0] != tid:
                    on[cpu] = [tid, t]
                charge(cpu, t)
                close(tid)
                th[tid]["nsys"] += 1
    for cpu in on:
        charge(cpu, last)
    for tid in list(th):
        close(tid)
    return th


def stats(r, secs):
    longs = sorted(x for x in r["runs"] if x >= LONG_MS * 1e6)
    return {"cpu": r["cpu"] / (secs * 1e9), "sys": r["nsys"] / secs,
            "long": sum(longs) / (secs * 1e9),
            "p50": longs[len(longs) // 2] / 1e6 if longs else 0.0,
            "max": max(r["runs"]) / 1e6 if r["runs"] else 0.0, "n": len(longs)}


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    path, secs = a[0], float(a[1])
    top = int(a[a.index("--top") + 1]) if "--top" in a else 10
    base = bsecs = None
    if "--baseline" in a:
        i = a.index("--baseline")
        base, bsecs = analyse(a[i + 1]), float(a[i + 2])
    th = analyse(path)
    rows = sorted(((stats(r, secs), tid, r) for tid, r in th.items() if tid),
                  key=lambda x: -x[0]["long"])

    print("syscall-free CPU runs per thread  (slice %.0f s; long = a run of >= %.0f ms)" % (secs, LONG_MS))
    print("%12s %-16s %8s %6s %8s %6s %7s %8s | %6s %8s %6s" % (
        "ns", "comm", "tid", "cpu%", "sys/s", "long%", "p50ms", "maxms", "b.cpu%", "b.sys/s", "b.long%"))
    for st, tid, r in rows[:top]:
        b = stats(base[tid], bsecs) if base is not None and tid in base else None
        print("%12s %-16s %8d %6.1f %8.0f %6.1f %7.1f %8.1f | %s" % (
            r["ns"], r["comm"][:16], tid, st["cpu"] * 100, st["sys"], st["long"] * 100, st["p50"],
            st["max"], "%6.1f %8.0f %6.1f" % (b["cpu"] * 100, b["sys"], b["long"] * 100) if b
            else "   (not in baseline)"))
    print()

    if not rows or rows[0][0]["long"] < SHARE_MIN:
        st, tid, r = rows[0] if rows else ({"long": 0, "max": 0}, 0, {"comm": "-", "ns": "-"})
        print("NO BLOCKED LOOP: the thread with the most syscall-free CPU is %s tid %d (ns %s): "
              "%.0f%% of the slice in runs >= %.0f ms, longest %.0f ms (bar: >= %.0f%%)"
              % (r["comm"], tid, r["ns"], st["long"] * 100, LONG_MS, st["max"], SHARE_MIN * 100))
        return
    if base is None:
        st, tid, r = rows[0]
        print("NOTE: no --baseline given; %s tid %d (ns %s) spends %.0f%% of the slice in syscall-free "
              "runs. That alone does not tell a blocked service loop from a CPU-bound job: cut a "
              "quiet slice before the change and run again." % (r["comm"], tid, r["ns"], st["long"] * 100))
        return
    notes = []
    for st, tid, r in rows:
        if st["long"] < SHARE_MIN:
            break
        who = "%s tid %d pid %d (ns %s)" % (r["comm"], tid, r["pid"], r["ns"])
        if tid not in base:
            notes.append("%s computes without system calls (%.0f%% of the slice) but did not exist "
                         "in the baseline: a new CPU-bound process, not a blocked service loop"
                         % (who, st["long"] * 100))
            continue
        b = stats(base[tid], bsecs)
        drop = b["sys"] / st["sys"] if st["sys"] > 0 else float("inf")
        if b["long"] <= BASE_MAX and drop >= DROP_MIN:
            print("VERDICT: BLOCKED LOOP: %s spends %.0f%% of the slice computing in %d runs of "
                  ">= %.0f ms with no system call (median %.0f ms, longest %.0f ms); in the baseline "
                  "the same thread spent %.1f%% there. Its system calls fell from %.0f/s to %.0f/s "
                  "(%.0fx) while its CPU use went from %.0f%% to %.0f%%. It was serving requests; "
                  "now it only computes, so everything that waits on this thread stalls."
                  % (who, st["long"] * 100, st["n"], LONG_MS, st["p50"], st["max"], b["long"] * 100,
                     b["sys"], st["sys"], drop, b["cpu"] * 100, st["cpu"] * 100))
            print("SHAPE: %.0f long runs per second, median %.0f ms -> %s" % (
                st["n"] / secs, st["p50"],
                "one long synchronous computation per request (event_loop_block)"
                if st["p50"] >= SHAPE_MS else
                "short equal busy stretches repeated per request (serial_work)"))
            return
        notes.append("%s computes without system calls (%.0f%% of the slice) but did the same in "
                     "the baseline (%.0f%%, system calls %.0f/s -> %.0f/s): a CPU-bound job, not a "
                     "change" % (who, st["long"] * 100, b["long"] * 100, b["sys"], st["sys"]))
    for n in notes[:3]:
        print("NOTE: " + n)
    print("NO BLOCKED LOOP: no thread that served system calls in the baseline has stopped doing so "
          "(bar: >= %.0f%% of the slice in runs >= %.0f ms, <= %.0f%% in the baseline, system calls "
          "down >= %.0fx)" % (SHARE_MIN * 100, LONG_MS, BASE_MAX * 100, DROP_MIN))


def _selftest():
    import os
    import tempfile
    ctx = '{ cpu_id = %d }, { pid = %d, tid = %d, procname = "%s", pid_ns = %s }'

    def ts(ns):
        return "[10:00:%02d.%09d]" % (ns // 1_000_000_000, ns % 1_000_000_000)

    def sysc(ns, cpu, tid, comm, pns):
        return "%s (+0.1) h syscall_entry_read: %s, { fd = 3 }" % (ts(ns), ctx % (cpu, tid, tid, comm, pns))

    def sw(ns, cpu, prev, comm, pns, state, nxt):
        return ('%s (+0.1) h sched_switch: %s, { prev_comm = "%s", prev_tid = %d, prev_prio = 20, '
                'prev_state = %d, next_comm = "x", next_tid = %d, next_prio = 20 }'
                % (ts(ns), ctx % (cpu, prev, prev, comm, pns), comm, prev, state, nxt))

    ms = 1_000_000
    base, fault = [], []
    for i in range(1000):                       # healthy loop: a syscall every ms, 2 s
        base.append(sysc(i * 2 * ms, 0, 7, "node", "77"))
    for i in range(10):                         # blocked: 200 ms of CPU per syscall, preempted once
        t0 = i * 200 * ms
        fault.append(sysc(t0, 0, 7, "node", "77"))
        fault.append(sw(t0 + 90 * ms, 0, 7, "node", "77", 0, 99))       # preempted, still runnable
        fault.append(sw(t0 + 100 * ms, 0, 99, "x", "1", 1, 7))          # back on after 10 ms
    fault.append(sysc(2000 * ms, 0, 7, "node", "77"))
    for i in range(20):                         # a burner that never existed before
        fault.append(sw(i * 100 * ms + 1, 1, 0, "swapper", "1", 0, 55) if i == 0 else
                     sw(i * 100 * ms, 1, 55, "stress", "88", 0, 55))
    fault.append(sw(2000 * ms, 1, 55, "stress", "88", 0, 0))
    paths = []
    for lines in (base, fault):
        fd, p = tempfile.mkstemp(suffix=".txt")
        os.write(fd, ("\n".join(sorted(lines)) + "\n").encode())
        os.close(fd)
        paths.append(p)
    try:
        b, f = analyse(paths[0]), analyse(paths[1])
        sb, sf = stats(b[7], 2), stats(f[7], 2)
        assert sb["long"] == 0 and sb["sys"] == 500, sb
        assert sf["n"] == 10 and abs(sf["p50"] - 190) < 1 and sf["long"] > 0.9, sf   # 200 - 10 preempted
        assert stats(f[55], 2)["long"] > 0.9 and 55 not in b
    finally:
        for p in paths:
            os.unlink(p)
    print("loop_block selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
