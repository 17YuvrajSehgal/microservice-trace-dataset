#!/usr/bin/env python3
# cpu_runs.py - find a container whose threads stay on the CPU for long stretches without
# making a system call.
#
# A normal service thread runs for a little while and then asks the kernel for something
# (read a socket, write an answer, wait). A busy-wait, a heavy computation or a regular
# expression that backtracks runs on the CPU and asks the kernel for nothing until it is done.
#
# For each container (pid namespace), in a baseline slice and a suspect slice, the tool cuts
# the time each thread is on a CPU at every system call it makes, and keeps the pieces of
# MIN_STRETCH_MS or longer ("stretches"):
#   per s      stretches per second
#   busy       seconds per second spent in such stretches (cores)
#   threads    threads that had at least one
#   p50, max   their length in ms
#
# Two kinds are told apart:
#   MANY THREADS, SHORT STRETCHES   work spread over many threads (a busy-wait or a hot loop in
#                                   a multi-threaded service): requests slower, still served
#   ONE THREAD, LONG STALLS         a few long stretches in one thread (a single-threaded
#                                   service stops for each one)
#
# Usage:
#   python3 cpu_runs.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 cpu_runs.py --selftest
#
#   both slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'sched_switch|syscall_entry_'
import re
import sys
from collections import defaultdict
from statistics import median

MIN_STRETCH_MS = 5.0   # a stretch: on the CPU this long with no system call
MIN_BUSY = 0.1         # the container spends at least this many cores in stretches
MIN_RISE = 5.0         # ... and this many times its baseline
LONG_MS = 100.0        # "long stall": a stretch this long
MIN_LONG = 3           # ... or at least this many long stalls in the slice, with none in the baseline
# The first three bars were set before the first run on labelled data (26-11-2026). MIN_LONG was
# ADDED after run 1 of code_regex_backtrack: the front-end had 6 stretches of 100-290 ms (median
# 133 ms, all in one thread, none before) but only 0.09 cores in them, under the 0.1 bar. A
# single-threaded service stops for each long stall however little CPU the stalls add up to.
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/", "migration/", "rcu_", "idle")

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_ctx = re.compile(r'tid = (\d+), procname = "([^"]*)".*?pid_ns = (\d+)')
re_sw = re.compile(r'prev_tid = (\d+), prev_prio = -?\d+, prev_state = \d+, next_comm = "[^"]*", next_tid = (\d+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    since = {}                                   # cpu -> (tid, time it went on, time of its last system call)
    pieces = defaultdict(list)                   # pid_ns -> [(ms, tid)]
    names = defaultdict(lambda: defaultdict(int))
    tid_ns = {}

    def cut(cpu, t):
        cur = since.get(cpu)
        if cur and cur[0] != '0':
            ms = (t - cur[2]) * 1000
            if ms >= MIN_STRETCH_MS and cur[0] in tid_ns:
                pieces[tid_ns[cur[0]]].append((ms, cur[0]))
        return cur

    for line in lines:
        t = tsec(line)
        if t is None:
            continue
        cm = re_cpu.search(line)
        if not cm:
            continue
        cpu = cm.group(1)
        cx = re_ctx.search(line)
        if cx and not cx.group(2).startswith(KERNEL_CTX):
            tid_ns[cx.group(1)] = cx.group(3)
            names[cx.group(3)][cx.group(2)] += 1
        if ' syscall_entry_' in line:
            cur = cut(cpu, t)
            if cur and cx and cur[0] == cx.group(1):
                since[cpu] = (cur[0], cur[1], t)
        elif ' sched_switch:' in line:
            sw = re_sw.search(line)
            if not sw:
                continue
            cut(cpu, t)
            since[cpu] = (sw.group(2), t, t)
    return pieces, names


def summary(pieces, secs):
    out = {}
    for ns, ps in pieces.items():
        ms = [m for m, _ in ps]
        per = defaultdict(int)
        for _, tid in ps:
            per[tid] += 1
        out[ns] = {"rate": len(ms) / secs, "busy": sum(ms) / 1000 / secs, "threads": len(per),
                   "p50": median(ms), "max": max(ms), "long": sum(1 for m in ms if m >= LONG_MS),
                   "top_share": max(per.values()) / len(ms)}
    return out


def report(base, fault, secs):
    b, f = summary(base[0], secs), summary(fault[0], secs)
    names = fault[1]

    def nm(ns):
        return max(names[ns], key=names[ns].get) if names.get(ns) else "?"
    rows = sorted(f.items(), key=lambda kv: -kv[1]["busy"])
    out = [f"On-CPU stretches of {MIN_STRETCH_MS:.0f} ms or more with no system call, per container, {secs:.0f} s slices",
           f"  {'pid_ns':>12} {'program':<16} {'per s':>7} {'busy':>6} {'threads':>8} {'p50 ms':>7} {'max ms':>8} {'busy before':>12}"]
    for ns, r in rows[:10]:
        out.append(f"  {ns:>12} {nm(ns):<16} {r['rate']:>7.1f} {r['busy']:>6.2f} {r['threads']:>8} {r['p50']:>7.1f} {r['max']:>8.1f} "
                   f"{b.get(ns, {}).get('busy', 0.0):>12.2f}")
    out.append("  busy = cores spent in such stretches; before = the baseline slice")
    hits = 0
    for ns, r in rows:
        bb = b.get(ns, {}).get("busy", 0.0)
        stalls = r["long"] >= MIN_LONG and not b.get(ns, {}).get("long", 0)
        if not stalls and (r["busy"] < MIN_BUSY or r["busy"] < MIN_RISE * max(bb, 0.005)):
            continue
        if r["long"] and r["top_share"] >= 0.8:
            kind = (f"KIND: ONE THREAD, LONG STALLS ({r['long']} stretches of {LONG_MS:.0f} ms or more, longest {r['max']:.0f} ms, "
                    f"{r['top_share']:.0%} of them in one thread: a single-threaded program stops for each one)")
        elif r["threads"] >= 2 and r["top_share"] < 0.8:
            kind = (f"KIND: MANY THREADS, SHORT STRETCHES ({r['threads']} threads, median {r['p50']:.0f} ms: work spread over "
                    f"many threads, requests slower but still served)")
        else:
            kind = "KIND: UNCLEAR"
        out.append(f"VERDICT: LONG CPU STRETCHES WITHOUT A SYSTEM CALL: {nm(ns)} (pid_ns {ns}) spends {r['busy']:.2f} cores in "
                   f"{r['rate']:.1f} stretches per second ({bb:.2f} cores in the baseline); {kind}")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"most: {nm(top[0])} (pid_ns {top[0]}) {top[1]['busy']:.2f} cores, {b.get(top[0], {}).get('busy', 0.0):.2f} before" if top
               else "no stretch in the slice")
        out.append(f"VERDICT: NO LONG CPU STRETCHES ({why}; the bars are {MIN_BUSY} cores and {MIN_RISE:.0f}x the baseline, "
                   f"or {MIN_LONG} stalls of {LONG_MS:.0f} ms with none before)")
    return out


