#!/usr/bin/env python3
# cpu_newcomer.py - is there a NEW CPU user, and does it fill the machine?
#
# cpu_hogs.py prints who used the CPU in one slice. This tool compares a baseline slice with
# a fault slice and gives one verdict line: a group that used no CPU before and uses a lot
# now. It also says whether the machine is full, which separates an uncapped stressor that
# takes every core (host CPU saturation) from a capped neighbor that takes one or two.
#
# A group is one container (one pid namespace). Processes on the host itself are grouped by
# program name, because they all share the host namespace.
#
# Usage:
#   python3 cpu_newcomer.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 cpu_newcomer.py --selftest
#
#   both slices: scheduling events, same length, cut with extract_slice.sh (default pattern)
import re
import sys
from collections import defaultdict

NEW_BASE_CORES = 0.05   # "was not there before" = less than this many cores in the baseline
MIN_CORES = 0.5         # a newcomer below this many cores is not reported
FULL_IDLE = 0.05        # the machine is "full" when less than this share of CPU time is idle
FULL_SHARE = 0.25       # ... and the newcomer holds at least this share of all CPUs

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    # The context of sched_switch is the thread going OUT, so the time since the last switch
    # on that CPU belongs to it.
    # ponytail: the last stretch on each CPU (after its final switch) is not charged
    last = {}                                  # cpu -> time of the last switch
    raw = defaultdict(float)                   # (pid_ns, comm) -> seconds on CPU
    pids = defaultdict(set)
    kns = defaultdict(int)                     # pid_ns of kernel worker threads = the host
    start = None
    for line in lines:
        if ' sched_switch:' not in line:
            continue
        t, cm, c, pn = tsec(line), re_cpu.search(line), re_ctx.search(line), re_pidns.search(line)
        if t is None or not cm:
            continue
        start = t if start is None else start
        cpu = cm.group(1)
        since = last.get(cpu, start)
        last[cpu] = t
        if not c or not pn or c.group(2) == '0':
            continue
        key = (pn.group(1), c.group(3))
        raw[key] += t - since
        pids[key].add(c.group(1))
        if c.group(3).startswith('kworker/'):
            kns[pn.group(1)] += 1
    host = max(kns, key=kns.get) if kns else None
    use = defaultdict(float)                   # group -> seconds
    gp = defaultdict(set)
    top = {}                                   # container -> (seconds, comm) of its busiest thread name
    for (ns, comm), s in raw.items():
        g = ('host', comm) if ns == host or ns == '0' else ('ns', ns)
        use[g] += s
        gp[g] |= pids[(ns, comm)]
        if g[0] == 'ns' and s > top.get(g, (0, ''))[0]:
            top[g] = (s, comm)
    name = {g: (g[1] if g[0] == 'host' else f"{top[g][1]} (pid_ns {g[1]})") for g in use}
    return use, gp, name, len(last)


def report(base, fault, secs):
    bu, _, _, _ = base
    fu, fp, name, ncpu = fault
    ncpu = max(1, ncpu)
    busy = sum(fu.values()) / (secs * ncpu)
    bbusy = sum(bu.values()) / (secs * ncpu)
    rows = sorted(fu.items(), key=lambda kv: -kv[1])
    out = [f"{ncpu} CPUs, slices of {secs:.0f} s. CPU busy: baseline {bbusy:.0%}, fault {busy:.0%}.",
           f"  {'group':<36}{'procs':>6}{'cores before':>14}{'cores now':>11}"]
    for g, s in rows[:8]:
        out.append(f"  {name[g]:<36}{len(fp[g]):>6}{bu.get(g, 0) / secs:>14.2f}{s / secs:>11.2f}")
    out.append("  group = one container (named by its busiest thread), or one program name on the host")
    new = [(g, s / secs) for g, s in rows if bu.get(g, 0) / secs < NEW_BASE_CORES and s / secs >= MIN_CORES]
    if not new:
        g, s = max(((g, s / secs - bu.get(g, 0) / secs) for g, s in rows), key=lambda r: r[1], default=(None, 0))
        why = f"largest rise: {name[g]} +{s:.2f} cores" if g else "no CPU use seen"
        out.append(f"VERDICT: NO NEW CPU USER ({why}; a newcomer has under {NEW_BASE_CORES} cores before "
                   f"and {MIN_CORES} or more now)")
        return out
    g, cores = new[0]
    what = f"{name[g]}, {len(fp[g])} processes, uses {cores:.1f} of {ncpu} cores ({cores / ncpu:.0%}), " \
           f"{bu.get(g, 0) / secs:.2f} before; the machine is {1 - busy:.0%} idle"
    if 1 - busy < FULL_IDLE and cores / ncpu >= FULL_SHARE:
        out.append(f"VERDICT: NEW CPU USER FILLS THE MACHINE: {what}")
    else:
        out.append(f"VERDICT: NEW CPU USER, MACHINE NOT FULL: {what}")
    return out


def selftest():
    def sw(t, cpu, tid, ns, nm):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = {cpu} }}, {{ pid = {tid}, tid = {tid}, '
                f'procname = "{nm}", pid_ns = {ns}, net_ns = 1 }}, {{ prev_comm = "{nm}", prev_tid = {tid}, '
                f'prev_prio = 20, prev_state = 1, next_comm = "x", next_tid = 0, next_prio = 20 }}')

    def idle(t, cpu):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = {cpu} }}, {{ pid = 0, tid = 0, '
                f'procname = "swapper/{cpu}", pid_ns = 1, net_ns = 1 }}, {{ prev_comm = "swapper", prev_tid = 0, '
                f'prev_prio = 20, prev_state = 0, next_comm = "x", next_tid = 5, next_prio = 20 }}')

    def slice_(hog_share):          # 2 CPUs, 10 s, 10 ms ticks; a service at 20% of cpu 0
        ls = []
        for i in range(1000):
            t = i * 0.01
            ls += [idle(t, 0), sw(t + 0.002, 0, 50, 7, "java"), sw(t + 0.0021, 0, 9, 1, "kworker/0:1")]
            if hog_share:
                ls += [idle(t, 1), sw(t + 0.01 * hog_share, 1, 100 + i % 4, 9, "stress-ng-cpu")]
        return sorted(ls, key=tsec)

    base = read(slice_(0))
    out = "\n".join(report(base, read(slice_(0.9)), 10))
    assert "NEW CPU USER, MACHINE NOT FULL: stress-ng-cpu (pid_ns 9), 4 processes, uses 0.9 of 2 cores" in out, out
    assert "java (pid_ns 7)" in out and "kworker/0:1" in out, out
    out = "\n".join(report(base, base, 10))
    assert "VERDICT: NO NEW CPU USER" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: cpu_newcomer.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
