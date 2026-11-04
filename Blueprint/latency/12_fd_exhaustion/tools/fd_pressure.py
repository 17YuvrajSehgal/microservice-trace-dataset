#!/usr/bin/env python3
"""
fd_pressure.py - did a process run out of file descriptors (or another per-process resource)?

Usage:
    python3 fd_pressure.py <slice.txt> <slice_seconds> [--top 10] [--min-hits 3]

Input:
    A slice made by extract_slice.sh with this event pattern (the FDEV in the blueprint):
      'sched_process_exec|sched_process_exit|syscall_exit_(accept4|accept|socket|socketpair|openat|open|creat|dup|dup2|dup3|pipe2|pipe|epoll_create1|epoll_create|eventfd2|memfd_create|timerfd_create|signalfd4|inotify_init1|connect)'
    Works with the microservice context block (pid, procname, pid_ns) and with bare-metal
    line shapes (no namespace: every process is reported under ns '-').

What it measures, per process (namespace, comm, pid):
    EMFILE   -24  : "too many open files" - THIS process hit its RLIMIT_NOFILE.
    ENFILE   -23  : the whole host's file table is full (rare; every process would see it).
    EADDRNOTAVAIL -99 : connect() ran out of ephemeral source ports (a client-side limit).
    ECONNREFUSED -111 : connect() refused by the peer (a server-side limit, not this process).
    highest fd    : the largest descriptor number any fd-creating call returned - how big the
                    table got. A process at a few hundred fds that also returns EMFILE sat at
                    a lowered limit; one at tens of thousands grew into the default limit.
    restarts      : sched_process_exec of the same comm in the same namespace inside the slice
                    (a crash-looping service shows several), and exits of that comm.

Verdicts (first line of the verdict block):
    VERDICT: FD EXHAUSTION: <comm> (ns N, pid P): K EMFILE returns on <calls> in S s (first at
             HH:MM:SS.mmm); highest fd seen F; R restarts of <comm> in that namespace
    NOTE: EPHEMERAL PORTS EXHAUSTED: <comm> ...: K EADDRNOTAVAIL on connect()
    NOTE: CONNECTS REFUSED: <comm> ...: K ECONNREFUSED on connect() - a peer's limit, not this
          process's descriptors (see 6_conn_pool_exhaustion)
    NO FD PRESSURE: 0 EMFILE/ENFILE returns in S s; highest fd per process: ...

Measured (Sock Shop v2, fd_exhaustion_aggressive_steady_r1, 120 s injection window on the
front-end): 23 EMFILE returns by `node` on accept4/socket, 0 in the 50 s baseline; the
front-end restarted repeatedly inside the window. No other process returned EMFILE.
"""
import re
import sys
from collections import defaultdict

ERR = {-24: "EMFILE", -23: "ENFILE", -99: "EADDRNOTAVAIL", -111: "ECONNREFUSED"}
FD_CALLS = {"accept4", "accept", "socket", "socketpair", "openat", "open", "creat", "dup", "dup2",
            "dup3", "pipe2", "pipe", "epoll_create1", "epoll_create", "eventfd2", "memfd_create",
            "timerfd_create", "signalfd4", "inotify_init1"}

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ev = re.compile(r' (syscall_exit_([a-z0-9_]+)|sched_process_exec|sched_process_exit):')
# microservice shape: pid = N, tid = N, procname = "x" ... pid_ns = N ; bare metal: procname only or vpid
re_pid = re.compile(r'\b(?:v?pid) = (\d+)')
re_name = re.compile(r'procname = "([^"]*)"')
re_ns = re.compile(r'pid_ns = (\d+)')
re_ret = re.compile(r'\{ ret = (-?\d+)')
re_comm = re.compile(r'comm = "([^"]*)"')
re_filename = re.compile(r'filename = "([^"]*)"')


def ts_text(line):
    m = re_time.match(line)
    return "%s:%s:%s.%s" % (m.group(1), m.group(2), m.group(3), m.group(4)[:3]) if m else "?"


