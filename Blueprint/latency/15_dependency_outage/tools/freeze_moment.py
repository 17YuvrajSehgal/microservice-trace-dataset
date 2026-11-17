#!/usr/bin/env python3
# freeze_moment.py - tell a FROZEN container from one that is merely idle or has finished.
#
# ns_silence.py finds a namespace that produces no events. Silence alone is not proof of a
# freeze: a service with no traffic is silent, and so is a helper that ended. Measured on
# all v2 runs, silence alone fires on about half of the Train Ticket runs.
#
# A freeze (docker pause, the cgroup freezer) has a moment that idleness does not have: the
# kernel makes EVERY thread of the container run once, so that it can park itself. In the
# trace, all threads of the namespace are scheduled out within about a millisecond, also the
# ones that had been asleep for minutes, and then none of them runs again. Measured on a
# paused JVM: 141 threads in 0.7 ms.
#
# An idle service goes quiet one thread at a time. A process that ends shows exits.
#
# Usage:
#   python3 freeze_moment.py <sched_slice.txt> <slice_seconds> [--ns PID_NS]
#   python3 freeze_moment.py --selftest
#
#   <sched_slice.txt>  must CONTAIN the moment the namespace went quiet, and at least 3 s
#        after it. Cut with:
#        extract_slice.sh TRACE DAY HH:MM:SS SECS out.txt 'sched_switch|sched_process_exit'
import re
import sys
from collections import defaultdict

MIN_SILENT_S = 3.0     # the namespace must stay quiet this long, up to the end of the slice
SWEEP_S = 0.05         # "at the same moment" = within this long before the last event
MIN_THREADS = 3        # with fewer threads "all of them" proves nothing
MIN_SHARE = 0.8        # share of the namespace's threads that must be in the sweep
DORMANT_S = 1.0        # a thread is "dormant" if it had not run for this long before the sweep
MIN_DORMANT = 3        # dormant threads that the sweep woke. A small program that just runs
                       # out of work also parks all its threads together, but those threads
                       # were all busy a moment before; a freeze wakes the sleeping ones too.
                       # Added after the sweep (a 3-9 thread proxy going idle read as frozen).

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def hms(t):
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"


def read(lines):
    # The context of sched_switch and sched_process_exit is the thread going out / exiting.
    last_out = defaultdict(dict)       # ns -> tid -> time of its last switch-out
    prev_out = defaultdict(dict)       # ns -> tid -> time of the switch-out before that
    start = None
    exits = defaultdict(list)          # ns -> [times of thread exits]
    names = defaultdict(lambda: defaultdict(int))
    end = None
    for line in lines:
        sw = ' sched_switch:' in line
        if not sw and ' sched_process_exit:' not in line:
            continue
        t, c, pn = tsec(line), re_ctx.search(line), re_pidns.search(line)
        if t is None:
            continue
        end = t
        start = t if start is None else start
        if not c or not pn or c.group(2) == '0':
            continue
        ns = pn.group(1)
        if sw:
            if c.group(2) in last_out[ns]:
                prev_out[ns][c.group(2)] = last_out[ns][c.group(2)]
            last_out[ns][c.group(2)] = t
            names[ns][c.group(3)] += 1
        else:
            exits[ns].append(t)
    return last_out, prev_out, exits, names, start, end


