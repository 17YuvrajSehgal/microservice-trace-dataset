#!/usr/bin/env python3
"""
proc_spawn.py - who is creating processes, how fast, and is that new?

Usage:
    python3 proc_spawn.py <slice.txt> <secs> [--baseline <base.txt> <base_secs>] [--top 10]

Input:
    Slices cut with extract_slice.sh and the pattern
      'sched_process_fork|sched_process_exec|sched_process_exit'
    Works with the microservice context (pid_ns) and without it (every group under ns '-').

What it counts, per (pid_ns, parent comm):
    processes  sched_process_fork with child_pid == child_tid   (a NEW PROCESS: fork, clone without CLONE_THREAD)
    threads    sched_process_fork with child_pid != child_tid   (a new THREAD: thread pools do this all day)
    execs      sched_process_exec in that namespace, with the most common program
    exits      sched_process_exit in that namespace
The two are kept apart on purpose: measured on our runs, a JVM creates 70-90 THREADS per
second with nothing wrong, while a process storm creates 100 PROCESSES per second.

Verdict:
    VERDICT: PROCESS STORM: <comm> (ns N) created P processes in S s (R/s; baseline B/s) ...
        - a group creates >= 20 processes/s AND >= 10x its baseline rate (or it was absent)
    NO PROCESS STORM: top process creator <comm> (ns N) R/s (baseline B/s)
    Without --baseline the table is printed and the verdict says the rate alone is not proof.
"""
import re
import sys
from collections import Counter, defaultdict

RATE_MIN = 20.0       # processes per second
RATIO_MIN = 10.0      # times the baseline rate
TRACER = ("lttng", "collect_trace")   # our own tracer scripts: never the culprit

re_ev = re.compile(r'\] \(\+[^)]*\) \S+ (sched_process_\w+):')
re_ns = re.compile(r'\bpid_ns = (\d+)')
re_pcomm = re.compile(r'parent_comm = "([^"]*)"')
re_cpid = re.compile(r'child_pid = (\d+)')
re_ctid = re.compile(r'child_tid = (\d+)')
re_file = re.compile(r'filename = "([^"]*)"')
re_proc = re.compile(r'procname = "([^"]*)"')


def analyse(path):
    procs, threads, execs, exits = Counter(), Counter(), defaultdict(Counter), Counter()
    with open(path, errors="replace") as f:
        for line in f:
            m = re_ev.search(line)
            if not m:
                continue
            ev = m.group(1)
            nm = re_ns.search(line)
            ns = nm.group(1) if nm else "-"
            if ev == "sched_process_fork":
                pc = re_pcomm.search(line)
                key = (ns, pc.group(1) if pc else "?")
                cp, ct = re_cpid.search(line), re_ctid.search(line)
                if cp and ct and cp.group(1) == ct.group(1):
                    procs[key] += 1
                else:
                    threads[key] += 1
            elif ev == "sched_process_exec":
                fn = re_file.search(line)
                execs[ns][fn.group(1).rsplit("/", 1)[-1] if fn else "?"] += 1
            elif ev == "sched_process_exit":
                exits[ns] += 1
    return procs, threads, execs, exits


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    path, secs = a[0], float(a[1])
    top = int(a[a.index("--top") + 1]) if "--top" in a else 10
    base = None
    if "--baseline" in a:
        i = a.index("--baseline")
        base = (analyse(a[i + 1]), float(a[i + 2]))
    procs, threads, execs, exits = analyse(path)
    bprocs = base[0][0] if base else Counter()
    bsecs = base[1] if base else 1.0

    print("process / thread creation per (namespace, parent comm)  (slice %.0f s)" % secs)
    print("%12s %-18s %9s %9s %10s %9s  %s" % ("ns", "parent", "proc/s", "base/s", "thread/s", "exits/s", "top exec"))
    keys = sorted(set(procs) | set(threads), key=lambda k: -(procs[k] * 10 + threads[k]))
    for k in keys[:top]:
        ex = execs[k[0]].most_common(1)
        print("%12s %-18s %9.1f %9.1f %10.1f %9.1f  %s" % (
            k[0], k[1][:18], procs[k] / secs, bprocs.get(k, 0) / bsecs, threads[k] / secs,
            exits[k[0]] / secs, "%s x%d" % ex[0] if ex else "-"))
    print()

    cands = [k for k in procs if not k[1].startswith(TRACER)]
    if not cands:
        print("NO PROCESS STORM: no process creation in %.0f s" % secs)
        return
    k = max(cands, key=lambda k: procs[k])
    rate, brate = procs[k] / secs, bprocs.get(k, 0) / bsecs
    ex = execs[k[0]].most_common(1)
    detail = ("%s (ns %s) created %d processes in %.0f s (%.0f/s; baseline %.1f/s)%s; %d exits in that namespace"
              % (k[1], k[0], procs[k], secs, rate, brate,
                 "; they run %s (%d execs)" % ex[0] if ex else "", exits[k[0]]))
    if base is None:
        print("NOTE: no --baseline given; top process creator %s. A rate alone is not proof: "
              "cut a quiet slice before the change and run again." % detail)
        return
    if rate >= RATE_MIN and (brate == 0 or rate / brate >= RATIO_MIN):
        print("VERDICT: PROCESS STORM: %s. New processes are created far faster than before, "
              "in one namespace; each costs a fork (page-table copy) and scheduler work." % detail)
    else:
        print("NO PROCESS STORM: top process creator %s (bar: >= %.0f/s and >= %.0fx baseline)"
              % (detail, RATE_MIN, RATIO_MIN))


def _selftest():
    import os
    import tempfile
    ctx = '{ cpu_id = 1 }, { pid = %d, tid = %d, procname = "%s", pid_ns = %s }'
    fork = ('[10:00:%02d.000000000] (+0.1) h sched_process_fork: %s, { parent_comm = "%s", parent_tid = 1, '
            'parent_pid = 1, child_comm = "%s", child_tid = %d, child_pid = %d }')
    lines = []
    for i in range(300):                         # a python storm: 300 processes in 10 s
        lines.append(fork % (i % 10, ctx % (5, 5, "python3", "77"), "python3", "python3", 1000 + i, 1000 + i))
    for i in range(800):                         # a JVM making threads: never a storm
        lines.append(fork % (i % 10, ctx % (9, 9, "java", "88"), "java", "java", 5000 + i, 9))
    for i in range(400):                         # our tracer forking: excluded
        lines.append(fork % (i % 10, ctx % (3, 3, "collect_trace.s", "1"), "collect_trace.s", "date", 9000 + i, 9000 + i))
    fd, p = tempfile.mkstemp(suffix=".txt")
    os.write(fd, ("\n".join(lines) + "\n").encode())
    os.close(fd)
    try:
        procs, threads, _, _ = analyse(p)
        assert procs[("77", "python3")] == 300 and threads[("88", "java")] == 800 and procs[("88", "java")] == 0
    finally:
        os.unlink(p)
    print("proc_spawn selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
