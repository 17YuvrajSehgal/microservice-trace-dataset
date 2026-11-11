#!/usr/bin/env python3
"""
ns_silence.py - which container went quiet, and did its processes die or just stop?

Usage:
    python3 ns_silence.py <base.txt> <base_secs> <fault.txt> <fault_secs> [--top 10]

Input:
    Two slices of the same recording, cut with extract_slice.sh and the pattern
      'sched_switch|sched_waking|sched_wakeup|sched_process_exit|sched_process_fork|sched_process_exec|syscall_'
    (any event works; more event types = a sharper count). Needs the pid_ns context (containers).

What it measures, per pid namespace (= per container):
    events per second in the quiet slice and in the fault slice, the main comm, and in the fault
    slice: process exits, forks and execs. A paused container (docker pause, SIGSTOP, a cgroup
    freezer) emits NOTHING: its threads are never scheduled, so no event carries its namespace.
    A crashed one shows exits first; a restarting one shows exits and new execs.
    Callers of a frozen service slow down with it: namespaces whose rate fell by half or more
    are listed as affected.

Verdict:
    VERDICT: SERVICE FROZEN: ns N (<comm>) went from R/s to 0 events/s, with no process exit:
             paused or stopped, not crashed; affected: ...
    VERDICT: SERVICE GONE: ns N (<comm>) ... and X process exits: it died
    NO SILENT SERVICE (the quietest namespace kept P% of its baseline rate)
The bar: >= 20 events/s in the quiet slice, < 1% of that in the fault slice.
"""
import re
import sys
from collections import Counter, defaultdict

RATE_MIN = 20.0
SILENT_SHARE = 0.01
re_ev = re.compile(r'\] \(\+[^)]*\) \S+ (\w+):')
re_ns = re.compile(r'\bpid_ns = (\d+)')
re_proc = re.compile(r'procname = "([^"]*)"')


def analyse(path):
    ev, comm, exits, forks, execs = Counter(), defaultdict(Counter), Counter(), Counter(), Counter()
    with open(path, errors="replace") as f:
        for line in f:
            m = re_ev.search(line)
            if not m:
                continue
            nm = re_ns.search(line)
            if not nm:
                continue
            ns = nm.group(1)
            ev[ns] += 1
            p = re_proc.search(line)
            if p:
                comm[ns][p.group(1)] += 1
            e = m.group(1)
            if e == "sched_process_exit":
                exits[ns] += 1
            elif e == "sched_process_fork":
                forks[ns] += 1
            elif e == "sched_process_exec":
                execs[ns] += 1
    return ev, comm, exits, forks, execs


def main():
    a = sys.argv[1:]
    if len(a) < 4:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    bpath, bsecs, fpath, fsecs = a[0], float(a[1]), a[2], float(a[3])
    top = int(a[a.index("--top") + 1]) if "--top" in a else 10
    bev, bcomm, _, _, _ = analyse(bpath)
    fev, fcomm, fexit, ffork, fexec = analyse(fpath)
    if not bev:
        print("no pid_ns in %s: this tool needs the container context" % bpath)
        return

    def name(ns):
        c = bcomm.get(ns) or fcomm.get(ns)
        return c.most_common(1)[0][0] if c else "?"
    rows = []
    for ns in set(bev) | set(fev):
        b, f = bev.get(ns, 0) / bsecs, fev.get(ns, 0) / fsecs
        rows.append((f / b if b else float("inf"), b, f, ns))
    rows.sort()
    print("events per second per namespace, quiet slice vs fault slice (lowest ratio first)")
    print("%12s %-18s %10s %10s %7s %6s %6s %6s" % ("ns", "comm", "base/s", "fault/s", "ratio", "exits", "forks", "execs"))
    for r, b, f, ns in rows[:top]:
        print("%12s %-18s %10.1f %10.1f %7.2f %6d %6d %6d" % (ns, name(ns)[:18], b, f, r, fexit[ns], ffork[ns], fexec[ns]))
    print()
    silent = [(r, b, f, ns) for r, b, f, ns in rows if b >= RATE_MIN and f < b * SILENT_SHARE]
    affected = ["%s (%s) x%.2f" % (ns, name(ns), r) for r, b, f, ns in rows
                if b >= RATE_MIN and SILENT_SHARE <= r <= 0.5][:5]
    if not silent:
        busy = [x for x in rows if x[1] >= RATE_MIN]
        q = busy[0] if busy else None
        print("NO SILENT SERVICE (the quietest busy namespace, %s, kept %.0f%% of its baseline rate)"
              % ("%s %s" % (q[3], name(q[3])) if q else "-", 100 * q[0] if q else 100))
        return
    r, b, f, ns = silent[0]
    aff = "; affected (rate fell by half or more): %s" % ", ".join(affected) if affected else ""
    if fexit[ns]:
        print("VERDICT: SERVICE GONE: ns %s (%s) went from %.0f/s to %.1f events/s and %d of its processes exited: "
              "it died%s%s" % (ns, name(ns), b, f, fexit[ns], " and was restarted (%d execs)" % fexec[ns] if fexec[ns] else "", aff))
    else:
        print("VERDICT: SERVICE FROZEN: ns %s (%s) went from %.0f/s to %.1f events/s with no process exit: its "
              "processes still exist but are never scheduled - paused or stopped, not crashed%s" % (ns, name(ns), b, f, aff))
    for r2, b2, f2, ns2 in silent[1:3]:
        print("NOTE: also silent: ns %s (%s) %.0f/s -> %.1f/s" % (ns2, name(ns2), b2, f2))


def _selftest():
    import os
    import tempfile
    line = '[10:00:00.0] (+0.1) h sched_switch: { cpu_id = 1 }, { pid = 1, tid = 1, procname = "%s", pid_ns = %s }, { }'
    base = [line % ("app", "11")] * 500 + [line % ("java", "22")] * 900 + [line % ("node", "33")] * 400
    fault = [line % ("java", "22")] * 400 + [line % ("node", "33")] * 410
    paths = []
    for rows in (base, fault):
        fd, p = tempfile.mkstemp(suffix=".txt")
        os.write(fd, ("\n".join(rows) + "\n").encode())
        os.close(fd)
        paths.append(p)
    try:
        bev = analyse(paths[0])[0]
        fev, _, fexit, _, _ = analyse(paths[1])
        assert bev["11"] == 500 and fev.get("11", 0) == 0 and fexit.get("11", 0) == 0
    finally:
        for p in paths:
            os.unlink(p)
    print("ns_silence selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
