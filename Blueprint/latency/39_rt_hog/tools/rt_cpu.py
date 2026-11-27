#!/usr/bin/env python3
# rt_cpu.py - find a CPU held by a real-time task.
#
# A task with a real-time policy (SCHED_FIFO or SCHED_RR) always runs before normal tasks on
# its CPU. LTTng prints a real-time task's priority as a negative number (a normal task is 0-39,
# 20 by default). The tool adds up, per CPU, the time the running task had a negative priority
# and was not a kernel thread (migration, watchdog and other kernel helpers are real-time too).
#
# Usage:
#   python3 rt_cpu.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 rt_cpu.py --selftest
#
#   both slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'sched_switch'
import re
import sys
from collections import defaultdict

MIN_SHARE = 0.5        # the CPU spends at least this share of the slice in user real-time tasks
MAX_BASE = 0.05        # ... and at most this in the baseline
# Bars set before the first run on labelled data (26-11-2026) and not fitted to it.
KERNEL = ("migration/", "watchdog/", "rcu_", "ksoftirqd/", "kworker/", "cpuhp/", "idle_inject/", "irq/", "swapper/")

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_sw = re.compile(r'next_comm = "([^"]*)", next_tid = (\d+), next_prio = (-?\d+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    cur = {}                                     # cpu -> (since, comm, tid, prio)
    rt = defaultdict(float)                      # cpu -> seconds in a user real-time task
    who = defaultdict(lambda: defaultdict(float))
    span = [None, None]
    for line in lines:
        if ' sched_switch:' not in line:
            continue
        t, cm, sw = tsec(line), re_cpu.search(line), re_sw.search(line)
        if t is None or not cm or not sw:
            continue
        span[0] = t if span[0] is None else span[0]
        span[1] = t
        cpu = cm.group(1)
        c = cur.get(cpu)
        if c and c[3] < 0 and not c[1].startswith(KERNEL):
            rt[cpu] += t - c[0]
            who[cpu][(c[1], c[2], c[3])] += t - c[0]
        cur[cpu] = (t, sw.group(1), sw.group(2), int(sw.group(3)))
    return rt, who, (span[1] - span[0]) if span[0] is not None else 1.0


def report(base, fault, secs):
    brt = base[0]
    rt, who, _ = fault
    out = [f"Time each CPU ran a user real-time task, in this {secs:.0f} s slice",
           f"  {'cpu':>4} {'share':>6} {'before':>7}  task (comm, tid, priority)"]
    rows = sorted(rt.items(), key=lambda kv: -kv[1])
    for cpu, s in rows[:12]:
        top = max(who[cpu], key=who[cpu].get)
        out.append(f"  {cpu:>4} {s / secs:>6.0%} {brt.get(cpu, 0.0) / secs:>7.0%}  {top[0]} tid {top[1]} prio {top[2]}")
    out.append("  share = time with a real-time task (negative priority) that is not a kernel thread; before = the baseline slice")
    hits = 0
    for cpu, s in rows:
        if s / secs < MIN_SHARE or brt.get(cpu, 0.0) / secs > MAX_BASE:
            continue
        top = max(who[cpu], key=who[cpu].get)
        out.append(f"VERDICT: A REAL-TIME TASK HOLDS A CPU: {top[0]} (tid {top[1]}, priority {top[2]}) ran on CPU {cpu} for "
                   f"{s / secs:.0%} of the slice ({brt.get(cpu, 0.0) / secs:.0%} in the baseline); normal threads there get only "
                   f"what is left")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"most: CPU {top[0]} {top[1] / secs:.0%}" if top else "no user real-time task ran")
        out.append(f"VERDICT: NO CPU HELD BY A REAL-TIME TASK ({why}; the bars are {MIN_SHARE:.0%} of the slice, "
                   f"{MAX_BASE:.0%} in the baseline)")
    return out


def selftest():
    def sw(t, cpu, comm, tid, prio):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = {cpu} }}, {{ pid = 1, tid = 1, procname = "x", pid_ns = 1 }}, '
                f'{{ prev_comm = "x", prev_tid = 1, prev_prio = 20, prev_state = 1, next_comm = "{comm}", next_tid = {tid}, next_prio = {prio} }}')
    base, fault = [], []
    for i in range(1000):
        t = i * 0.01
        base += [sw(t, 3, "java", 10, 20), sw(t + 0.004, 3, "swapper/3", 0, 20)]
        fault += [sw(t, 3, "python3", 99, -51), sw(t + 0.0095, 3, "java", 10, 20)]
        fault.append(sw(t + 0.002, 2, "migration/2", 15, -100))
        fault.append(sw(t + 0.008, 2, "swapper/2", 0, 20))
    out = "\n".join(report(read(base), read(sorted(fault, key=tsec)), 10))
    assert "A REAL-TIME TASK HOLDS A CPU: python3 (tid 99, priority -51) ran on CPU 3 for 95% of the slice (0% in the baseline)" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(base), read(base), 10))
    assert "NO CPU HELD BY A REAL-TIME TASK" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: rt_cpu.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
