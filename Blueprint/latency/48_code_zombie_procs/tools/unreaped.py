#!/usr/bin/env python3
# unreaped.py - find a program that starts child processes and never collects them.
#
# When a process ends, the kernel keeps a small record of it until its parent asks how it
# ended (wait). Only then is the record freed. A parent that never asks leaves one dead entry
# in the process table per child: a zombie. Zombies use no CPU and almost no memory, so nothing
# slows down, until the process table or the container's process limit is full and nothing new
# can be started.
#
# The kernel trace shows each step: the parent creates the child (sched_process_fork), the
# child ends (sched_process_exit) and its record is freed (sched_process_free). A child that
# ended and was not freed by the end of the slice is still a zombie.
#
# For each parent process:
#   children  processes it created in the slice
#   ended     of those, how many ended at least GRACE seconds before the end of the slice
#   unreaped  of those, how many were never freed
#
# Usage:
#   python3 unreaped.py <baseline_slice.txt> <fault_slice.txt>
#   python3 unreaped.py --selftest
#
#   both slices 60 s, cut with: extract_slice.sh TRACE DAY HH:MM:SS 60 out.txt \
#     'sched_process_fork|sched_process_exit|sched_process_free'
import re
import sys
from collections import defaultdict

MIN_UNREAPED = 20      # children of one parent that ended and were not freed, in the slice
MIN_SHARE = 0.8        # ... and at least this share of its children that ended
MAX_BASE = 0.1         # ... and the baseline has at most this share of them
GRACE = 2.0            # a child that ended in the last seconds of the slice may still be collected
# Bars set before the first run on labelled data (27-11-2026) and not fitted to it.

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_fork = re.compile(r'parent_comm = "([^"]*)", parent_tid = \d+, parent_pid = (\d+), parent_ns_inum = (\d+), '
                     r'child_comm = "[^"]*", child_tid = (\d+),.*?child_pid = (\d+)')
