#!/usr/bin/env python3
"""
futex_hang.py - threads that went into a lock wait and never came back.

Usage:
    python3 futex_hang.py <slice.txt> <secs> [--min-s 5] [--top 10]

Input:
    A LONG slice (60 s or more) cut with extract_slice.sh and the pattern
      'syscall_entry_futex|syscall_exit_futex|sched_process_fork|sched_process_exit'
    Works with or without the microservice context block.

What it finds:
    A thread that enters futex(FUTEX_WAIT) WITHOUT a timeout (utime = 0) and has no matching
    exit before the slice ends is still blocked on that lock. Waits that started less than
    --min-s seconds before the end are ignored (they may simply be in progress), and so are
    timed waits (they return by themselves). Waits that END are the job of futex_wait.py;
    a deadlock never ends, so that tool cannot see it - this one can.
    Per process it reports: threads hung, how many of them were born inside the slice, how
    soon after birth they hung, how many distinct lock addresses they wait on, and whether
    the number of hung threads keeps GROWING across the slice (thirds).

Verdict:
    VERDICT: DEADLOCK: <comm> (pid P, ns N): K threads blocked forever in futex (no timeout) on
             L distinct locks, longest X s; hung threads keep appearing (a/b/c per third) ...
        - K >= 2 threads that were CREATED inside the slice and hung within 1 s of birth,
          L >= 2 (a deadlock needs two locks), longest >= --min-s
        Threads that already existed and sit parked with no timeout are idle pool threads
        (every JVM and Go service has them) and only appear as NOTE lines.
    NOTE: HUNG ON ONE LOCK: ... - threads stuck on a single address (a lost wake-up or a holder
          that died); a finding, not a deadlock
    NO HUNG LOCK WAITS (...)

Measured (Sock Shop v2, deadlock_aggressive_steady_r1): a new thread pair every 5 s; each thread
makes one last futex wait with utime = 0 within a millisecond of being created and never returns.
"""
import re
import sys
from collections import Counter, defaultdict

re_ts = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ev = re.compile(r'\] \(\+[^)]*\) \S+ (\w+):')
re_tid = re.compile(r'\btid = (\d+)')
re_pid = re.compile(r'\b(?:v?pid) = (\d+)')
re_ns = re.compile(r'\bpid_ns = (\d+)')
re_proc = re.compile(r'procname = "([^"]*)"')
re_op = re.compile(r'\bop = (\d+)')
re_ut = re.compile(r'\butime = (\d+)')
re_ua = re.compile(r'\buaddr = (\d+)')
re_ctid = re.compile(r'child_tid = (\d+)')

FUTEX_WAIT_OPS = {0, 9}
FRESH_S = 1.0                 # born and hung within this many seconds = a new thread that blocked at once       # FUTEX_WAIT, FUTEX_WAIT_BITSET (low bits of op, after PRIVATE/CLOCK flags)


def ts(line):
    m = re_ts.match(line)
    if not m:
        return None
    h, mi, s, f = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(f.ljust(9, "0")) / 1e9


