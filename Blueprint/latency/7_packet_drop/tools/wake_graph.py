"""
wake_graph.py - which processes wake a given process, and which processes it
wakes, counted from sched_waking events.

Usage:
    python3 wake_graph.py <sched_events.txt> <pid> [rows]

Input:
    The same slice file that sched_budget.py reads (sched_switch and
    sched_waking lines from babeltrace2 --clock-gmt).

Why it helps:
    When process A sends a request or an answer to process B on the same
    machine, the kernel often wakes B while running in A's context. So the
    waker -> wakee pairs hint at who talks to whom. This is a hint, not proof:
    a wakeup can also come from an interrupt, a timer, or a lock.

Notes:
    - A sched_waking line names the waker by pid and the wakee only by thread
      id (tid). The script maps a tid to its pid with the sched_switch lines
      in the same file. A wakee that never ran in the slice stays unresolved.
    - pid 0 means the wakeup came from interrupt or idle context, not from a
      process.
"""
import re
import sys
from collections import Counter, defaultdict

re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_wk = re.compile(r'\{ comm = "([^"]*)", tid = (\d+), prio')


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    path, victim = sys.argv[1], sys.argv[2]
    rows = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    tid_pid = {}                          # tid -> pid
    pid_names = defaultdict(Counter)      # pid -> thread names seen
    wakes = []                            # (waker_pid, wakee_tid, wakee_comm)

    with open(path) as f:
        for line in f:
            if " sched_switch:" in line:
                c = re_ctx.search(line)
                if c:
                    pid, tid, name = c.groups()
                    tid_pid[tid] = pid
                    pid_names[pid][name] += 1
            elif " sched_waking:" in line:
                c, w = re_ctx.search(line), re_wk.search(line)
                if c and w:
                    wpid, _, wname = c.groups()
                    pid_names[wpid][wname] += 1
                    wakes.append((wpid, w.group(2), w.group(1)))

    def name(pid):
        if pid == "0":
            return "(interrupt or idle)"
        n = pid_names.get(pid)
        return n.most_common(1)[0][0] if n else "?"

    victim_tids = {t for t, p in tid_pid.items() if p == victim}
    it_wakes, woken_by = Counter(), Counter()
    self_wakes = unresolved = 0
    for wpid, ttid, tcomm in wakes:
        tpid = tid_pid.get(ttid)
        if wpid == victim:
            if tpid == victim:
                self_wakes += 1
            elif tpid is None:
                unresolved += 1
            else:
                it_wakes[tpid] += 1
        elif ttid in victim_tids:
            woken_by[wpid] += 1

    print(f"pid {victim} ({name(victim)}): {len(victim_tids)} threads seen in the slice")
    print(f"wakeups between its own threads: {self_wakes}")
    print()
    print(f"processes that pid {victim} wakes (top {rows}):")
    print(f"{'count':>8} {'pid':>8}  name")
    for pid, n in it_wakes.most_common(rows):
        print(f"{n:>8} {pid:>8}  {name(pid)}")
    if unresolved:
        print(f"{unresolved:>8} {'?':>8}  (threads that never ran in this slice)")
    print()
    print(f"processes that wake pid {victim} (top {rows}):")
    print(f"{'count':>8} {'pid':>8}  name")
    for pid, n in woken_by.most_common(rows):
        print(f"{n:>8} {pid:>8}  {name(pid)}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
