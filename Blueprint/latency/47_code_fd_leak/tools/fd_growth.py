#!/usr/bin/env python3
# fd_growth.py - find one process that opens files and does not close them.
#
# Every open file, socket or pipe of a process is a file descriptor. A healthy process closes
# what it opens, so over a few seconds its opens and closes are about equal. A descriptor leak
# is a process whose opens stay ahead of its closes: the count only grows, slowly, and nothing
# fails until the limit is reached, which can be hours later.
#
# For each process (pid), in a baseline slice and a suspect slice:
#   opened    system calls that returned a new descriptor, files (openat, open, pipe, ...) and
#             sockets (socket, accept) counted apart
#   closed    of those, how many were closed again in the slice (followed by descriptor number)
#   net       opened - closed: what stayed open
#
# Usage:
#   python3 fd_growth.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 fd_growth.py --selftest
#
#   both slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt \
#     'syscall_exit_openat|syscall_exit_open|syscall_exit_socket|syscall_exit_accept|syscall_exit_dup|syscall_exit_epoll_create|syscall_exit_eventfd|syscall_exit_pipe|syscall_entry_close'
import re
import sys
from collections import defaultdict

MIN_NET = 30           # file descriptors (not sockets) that stayed open, in the slice
MIN_SHARE = 0.2        # ... and at least this share of the FILES the process opened
MAX_BASE = 0.2         # ... and the baseline's net growth is at most this share of it
# CHANGED AFTER RUN 1 (27-11-2026), four things. Runs 2-5 were tested with this version.
# 1. The first version asked that the net growth be 20% of the process's opens. The leaking service
#    had net +72 against +1 in the baseline and was missed: it opens about 150 sockets per second in
#    normal work (a new database connection for most requests), so 72 was 2% of its opens.
# 2. dup2 and dup3 were counted as opens. They put a descriptor on a number the caller chooses and
#    close what was there, so they add nothing: two Java services showed a "growth" of 60, all dup2.
# 3. Sockets and files were counted together. On run 1 of two OTHER families a service's sockets
#    grew (+316 when it got four times the calls, +37 on a proxy whose callee was failing): connections
#    pile up whenever a service falls behind, and that is not a leak. The tool now follows each
#    descriptor number from its open to its close, gives a verdict for FILES only, and lists socket
#    growth without a verdict. A socket leak is therefore not confirmed by this tool.
# 4. The share bar is kept, for files only. cadvisor opens about 7,700 files in 20 s and had 8 to 60
#    of them open at the end of a slice (under 1%); the leaking service kept 74 of 110 (67%).
FILES = ("openat", "open", "dup", "epoll_create", "epoll_create1", "eventfd", "eventfd2", "pipe", "pipe2")
SOCKETS = ("socket", "accept", "accept4")

re_ev = re.compile(r' syscall_(entry|exit)_(\w+):')
re_ctx = re.compile(r'\{ pid = (\d+), tid = (\d+), procname = "([^"]*)".*?pid_ns = (\d+)')
re_ret = re.compile(r'\{ ret = (-?\d+)')
re_fd = re.compile(r'\{ fd = (\d+) \}')
re_pipe = re.compile(r'fildes = \[ \[0\] = (\d+), \[1\] = (\d+) \]')


def read(lines):
    """Per process: {kind: [opened, closed]} for kind in file, socket; and what opened the files."""
    cnt = defaultdict(lambda: {"file": [0, 0], "socket": [0, 0]})
    kind = defaultdict(dict)                     # pid -> {descriptor number: kind}, for descriptors opened in the slice
    how = defaultdict(lambda: defaultdict(int))
    name, ns = {}, {}
    for line in lines:
        e = re_ev.search(line)
        if not e:
            continue
        m = re_ctx.search(line)
        if not m:
            continue
        pid, sc = m.group(1), e.group(2)
        if e.group(1) == "entry":
            if sc != "close":
                continue
            f = re_fd.search(line)
            k = kind[pid].pop(f.group(1), None) if f else None
            if k:                                # a close of something opened before the slice is not counted
                cnt[pid][k][1] += 1
            continue
        if sc in ("pipe", "pipe2"):
            f, r = re_pipe.search(line), re_ret.search(line)
            fds = [f.group(1), f.group(2)] if f and r and r.group(1) == "0" else []
        elif sc in FILES or sc in SOCKETS:
            r = re_ret.search(line)
            fds = [r.group(1)] if r and int(r.group(1)) >= 0 else []
        else:
            continue
        k = "socket" if sc in SOCKETS else "file"
        for fd in fds:
            kind[pid][fd] = k
            cnt[pid][k][0] += 1
            if k == "file":
                how[pid][sc] += 1
        name.setdefault(pid, m.group(3))
        ns.setdefault(pid, m.group(4))
    return cnt, how, name, ns


def net(cnt, p, k):
    c = cnt.get(p)
    return c[k][0] - c[k][1] if c else 0


