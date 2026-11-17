#!/usr/bin/env python3
# beacon.py - find a process that phones out at a fixed interval, and say whether the same
# process is also burning CPU.
#
# Abusive compute (a miner, a bot) has two halves in a kernel trace: it uses CPU like any heavy
# job, and it keeps a small regular contact with something - a heartbeat. The CPU half looks
# like a noisy neighbour. The heartbeat is what a batch job does not have.
#
# This tool reads connect() calls. For every (process, destination) pair it takes the gaps
# between consecutive connects and keeps the pairs whose gaps are all about the same: a
# PERIODIC connector. Monitoring and service discovery are periodic too, so periodic alone is
# not a verdict. With --sched it also adds up each process's on-CPU time; the verdict needs
# one process that is BOTH periodic and CPU-heavy.
#
# Usage:
#   python3 beacon.py <connect_slice.txt> <slice_seconds> [--sched <sched_slice.txt>]
#   python3 beacon.py --selftest
#
#   <connect_slice.txt>  60 s or more, cut with:
#        extract_slice.sh TRACE DAY HH:MM:SS 60 out.txt 'syscall_entry_connect'
#   <sched_slice.txt>    a 10 s slice of the same window with the default (scheduling) events
import re
import sys
from collections import defaultdict
from statistics import median

