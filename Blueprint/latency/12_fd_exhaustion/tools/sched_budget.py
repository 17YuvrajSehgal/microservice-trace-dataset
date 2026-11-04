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
# Two trace shapes. A microservice host puts a context block `{ pid = P, tid = T, procname = "X" }`
# (or `{ vtid = T, vpid = P, procname = "X" }`) before the payload. A switch/router trace has no
# context block at all and prints prev_state as an enum `( "TASK_INTERRUPTIBLE" : container = 1 )`.
# Without context one row = one thread (pid := tid) named by its comm. Both shapes parse here;
# the old regexes matched only the first and printed an empty table on the second.
re_ctx  = re.compile(r'\bv?pid = (\d+),[^}]*procname = "([^"]*)"')
re_sw   = re.compile(r'prev_comm = "([^"]*)", prev_tid = (\d+), prev_prio = -?\d+, '
                     r'prev_state = (?:\([^()]*?container = )?(\d+)\s*\)?, next_comm = "[^"]*", next_tid = (\d+)')
re_wk   = re.compile(r'\{ comm = "[^"]*", tid = (\d+), prio')
re_cpu  = re.compile(r'cpu_id = (\d+)')
re_tcpu = re.compile(r'target_cpu = (\d+)')
ctx_seen = False
# A CPU with a runnable thread waiting for it cannot be silent. A wait that overlaps a period
# where its CPU shows no event at all for >= 0.5 s is lost trace data (snapshot buffers,
# discarded events) or a stalled CPU, not scheduling latency - measured: 1-9 s "waits" on
# switch traces that were holes. Such waits are counted apart and reported, not in the table.
GAP_NS = 500_000_000
last_cpu_t = {}                        # cpu -> last event seen there
gaps = defaultdict(list)               # cpu -> [(since, until)] silent periods
skipped = [0, 0]                       # [count, ns] of waits that overlapped a hole

state = {}   # tid -> (kind, since_ns, cpu). kinds: run, rqP, rqW, S, D, O
who = {}     # tid -> (pid, procname)
names = {}
acc = defaultdict(lambda: defaultdict(int))   # pid -> kind -> ns
big = defaultdict(lambda: [0, 0, 0, 0])       # pid -> [>=1ms, >=10ms, >=50ms, max_ns]
codes = defaultdict(int)

def close(tid, t):
    st, w = state.get(tid), who.get(tid)
    if st is None or w is None:
        return
    kind, since, cpu = st
    d = t - since
    pid = w[0]
    if kind in ('rqP', 'rqW') and d >= GAP_NS and \
            any(g0 < t and g1 > since for g0, g1 in gaps.get(cpu, ())):
        skipped[0] += 1
        skipped[1] += d
        return
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
        cm = re_cpu.search(line)
        cpu = cm.group(1) if cm else '?'
        lt = last_cpu_t.get(cpu)
        if lt is not None and t - lt >= GAP_NS:
            gaps[cpu].append((lt, t))
        last_cpu_t[cpu] = t
        if ' sched_switch:' in line:
            c, sw = re_ctx.search(line), re_sw.search(line)
            if not sw:
                continue
            prev_comm, prev_tid, ps, next_tid = sw.groups()
            if c:
                pid, pname = c.groups()
                ctx_seen = True
            else:
                pid, pname = prev_tid, prev_comm
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
                state[prev_tid] = (kind, t, cpu)
            if next_tid != '0':
                if state.get(next_tid, ('',))[0] != 'run':
                    close(next_tid, t)
                state[next_tid] = ('run', t, cpu)
        elif ' sched_waking:' in line:
            wk = re_wk.search(line)
            if not wk:
                continue
            tid = wk.group(1)
            st = state.get(tid)
            if st and st[0] in ('S', 'D', 'O'):
                close(tid, t)
                tc = re_tcpu.search(line)
                state[tid] = ('rqW', t, tc.group(1) if tc else cpu)

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
if skipped[0]:
    print(f"trace holes: {skipped[0]} waits ({skipped[1] / 1e9:.1f} s in all) overlapped a period "
          f"where their CPU showed no event for >= 0.5 s - lost trace data or a stalled CPU, not "
          f"scheduling latency; they are left out of the table")
if not ctx_seen:
    print("identity: this trace has no pid context - one row = one THREAD (the pid column is its "
          "tid), named by its comm. Pass that tid to the other tools where they ask for a pid.")
print(f"{'pid':>8} {'name':<16}{'run':>7}{'wait':>7}{'preempt':>8}{'S':>8}{'D':>7}{'>=1ms':>8}{'>=10ms':>8}{'>=50ms':>8}{'max_ms':>9}")
for r in show:
    print(f"{r[0]:>8} {r[1]:<16}{r[2]:>7.2f}{r[3]:>7.2f}{r[4]:>8.2f}{r[5]:>8.1f}{r[6]:>7.2f}{r[7]:>8}{r[8]:>8}{r[9]:>8}{r[10]:>9.1f}")