def report(base, fault, secs):
    bcnt = base[0]
    cnt, how, name, ns = fault
    rows = sorted(cnt, key=lambda p: -net(cnt, p, "file"))
    out = [f"File descriptors opened in this {secs:.0f} s slice and closed again, per process (largest net growth of files first)",
           f"  {'pid':>8} {'program':<16} {'pid_ns':>12} {'files opened':>13} {'closed':>7} {'net':>5} {'net before':>11} "
           f"{'sockets opened':>15} {'net':>5} {'net before':>11}  files opened by"]
    for p in rows[:10]:
        c = cnt[p]
        calls = ", ".join(f"{k} {v}" for k, v in sorted(how[p].items(), key=lambda kv: -kv[1])[:3])
        out.append(f"  {p:>8} {name.get(p, '?'):<16} {ns.get(p, '?'):>12} {c['file'][0]:>13} {c['file'][1]:>7} {net(cnt, p, 'file'):>5} "
                   f"{net(bcnt, p, 'file'):>11} {c['socket'][0]:>15} {net(cnt, p, 'socket'):>5} {net(bcnt, p, 'socket'):>11}  {calls}")
    out.append("  net = opened in the slice and not closed in it; before = the same in the baseline slice")
    hits = 0
    for p in rows:
        n, b = net(cnt, p, "file"), net(bcnt, p, "file")
        if n < MIN_NET or n < MIN_SHARE * cnt[p]['file'][0] or b > MAX_BASE * n:
            continue
        top = max(how[p], key=how[p].get)
        out.append(f"VERDICT: FILES ARE OPENED AND NOT CLOSED: {name.get(p, '?')} (pid {p}, pid_ns {ns.get(p, '?')}) opened "
                   f"{cnt[p]['file'][0]} file descriptors in {secs:.0f} s and closed {cnt[p]['file'][1]} of them; {n} stayed open "
                   f"({n / secs:.1f} per second), {b} in the baseline; most were opened by {top} ({how[p][top]}) - "
                   f"its descriptor count only grows")
        hits += 1
    for p in sorted(cnt, key=lambda p: -net(cnt, p, "socket")):
        n, b = net(cnt, p, "socket"), net(bcnt, p, "socket")
        if n >= MIN_NET and b <= MAX_BASE * n:
            out.append(f"OTHER GROWTH (sockets, no verdict): {name.get(p, '?')} (pid {p}, pid_ns {ns.get(p, '?')}) opened "
                       f"{cnt[p]['socket'][0]} sockets and {n} stayed open, {b} in the baseline - connections pile up when a "
                       f"service falls behind, so this alone is not a leak")
    if not hits:
        t = rows[0] if rows else None
        why = (f"largest: {name.get(t, '?')} (pid {t}) {net(cnt, t, 'file')} files stayed open of {cnt[t]['file'][0]} opened" if t
               else "no descriptor was opened")
        out.append(f"VERDICT: NO FILE DESCRIPTOR GROWTH ({why}; the bars are {MIN_NET} files that stay open, {MIN_SHARE:.0%} of the files opened, "
                   f"baseline at most {MAX_BASE:.0%} of it)")
    return out


def selftest():
    def ev(t, kind, sc, pid, tail, comm="app", ns=7):
        return (f'[10:00:{t:012.9f}] (+0.0) h syscall_{kind}_{sc}: {{ cpu_id = 1 }}, {{ pid = {pid}, tid = {pid}, procname = "{comm}", '
                f'cgroup_ns = 1, pid_ns = {ns}, net_ns = 1, ipc_ns = 1, user_ns = 1 }}, {{ {tail} }}')

    busy = []
    for i in range(2000):                        # a busy server: accepts and closes, opens that fail, a dup2
        fd = 12 + i % 4
        busy += [ev(i * 0.01, "exit", "accept4", 100, f"ret = {fd}", "java", 3), ev(i * 0.01 + 0.005, "entry", "close", 100, f"fd = {fd}", "java", 3)]
        busy.append(ev(i * 0.01, "exit", "openat", 100, "ret = -2", "java", 3))
        busy.append(ev(i * 0.01, "exit", "dup2", 100, "ret = 1", "java", 3))
    busy.append(ev(1, "entry", "close", 100, "fd = 900", "java", 3))          # opened before the slice
    leak = busy + [ev(i * 0.33, "exit", "openat", 200, f"ret = {20 + i}") for i in range(60)]
    out = "\n".join(report(read(busy), read(leak), 20))
    assert "FILES ARE OPENED AND NOT CLOSED: app (pid 200, pid_ns 7) opened 60 file descriptors in 20 s and closed 0 of them; 60 stayed open (3.0 per second), 0 in the baseline; most were opened by openat (60)" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(read(busy), read(busy), 20))
    assert "NO FILE DESCRIPTOR GROWTH (largest: java (pid 100) 0 files stayed open of 0 opened" in out, out
    pile = busy + [ev(i * 0.05, "exit", "socket", 300, f"ret = {20 + i}", "node", 5) for i in range(300)]   # sockets pile up: no verdict
    pile += [ev(5, "exit", "pipe2", 300, "ret = 0, fildes = [ [0] = 3, [1] = 4 ]", "node", 5), ev(5.1, "entry", "close", 300, "fd = 3", "node", 5)]
    out = "\n".join(report(read(busy), read(pile), 20))
    assert "OTHER GROWTH (sockets, no verdict): node (pid 300, pid_ns 5) opened 300 sockets and 300 stayed open, 0 in the baseline" in out, out
    assert "VERDICT: NO FILE DESCRIPTOR GROWTH (largest: node (pid 300) 1 files stayed open of 2 opened" in out and out.count("VERDICT") == 1, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: fd_growth.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