def analyse(path):
    open_wait = {}            # tid -> (t_entry, uaddr, pid, comm, ns)
    born = {}                 # tid -> t
    first = last = None
    with open(path, errors="replace") as f:
        for line in f:
            m = re_ev.search(line)
            if not m:
                continue
            t = ts(line)
            if t is None:
                continue
            first = t if first is None else first
            last = t
            ev = m.group(1)
            tm = re_tid.search(line)
            tid = tm.group(1) if tm else None
            if ev == "sched_process_fork":
                c = re_ctid.search(line)
                if c:
                    born[c.group(1)] = t
            elif ev == "syscall_entry_futex" and tid:
                op = int(re_op.search(line).group(1)) if re_op.search(line) else -1
                ut = int(re_ut.search(line).group(1)) if re_ut.search(line) else 1
                if (op & 127) in FUTEX_WAIT_OPS and ut == 0:
                    pm, nm, pr = re_pid.search(line), re_ns.search(line), re_proc.search(line)
                    open_wait[tid] = (t, re_ua.search(line).group(1) if re_ua.search(line) else "?",
                                      pm.group(1) if pm else "?", pr.group(1) if pr else "?",
                                      nm.group(1) if nm else "-")
                else:
                    open_wait.pop(tid, None)
            elif ev in ("syscall_exit_futex", "sched_process_exit") and tid:
                open_wait.pop(tid, None)
    return open_wait, born, first, last


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    path, secs = a[0], float(a[1])
    min_s = float(a[a.index("--min-s") + 1]) if "--min-s" in a else 5.0
    top = int(a[a.index("--top") + 1]) if "--top" in a else 10
    open_wait, born, first, last = analyse(path)
    if last is None:
        print("no futex events in %s: wrong slice pattern?" % path)
        return
    span = max(last - first, 1e-9)
    hung = {tid: w for tid, w in open_wait.items() if last - w[0] >= min_s}
    by = defaultdict(list)
    for tid, w in hung.items():
        by[(w[2], w[3], w[4])].append((tid, w))
    print("threads blocked in futex with no timeout and no return, >= %.0f s before the slice end "
          "(slice %.1f s of events)" % (min_s, span))
    print("%8s %-16s %12s %6s %6s %6s %10s  %s" % ("pid", "comm", "ns", "hung", "locks", "born", "longest_s", "per third"))
    rows = sorted(by.items(), key=lambda kv: -len(kv[1]))
    for (pid, comm, ns), lst in rows[:top]:
        locks = len({w[1] for _, w in lst})
        nborn = sum(1 for tid, _ in lst if tid in born)
        longest = max(last - w[0] for _, w in lst)
        thirds = Counter(min(2, int((w[0] - first) / span * 3)) for _, w in lst)
        print("%8s %-16s %12s %6d %6d %6d %10.1f  %d/%d/%d" % (pid, comm[:16], ns, len(lst), locks, nborn,
                                                         longest, thirds[0], thirds[1], thirds[2]))
    print()
    if not rows:
        print("NO HUNG LOCK WAITS (no untimed futex wait was still open >= %.0f s before the slice end)" % min_s)
        return
    # A deadlock among NEW threads: born inside the slice and hung soon after birth. Long-lived
    # pool threads parked until work arrives (JVM executors, Go runtime) also wait with no
    # timeout - measured on every Java service in every run - and are never the verdict.
    def fresh(lst):
        return [(tid, w) for tid, w in lst if tid in born and w[0] - born[tid] <= FRESH_S]
    rows.sort(key=lambda kv: (-len(fresh(kv[1])), -len(kv[1])))
    (pid, comm, ns), lst = rows[0]
    if len(fresh(lst)) < 2:
        parked = ", ".join("%s (pid %s) %d" % (c, p, len(l)) for (p, c, n), l in rows[:4])
        print("NO HUNG LOCK WAITS AMONG NEW THREADS (threads parked with no timeout that already existed when "
              "the slice began are idle pool threads, not a deadlock: %s)" % parked)
        return
    lst = fresh(lst)
    locks = {w[1] for _, w in lst}
    longest = max(last - w[0] for _, w in lst)
    thirds = Counter(min(2, int((w[0] - first) / span * 3)) for _, w in lst)
    gaps = sorted(w[0] - born[tid] for tid, w in lst if tid in born)
    born_txt = ("; %d of them were created inside the slice and hung %.0f ms after birth (median)"
                % (len(gaps), 1000 * gaps[len(gaps) // 2]) if gaps else "")
    growing = thirds[2] > 0 and (thirds[1] > 0 or thirds[0] > 0)
    detail = ("%s (pid %s, ns %s): %d threads blocked forever in futex (no timeout) on %d distinct locks, "
              "longest %.1f s; new hung threads per third of the slice %d/%d/%d%s"
              % (comm, pid, ns, len(lst), len(locks), longest, thirds[0], thirds[1], thirds[2], born_txt))
    if len(locks) >= 2:
        print("VERDICT: DEADLOCK: %s. Threads that wait on each other's locks never wake: the process "
              "is alive but those threads do no work%s." % (detail, ", and the number keeps growing" if growing else ""))
    else:
        print("NOTE: HUNG ON ONE LOCK: %s - a lost wake-up or a holder that is gone; a finding, not a deadlock" % detail)
    for (p2, c2, n2), l2 in rows[1:4]:
        print("NOTE: parked threads (existed before the slice; idle pool threads are normal): %s (pid %s, ns %s) %d"
              % (c2, p2, n2, len(l2)))


def _selftest():
    import os
    import tempfile
    ctx = '{ cpu_id = 1 }, { pid = %d, tid = %d, procname = "%s", pid_ns = 77 }'
    L = []
    t = 0.0
    def at(x):
        return "[10:00:%02d.%09d] (+0.1) h" % (int(x), int((x - int(x)) * 1e9))
    for pair in range(4):                              # a new deadlocked pair every 5 s
        t = pair * 5.0
        for k, ua in ((0, 111), (1, 222)):
            tid = 100 + pair * 2 + k
            L.append('%s sched_process_fork: %s, { parent_comm = "py", child_tid = %d, child_pid = 50 }' % (at(t), ctx % (50, 50, "py"), tid))
            L.append('%s syscall_entry_futex: %s, { uaddr = %d, op = 393, val = 0, utime = 0 }' % (at(t + 0.001), ctx % (50, tid, "py"), ua + pair))
    for i in range(30):                                # a healthy timed waiter: never hung
        L.append('%s syscall_entry_futex: %s, { uaddr = 9, op = 393, val = 0, utime = 140 }' % (at(i * 0.5), ctx % (60, 61, "java")))
    L.append('%s syscall_exit_futex: %s, { ret = 0 }' % (at(29.9), ctx % (60, 61, "java")))
    fd, p = tempfile.mkstemp(suffix=".txt")
    os.write(fd, ("\n".join(L) + "\n").encode())
    os.close(fd)
    try:
        ow, born, first, last = analyse(p)
        hung = {k: v for k, v in ow.items() if last - v[0] >= 5}
        assert len(hung) == 8 and all(v[3] == "py" for v in hung.values()), hung   # all 4 pairs, never the timed java wait
        assert len({v[1] for v in hung.values()}) == 8
    finally:
        os.unlink(p)
    print("futex_hang selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
