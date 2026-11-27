#!/usr/bin/env python3
# new_programs.py - find programs started inside a container that never started there before.
#
# Every container runs the same few programs all day. A program that appears in one container
# for the first time (a shell, `id`, `uname`, `ps`...) is what a compromised service looks like.
#
# For each container (pid namespace) the tool lists the program names (the basename of the
# executed file) started in the suspect slice that were never started in that container in the
# baseline slice. The host's own namespace is left out: monitoring scripts start hundreds of
# programs per minute there (about 1,280 per minute on the collection VM).
#
# Usage:
#   python3 new_programs.py <baseline_slice.txt> <fault_slice.txt>
#   python3 new_programs.py --selftest
#
#   both slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 60 out.txt 'sched_process_exec'
#   (a long baseline helps: a program started once a minute in normal operation must be in it)
import os
import re
import sys
from collections import defaultdict, Counter

MIN_NEW = 2            # different new programs in one container
# Bar set before the first run on labelled data (26-11-2026) and not fitted to it.

re_ex = re.compile(r'procname = "([^"]*)".*?pid_ns = (\d+).*filename = "([^"]*)"')


def read(lines):
    progs = defaultdict(Counter)                 # pid_ns -> program -> starts
    for line in lines:
        if ' sched_process_exec:' not in line:
            continue
        m = re_ex.search(line)
        if m:
            progs[m.group(2)][os.path.basename(m.group(3))] += 1
    return progs


def report(base, fault):
    allns = Counter({ns: sum(c.values()) for ns, c in base.items()})
    host = allns.most_common(1)[0][0] if allns else None   # the busiest namespace is the host's
    out = [f"Programs started per container (host namespace {host} left out)",
           f"  {'pid_ns':>12} {'starts':>7} {'before':>7} {'new programs (starts)'}"]
    hits = 0
    rows = []
    for ns, c in fault.items():
        if ns == host:
            continue
        new = {p: n for p, n in c.items() if p not in base.get(ns, {})}
        rows.append((len(new), ns, c, new))
    rows.sort(key=lambda r: -r[0])
    for k, ns, c, new in rows[:10]:
        out.append(f"  {ns:>12} {sum(c.values()):>7} {sum(base.get(ns, {}).values()):>7} "
                   + (", ".join(f"{p} ({n})" for p, n in sorted(new.items(), key=lambda kv: -kv[1])) or "-"))
    for k, ns, c, new in rows:
        if k < MIN_NEW:
            continue
        out.append(f"VERDICT: NEW PROGRAMS IN A CONTAINER: pid_ns {ns} started {k} programs never started there in the baseline: "
                   + ", ".join(sorted(new)) + f" ({sum(new.values())} starts) - a shell or tools run inside the service")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"most: {top[0]} new in pid_ns {top[1]}" if top else "no program started in a container")
        out.append(f"VERDICT: NO NEW PROGRAMS ({why}; the bar is {MIN_NEW} different new programs in one container)")
    return out


def selftest():
    def ex(t, ns, prog, comm="x"):
        return (f'[10:00:{t:012.9f}] (+0.0) h sched_process_exec: {{ cpu_id = 3 }}, {{ pid = 5, tid = 5, procname = "{comm}", '
                f'cgroup_ns = 1, pid_ns = {ns}, net_ns = 1 }}, {{ filename = "/usr/bin/{prog}", tid = 5, old_tid = 5 }}')
    base = [ex(i * 0.1, 1, p) for i, p in enumerate(["sleep", "cat", "docker", "ps"] * 50)] + [ex(5, 7, "java")]
    fault = base[:] + [ex(9 + i, 8, p) for i, p in enumerate(["sh", "id", "uname", "ls"])]
    out = "\n".join(report(read(base), read(fault)))
    assert "NEW PROGRAMS IN A CONTAINER: pid_ns 8 started 4 programs never started there in the baseline: id, ls, sh, uname (4 starts)" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(base), read(base)))
    assert "NO NEW PROGRAMS" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: new_programs.py <baseline_slice.txt> <fault_slice.txt>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa)))
