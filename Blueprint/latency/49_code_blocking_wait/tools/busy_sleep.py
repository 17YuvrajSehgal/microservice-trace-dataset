#!/usr/bin/env python3
# busy_sleep.py - find a busy thread that keeps stopping for a fixed time while it has work.
#
# A thread that does all the work of a service (the event loop of a Node service, or the one
# worker of a small pool) is on the CPU most of the time, and when it sleeps it sleeps for well
# under a millisecond: it only waits for the next event. If the code makes a blocking call on
# that thread (a sleep, a wait on a lock or on another thread, a synchronous read), the thread
# is off the CPU for the length of that call and everything queued behind it waits too. The CPU
# is free meanwhile, so nothing looks busy.
#
# For each thread that is on the CPU at least MIN_BUSY of the slice:
#   sleeps    times it left the CPU to sleep (not: was pushed off by another thread)
#   long      sleeps of LONG_MS or more, and their median length
#   lost      time spent in the long sleeps
#
# Usage:
#   python3 busy_sleep.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 busy_sleep.py --selftest
#
#   both slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'sched_switch'
import re
import sys
from collections import defaultdict

MIN_BUSY = 0.5         # the thread is on the CPU at least this share of the slice
LONG_MS = 15.0         # a long sleep
MIN_LONG = 2.0         # long sleeps per second by that thread
MAX_BASE = 0.1         # ... and the same thread has at most this share of them in the baseline
FIXED = 1.5            # the sleeps have one length when the 90th percentile is at most this times the 10th
# The bars were set on run 1 of code_blocking_wait (27-11-2026): the front-end's main thread was
# on the CPU 84-95% of every slice looked at, had 0 sleeps of 15 ms or more in the baseline and
# under three other faults, and 39 of 25-40 ms in 10 s under this one. Runs 2-5 were not seen first.
# CHANGED AFTER THE 50-RUN TEST (27-11-2026): the verdict is now given only for sleeps of ONE FIXED
# LENGTH. A MongoDB connection thread (conn34, conn57, conn66) was on the CPU 50-56% of some healthy
# slices and slept 42-53 times for 18 to 182 ms: it works on a slow query and then waits for the next
# one. From the scheduler alone, waiting for work and a blocking call of varying length look the same,
# so sleeps of mixed length are listed without a verdict. The first version fired on two healthy
# baselines because of this. A blocking call whose length varies is therefore not confirmed here.

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'\{ pid = (\d+), tid = (\d+), procname = "([^"]*)".*?pid_ns = (\d+)')
re_sw = re.compile(r'prev_tid = (\d+), prev_prio = -?\d+, prev_state = (\d+), next_comm = "[^"]*", next_tid = (\d+)')


def tsec(line):
    m = re_time.match(line)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1e9 if m else None


def read(lines):
    on_at, out_at = {}, {}
    oncpu = defaultdict(float)
    sleeps = defaultdict(list)
    info = {}
    for line in lines:
        if ' sched_switch:' not in line:
            continue
        t, c, s = tsec(line), re_ctx.search(line), re_sw.search(line)
        if t is None or not c or not s:
            continue
        tid, nxt = s.group(1), s.group(3)
        if tid != "0":
            info.setdefault(tid, (c.group(3), c.group(1), c.group(4)))
            if tid in on_at:
                oncpu[tid] += t - on_at.pop(tid)
            if s.group(2) != "0":                # it went to sleep; 0 = still runnable, pushed off the CPU
                out_at[tid] = t
        if nxt != "0":
            on_at[nxt] = t
            if nxt in out_at:
                sleeps[nxt].append(t - out_at.pop(nxt))
    return oncpu, sleeps, info


def pct(x, p):
    x = sorted(x)
    return x[min(len(x) - 1, int(p * len(x)))] if x else 0.0


