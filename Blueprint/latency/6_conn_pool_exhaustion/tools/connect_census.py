#!/usr/bin/env python3
# connect_census.py - what happens when a process tries to OPEN a connection.
#
# Connection-pool / connection-limit exhaustion is a latency fault that lives at
# connect() time, not at read() time. A shared datastore (or its pool) runs out
# of room, so NEW connections are refused or made to wait - while the
# connections that are already open keep getting fast answers. That healthy-looking
# datastore is the trap: sock_lag.py on the established fds reads normal, and the
# CPU/disk tables are quiet. The evidence is here, in the connect() calls.
#
# This tool pairs syscall_entry_connect with syscall_exit_connect per thread and
# reports, per process:
#   - how many connect() attempts were made,
#   - how they RETURNED (ok / refused / timed-out / in-progress / other error),
#   - how LONG the blocking ones took (p50/p90/max).
#
# Two shapes of the same fault, because runtimes differ:
#   - Blocking client (a JVM/C MySQL driver, HikariCP): connect() itself blocks
#     and either returns ECONNREFUSED/ETIMEDOUT or sits for a long time -> the
#     refused counts rise, or the connect-duration percentiles jump.
#   - Non-blocking client (Go, Node): connect() returns EINPROGRESS at once and
#     the result is learned later via epoll + getsockopt(SO_ERROR). The stall is
#     not in connect()'s own duration there; it shows as a burst of connect
#     attempts (retries) and EINPROGRESS without the fd ever carrying traffic.
#     Read the attempt COUNT and the retry pattern, not just the duration.
#
# errno returns (x86-64): 0 ok; -115 EINPROGRESS (non-blocking start, normal);
# -111 ECONNREFUSED (the server refused - a connection limit); -110 ETIMEDOUT;
# -11 EAGAIN; -99 EADDRNOTAVAIL (ephemeral ports exhausted); -24 EMFILE /
# -23 ENFILE (the CLIENT ran out of fds - that is fd_exhaustion, a different fault).
#
# Usage:
#   python3 connect_census.py <slice.txt> <slice_seconds> [pid|all] [top]
#
#   <slice.txt> made with dep_slice.sh (it keeps syscalls with their fd and ret).
#
# Compare a baseline slice with a fault slice: the victim is the process whose
# refused/timed-out connects appear (near zero at baseline), or whose connect
# duration jumps, while sock_lag.py on its established fds stays flat.
import re
import sys
from collections import defaultdict

if len(sys.argv) < 3:
    print("usage: connect_census.py <slice.txt> <slice_seconds> [pid|all] [top]", file=sys.stderr)
    sys.exit(1)
path, secs = sys.argv[1], float(sys.argv[2])
target = sys.argv[3] if len(sys.argv) > 3 else "all"
top = int(sys.argv[4]) if len(sys.argv) > 4 else 12

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_sys = re.compile(r' syscall_(entry|exit)_connect:')
re_ret = re.compile(r'\{ ret = (-?\d+)')

# errno -> label; anything else negative is "other error"
ERRNO = {0: "ok", -115: "inprogress", -111: "refused", -110: "timedout",
         -11: "again", -99: "no_ephem_port", -24: "emfile", -23: "enfile"}

entry_t = {}                          # tid -> connect entry timestamp
stats = defaultdict(lambda: defaultdict(int))   # pid -> {label: count}
durs = defaultdict(list)              # pid -> [connect wall-ns] (completed connects)
pid_name = {}


def ts(line):
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1_000_000_000 + int(fr.ljust(9, '0'))


with open(path, errors="replace") as f:
    for line in f:
        sm = re_sys.search(line)
        if not sm:
            continue
        c = re_ctx.search(line)
        if not c:
            continue
        pid, tid = c.group(1), c.group(2)
        if target != "all" and pid != target:
            continue
        t = ts(line)
        if t is None:
            continue
        pid_name[pid] = c.group(3)
        if sm.group(1) == 'entry':
            entry_t[tid] = t
            continue
        t0 = entry_t.pop(tid, None)
        rm = re_ret.search(line)
        ret = int(rm.group(1)) if rm else 0
        label = ERRNO.get(ret, "other_err" if ret < 0 else "ok")
        stats[pid][label] += 1
        stats[pid]["total"] += 1
        if t0 is not None:
            durs[pid].append(t - t0)


if not stats:
    print("no connect() calls found. Wrong pid, or the slice was cut with extract_slice.sh "
          "(which drops syscalls) - use dep_slice.sh.")
    sys.exit(0)


def pct(xs, q):
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0


rows = sorted(stats.items(), key=lambda kv: -(kv[1].get("refused", 0) + kv[1].get("timedout", 0)
                                              + kv[1].get("total", 0) * 0.001))
print("connect() census per process  (slice %.0f s)" % secs)
print(f"{'pid':>8} {'name':<16}{'total':>7}{'ok':>6}{'refused':>8}{'timedout':>9}"
      f"{'inprog':>7}{'othererr':>9}{'dur_p50':>9}{'dur_p90':>9}{'dur_max':>9}")
for pid, st in rows[:top]:
    d = sorted(durs.get(pid, []))
    print(f"{pid:>8} {pid_name.get(pid,'?'):<16}{st.get('total',0):>7}{st.get('ok',0):>6}"
          f"{st.get('refused',0):>8}{st.get('timedout',0):>9}{st.get('inprogress',0):>7}"
          f"{st.get('other_err',0):>9}"
          f"{pct(d,.5)/1e6:>9.1f}{pct(d,.9)/1e6:>9.1f}{(d[-1]/1e6 if d else 0):>9.1f}")
print()
print("Read it (compare against a baseline slice; near-zero refused/timedout at baseline):")
print("- POOL / CONNECTION-LIMIT EXHAUSTION: new connect()s are REFUSED (ECONNREFUSED) or")
print("  TIME OUT, or their duration jumps, on connections to one datastore - while sock_lag.py")
print("  on that process's already-open fds stays FAST. The datastore is healthy; there is no")
print("  room to open a new talk to it. That read-fast / connect-failing split IS the fault.")
print("- SLOW DEPENDENCY instead: connect() is fine; the ESTABLISHED fds' read gap is what")
print("  jumps (sock_lag.py). Opposite signature - hand to the slow_db blueprint.")
print("- Non-blocking client (Go/Node): look for a BURST of attempts / EINPROGRESS with no")
print("  traffic following, not a connect duration - its connect() never blocks.")
print("- emfile/enfile on the CLIENT means the client ran out of file descriptors: that is")
print("  fd_exhaustion, not pool exhaustion. no_ephem_port means the client ran out of source")
print("  ports. Both are client-side, not the shared datastore refusing you.")