def selftest():
    def sw(t, cpu, prev, nxt, comm="app", ns=7):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = {cpu} }}, {{ pid = {prev}, tid = {prev}, procname = "{comm}", '
                f'cgroup_ns = 1, pid_ns = {ns}, net_ns = 1 }}, {{ prev_comm = "{comm}", prev_tid = {prev}, prev_prio = 20, prev_state = 1, '
                f'next_comm = "x", next_tid = {nxt}, next_prio = 20 }}')

    def sc(t, cpu, tid, comm="app", ns=7):
        return (f'[10:00:{t:012.9f}] (+0.0) h syscall_entry_read: {{ cpu_id = {cpu} }}, {{ pid = {tid}, tid = {tid}, procname = "{comm}", '
                f'cgroup_ns = 1, pid_ns = {ns}, net_ns = 1 }}, {{ fd = 3 }}')

    def normal():                                # each thread runs 1 ms, makes a call, sleeps
        ls = []
        for i in range(2000):
            t, cpu, tid = i * 0.005, i % 4, 100 + i % 8
            ls += [sw(t, cpu, 0, tid, "swapper/0", 0), sc(t + 0.0005, cpu, tid), sc(t + 0.001, cpu, tid), sw(t + 0.002, cpu, tid, 0)]
        return ls

    spin = normal()
    for i in range(400):                         # 8 threads, 15 ms each with no call
        t, tid = i * 0.025, 300 + i % 8
        spin += [sw(t, 5 + i % 3, 0, tid, "swapper/5", 0), sc(t + 0.0002, 5 + i % 3, tid, "srv", 9),
                 sc(t + 0.0152, 5 + i % 3, tid, "srv", 9), sw(t + 0.016, 5 + i % 3, tid, 0, "srv", 9)]
    spin.sort(key=tsec)
    out = "\n".join(report(read(normal()), read(spin), 10))
    assert "LONG CPU STRETCHES WITHOUT A SYSTEM CALL: srv (pid_ns 9) spends 0.60 cores in 40.0 stretches per second" in out, out
    assert "KIND: MANY THREADS, SHORT STRETCHES (8 threads, median 15 ms" in out and out.count("VERDICT") == 1, out
    stall = normal()
    for i in range(4):                           # one thread, 200 ms each, now and then: few, little CPU
        t = 0.3 + i * 0.8
        stall += [sw(t, 6, 0, 400, "swapper/6", 0), sc(t + 0.0001, 6, 400, "node", 8), sc(t + 0.2001, 6, 400, "node", 8),
                  sw(t + 0.201, 6, 400, 0, "node", 8)]
    stall.sort(key=tsec)
    out = "\n".join(report(read(normal()), read(stall), 10))
    assert "node (pid_ns 8) spends 0.08 cores" in out and "KIND: ONE THREAD, LONG STALLS (4 stretches of 100 ms or more, longest 200 ms, 100% of them in one thread" in out, out
    out = "\n".join(report(read(normal()), read(normal()), 10))
    assert "NO LONG CPU STRETCHES" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: cpu_runs.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
