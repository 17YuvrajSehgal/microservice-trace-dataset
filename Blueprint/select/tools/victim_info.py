"""
victim_info.py - everything the kernel trace says about who a process is,
and which of its threads suffered most.

Usage:
    python3 victim_info.py <sched_events.txt> <slice_seconds> <pid> [rows]

Input:
    A slice file made by extract_slice.sh, best taken inside the fault window.

Output:
    1. Identity: pid, program name, thread names, number of threads.
    2. Container: the namespace numbers recorded with each event (if the
       trace has them), compared with the host's, and the other processes
       that share the victim's pid namespace (the same container).
    3. Threads: the threads (tid + thread name) that waited longest for a CPU.

The trace never holds a service or container NAME. Report the most specific
identity it gives. If you have a list that maps PIDs or containers to
service names, from the platform that ran the system, add the name from it.
"""
import re
import sys
from collections import Counter, defaultdict

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'\{ pid = (\d+), tid = (\d+), procname = "([^"]*)"([^}]*)\}')
re_ns = re.compile(r'(\w+_ns) = (\d+)')
re_sw = re.compile(r'prev_tid = (\d+), prev_prio = \d+, prev_state = (\d+), next_comm = "[^"]*", next_tid = (\d+)')
re_wk = re.compile(r'\{ comm = "[^"]*", tid = (\d+), prio')


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    path, secs, victim = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    rows = int(sys.argv[4]) if len(sys.argv) > 4 else 10

    tid_pid = {}
    tid_names = defaultdict(Counter)
    pid_names = defaultdict(Counter)
    pid_ns = {}                         # pid -> dict of namespace numbers
    host_ns = Counter()                 # namespace tuples seen for pid 0 (idle / interrupt)
    state = {}                          # tid -> (kind, since)
    acc = defaultdict(lambda: defaultdict(int))   # tid -> kind -> ns
    big = defaultdict(lambda: [0, 0])             # tid -> [>=50ms count, max_ns]

    def close(tid, t):
        st = state.get(tid)
        if st is None:
            return
        kind, since = st
        d = t - since
        acc[tid][kind] += d
        if kind in ('rqP', 'rqW'):
            b = big[tid]
            if d >= 50_000_000:
                b[0] += 1
            if d > b[1]:
                b[1] = d

    with open(path) as f:
        for line in f:
            m = re_time.match(line)
            c = re_ctx.search(line)
            if not m or not c:
                continue
            h, mi, s, fr = m.groups()
            t = ((int(h) * 60 + int(mi)) * 60 + int(s)) * 10**9 + int(fr.ljust(9, '0'))
            pid, tid, pname, rest = c.groups()
            # A namespace number of 0 is never a real namespace: it means the tracer could
            # not resolve that field for this event. Keeping it would make the process look
            # like a different container than it is - drop it, and merge the real values
            # across events instead of letting the last event win.
            ns = {k: v for k, v in re_ns.findall(rest) if v != '0'}
            if pid == '0':
                if ns:
                    host_ns[tuple(sorted(ns.items()))] += 1
            else:
                tid_pid[tid] = pid
                tid_names[tid][pname] += 1
                pid_names[pid][pname] += 1
                if ns:
                    pid_ns.setdefault(pid, {}).update(ns)
            if ' sched_switch:' in line:
                sw = re_sw.search(line)
                if not sw:
                    continue
                prev_tid, ps, next_tid = sw.groups()
                if prev_tid != '0':
                    if state.get(prev_tid, ('',))[0] == 'run':
                        close(prev_tid, t)
                    code = int(ps)
                    base = code & 0xFF
                    kind = 'rqP' if (code & 0x100) or base == 0 else 'S' if base == 1 else 'D' if base == 2 else 'O'
                    state[prev_tid] = (kind, t)
                if next_tid != '0':
                    if state.get(next_tid, ('',))[0] != 'run':
                        close(next_tid, t)
                    state[next_tid] = ('run', t)
            elif ' sched_waking:' in line:
                wk = re_wk.search(line)
                if wk:
                    wt = wk.group(1)
                    st = state.get(wt)
                    if st and st[0] in ('S', 'D', 'O'):
                        close(wt, t)
                        state[wt] = ('rqW', t)

    vtids = [t for t, p in tid_pid.items() if p == victim]
    if not vtids:
        raise SystemExit(f"pid {victim} does not appear in {path}")

    # 1. identity
    names = pid_names[victim]
    print("Identity (from the kernel trace)")
    print(f"  process id (pid) : {victim}")
    if victim in tid_names:
        print(f"  program name     : {tid_names[victim].most_common(1)[0][0]}   (name of the main thread, tid = pid)")
    else:
        print(f"  program name     : not seen (the main thread did not run in this slice)")
    print(f"  thread names     : " + ", ".join(f"{n} ({k})" for n, k in names.most_common(6)))
    print(f"  threads seen     : {len(vtids)}")

    # 2. container
    print()
    print("Container")
    vns = pid_ns.get(victim)
    if not vns:
        print("  namespace numbers were not recorded in this trace, so this cannot be told")
    else:
        print("  victim namespaces : " + ", ".join(f"{k}={v}" for k, v in sorted(vns.items())))
        if host_ns:
            hns = dict(host_ns.most_common(1)[0][0])
            print("  host namespaces   : " + ", ".join(f"{k}={v}" for k, v in sorted(hns.items())))
            shared = [k for k in vns if k in hns]
            differ = [k for k in shared if vns[k] != hns[k]]
            if differ:
                print(f"  runs in a container: yes ({', '.join(differ)} differ from the host)")
            elif shared:
                print(f"  runs in a container: no sign of it "
                      f"(same as the host on {', '.join(sorted(shared))})")
            else:
                print("  runs in a container: cannot be compared (no shared fields read)")
        else:
            print("  host namespaces   : not seen in this slice, so this cannot be compared")
        key = 'pid_ns' if 'pid_ns' in vns else sorted(vns)[0]
        mates = sorted(p for p, ns in pid_ns.items() if p != victim and ns.get(key) == vns[key])
        if mates:
            print(f"  other processes with the same {key}: " +
                  ", ".join(f"{p} ({pid_names[p].most_common(1)[0][0]})" for p in mates[:10]))
        else:
            print(f"  other processes with the same {key}: none seen in this slice")

    # 3. threads
    n = secs * 1e9
    trs = []
    for t in vtids:
        a = acc[t]
        trs.append((t, tid_names[t].most_common(1)[0][0], a['run'] / n,
                    (a['rqP'] + a['rqW']) / n, big[t][0], big[t][1] / 1e6))
    trs.sort(key=lambda r: r[3], reverse=True)
    print()
    print(f"Threads that waited most for a CPU (top {rows} of {len(trs)})")
    print(f"{'tid':>9}  {'thread name':<16}{'run':>7}{'wait':>7}{'>=50ms':>8}{'max_ms':>9}")
    for r in trs[:rows]:
        print(f"{r[0]:>9}  {r[1]:<16}{r[2]:>7.3f}{r[3]:>7.3f}{r[4]:>8}{r[5]:>9.1f}")
    print()
    print("run and wait are average CPU cores / waiting threads over the slice, per thread")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