def report(base, fault, secs):
    boncpu, bsleeps, _ = base
    oncpu, sleeps, info = fault
    lim = LONG_MS / 1e3
    busy = sorted((t for t in oncpu if oncpu[t] >= MIN_BUSY * secs), key=lambda t: -len([v for v in sleeps[t] if v >= lim]))
    out = [f"Threads on the CPU at least {MIN_BUSY:.0%} of this {secs:.0f} s slice, and their sleeps (most long sleeps first)",
           f"  {'tid':>8} {'program':<16} {'pid_ns':>12} {'on CPU':>7} {'sleeps':>7} {'long':>5} {'median ms':>10} {'lost s':>7} {'long before':>12}"]
    rows = []
    for t in busy:
        lg = [v for v in sleeps[t] if v >= lim]
        b = len([v for v in bsleeps.get(t, []) if v >= lim])
        rows.append((t, lg, b))
        out.append(f"  {t:>8} {info[t][0]:<16} {info[t][2]:>12} {oncpu[t] / secs:>7.0%} {len(sleeps[t]):>7} {len(lg):>5} "
                   f"{pct(lg, 0.5) * 1e3:>10.1f} {sum(lg):>7.2f} {b:>12}")
    out.append(f"  long = sleeps of {LONG_MS:.0f} ms or more; lost = time in them; before = the same thread in the baseline slice")
    hits = 0
    for t, lg, b in rows:
        if len(lg) < MIN_LONG * secs or b > MAX_BASE * len(lg):
            continue
        if pct(lg, 0.9) > FIXED * pct(lg, 0.1):
            out.append(f"OTHER LONG SLEEPS (mixed length, no verdict): {info[t][0]} (tid {t}, pid_ns {info[t][2]}) is on the CPU "
                       f"{oncpu[t] / secs:.0%} of the slice and slept {len(lg)} times for {pct(lg, 0.1) * 1e3:.0f} to "
                       f"{pct(lg, 0.9) * 1e3:.0f} ms, {b} times in the baseline - this can be a thread that waits for its next piece of work")
            continue
        out.append(f"VERDICT: A BUSY THREAD KEEPS STOPPING: {info[t][0]} (tid {t}, pid {info[t][1]}, pid_ns {info[t][2]}) is on the CPU "
                   f"{oncpu[t] / secs:.0%} of the slice and slept {len(lg)} times for {LONG_MS:.0f} ms or more in {secs:.0f} s, {b} times in "
                   f"the baseline; the sleeps are all about {pct(lg, 0.5) * 1e3:.0f} ms long (from {pct(lg, 0.1) * 1e3:.0f} to "
                   f"{pct(lg, 0.9) * 1e3:.0f}) and took {sum(lg):.2f} s in total - a blocking call of one fixed length on a thread that has work waiting")
        hits += 1
    if not hits:
        why = (f"most: {info[rows[0][0]][0]} (tid {rows[0][0]}) {len(rows[0][1])} long sleeps, {rows[0][2]} in the baseline" if rows
               else "no thread is that busy")
        out.append(f"VERDICT: NO BUSY THREAD STOPS ({why}; the bars are {MIN_LONG:.0f} sleeps of {LONG_MS:.0f} ms per second on a thread "
                   f"that is on the CPU {MIN_BUSY:.0%} of the time, baseline at most {MAX_BASE:.0%} of it)")
    return out


def selftest():
    def sw(t, prev, state, nxt, comm="node", ns=7):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = 0 }}, {{ pid = {prev}, tid = {prev}, procname = "{comm}", '
                f'cgroup_ns = 1, pid_ns = {ns}, net_ns = 1 }}, {{ prev_comm = "{comm}", prev_tid = {prev}, prev_prio = 20, prev_state = {state}, '
                f'next_comm = "x", next_tid = {nxt}, next_prio = 20 }}')

    def loop(block_every=0):
        o, t, i = [sw(0, 0, 0, 50, "swapper/0", 1)], 0.0, 0
        while t < 10:
            i += 1
            t += 0.009                           # 9 ms of work
            nap = 0.030 if block_every and i % block_every == 0 else 0.0005
            o += [sw(t, 50, 1, 0), sw(t + nap, 0, 0, 50, "swapper/0", 1)]
            t += nap
        return o

    out = "\n".join(report(read(loop()), read(loop(20)), 10))
    assert "A BUSY THREAD KEEPS STOPPING: node (tid 50, pid 50, pid_ns 7) is on the CPU 82% of the slice and slept 45 times for 15 ms or more in 10 s, 0 times in the baseline; the sleeps are all about 30 ms long (from 30 to 30) and took 1.35 s in total" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(loop()), read(loop()), 10))
    assert "NO BUSY THREAD STOPS (most: node (tid 50) 0 long sleeps, 0 in the baseline" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: busy_sleep.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
