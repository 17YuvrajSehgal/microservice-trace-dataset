"""
sched_budget.py - time budget per process for one slice of scheduling events.

Usage:
    python3 sched_budget.py <sched_events.txt> <slice_seconds> [pid_to_always_show]

Input:
    A slice file made by extract_slice.sh (sched_switch and sched_waking lines).

Output:
    The 12 processes with the most waiting time, plus the pid you ask for.
    run      average number of CPU cores in use
    wait     average number of threads that were ready but had no CPU
    preempt  the part of wait that came from being switched out while still runnable
    S        average number of threads asleep (event, lock, timer, network)
    D        average number of threads in disk-type sleep
    >=1ms, >=10ms, >=50ms   how many single waits for a CPU lasted at least that long
    max_ms   the longest single wait for a CPU

prev_state codes of sched_switch (the script prints every code it saw):
    0      runnable (gave up the CPU but still wants it)
    1      S, sleeping
    2      D, disk-type sleep
    4, 8   stopped, traced
    16, 32 exiting (dead, zombie)
    64     parked
    128    I, idle sleep (kernel worker threads)
    256    flag: preempted while runnable (counted as waiting)
    Codes other than 0, 1, 2 and 256 are counted as "other sleep". They are
    not shown in a column, but their wake-up waits still count in wait.
"""
import re, sys
from collections import defaultdict

if len(sys.argv) < 3:
    raise SystemExit(__doc__)
path, secs = sys.argv[1], float(sys.argv[2])
mark = sys.argv[3] if len(sys.argv) > 3 else None   # a pid to always show

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx  = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"')
re_sw   = re.compile(r'prev_tid = (\d+), prev_prio = \d+, prev_state = (\d+), next_comm = "[^"]*", next_tid = (\d+)')
re_wk   = re.compile(r'\{ comm = "[^"]*", tid = (\d+), prio')

state = {}   # tid -> (kind, since_ns). kinds: run, rqP, rqW, S, D, O
who = {}     # tid -> (pid, procname)
names = {}
acc = defaultdict(lambda: defaultdict(int))   # pid -> kind -> ns
big = defaultdict(lambda: [0, 0, 0, 0])       # pid -> [>=1ms, >=10ms, >=50ms, max_ns]
codes = defaultdict(int)

def close(tid, t):
    st, w = state.get(tid), who.get(tid)
    if st is None or w is None:
        return
    kind, since = st
    d = t - since
    pid = w[0]
    acc[pid][kind] += d
    if kind in ('rqP', 'rqW'):
        b = big[pid]
        if d >= 1_000_000:  b[0] += 1
        if d >= 10_000_000: b[1] += 1
        if d >= 50_000_000: b[2] += 1
        if d > b[3]: b[3] = d

with open(path) as f:
    for line in f:
        m = re_time.match(line)
        if not m:
            continue
        h, mi, s, fr = m.groups()
        t = ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1_000_000_000 + int(fr.ljust(9, '0'))
        if ' sched_switch:' in line:
            c, sw = re_ctx.search(line), re_sw.search(line)
            if not c or not sw:
                continue
            pid, pname = c.groups()
            prev_tid, ps, next_tid = sw.groups()
            if prev_tid != '0':
                who[prev_tid] = (pid, pname)
                names[pid] = pname
                if state.get(prev_tid, ('',))[0] == 'run':
                    close(prev_tid, t)
                code = int(ps)
                codes[code] += 1
                # prev_state low bits are the base sleep state; 0x100 (256) is
                # the kernel's "preempted while runnable" flag (TASK_REPORT_MAX)
                # on newer kernels (e.g. 7.0.0-gcp). Both code 0 and the 0x100
                # flag mean "still wants CPU" -> runnable wait. Mask the flag off
                # to read the base state (S/D). Before this, 256 fell through to
                # 'O' and all CFS-throttle wait was silently dropped.
                base = code & 0xFF
                kind = 'rqP' if (code & 0x100) or base == 0 else 'S' if base == 1 else 'D' if base == 2 else 'O'
                state[prev_tid] = (kind, t)
            if next_tid != '0':
                if state.get(next_tid, ('',))[0] != 'run':
                    close(next_tid, t)
                state[next_tid] = ('run', t)
        elif ' sched_waking:' in line:
            wk = re_wk.search(line)
            if not wk:
                continue
            tid = wk.group(1)
            st = state.get(tid)
            if st and st[0] in ('S', 'D', 'O'):
                close(tid, t)
                state[tid] = ('rqW', t)

n = secs * 1e9
def row(pid):
    a, b = acc[pid], big[pid]
    return (pid, names.get(pid, '?'), a['run'] / n, (a['rqP'] + a['rqW']) / n,
            a['rqP'] / n, a['S'] / n, a['D'] / n, b[0], b[1], b[2], b[3] / 1e6)

rows = sorted((row(p) for p in acc if p != '0'), key=lambda r: r[3], reverse=True)
show = rows[:12]
if mark and mark in acc and mark not in [r[0] for r in show]:
    show.append(row(mark))

print("prev_state codes seen:", dict(codes))
print(f"{'pid':>8} {'name':<16}{'run':>7}{'wait':>7}{'preempt':>8}{'S':>8}{'D':>7}{'>=1ms':>8}{'>=10ms':>8}{'>=50ms':>8}{'max_ms':>9}")
for r in show:
    print(f"{r[0]:>8} {r[1]:<16}{r[2]:>7.2f}{r[3]:>7.2f}{r[4]:>8.2f}{r[5]:>8.1f}{r[6]:>7.2f}{r[7]:>8}{r[8]:>8}{r[9]:>8}{r[10]:>9.1f}")
