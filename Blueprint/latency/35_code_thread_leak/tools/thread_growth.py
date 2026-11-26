#!/usr/bin/env python3
# thread_growth.py - find one process whose threads are started and do not end.
#
# Programs start threads all the time (a Java service here starts about 150 per second when
# nothing is wrong), and most of them end again. A thread leak is a process that starts
# threads and does not end them: its thread count only grows.
#
# For each process (pid), in a baseline slice and a suspect slice:
#   started   threads created (sched_process_fork with the child in the same process)
#   ended     threads of that process that exited (sched_process_exit)
#   net       started - ended
#
# Usage:
#   python3 thread_growth.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 thread_growth.py --selftest
#
#   both slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'sched_process_fork|sched_process_exit'
import re
import sys
from collections import defaultdict

MIN_NET = 30           # threads that stayed, in the slice
MAX_ENDED = 0.2        # ... and at most this share of the started ones ended
MAX_BASE = 0.2         # ... and the baseline's net growth is at most this share of it
# Bars set before the first run on labelled data (26-11-2026) and not fitted to it.

re_fork = re.compile(r'parent_comm = "([^"]*)", parent_tid = (\d+), parent_pid = (\d+), parent_ns_inum = (\d+), '
                     r'child_comm = "[^"]*", child_tid = (\d+),.*?child_pid = (\d+)')
re_ctx = re.compile(r'\{ pid = (\d+), tid = (\d+), procname = "([^"]*)".*?pid_ns = (\d+)')


def read(lines):
    started = defaultdict(int)
    ended = defaultdict(int)
    name, ns = {}, {}
    for line in lines:
        if ' sched_process_fork:' in line:
            m = re_fork.search(line)
            if m and m.group(3) == m.group(6):          # a new thread, not a new process
                pid = m.group(3)
                started[pid] += 1
                name.setdefault(pid, m.group(1))
                ns.setdefault(pid, m.group(4))
        elif ' sched_process_exit:' in line:
            m = re_ctx.search(line)
            if m and m.group(1) != m.group(2):          # a thread of the process, not its last task
                ended[m.group(1)] += 1
                name.setdefault(m.group(1), m.group(3))
                ns.setdefault(m.group(1), m.group(4))
    return started, ended, name, ns


def report(base, fault, secs):
    bs, be, _, _ = base
    fs, fe, name, ns = fault
    rows = sorted(((fs[p] - fe[p], p) for p in set(fs) | set(fe)), reverse=True)
    out = [f"Threads started and ended per process in this {secs:.0f} s slice (largest net growth first)",
           f"  {'pid':>8} {'program':<16} {'pid_ns':>12} {'started':>8} {'ended':>6} {'net':>6} {'net before':>11}"]
    for net, p in rows[:10]:
        out.append(f"  {p:>8} {name.get(p, '?'):<16} {ns.get(p, '?'):>12} {fs[p]:>8} {fe[p]:>6} {net:>6} {bs[p] - be[p]:>11}")
    out.append("  net = started - ended; before = the same in the baseline slice")
    hits = 0
    for net, p in rows:
        bnet = bs[p] - be[p]
        if net < MIN_NET or fe[p] > MAX_ENDED * fs[p] or bnet > MAX_BASE * net:
            continue
        out.append(f"VERDICT: THREADS ARE STARTED AND NOT ENDED: {name.get(p, '?')} (pid {p}, pid_ns {ns.get(p, '?')}) started {fs[p]} "
                   f"threads in {secs:.0f} s ({fs[p] / secs:.1f} per second) and {fe[p]} of its threads ended; net growth {net}, "
                   f"{bnet} in the baseline - its thread count only grows")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"largest: {name.get(top[1], '?')} (pid {top[1]}) net {top[0]}, {fs[top[1]]} started, {fe[top[1]]} ended" if top
               else "no thread was started")
        out.append(f"VERDICT: NO THREAD GROWTH ({why}; the bars are net {MIN_NET}, at most {MAX_ENDED:.0%} ended, "
                   f"baseline at most {MAX_BASE:.0%} of it)")
    return out


def selftest():
    def fork(t, pid, tid, child, comm="java", ns=7):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_process_fork: {{ cpu_id = 0 }}, {{ pid = {pid}, tid = {tid}, procname = "{comm}", '
                f'cgroup_ns = 1, pid_ns = {ns}, net_ns = 1 }}, {{ parent_comm = "{comm}", parent_tid = {tid}, parent_pid = {pid}, '
                f'parent_ns_inum = {ns}, child_comm = "{comm}", child_tid = {child}, _vtids_length = 2, vtids = [ [0] = {child} ], '
                f'child_pid = {pid}, child_ns_inum = {ns} }}')

    def ex(t, pid, tid, comm="java", ns=7):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_process_exit: {{ cpu_id = 1 }}, {{ pid = {pid}, tid = {tid}, procname = "{comm}", '
                f'cgroup_ns = 1, pid_ns = {ns}, net_ns = 1 }}, {{ comm = "{comm}", tid = {tid}, prio = 20, group_dead = 0 }}')

    busy = []
    for i in range(300):                         # a busy Java service: threads start and end
        busy += [fork(i * 0.03, 100, 101, 5000 + i), ex(i * 0.03 + 0.01, 100, 5000 + i)]
    leak = busy + [fork(i * 0.1, 200, 201, 9000 + i, "app", 9) for i in range(80)]
    out = "\n".join(report(read(busy), read(leak), 10))
    assert "THREADS ARE STARTED AND NOT ENDED: app (pid 200, pid_ns 9) started 80 threads in 10 s (8.0 per second) and 0 of its threads ended; net growth 80, 0 in the baseline" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(busy), read(busy), 10))
    assert "NO THREAD GROWTH (largest: java (pid 100) net 0, 300 started, 300 ended" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: thread_growth.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
