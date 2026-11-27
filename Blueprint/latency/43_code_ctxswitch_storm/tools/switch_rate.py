#!/usr/bin/env python3
# switch_rate.py - find one process whose many threads wake up and go back to sleep all the time.
#
# A thread that wakes up, does almost nothing and sleeps again costs two context switches each
# time. One such thread is harmless. Hundreds of them (a thread pool that is far too large, or
# threads that poll with a short sleep) keep the scheduler busy: every other thread on the host
# is interrupted more often, and the process's real work waits behind its own idle threads.
#
# For each process (pid), from the context switches in the slice:
#   switches  times one of its threads left the CPU
#   threads   different threads of it that ran
#   run       how long a thread stayed on the CPU each time (median, in microseconds)
#   cores     CPU time used, in cores
#
# Usage:
#   python3 switch_rate.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 switch_rate.py --selftest
#
#   both slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'sched_switch'
import re
import sys
from collections import defaultdict

MIN_RATE = 20000       # context switches per second by one process
MIN_THREADS = 100      # ... spread over at least this many of its threads
MAX_RUN_US = 200       # ... that stay on the CPU at most this long each time (median)
MIN_RISE = 5.0         # ... and this many times the process's rate in the baseline
# Bars set before the first run on labelled data (27-11-2026) and not fitted to it.

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_ctx = re.compile(r'\{ pid = (\d+), tid = (\d+), procname = "([^"]*)".*?pid_ns = (\d+)')


def tsec(line):
    m = re_time.match(line)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1e9 if m else None


def read(lines):
    n = defaultdict(int)
    tids = defaultdict(set)
    runs = defaultdict(list)
    name, ns = {}, {}
    since = {}                                   # cpu -> time of the last switch on it
    for line in lines:
        if ' sched_switch:' not in line:
            continue
        t, c, m = tsec(line), re_cpu.search(line), re_ctx.search(line)
        if t is None or not c or not m:
            continue
        cpu, pid = c.group(1), m.group(1)
        t0 = since.get(cpu)
        since[cpu] = t
        if pid == "0":                           # the idle task
            continue
        n[pid] += 1
        tids[pid].add(m.group(2))
        name.setdefault(pid, m.group(3))
        ns.setdefault(pid, m.group(4))
        if t0 is not None:
            runs[pid].append(t - t0)
    return n, tids, runs, name, ns


def med(x):
    x = sorted(x)
    return x[len(x) // 2] if x else 0.0


def report(base, fault, secs):
    bn = base[0]
    n, tids, runs, name, ns = fault
    rows = sorted(n, key=lambda p: -n[p])
    out = [f"Context switches per process in this {secs:.0f} s slice (most first)",
           f"  {'pid':>8} {'program':<16} {'pid_ns':>12} {'switches/s':>11} {'threads':>8} {'run us':>7} {'cores':>6} {'per s before':>13}"]
    for p in rows[:10]:
        out.append(f"  {p:>8} {name[p]:<16} {ns[p]:>12} {n[p] / secs:>11.0f} {len(tids[p]):>8} {med(runs[p]) * 1e6:>7.0f} "
                   f"{sum(runs[p]) / secs:>6.2f} {bn.get(p, 0) / secs:>13.0f}")
    out.append("  run = median time on the CPU each time, in microseconds; before = the same process in the baseline slice")
    hits = 0
    for p in rows:
        rate, b = n[p] / secs, bn.get(p, 0) / secs
        if rate < MIN_RATE or len(tids[p]) < MIN_THREADS or med(runs[p]) * 1e6 > MAX_RUN_US or rate < MIN_RISE * max(1.0, b):
            continue
        out.append(f"VERDICT: MANY THREADS WAKE UP ALL THE TIME: {name[p]} (pid {p}, pid_ns {ns[p]}) made {rate:.0f} context switches "
                   f"per second over {len(tids[p])} threads, {b:.0f} per second in the baseline; each thread stayed on the CPU "
                   f"{med(runs[p]) * 1e6:.0f} microseconds (median) and the process used {sum(runs[p]) / secs:.2f} cores - "
                   f"a pool of threads that wake up and do almost nothing")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"most: {name[top]} (pid {top}) {n[top] / secs:.0f} per second over {len(tids[top])} threads, median run "
               f"{med(runs[top]) * 1e6:.0f} us" if top else "no context switch in the slice")
        out.append(f"VERDICT: NO THREAD STORM ({why}; the bars are {MIN_RATE} per second, {MIN_THREADS} threads, runs of at most "
                   f"{MAX_RUN_US} us, {MIN_RISE:.0f}x the baseline)")
    return out


def selftest():
    def sw(t, cpu, pid, tid, comm="app", ns=7):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = {cpu} }}, {{ pid = {pid}, tid = {tid}, procname = "{comm}", '
                f'cgroup_ns = 1, pid_ns = {ns}, net_ns = 1 }}, {{ prev_comm = "{comm}", prev_tid = {tid}, prev_prio = 20, prev_state = 1, '
                f'next_comm = "swapper/{cpu}", next_tid = 0, next_prio = 20 }}')

    def idle(t, cpu):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = {cpu} }}, {{ pid = 0, tid = 0, procname = "swapper/{cpu}", '
                f'cgroup_ns = 1, pid_ns = 1, net_ns = 1 }}, {{ prev_comm = "swapper/{cpu}", prev_tid = 0, prev_prio = 20, prev_state = 0, '
                f'next_comm = "x", next_tid = 5, next_prio = 20 }}')

    busy = []                                    # a busy service: 16 threads, 2 ms runs, 1,000 switches per second
    for i in range(1000):
        busy += [idle(i * 0.001, 0), sw(i * 0.001 + 0.0008, 0, 100, 101 + i % 16, "java", 3)]
    storm = list(busy)                           # 300 threads, 30 us runs, 30,000 switches per second
    for i in range(30000):
        t = i / 30000.0
        storm += [idle(t, 1), sw(t + 0.00003, 1, 200, 1000 + i % 300, "app", 9)]
    storm.sort()
    out = "\n".join(report(read(busy), read(storm), 1))
    assert "MANY THREADS WAKE UP ALL THE TIME: app (pid 200, pid_ns 9) made 30000 context switches per second over 300 threads, 0 per second in the baseline; each thread stayed on the CPU 30 microseconds" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(busy), read(busy), 1))
    assert "NO THREAD STORM (most: java (pid 100) 1000 per second over 16 threads, median run 800 us" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: switch_rate.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
