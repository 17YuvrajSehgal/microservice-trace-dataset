#!/usr/bin/env python3
# mem_growth.py - find a process whose memory only grows (a leak, or a cache with no limit).
#
# A process gets memory from the kernel in two ways, and both are system calls:
#   brk    moves the end of the heap; the return value is the new end
#   mmap   maps a new anonymous region; munmap gives one back
# A healthy service reaches a steady size: it asks and gives back in turn. A leak asks in
# every second and gives nothing back.
#
# Usage:
#   python3 mem_growth.py <syscall_slice.txt> <slice_seconds>
#   python3 mem_growth.py --selftest
#
#   <syscall_slice.txt>  30 s or more, cut with:
#        extract_slice.sh TRACE DAY HH:MM:SS 30 out.txt \
#          'syscall_exit_brk|syscall_entry_mmap|syscall_entry_munmap|sched_process_fork'
import re
import sys
from collections import defaultdict

MIN_MB_S = 0.5         # net growth of one process, MB per second over the slice
MIN_GROW_SECS = 0.8    # share of the seconds in which it grew
MAX_ONE_STEP = 0.5     # no single second holds more than this share of the growth (a start-up
                       # or one big allocation is not a leak)
MIN_KEPT = 0.1         # it keeps at least this share of what it asked for. A JVM asks for and
                       # gives back about 2 GB in 30 s and keeps 1% (measured on healthy runs);
                       # added after the first sweep
THREAD_MB = 2          # growth of up to this much per thread started is thread stacks: work is
                       # piling up, nothing leaks. Measured: a JVM whose dependency was frozen
                       # grew 333 MB while starting 1,565 threads; added after the second sweep