def analyse(path):
    procs = {}      # (ns, comm, pid) -> stats
    execs = defaultdict(int)   # (ns, comm) -> exec count
    exits = defaultdict(int)   # (ns, comm) -> exit count
    with open(path, errors="replace") as f:
        for line in f:
            m = re_ev.search(line)
            if not m:
                continue
            ev, call = m.group(1), m.group(2)
            nm = re_name.search(line)
            pm = re_pid.search(line)
            nsm = re_ns.search(line)
            ns = nsm.group(1) if nsm else "-"
            if ev == "sched_process_exec":
                # the comm after exec is the new program; LTTng gives the filename and the
                # (pre-exec) procname - count by the file's basename so a restart loop of one
                # service is one key
                fn = re_filename.search(line)
                comm = fn.group(1).rsplit("/", 1)[-1] if fn else (nm.group(1) if nm else "?")
                execs[(ns, comm)] += 1
                continue
            if ev == "sched_process_exit":
                cm = re_comm.search(line)
                comm = cm.group(1) if cm else (nm.group(1) if nm else "?")
                exits[(ns, comm)] += 1
                continue
            if call not in FD_CALLS and call != "connect":
                continue
            rm = re_ret.search(line)
            if not rm:
                continue
            ret = int(rm.group(1))
            key = (ns, nm.group(1) if nm else "?", pm.group(1) if pm else "?")
            st = procs.get(key)
            if st is None:
                st = procs[key] = {"errs": defaultdict(int), "err_calls": defaultdict(set),
                                   "max_fd": -1, "first_err": None, "calls": 0}
            st["calls"] += 1
            if ret >= 0 and call in FD_CALLS:
                if ret > st["max_fd"]:
                    st["max_fd"] = ret
            elif ret in ERR and (call == "connect") == (ret in (-99, -111)):
                st["errs"][ERR[ret]] += 1
                st["err_calls"][ERR[ret]].add(call)
                if ret in (-24, -23) and st["first_err"] is None:
                    st["first_err"] = ts_text(line)
    return procs, execs, exits


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    path, secs = args[0], float(args[1])
    opt = {"--top": 10, "--min-hits": 3}
    for i, a in enumerate(sys.argv):
        if a in opt and i + 1 < len(sys.argv):
            opt[a] = int(sys.argv[i + 1])
    procs, execs, exits = analyse(path)
    if not procs:
        print("no fd-creating syscall exits in %s: wrong file, or the slice was cut without the "
              "FDEV event pattern" % path)
        sys.exit(0)

    rows = sorted(procs.items(), key=lambda kv: (-(kv[1]["errs"]["EMFILE"] + kv[1]["errs"]["ENFILE"]),
                                                 -sum(kv[1]["errs"].values()), -kv[1]["max_fd"]))
    print("fd pressure per process  (slice %.0f s; errors are syscall return codes)" % secs)
    print(f"{'ns':>12} {'name':<16}{'pid':>8}{'calls':>8}{'EMFILE':>8}{'ENFILE':>8}{'EADDRNA':>8}"
          f"{'REFUSED':>8}{'max_fd':>8}{'restarts':>9}{'exits':>7}")
    for (ns, comm, pid), st in rows[:opt["--top"]]:
        e = st["errs"]
        print(f"{ns:>12} {comm[:15]:<16}{pid:>8}{st['calls']:>8}{e['EMFILE']:>8}{e['ENFILE']:>8}"
              f"{e['EADDRNOTAVAIL']:>8}{e['ECONNREFUSED']:>8}{st['max_fd']:>8}"
              f"{execs.get((ns, comm), 0):>9}{exits.get((ns, comm), 0):>7}")
    print()

    hit = [(k, st) for k, st in rows if st["errs"]["EMFILE"] + st["errs"]["ENFILE"] >= opt["--min-hits"]]
    if hit:
        for (ns, comm, pid), st in hit:
            e = st["errs"]
            calls = "/".join(sorted(st["err_calls"]["EMFILE"] | st["err_calls"]["ENFILE"]))
            kind = "EMFILE" if e["EMFILE"] >= e["ENFILE"] else "ENFILE (host file table)"
            print(f"VERDICT: FD EXHAUSTION: {comm} (ns {ns}, pid {pid}): {e['EMFILE'] + e['ENFILE']} "
                  f"{kind} returns on {calls} in {secs:.0f} s (first at {st['first_err']}); highest fd "
                  f"seen {st['max_fd']}; {execs.get((ns, comm), 0)} restarts of {comm} in that namespace")
        print("FIX HINT: raise RLIMIT_NOFILE for that service (ulimits.nofile / prlimit), or find the "
              "descriptor leak if the highest fd kept climbing before the first EMFILE")
    else:
        top = ", ".join(f"{c} {st['max_fd']}" for (ns, c, p), st in
                        sorted(rows, key=lambda kv: -kv[1]["max_fd"])[:4])
        print(f"NO FD PRESSURE: 0 EMFILE/ENFILE returns in {secs:.0f} s (fewer than {opt['--min-hits']}); "
              f"highest fd per process: {top}")
    for (ns, comm, pid), st in rows:
        e = st["errs"]
        if e["EADDRNOTAVAIL"] >= opt["--min-hits"]:
            print(f"NOTE: EPHEMERAL PORTS EXHAUSTED: {comm} (ns {ns}, pid {pid}): {e['EADDRNOTAVAIL']} "
                  f"EADDRNOTAVAIL on connect() - a client-side port limit, not descriptors")
        if e["ECONNREFUSED"] >= opt["--min-hits"]:
            print(f"NOTE: CONNECTS REFUSED: {comm} (ns {ns}, pid {pid}): {e['ECONNREFUSED']} ECONNREFUSED "
                  f"on connect() - a peer's limit, not this process's descriptors "
                  f"(see 6_conn_pool_exhaustion)")
    # No generic "restart loop" note: measured on a microservice host, every slice carried
    # 12-30 execs of chronyc / iptables / sed / sleep from the host's own scripts, so the note
    # was noise in every run. The restarts that matter are the EMFILE process's, in the verdict.