def report(last_out, prev_out, exits, names, start, end, only=None):
    rows = []
    for ns, tids in last_out.items():
        if only and ns != only:
            continue
        L = max(tids.values())
        if end - L < MIN_SILENT_S:
            continue
        sweep = [t for t in tids.values() if t >= L - SWEEP_S]
        # dormant = in the sweep, and before it not seen for DORMANT_S (or never in the slice)
        dormant = sum(1 for tid, t in tids.items() if t >= L - SWEEP_S
                      and t - prev_out[ns].get(tid, start) >= DORMANT_S)
        gone = sum(1 for t in exits.get(ns, ()) if t >= L - 1.0)
        rows.append((ns, max(names[ns], key=names[ns].get), len(tids), L, end - L,
                     len(sweep), (L - min(sweep)) * 1000, gone, dormant))
    rows.sort(key=lambda r: r[3])
    out = [f"namespaces that went quiet in this slice and stayed quiet for {MIN_SILENT_S:.0f} s or more: {len(rows)}",
           f"  {'pid_ns':>12} {'program':<16}{'threads':>8} {'last event':>14} {'quiet s':>8} {'in sweep':>9} {'dormant':>8} {'sweep ms':>9} {'exits':>6}"]
    for ns, nm, n, L, q, k, ms, gone, dm in rows:
        out.append(f"  {ns:>12} {nm:<16}{n:>8} {hms(L):>14} {q:>8.1f} {k:>9} {dm:>8} {ms:>9.2f} {gone:>6}")
    out.append(f"  in sweep = threads scheduled out in the last {SWEEP_S * 1000:.0f} ms before the namespace went quiet; "
               f"dormant = those of them that had not run for {DORMANT_S:.0f} s or more; exits = thread exits in its last second")
    hits = 0
    for ns, nm, n, L, q, k, ms, gone, dm in rows:
        if gone >= max(1, n // 2):
            out.append(f"VERDICT: EXITED AT {hms(L)}: ns {ns} ({nm}): {gone} thread exits in its last second - "
                       f"it ended or was killed, it is not frozen")
            hits += 1
        elif n >= MIN_THREADS and k >= MIN_SHARE * n and dm >= MIN_DORMANT:
            out.append(f"VERDICT: FROZEN AT {hms(L)}: ns {ns} ({nm}): {k} of its {n} threads were scheduled out "
                       f"within {ms:.1f} ms ({dm} of them had been asleep for {DORMANT_S:.0f} s or more) and none ran again in the remaining {q:.0f} s, no exit")
            hits += 1
    if not hits:
        why = "; ".join(f"ns {r[0]} ({r[1]}): {r[5]} of {r[2]} threads in the sweep, {r[8]} dormant" for r in rows[:4]) or "nothing went quiet"
        out.append(f"VERDICT: NO FREEZE MOMENT ({why}; a freeze needs {MIN_SHARE:.0%} of at least {MIN_THREADS} threads, {MIN_DORMANT} of them dormant)")
    return out


def selftest():
    def sw(t, tid, ns, nm="java"):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_switch: {{ cpu_id = 1 }}, {{ pid = {ns}, tid = {tid}, '
                f'procname = "{nm}", pid_ns = {ns}, net_ns = 1 }}, {{ prev_comm = "{nm}", prev_tid = {tid}, '
                f'prev_prio = 20, prev_state = 1, next_comm = "x", next_tid = 0, next_prio = 20 }}')

    def ex(t, tid, ns, nm):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_process_exit: {{ cpu_id = 1 }}, {{ pid = {ns}, tid = {tid}, '
                f'procname = "{nm}", pid_ns = {ns}, net_ns = 1 }}, {{ comm = "{nm}", tid = {tid}, prio = 20 }}')

    lines = []
    for i in range(400):                                             # 20 s of background, ns 1 never stops
        lines.append(sw(i * 0.05, 10 + i % 3, 1, "busy"))
    for i in range(40):                                              # ns 2: 3 of its 20 threads work, then a freeze
        lines.append(sw(i * 0.1, 200 + i % 3, 2))
    lines += [sw(5.0 + j * 0.00003, 200 + j, 2) for j in range(20)]  # all 20 threads within 0.6 ms
    for j in range(10):                                              # ns 3: goes idle one thread at a time
        lines.append(sw(1.0 + j * 0.4, 300 + j, 3, "idle"))
    for i in range(60):                                              # ns 5: 4 busy threads that all run out of work
        lines.append(sw(i * 0.05, 500 + i % 4, 5, "proxy"))
    lines += [sw(3.0 + j * 0.001, 500 + j, 5, "proxy") for j in range(4)]
    for j in range(4):                                               # ns 4: a helper that ends
        lines += [sw(6.0 + j * 0.001, 400 + j, 4, "helper"), ex(6.0 + j * 0.001 + 0.0001, 400 + j, 4, "helper")]
    lines.sort(key=tsec)
    out = "\n".join(report(*read(lines)))
    assert "FROZEN AT 10:00:05.001: ns 2 (java): 20 of its 20 threads were scheduled out within 0.6 ms (20 of them" in out, out
    assert "EXITED AT 10:00:06.003: ns 4 (helper): 4 thread exits" in out, out
    assert out.count("FROZEN AT") == 1 and " idle " in out and " proxy " in out, out   # listed, not a verdict
    out = "\n".join(report(*read(lines), only="3"))
    assert "NO FREEZE MOMENT (ns 3 (idle): 1 of 10 threads in the sweep, 1 dormant" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: freeze_moment.py <sched_slice.txt> <slice_seconds> [--ns PID_NS]", file=sys.stderr)
        sys.exit(1)
    only = sys.argv[sys.argv.index("--ns") + 1] if "--ns" in sys.argv else None
    with open(sys.argv[1], errors="replace") as f:
        res = read(f)
    print("\n".join(report(*res, only=only)))
