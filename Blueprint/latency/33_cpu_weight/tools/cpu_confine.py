#!/usr/bin/env python3
# cpu_confine.py - find a container that is restricted to fewer CPU cores than before.
#
# A cpuset (cores a container may run on) that is too small has no error and no throttling:
# the service is never stopped, its threads just all queue for the same core while the rest
# of the machine has room. The trace shows it directly: every scheduling event of the
# container carries the CPU it happened on.
#
# For each container (pid namespace) the tool counts, in a baseline slice and a fault slice:
#   CPUs      the cores that carry 99% of its time on a CPU
#   cores     how much CPU it used
#   CPU wait  thread-seconds per second its threads were ready and waiting for a core
#
# Usage:
#   python3 cpu_confine.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 cpu_confine.py --selftest
#
#   both slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 10 out.txt 'sched_switch|sched_waking|sched_wakeup'
import re
import sys
from collections import defaultdict

MIN_CORES = 0.2        # the container must use at least this much CPU in both slices to be judged
MIN_THREADS = 8        # ... and have this many threads (one busy thread sits on one core anyway)
MIN_BASE_CPUS = 4      # it ran on at least this many CPUs before
MAX_KEPT = 0.5         # ... and now runs on at most this share of them
COVER = 0.99           # "runs on" = the fewest CPUs that carry this share of its CPU time

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_cpu = re.compile(r'cpu_id = (\d+)')
re_ctx = re.compile(r'tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_sw = re.compile(r'prev_tid = (\d+), prev_prio = -?\d+, prev_state = (\d+), next_comm = "[^"]*", next_tid = (\d+)')
re_wk = re.compile(r'\{ comm = "[^"]*", tid = (\d+), prio')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    last = {}                                             # cpu -> time of the last switch
    oncpu = defaultdict(lambda: defaultdict(float))      # pid_ns -> cpu -> seconds
    tids = defaultdict(set)
    names = defaultdict(lambda: defaultdict(float))
    tid_ns, ready, wait_tid = {}, {}, defaultdict(float)
    idle = defaultdict(float)                             # cpu -> idle seconds
    start = end = None
    for line in lines:
        if ' sched_switch:' in line:
            t, cm, sw = tsec(line), re_cpu.search(line), re_sw.search(line)
            if t is None or not cm or not sw:
                continue
            start = t if start is None else start
            end = t
            cpu = cm.group(1)
            since = last.get(cpu, start)
            last[cpu] = t
            prev_tid, prev_state, next_tid = sw.groups()
            if prev_tid == '0':
                idle[cpu] += t - since
            else:
                pn, cx = re_pidns.search(line), re_ctx.search(line)
                if pn and cx:                             # the context of a switch is the thread going out
                    ns = pn.group(1)
                    oncpu[ns][cpu] += t - since
                    tids[ns].add(prev_tid)
                    names[ns][cx.group(2)] += t - since
                    tid_ns[prev_tid] = ns
                    if prev_state == '0':                 # still runnable: pushed off the core
                        ready[prev_tid] = t
            if next_tid in ready:
                wait_tid[next_tid] += t - ready.pop(next_tid)
        elif ' sched_waking:' in line or ' sched_wakeup:' in line:
            t, wk = tsec(line), re_wk.search(line)
            if t is not None and wk:
                ready.setdefault(wk.group(1), t)
    wait = defaultdict(float)
    for tid, s in wait_tid.items():
        if tid in tid_ns:
            wait[tid_ns[tid]] += s
    span = (end - start) if start is not None and end > start else 1.0
    return {"oncpu": oncpu, "tids": tids, "names": names, "wait": wait, "idle": idle, "ncpu": len(last), "span": span}


def cpus_used(percpu):
    tot = sum(percpu.values())
    acc, used = 0.0, []
    for cpu, s in sorted(percpu.items(), key=lambda kv: -kv[1]):
        used.append(cpu)
        acc += s
        if acc >= COVER * tot:
            break
    return used