def _selftest():
    import os
    import tempfile
    L = []
    ctx = '{ cpu_id = 1 }, { pid = %d, tid = %d, procname = "%s", pid_ns = %d }'
    for i in range(6):
        L.append('[10:00:0%d.000000000] (+0.1) h syscall_exit_accept4: %s, { ret = %d }'
                 % (i, ctx % (500, 500, "node", 7001), 40 + i))
    for i in range(4):
        L.append('[10:00:1%d.000000000] (+0.1) h syscall_exit_accept4: %s, { ret = -24 }'
                 % (i, ctx % (500, 500, "node", 7001)))
    L.append('[10:00:15.000000000] (+0.1) h syscall_exit_socket: %s, { ret = -24 }' % (ctx % (500, 500, "node", 7001)))
    for i in range(3):
        L.append('[10:00:2%d.000000000] (+0.1) h sched_process_exec: { cpu_id = 2 }, { pid = %d, tid = %d, '
                 'procname = "sh", pid_ns = 7001 }, { filename = "/usr/local/bin/node", tid = %d, old_tid = %d }'
                 % (i, 600 + i, 600 + i, 600 + i, 600 + i))
    L.append('[10:00:30.000000000] (+0.1) h syscall_exit_connect: %s, { ret = -111 }' % (ctx % (700, 700, "app", 7002)))
    L.append('[10:00:31.000000000] (+0.1) h syscall_exit_openat: %s, { ret = 9 }' % (ctx % (700, 700, "app", 7002)))
    # bare-metal shape: no namespace, procname only
    L.append('[10:00:32.000000000] (+0.1) h syscall_exit_socket: { cpu_id = 0 }, { procname = "daemon" }, { ret = 12 }')
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as tf:
        tf.write("\n".join(L) + "\n")
        p = tf.name
    try:
        procs, execs, exits = analyse(p)
        n = procs[("7001", "node", "500")]
        assert n["errs"]["EMFILE"] == 5 and n["max_fd"] == 45, n
        assert n["err_calls"]["EMFILE"] == {"accept4", "socket"} and n["first_err"] == "10:00:10.000"
        assert execs[("7001", "node")] == 3
        a = procs[("7002", "app", "700")]
        assert a["errs"]["ECONNREFUSED"] == 1 and a["errs"]["EMFILE"] == 0 and a["max_fd"] == 9
        assert procs[("-", "daemon", "?")]["max_fd"] == 12
    finally:
        os.unlink(p)
    print("fd_pressure selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