re_ctx = re.compile(r'\{ pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_free = re.compile(r'\{ comm = "[^"]*", tid = (\d+), prio')


def tsec(line):
    m = re_time.match(line)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1e9 if m else None


def read(lines):
    parent = {}                                  # child pid -> parent pid
    name, ns = {}, {}
    ended = {}                                   # child pid -> time its main thread ended
    freed = set()
    last = 0.0
    for line in lines:
        t = tsec(line)
        if t is None:
            continue
        last = max(last, t)
        if ' sched_process_fork:' in line:
            m = re_fork.search(line)
            if m and m.group(4) == m.group(5):   # a new process, not a new thread
                parent[m.group(5)] = m.group(2)
                name.setdefault(m.group(2), m.group(1))
                ns.setdefault(m.group(2), m.group(3))
        elif ' sched_process_exit:' in line:
            m = re_ctx.search(line)
            if m and m.group(1) == m.group(2) and m.group(1) in parent:
                ended[m.group(1)] = t
        elif ' sched_process_free:' in line:
            m = re_free.search(line)
            if m:
                freed.add(m.group(1))
    kids = defaultdict(int)
    done = defaultdict(int)
    left = defaultdict(int)
    for child, par in parent.items():
        kids[par] += 1
        if child in ended and ended[child] <= last - GRACE:
            done[par] += 1
            left[par] += child not in freed
    return kids, done, left, name, ns


def report(base, fault):
    bleft = base[2]
    kids, done, left, name, ns = fault
    rows = sorted(kids, key=lambda p: (-left[p], -kids[p]))
    out = ["Child processes per parent in this slice (most unreaped first)",
           f"  {'parent pid':>10} {'program':<16} {'pid_ns':>12} {'children':>9} {'ended':>6} {'unreaped':>9} {'unreaped before':>16}"]
    for p in rows[:10]:
        out.append(f"  {p:>10} {name.get(p, '?'):<16} {ns.get(p, '?'):>12} {kids[p]:>9} {done[p]:>6} {left[p]:>9} {bleft.get(p, 0):>16}")
    out.append(f"  ended = ended at least {GRACE:.0f} s before the end of the slice; unreaped = ended and never freed; before = the baseline slice")
    hits = 0
    for p in rows:
        if left[p] < MIN_UNREAPED or left[p] < MIN_SHARE * done[p] or bleft.get(p, 0) > MAX_BASE * left[p]:
            continue
        out.append(f"VERDICT: CHILD PROCESSES ARE NEVER COLLECTED: {name.get(p, '?')} (pid {p}, pid_ns {ns.get(p, '?')}) started "
                   f"{kids[p]} child processes in the slice; {done[p]} of them ended and {left[p]} of those were never freed "
                   f"({left[p] / done[p]:.0%}), {bleft.get(p, 0)} in the baseline - each one stays in the process table as a zombie")
        hits += 1
    if not hits:
        t = rows[0] if rows else None
        why = (f"most: {name.get(t, '?')} (pid {t}) {left[t]} unreaped of {done[t]} ended" if t else "no process was created")
        out.append(f"VERDICT: NO UNREAPED CHILDREN ({why}; the bars are {MIN_UNREAPED} unreaped, {MIN_SHARE:.0%} of the ended children, "
                   f"baseline at most {MAX_BASE:.0%} of it)")
    return out


def selftest():
    H = '[10:00:%012.9f] (+0.0) h '

    def fork(t, ppid, child, comm="bash", ns=1):
        return (H % t + f'sched_process_fork: {{ cpu_id = 0 }}, {{ pid = {ppid}, tid = {ppid}, procname = "{comm}", pid_ns = {ns} }}, '
                f'{{ parent_comm = "{comm}", parent_tid = {ppid}, parent_pid = {ppid}, parent_ns_inum = {ns}, child_comm = "{comm}", '
                f'child_tid = {child}, _vtids_length = 1, vtids = [ [0] = {child} ], child_pid = {child}, child_ns_inum = {ns} }}')

    def ex(t, pid, tid=None):
        tid = tid or pid
        return (H % t + f'sched_process_exit: {{ cpu_id = 1 }}, {{ pid = {pid}, tid = {tid}, procname = "x", pid_ns = 1 }}, '
                f'{{ comm = "x", tid = {tid}, prio = 20, group_dead = 1 }}')

    def free(t, tid):
        return (H % t + f'sched_process_free: {{ cpu_id = 1 }}, {{ pid = 9, tid = 9, procname = "other", pid_ns = 1 }}, '
                f'{{ comm = "x", tid = {tid}, prio = 20 }}')

    shell = []                                   # a shell script: starts 200 children and collects each one
    for i in range(200):
        t = i * 0.25
        shell += [fork(t, 100, 1000 + i), ex(t + 0.01, 1000 + i), free(t + 0.011, 1000 + i)]
    shell.append(ex(59.9, 5, 6))                 # something at the end of the slice
    bad = list(shell)
    for i in range(150):                         # a service: 150 children, a helper thread each, none collected
        t = i * 0.3
        bad += [fork(t, 200, 5000 + 2 * i, "app", 7), ex(t + 0.004, 5000 + 2 * i, 5001 + 2 * i), free(t + 0.0041, 5001 + 2 * i),
                ex(t + 0.005, 5000 + 2 * i)]
    bad.sort()
    out = "\n".join(report(read(shell), read(bad)))
    assert "CHILD PROCESSES ARE NEVER COLLECTED: app (pid 200, pid_ns 7) started 150 child processes in the slice; 150 of them ended and 150 of those were never freed (100%), 0 in the baseline" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(shell), read(shell)))
    assert "NO UNREAPED CHILDREN (most: bash (pid 100) 0 unreaped of 200 ended" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: unreaped.py <baseline_slice.txt> <fault_slice.txt>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa)))
