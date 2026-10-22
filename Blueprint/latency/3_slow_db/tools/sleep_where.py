#!/usr/bin/env python3
# sleep_where.py - WHERE does each process's sleep time go?
#
# A slow dependency does not make its victim wait for the CPU. The victim
# SLEEPS, inside the system call that talks to the dependency. So the wait
# table of sched_budget.py stays quiet, and this table is where the victim
# shows up instead: its sleep time piles up in SOCKET READS.
#
# For every process it splits sleeping time (state S) by the system call the
# thread was inside when it fell asleep:
#
#   sock_read   read/readv/recv/recvfrom/recvmsg - waiting for an answer
#               on a socket or pipe. THE slow-dependency column.
#   event_loop  epoll/poll/select - a server parked waiting for any work.
#               Normal and large; it is not suffering.
#   locks       futex - waiting for another thread to release a lock.
#   send        write/send family - blocked sending (full buffers).
#   timer       nanosleep - deliberate sleeping.
#   other       asleep in some other call.
#   none        asleep with no system call seen (kernel threads, gaps).
#
# D (disk-type sleep) is kept in its own column, whatever the call.
#
# Usage:
#   python3 sleep_where.py <slice.txt> <slice_seconds> [pid]
#
#   <slice.txt> made with dep_slice.sh (it keeps syscalls; extract_slice.sh
#   does not). [pid]: always show this process, even outside the top rows.
# Numbers are average sleeping THREADS over the slice (like sched_budget's
# S column, split up). Sorted by sock_read, because that is the question.
import re
import sys
from collections import defaultdict

if len(sys.argv) < 3:
    print("usage: sleep_where.py <slice.txt> <slice_seconds> [pid]", file=sys.stderr)
    sys.exit(1)
path, secs = sys.argv[1], float(sys.argv[2])
mark = sys.argv[3] if len(sys.argv) > 3 else None

BUCKET = {}
for n in ("read", "readv", "recv", "recvfrom", "recvmsg", "recvmmsg"):
    BUCKET[n] = "sock_read"
for n in ("epoll_wait", "epoll_pwait", "epoll_pwait2", "poll", "ppoll",
          "select", "pselect6"):
    BUCKET[n] = "event_loop"
BUCKET["futex"] = "locks"
for n in ("write", "writev", "sendto", "sendmsg", "sendmmsg"):
    BUCKET[n] = "send"
for n in ("nanosleep", "clock_nanosleep"):
    BUCKET[n] = "timer"
for n in ("connect", "accept", "accept4"):
    BUCKET[n] = "connect"

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_sw = re.compile(r'prev_tid = (\d+), prev_prio = \d+, prev_state = (\d+), next_comm = "[^"]*", next_tid = (\d+)')
re_wk = re.compile(r'\{ comm = "[^"]*", tid = (\d+), prio')
re_sys = re.compile(r' syscall_(entry|exit)_([a-z0-9_]+):')

cur_sys = {}             # tid -> syscall name the thread is inside
asleep = {}              # tid -> (kind, bucket, since)   kind: S or D
tid_pid = {}
pid_name = {}
acc = defaultdict(lambda: defaultdict(int))     # pid -> column -> ns

def close(tid, t):
    st = asleep.pop(tid, None)
    if st is None:
        return
    kind, bucket, since = st
    pid = tid_pid.get(tid)
    if pid is None:
        return
    if kind == 'D':
        acc[pid]['D'] += t - since
    else:
        acc[pid][bucket] += t - since

with open(path, errors="replace") as f:
    for line in f:
        m = re_time.match(line)
        if not m:
            continue
        h, mi, s, fr = m.groups()
        t = ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1_000_000_000 + int(fr.ljust(9, '0'))
        c = re_ctx.search(line)
        sm = re_sys.search(line)
        if sm:
            if c:
                tid = c.group(2)
                tid_pid[tid] = c.group(1)
                pid_name[c.group(1)] = c.group(3)
                if sm.group(1) == 'entry':
                    cur_sys[tid] = sm.group(2)
                else:
                    cur_sys.pop(tid, None)
            continue
        if ' sched_switch:' in line:
            sw = re_sw.search(line)
            if not sw:
                continue
            prev_tid, ps, next_tid = sw.groups()
            if c and prev_tid != '0':
                tid_pid[prev_tid] = c.group(1)
                pid_name[c.group(1)] = c.group(3)
            code = int(ps)
            base = code & 0xFF
            if prev_tid != '0':
                close(prev_tid, t)              # safety: no nested intervals
                if not (code & 0x100) and base in (1, 2):
                    kind = 'D' if base == 2 else 'S'
                    sysname = cur_sys.get(prev_tid)
                    bucket = BUCKET.get(sysname, 'other' if sysname else 'none')
                    asleep[prev_tid] = (kind, bucket, t)
            if next_tid != '0':
                close(next_tid, t)
        elif ' sched_waking:' in line or ' sched_wakeup' in line:
            wk = re_wk.search(line)
            if wk:
                close(wk.group(1), t)

n = secs * 1e9
COLS = ['sock_read', 'event_loop', 'locks', 'send', 'connect', 'timer',
        'other', 'none', 'D']

def row(pid):
    a = acc[pid]
    return [pid, pid_name.get(pid, '?')] + [a[c] / n for c in COLS]

rows = sorted((row(p) for p in acc), key=lambda r: r[2], reverse=True)
show = rows[:12]
if mark and mark in acc and mark not in [r[0] for r in show]:
    show.append(row(mark))

print("Average sleeping threads over the slice, split by WHERE they slept.")
print("A slow dependency piles up in sock_read. event_loop is normal idling.")
print(f"{'pid':>8} {'name':<16}" + "".join(f"{c:>11}" for c in COLS))
for r in show:
    print(f"{r[0]:>8} {r[1]:<16}" + "".join(f"{v:>11.2f}" for v in r[2:]))