def report(base, fault, secs):
    ncpu = max(1, fault["ncpu"])
    rows = []
    for ns, percpu in fault["oncpu"].items():
        if ns == '0' or ns not in base["oncpu"]:          # 0 = namespace could not be read
            continue
        fc, bc = sum(percpu.values()) / secs, sum(base["oncpu"][ns].values()) / secs
        if min(fc, bc) < MIN_CORES or len(fault["tids"][ns]) < MIN_THREADS:
            continue
        fu, bu = cpus_used(percpu), cpus_used(base["oncpu"][ns])
        nm = max(fault["names"][ns], key=fault["names"][ns].get)
        rows.append({"ns": ns, "name": nm, "threads": len(fault["tids"][ns]), "bu": len(bu), "fu": fu, "bc": bc, "fc": fc,
                     "bw": base["wait"].get(ns, 0.0) / secs, "fw": fault["wait"].get(ns, 0.0) / secs})
    rows.sort(key=lambda r: len(r["fu"]) / max(1, r["bu"]))
    out = [f"{ncpu} CPUs, slices of {secs:.0f} s. Containers with {MIN_THREADS}+ threads and {MIN_CORES}+ cores of CPU use in both slices:",
           f"  {'pid_ns':>12} {'program':<16} {'threads':>8} {'CPUs before':>12} {'CPUs now':>9} {'cores before':>13} {'cores now':>10} "
           f"{'CPU wait before':>16} {'CPU wait now':>13}"]
    for r in rows[:12]:
        out.append(f"  {r['ns']:>12} {r['name']:<16} {r['threads']:>8} {r['bu']:>12} {len(r['fu']):>9} {r['bc']:>13.2f} {r['fc']:>10.2f} "
                   f"{r['bw']:>16.2f} {r['fw']:>13.2f}")
    out.append(f"  CPUs = the fewest cores that carry {COVER:.0%} of the container's CPU time; CPU wait = thread-seconds per "
               "second its threads were ready and waiting for a core")
    hits = 0
    for r in rows:
        if r["bu"] >= MIN_BASE_CPUS and len(r["fu"]) <= MAX_KEPT * r["bu"]:
            other = [c for c in fault["idle"] if c not in r["fu"]]
            idle = sum(fault["idle"][c] for c in other) / (fault["span"] * max(1, len(other)))
            cl = ",".join(sorted(r["fu"], key=int))
            out.append(f"VERDICT: CONTAINER CONFINED TO FEW CPUS: {r['name']} (pid_ns {r['ns']}), {r['threads']} threads, runs on "
                       f"{len(r['fu'])} of {ncpu} CPUs (cpu {cl}), on {r['bu']} in the baseline; it uses {r['fc']:.2f} cores "
                       f"({r['bc']:.2f} before) and its threads wait {r['fw']:.2f} thread-seconds per second for a core "
                       f"({r['bw']:.2f} before), while the other CPUs are {idle:.0%} idle")
            hits += 1
    if not hits:
        low = rows[0] if rows else None
        why = (f"fewest: {low['name']} (pid_ns {low['ns']}) on {len(low['fu'])} CPUs, {low['bu']} before" if low
               else "no container is active in both slices")
        out.append(f"VERDICT: NO CONTAINER CONFINED TO FEW CPUS ({why}; a confined container ran on {MIN_BASE_CPUS}+ CPUs "
                   f"before and runs on at most {MAX_KEPT:.0%} of them now)")
    return out


def selftest():
    def sw(t, cpu, tid, ns, nm, state=1):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = {cpu} }}, {{ pid = {ns}, tid = {tid}, '
                f'procname = "{nm}", pid_ns = {ns} }}, {{ prev_comm = "{nm}", prev_tid = {tid}, prev_prio = 20, '
                f'prev_state = {state}, next_comm = "x", next_tid = 0, next_prio = 20 }}')

    def idle(t, cpu, nxt):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = {cpu} }}, {{ pid = 0, tid = 0, '
                f'procname = "swapper/{cpu}", pid_ns = 1 }}, {{ prev_comm = "swapper", prev_tid = 0, prev_prio = 20, '
                f'prev_state = 0, next_comm = "x", next_tid = {nxt}, next_prio = 20 }}')

    def slice_(confined):
        ls = []
        for i in range(2000):                      # 8 CPUs, 10 s, 5 ms ticks
            t = i * 0.005
            for k in range(4):                     # "java": 16 threads, 4 run per tick, 2 ms each
                tid = 100 + (i * 4 + k) % 16
                cpu = 7 if confined else (i + k) % 8
                off = k * 0.001 if confined else 0.0
                ls += [idle(t + off, cpu, tid), sw(t + off + 0.002 if not confined else t + off + 0.001, cpu, tid, 9, "java")]
            tid = 300 + i % 10                     # "node": 10 threads, spread over all CPUs in both slices
            ls += [idle(t + 0.0045, i % 8, tid), sw(t + 0.0049, i % 8, tid, 5, "node")]
        return sorted(ls, key=tsec)

    base = read(slice_(False))
    out = "\n".join(report(base, read(slice_(True)), 10))
    assert "CONTAINER CONFINED TO FEW CPUS: java (pid_ns 9), 16 threads, runs on 1 of 8 CPUs (cpu 7), on 8 in the baseline" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(base, base, 10))
    assert "NO CONTAINER CONFINED TO FEW CPUS" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: cpu_confine.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
