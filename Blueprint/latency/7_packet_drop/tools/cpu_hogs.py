#!/usr/bin/env python3
# cpu_hogs.py - who is eating the CPU, and who runs while the victim waits.
#
# Two questions, one pass over the scheduling events:
#   1. Which processes used the most CPU time in this slice? (the hogs)
#   2. While the victim was ready-but-waiting, what were the CPUs doing?
#      Running an aggressor? Or sitting idle?
#
# That second answer is the heart of the noisy-neighbor check:
#   - NEIGHBOR: while the victim waits, the CPUs are BUSY, and mostly with
#     one process or one group of processes. That group is the aggressor.
#   - CAP: while the victim waits, much of the CPU is IDLE. Nobody took the
#     CPU away - the kernel just refused to give it to the victim (a quota).
#   - OVERLOAD: the CPUs are busy with MANY different processes, no single
#     group dominating, and other victims wait too.
#
# Usage:
#   python3 cpu_hogs.py <slice.txt> <slice_seconds> [victim_pid]
#
#   <slice.txt>   text file of scheduling events (made with extract_slice.sh)
#   [victim_pid]  with a victim, part 2 is printed; without, only the hogs
import re
import sys
from collections import defaultdict

if len(sys.argv) < 3:
    print("usage: cpu_hogs.py <slice.txt> <slice_seconds> [victim_pid]", file=sys.stderr)
    sys.exit(1)
path, secs = sys.argv[1], float(sys.argv[2])
victim = sys.argv[3] if len(sys.argv) > 3 else None

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_ctx = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"')
re_sw = re.compile(r'prev_tid = (\d+), prev_prio = \d+, prev_state = (\d+), next_comm = "([^"]*)", next_tid = (\d+)')
re_wk = re.compile(r'\{ comm = "[^"]*", tid = (\d+), prio')

occupant = {}            # cpu -> tid currently on it (0 = idle)
tid_info = {}            # tid -> (pid, procname), learned at switch-out
next_name = {}           # tid -> name, learned from next_comm at switch-in
on_since = {}            # (cpu) -> since_ns for the current occupant
on_cpu = defaultdict(int)       # tid -> ns on cpu
vstate = {}              # victim tid -> 'wait' | None
n_waiting = 0            # victim tids currently waiting
wait_ns = 0              # total victim wait time (wall, any tid waiting)
while_wait = defaultdict(int)   # tid (or 'idle') -> cpu-ns while the victim waited
last_t = None
cpus = set()


def tick(t):
    """Advance the clock: charge [last_t, t) to each CPU's occupant."""
    global last_t
    if last_t is None:
        last_t = t
        return
    dt = t - last_t
    last_t = t
    if dt <= 0:
        return
    for c in cpus:
        tid = occupant.get(c, '0')
        on_cpu[tid] += dt
        if victim is not None and n_waiting > 0:
            while_wait[tid if tid != '0' else 'idle'] += dt


with open(path, errors="replace") as f:
    for line in f:
        if ' sched_switch:' not in line and ' sched_waking:' not in line \
                and ' sched_wakeup' not in line:
            continue
        m = re_time.match(line)
        cm = re_cpu.search(line)
        if not m or not cm:
            continue
        h, mi, s, fr = m.groups()
        t = ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1_000_000_000 + int(fr.ljust(9, '0'))
        cpu = cm.group(1)
        cpus.add(cpu)
        tick(t)
        if ' sched_switch:' in line:
            c, sw = re_ctx.search(line), re_sw.search(line)
            if not sw:
                continue
            prev_tid, ps, next_comm, next_tid = sw.groups()
            if c and prev_tid != '0':
                tid_info[prev_tid] = (c.group(1), c.group(2))
            if next_tid != '0':
                next_name.setdefault(next_tid, next_comm)
            occupant[cpu] = next_tid
            if victim is not None:
                # victim thread switched OUT while still runnable -> it starts waiting
                code = int(ps)
                vp = tid_info.get(prev_tid, (None,))[0]
                if vp == victim:
                    if (code & 0x100) or (code & 0xFF) == 0:
                        if vstate.get(prev_tid) != 'wait':
                            vstate[prev_tid] = 'wait'
                            n_waiting += 1
                    elif vstate.get(prev_tid) == 'wait':
                        vstate[prev_tid] = None
                        n_waiting -= 1
                # victim thread switched IN -> it stops waiting
                if vstate.get(next_tid) == 'wait':
                    vstate[next_tid] = None
                    n_waiting -= 1
        else:                       # sched_waking / sched_wakeup
            wk = re_wk.search(line)
            if victim is not None and wk:
                tid = wk.group(1)
                if tid_info.get(tid, (None,))[0] == victim \
                        and vstate.get(tid) != 'wait':
                    vstate[tid] = 'wait'
                    n_waiting += 1


def name_of(tid):
    if tid in tid_info:
        return tid_info[tid][1]
    return next_name.get(tid, "tid " + tid)


def pid_of(tid):
    return tid_info.get(tid, (None,))[0]


# ---- part 1: the hogs -------------------------------------------------------
total = secs * 1e9 * max(1, len(cpus))
by_name = defaultdict(lambda: [0, set()])        # name -> [ns, set of pids]
for tid, ns in on_cpu.items():
    if tid == '0':
        continue
    nm = name_of(tid)
    by_name[nm][0] += ns
    p = pid_of(tid)
    if p:
        by_name[nm][1].add(p)
busy = sum(ns for tid, ns in on_cpu.items() if tid != '0')
print(f"{len(cpus)} CPUs, slice {secs:.0f} s. CPU busy {busy/total:.0%}, idle {1-busy/total:.0%}.")
print()
print(f"Top CPU users (grouped by process name):")
print(f"{'name':<18}{'procs':>6}{'on-CPU s':>10}{'share of all CPU':>18}")
rows = sorted(by_name.items(), key=lambda kv: -kv[1][0])
for nm, (ns, pids) in rows[:10]:
    print(f"{nm:<18}{max(1, len(pids)):>6}{ns/1e9:>10.2f}{ns/total:>17.0%}")

# ---- part 2: while the victim waited ---------------------------------------
if victim is not None:
    tw = sum(while_wait.values())
    if tw == 0:
        print(f"\nvictim {victim}: no waiting time found in this slice. Wrong pid, or it "
              f"never waited here - sched_budget.py shows who waited.")
        sys.exit(0)
    vw = defaultdict(int)
    for tid, ns in while_wait.items():
        vw['idle' if tid == 'idle' else name_of(tid)] += ns
    print(f"\nWhile victim {victim} ({name_of(victim)}) had a thread ready-but-waiting,")
    print(f"the CPUs were spending their time on:")
    for nm, ns in sorted(vw.items(), key=lambda kv: -kv[1])[:8]:
        marker = "  <- idle while the victim waited" if nm == 'idle' else ""
        print(f"  {nm:<18}{ns/tw:>6.0%}{marker}")
    print()
    print("Read it:")
    print("- NEIGHBOR: one process (or one group, e.g. many workers with the same")
    print("  name) takes most of this time, and idle is small. That group is the")
    print("  aggressor - name it.")
    print("- CAP: idle is a large share. Nobody took the CPU; a quota held the")
    print("  victim back. Check with cpu_ceiling.py.")
    print("- OVERLOAD: many unrelated names share the time, idle is small, and")
    print("  other processes wait too (sched_budget.py shows them).")
