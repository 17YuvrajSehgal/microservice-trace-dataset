#!/usr/bin/env python3
# sock_lag.py - how long a process waits for answers on its connections.
#
# THE TRAP THIS TOOL AVOIDS. A threaded program (mysqld, java) blocks INSIDE
# read() until the answer comes, so the read's duration is the answer time.
# But Go and Node use non-blocking sockets: read() returns instantly (with
# "try again"), the runtime parks in epoll, and reads only happen once data
# is already there. Every read looks instant even when the service is dying.
# Measured on a real victim: all reads 0.0 ms while every request took 500 ms.
#
# So this tool measures the REQUEST-TO-ANSWER GAP instead, which works for
# both kinds of runtime: on each connection (fd), the time from a completed
# WRITE (the request going out) to the next completed READ THAT RETURNED
# DATA (the answer coming back).
#
# Usage:
#   python3 sock_lag.py <slice.txt> <slice_seconds> <pid> [top]   one process, per fd
#   python3 sock_lag.py <slice.txt> <slice_seconds> all [top]     every process, summary
#
#   <slice.txt> made with dep_slice.sh (it keeps syscalls with their fd and ret)
#
# Compare a baseline slice with a fault slice:
#   - the victim is the process whose gap p50 jumps;
#   - the slow CONNECTION is the fd that carries the jump;
#   - the jump itself is the dependency's added delay.
# A gap can also include time the requester spent between requests, so read
# p50 rather than max, and trust a jump that baseline does not have.
import re
import sys
from collections import defaultdict

if len(sys.argv) < 4:
    print("usage: sock_lag.py <slice.txt> <slice_seconds> <pid|all> [top]", file=sys.stderr)
    sys.exit(1)
path, secs, target = sys.argv[1], float(sys.argv[2]), sys.argv[3]
top = int(sys.argv[4]) if len(sys.argv) > 4 else 10

READS = ("read", "readv", "recv", "recvfrom", "recvmsg")
WRITES = ("write", "writev", "send", "sendto", "sendmsg")
re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_sys = re.compile(r' syscall_(entry|exit)_([a-z0-9_]+):')
re_fd = re.compile(r'\{ fd = (\d+)')
re_ret = re.compile(r'\{ ret = (-?\d+)')

in_call = {}                  # tid -> (kind, fd) from the entry
pending = {}                  # (pid, fd) -> t of the request write
gaps = defaultdict(list)      # (pid, fd) -> [gap_ns]
nreads = defaultdict(int)     # (pid, fd) -> reads that returned data
pid_name = {}

with open(path, errors="replace") as f:
    for line in f:
        sm = re_sys.search(line)
        if not sm:
            continue
        name = sm.group(2)
        is_r, is_w = name in READS, name in WRITES
        if not (is_r or is_w):
            continue
        c = re_ctx.search(line)
        if not c:
            continue
        pid, tid = c.group(1), c.group(2)
        if target != "all" and pid != target:
            continue
        m = re_time.match(line)
        if not m:
            continue
        h, mi, s, fr = m.groups()
        t = ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1_000_000_000 + int(fr.ljust(9, '0'))
        pid_name[pid] = c.group(3)
        if sm.group(1) == 'entry':
            fm = re_fd.search(line)
            if fm:
                in_call[tid] = ('r' if is_r else 'w', fm.group(1))
            continue
        call = in_call.pop(tid, None)
        if call is None:
            continue
        rm = re_ret.search(line)
        ret = int(rm.group(1)) if rm else -1
        if ret <= 0:
            continue                      # no data moved: EAGAIN polls, errors
        kind, fd = call
        key = (pid, fd)
        if kind == 'w':
            if key not in pending:        # first write starts the clock
                pending[key] = t
        else:
            nreads[key] += 1
            t0 = pending.pop(key, None)
            if t0 is not None:
                gaps[key].append(t - t0)

if not gaps:
    print("no request-to-answer pairs found. Wrong pid, or the slice was cut with "
          "extract_slice.sh (which drops syscalls) - use dep_slice.sh.")
    sys.exit(0)


def pct(xs, q):
    return xs[min(len(xs) - 1, int(q * len(xs)))]


if target == "all":
    bypid = defaultdict(list)
    for (pid, fd), xs in gaps.items():
        bypid[pid].extend(xs)
    print("Request-to-answer gap per process (all connections together).")
    print("The victim of a slow dependency is the process whose p50 jumps against baseline.")
    print(f"{'pid':>8} {'name':<16}{'answers':>9}{'p50_ms':>9}{'p90_ms':>9}{'max_ms':>9}")
    rows = sorted(bypid.items(), key=lambda kv: -pct(sorted(kv[1]), .5))
    for pid, xs in rows[:top]:
        xs.sort()
        print(f"{pid:>8} {pid_name.get(pid,'?'):<16}{len(xs):>9}{pct(xs,.5)/1e6:>9.1f}"
              f"{pct(xs,.9)/1e6:>9.1f}{xs[-1]/1e6:>9.1f}")
else:
    print(f"Request-to-answer gaps of pid {target} ({pid_name.get(target,'?')}), "
          f"per connection (fd):")
    print(f"{'fd':>6} {'answers':>8} {'p50_ms':>9} {'p90_ms':>9} {'max_ms':>9} {'total_s':>9}")
    rows = sorted(gaps.items(), key=lambda kv: -sum(kv[1]))
    for (pid, fd), xs in rows[:top]:
        xs.sort()
        print(f"{fd:>6} {len(xs):>8} {pct(xs,.5)/1e6:>9.1f} {pct(xs,.9)/1e6:>9.1f} "
              f"{xs[-1]/1e6:>9.1f} {sum(xs)/1e9:>9.2f}")
    allx = sorted(g for xs in gaps.values() for g in xs)
    print(f"{'ALL':>6} {len(allx):>8} {pct(allx,.5)/1e6:>9.1f} {pct(allx,.9)/1e6:>9.1f} "
          f"{allx[-1]/1e6:>9.1f} {sum(allx)/1e9:>9.2f}")
print()
print("Read it:")
print("- SLOW DEPENDENCY: the gap p50 on one connection (or one process) sits near")
print("  the dependency's answer time, far above its own baseline. The fd names the")
print("  connection; wake_graph.py and victim_info.py help name who is on it.")
print("- All of a process's connections slow: the path or the host, not one dependency.")
print("- Gaps unchanged but fewer answers: the requester itself slowed down - look at")
print("  CPU (sched_budget.py) instead.")