BRK_JUMP = 2**30       # a heap end that moves more than this in one call is a new program in
                       # the same pid (exec), not growth

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_ret = re.compile(r'ret = (-?\d+)')
re_mmap = re.compile(r'len = (\d+), prot = (\d+), flags = (\d+), fd = (-?\d+)')
re_len = re.compile(r'len = (\d+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    grow = defaultdict(lambda: defaultdict(int))   # pid -> second -> net bytes
    brk = {}                                       # pid -> last heap end
    parts = defaultdict(lambda: [0, 0, 0])         # pid -> [brk net, mmap, munmap] bytes
    info = {}
    started = defaultdict(int)                     # pid -> threads and processes it started
    t0 = None
    for line in lines:
        kind = (1 if ' syscall_exit_brk:' in line else 2 if ' syscall_entry_mmap:' in line
                else 3 if ' syscall_entry_munmap:' in line else 4 if ' sched_process_fork:' in line else 0)
        if not kind:
            continue
        t, c = tsec(line), re_ctx.search(line)
        if t is None or not c:
            continue
        t0 = t if t0 is None else t0
        pid = c.group(1)
        if kind == 4:
            started[pid] += 1
            continue
        pn = re_pidns.search(line)
        info[pid] = (c.group(2), pn.group(1) if pn else "?")
        n = 0
        if kind == 1:
            r = re_ret.search(line)
            if not r:
                continue
            end = int(r.group(1))
            n = end - brk.get(pid, end)            # the first brk of a pid only sets the start
            brk[pid] = end
            if abs(n) > BRK_JUMP:
                n = 0
            parts[pid][0] += n
        elif kind == 2:
            m = re_mmap.search(line)
            # anonymous and writable only: a PROT_NONE mapping is an address reservation
            if m and int(m.group(3)) & 0x20 and int(m.group(2)) & 2:
                n = int(m.group(1))
                parts[pid][1] += n
        else:
            m = re_len.search(line)
            if m:
                n = -int(m.group(1))
                parts[pid][2] -= n
        if n:
            grow[pid][int(t - t0)] += n
    return grow, parts, info, started


def report(grow, parts, info, started, secs):
    n_sec = max(1, int(round(secs)))
    rows = []
    for pid, sec in grow.items():
        net = sum(sec.values())
        up = sum(1 for v in sec.values() if v > 0)
        rows.append((net, pid, up / n_sec, max(sec.values()) / net if net > 0 else 0.0))
    rows.sort(reverse=True)

    def kept(pid, net):
        asked = net + parts[pid][2]
        return net / asked if asked > 0 and net > 0 else 0.0
    out = [f"Memory asked from the kernel in this {secs:.0f} s slice, per process (brk and anonymous mmap, minus munmap)",
           f"  {'pid':>8} {'pid_ns':>12} {'name':<16}{'net MB':>9}{'MB/s':>7}{'brk MB':>8}{'mmap MB':>9}{'munmap MB':>11}"
           f"{'secs growing':>14}{'largest sec':>13}{'kept':>6}{'started':>9}"]
    for net, pid, up, big in rows[:8]:
        nm, ns = info[pid]
        b, m, u = parts[pid]
        out.append(f"  {pid:>8} {ns:>12} {nm:<16}{net / 2**20:>9.1f}{net / 2**20 / secs:>7.2f}{b / 2**20:>8.1f}{m / 2**20:>9.1f}"
                   f"{u / 2**20:>11.1f}{up:>14.0%}{big:>13.0%}{kept(pid, net):>6.0%}{started.get(pid, 0):>9}")
    out.append("  secs growing = share of the seconds with net growth; largest sec = share of the net growth in one second; "
               "kept = net growth as a share of what it asked for; started = threads and processes it started")
    hits = 0
    for net, pid, up, big in rows:
        if net / 2**20 / secs >= MIN_MB_S and up >= MIN_GROW_SECS and big <= MAX_ONE_STEP and kept(pid, net) >= MIN_KEPT:
            nm, ns = info[pid]
            if net <= started.get(pid, 0) * THREAD_MB * 2**20:
                out.append(f"VERDICT: MEMORY GROWS WITH NEW THREADS: {nm} (pid {pid}, pid_ns {ns}) took {net / 2**20:.0f} MB more "
                           f"in {secs:.0f} s and started {started[pid]} threads - requests are piling up, this is not a leak")
                hits += 1
                continue
            out.append(f"VERDICT: MEMORY ONLY GROWS: {nm} (pid {pid}, pid_ns {ns}) took {net / 2**20:.0f} MB more in {secs:.0f} s "
                       f"({net / 2**20 / secs:.1f} MB/s), growing in {up:.0%} of the seconds, "
                       f"{parts[pid][2] / 2**20:.0f} MB given back, {started.get(pid, 0)} threads started")
            hits += 1
    if not hits:
        why = "nothing grew"
        if rows and rows[0][0] > 0:
            net, pid, up, big = rows[0]
            why = (f"largest: {info[pid][0]} +{net / 2**20:.1f} MB, growing in {up:.0%} of the seconds, "
                   f"{big:.0%} of it in one second, keeps {kept(pid, net):.0%}")
        out.append(f"VERDICT: NO STEADY MEMORY GROWTH ({why}; the bars are {MIN_MB_S} MB/s, {MIN_GROW_SECS:.0%} of the seconds, "
                   f"at most {MAX_ONE_STEP:.0%} in one second, {MIN_KEPT:.0%} kept)")
    return out


def selftest():
    def ev(t, pid, nm, what):
        return (f'[10:00:{t:012.9f}] (+0.0) h {what[0]}: {{ cpu_id = 1 }}, {{ pid = {pid}, tid = {pid}, '
                f'procname = "{nm}", pid_ns = {pid} }}, {{ {what[1]} }}')

    ls = []
    for i in range(300):                                   # leak: the heap end moves up 400 kB ten times a second
        ls.append(ev(i * 0.1, 5, "node", ("syscall_exit_brk", f"ret = {10**9 + i * 400_000}")))
    for i in range(30):                                    # healthy: maps 81 MB and gives 80 back every second
        ls += [ev(i + 0.2, 6, "java", ("syscall_entry_mmap", "addr = 0x0, len = 84934656, prot = 3, flags = 34, fd = -1, offset = 0")),
               ev(i + 0.7, 6, "java", ("syscall_entry_munmap", "addr = 0x1, len = 83886080"))]
    ls += [ev(1.0, 9, "sh", ("syscall_exit_brk", "ret = 1000")), ev(1.1, 9, "sh", ("syscall_exit_brk", f"ret = {2**45}"))]   # exec
    ls.append(ev(3.0, 7, "stress-ng-vm", ("syscall_entry_mmap", "addr = 0x0, len = 8589934592, prot = 3, flags = 34, fd = -1, offset = 0")))
    for i in range(300):                                   # pile-up: one thread and its 1 MB stack, ten times a second
        ls += [ev(i * 0.1, 8, "tomcat", ("sched_process_fork", "parent_comm = x, child_tid = 1")),
               ev(i * 0.1, 8, "tomcat", ("syscall_entry_mmap", "addr = 0x0, len = 1048576, prot = 3, flags = 34, fd = -1, offset = 0"))]
    ls.sort(key=tsec)
    out = "\n".join(report(*read(ls), 30))
    assert "MEMORY ONLY GROWS: node (pid 5, pid_ns 5) took 114 MB more in 30 s (3.8 MB/s), growing in 100% of the seconds" in out, out
    assert "MEMORY GROWS WITH NEW THREADS: tomcat (pid 8, pid_ns 8) took 300 MB more in 30 s and started 300 threads" in out, out
    assert out.count("VERDICT") == 2 and " sh " not in out, out
    out = "\n".join(report(*read([l for l in ls if "node" not in l and "tomcat" not in l]), 30))
    assert "NO STEADY MEMORY GROWTH (largest: stress-ng-vm +8192.0 MB, growing in 3% of the seconds, 100% of it in one second, keeps 100%" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: mem_growth.py <syscall_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        res = read(f)
    print("\n".join(report(*res, float(sys.argv[2]))))