MIN_CONNECTS = 5       # at least this many connects to one destination to call it periodic
MIN_PERIOD_S = 1.0     # faster than this is ordinary service traffic, not a heartbeat
MAX_JITTER = 0.10      # median distance of a gap from the median gap, as a share of it
MAX_OUTLIER = 0.35     # no single gap further than this from the median gap
HEAVY_CORES = 0.5      # "CPU-heavy" from this many cores (measured hog: 0.95-1.01)

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_port = re.compile(r'dport = (\d+)')
re_v4 = re.compile(r'v4addr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_prev = re.compile(r'prev_tid = (\d+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight would give one negative gap
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def periodic(times):
    """(period, jitter) if the connect times are evenly spaced, else None."""
    if len(times) < MIN_CONNECTS:
        return None
    gaps = [b - a for a, b in zip(times, times[1:])]
    med = median(gaps)
    if med < MIN_PERIOD_S:
        return None
    jitter = median(abs(g - med) for g in gaps) / med
    if jitter > MAX_JITTER or max(abs(g - med) for g in gaps) > MAX_OUTLIER * med:
        return None
    return med, jitter


def read_connects(lines):
    conn = defaultdict(list)          # (pid, dest) -> [t]
    who = {}                          # pid -> (procname, pid_ns)
    for line in lines:
        if ' syscall_entry_connect:' not in line:
            continue
        t, c = tsec(line), re_ctx.search(line)
        if t is None or not c:
            continue
        pid = c.group(1)
        pn = re_pidns.search(line)
        who[pid] = (c.group(3), pn.group(1) if pn else '?')
        a, p = re_v4.search(line), re_port.search(line)
        dest = (".".join(a.groups()) if a else "non-ipv4") + ":" + (p.group(1) if p else "?")
        conn[(pid, dest)].append(t)
    return conn, who


def read_cpu(lines):
    """pid -> on-CPU seconds. A sched_switch's context is the thread going OUT."""
    last = {}
    oncpu = defaultdict(float)
    lo = hi = None
    for line in lines:
        if ' sched_switch:' not in line:
            continue
        t, c, cpu, pv = tsec(line), re_ctx.search(line), re_cpu.search(line), re_prev.search(line)
        if t is None or not c or not cpu:
            continue
        lo = t if lo is None else lo
        hi = t
        k = cpu.group(1)
        if k in last and pv and pv.group(1) != '0':      # tid 0 = idle
            oncpu[c.group(1)] += t - last[k]
        last[k] = t
    return oncpu, (hi - lo) if lo is not None and hi > lo else 0.0


def report(conn, who, oncpu=None, span=0.0, secs=60.0):
    rows = []
    for (pid, dest), times in conn.items():
        p = periodic(sorted(times))
        if p:
            cores = (oncpu.get(pid, 0.0) / span) if oncpu is not None and span else None
            rows.append((pid, dest, len(times), p[0], p[1], cores))
    rows.sort(key=lambda r: (-(r[5] or 0), r[3]))
    out = [f"connect() calls in this {secs:.0f} s slice: {sum(len(v) for v in conn.values())} "
           f"by {len(who)} processes; {len(rows)} (process, destination) pairs are periodic"]
    if rows:
        out.append(f"  {'pid':>8} {'pid_ns':>12} {'name':<16}{'destination':<24}{'n':>4}{'every s':>9}{'jitter':>8}{'cores':>7}")
        for pid, dest, n, per, jit, cores in rows[:12]:
            nm, nsid = who[pid]
            out.append(f"  {pid:>8} {nsid:>12} {nm:<16}{dest:<24}{n:>4}{per:>9.1f}{jit:>8.0%}"
                       f"{(f'{cores:.2f}' if cores is not None else 'n/a'):>7}")
    heavy = [r for r in rows if r[5] is not None and r[5] >= HEAVY_CORES]
    if oncpu is None:
        out.append("NOTE: no --sched slice given, so CPU use is unknown. Periodic alone is not a "
                   "verdict: monitoring and service discovery are periodic too.")
    elif heavy:
        pid, dest, n, per, jit, cores = heavy[0]
        nm, nsid = who[pid]
        out.append(f"VERDICT: RESOURCE ABUSE SHAPE: {nm} (pid {pid}, pid_ns {nsid}) uses {cores:.2f} "
                   f"cores and connects to {dest} every {per:.1f} s ({n} connects, jitter {jit:.0%})")
    else:
        out.append(f"VERDICT: NO BEACON FROM A CPU-HEAVY PROCESS ({len(rows)} periodic connectors, "
                   f"none uses {HEAVY_CORES} cores or more)")
    return out


def selftest():
    def conn_line(t, pid, nm, port):
        return (f'[10:00:{t:012.9f}] (+0.0) h syscall_entry_connect: {{ cpu_id = 1 }}, {{ pid = {pid}, '
                f'tid = {pid}, procname = "{nm}", cgroup_ns = 1, pid_ns = 77, net_ns = 1 }}, '
                f'{{ fd = 3, family = 2, dport = {port}, _v4addr_length = 4, v4addr = [ [0] = 127, '
                f'[1] = 0, [2] = 0, [3] = 1 ] }}')

    def sw(t, cpu, pid, prev_tid):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = {cpu} }}, {{ pid = {pid}, '
                f'tid = {pid}, procname = "x", pid_ns = 77 }}, {{ prev_comm = "x", prev_tid = {prev_tid}, '
                f'prev_prio = 20, prev_state = 0, next_comm = "y", next_tid = 1, next_prio = 20 }}')

    lines = [conn_line(5.1 * i + 0.02 * (i % 3), 100, "miner", 18098) for i in range(11)]   # the beacon
    lines += [conn_line(5.0 * i, 200, "scraper", 9090) for i in range(11)]                  # periodic, idle
    lines += [conn_line(0.01 * i, 300, "svc", 3306) for i in range(500)]                    # busy service
    lines += [conn_line(t, 400, "bursty", 80) for t in (1, 2, 9, 10, 30, 31, 50)]           # irregular
    conn, who = read_connects(lines)
    sched = [sw(0.0, 0, 100, 100), sw(9.0, 0, 100, 100), sw(10.0, 0, 200, 200)]             # miner 0.9 core
    oncpu, span = read_cpu(sched)
    out = "\n".join(report(conn, who, oncpu, span))
    assert "RESOURCE ABUSE SHAPE: miner (pid 100" in out and "every 5.1 s" in out, out
    assert "2 (process, destination) pairs are periodic" in out, out
    out = "\n".join(report(conn, who, defaultdict(float), 10.0))                            # nobody heavy
    assert "NO BEACON FROM A CPU-HEAVY PROCESS (2 periodic" in out, out
    assert "NOTE: no --sched" in "\n".join(report(conn, who))
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: beacon.py <connect_slice.txt> <slice_seconds> [--sched <sched_slice.txt>]", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        conn, who = read_connects(f)
    oncpu, span = None, 0.0
    if "--sched" in sys.argv:
        with open(sys.argv[sys.argv.index("--sched") + 1], errors="replace") as f:
            oncpu, span = read_cpu(f)
    print("\n".join(report(conn, who, oncpu, span, float(sys.argv[2]))))
