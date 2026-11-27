#!/usr/bin/env python3
# dns_retry.py - find a process whose name lookups time out and are sent again.
#
# A resolver that loses queries breaks nothing: the lookup is simply sent again after a
# timeout and usually works the second time. The request that needed the name waited a few
# seconds; every other request was fast. Averages and percentiles stay healthy.
#
# A lookup by the C library resolver is a short, fixed sequence of system calls in ONE thread:
#     socket, bind            a fresh UDP socket
#     sendto (with address)   the query (often two: A and AAAA)
#     poll(timeout)           wait for the answer
#     close
# When a query or its answer is lost, poll returns 0 (timed out) and the SAME thread sends
# again on the SAME socket. That poll-timeout-then-resend is what this tool counts.
#
# Usage:
#   python3 dns_retry.py <slice.txt> <slice_seconds>
#   python3 dns_retry.py --selftest
#
#   <slice.txt>  60 s or more, cut with:
#        extract_slice.sh TRACE DAY HH:MM:SS 60 out.txt \
#          'syscall_entry_sendto|syscall_entry_poll|syscall_exit_poll|syscall_entry_close|sched_process_exec'
import re
import sys
from collections import defaultdict

MIN_TIMEOUT_S = 0.5    # a poll that gave up sooner than this is not a resolver timeout
MIN_RETRIED = 3        # lookups with a timeout-and-resend, in one container, for a verdict
MIN_SHARE = 0.05       # ... and at least this share of that container's lookups

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_fd = re.compile(r'\{ fd = (\d+)')
re_ret = re.compile(r'\{ ret = (-?\d+)')
re_alen = re.compile(r'addr_len = (\d+)')


def tsec(line):
    # ponytail: time of day only, a slice that crosses midnight is not handled
    m = re_time.match(line)
    if not m:
        return None
    h, mi, s, fr = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(s) + int(fr.ljust(9, '0')) / 1e9


def read(lines):
    # ponytail: only resolvers that send with sendto(address) and wait in poll() are seen
    # (musl, and glibc when it does not connect first). Go and c-ares wait in epoll: add
    # connect-to-port-53 + epoll tracking if a trace needs it.
    look = {}                          # tid -> [fd, t first send, t last send, timeouts, resends, timed_out_now]
    poll_in = {}                       # tid -> t of poll entry
    done = defaultdict(list)           # (pid_ns, name) -> [(duration, timeouts, resends)]
    execs = defaultdict(int)           # pid_ns -> exec() calls (a restarting container)
    pids = defaultdict(set)            # (pid_ns, name) -> pids

    def finish(tid, t, key):
        fd, t0, tl, to, rs, _ = look.pop(tid)
        done[key].append((t - t0, to, rs))

    for line in lines:
        if ' syscall_' not in line and ' sched_process_exec:' not in line:
            continue
        c = re_ctx.search(line)
        t = tsec(line)
        if not c or t is None:
            continue
        pid, tid, name = c.groups()
        pn = re_pidns.search(line)
        key = (pn.group(1) if pn else "?", name)
        if ' sched_process_exec:' in line:
            execs[key[0]] += 1
        elif ' syscall_entry_sendto:' in line:
            a, fd = re_alen.search(line), re_fd.search(line)
            if not a or not fd or a.group(1) == '0':
                continue
            L = look.get(tid)
            if L and L[0] != fd.group(1):
                finish(tid, t, key)
                L = None
            if L is None:
                look[tid] = [fd.group(1), t, t, 0, 0, False]
                pids[key].add(pid)
            else:
                if L[5]:
                    L[4] += 1
                    L[5] = False
                L[2] = t
        elif ' syscall_entry_poll:' in line:
            if tid in look:
                poll_in[tid] = t
        elif ' syscall_exit_poll:' in line:
            t0 = poll_in.pop(tid, None)
            r = re_ret.search(line)
            if t0 is not None and tid in look and r and r.group(1) == '0' and t - t0 >= MIN_TIMEOUT_S:
                look[tid][3] += 1
                look[tid][5] = True
        elif ' syscall_entry_close:' in line:
            fd = re_fd.search(line)
            if tid in look and fd and fd.group(1) == look[tid][0]:
                finish(tid, t, key)
    return done, execs, pids


def report(done, execs, pids, secs):
    rows = []
    for key, ls in done.items():
        retried = [l for l in ls if l[2] > 0]
        failed = [l for l in ls if l[1] > 0 and l[2] == 0]         # timed out and gave up
        rows.append((len(retried), len(ls), len(failed), max(l[0] for l in ls),
                     sum(l[0] for l in ls if l[1] > 0), key))
    rows.sort(reverse=True)
    out = [f"name lookups (sendto with an address, then poll) in this {secs:.0f} s slice: "
           f"{sum(r[1] for r in rows)} by {len(rows)} programs",
           f"  {'lookups':>7} {'resent':>7} {'gave up':>8} {'slowest s':>10} {'lost s':>7}  {'program':<18}{'pid_ns':>12} {'pids':>5} {'execs':>6}"]
    for retried, n, failed, worst, lost, key in rows[:8]:
        out.append(f"  {n:>7} {retried:>7} {failed:>8} {worst:>10.2f} {lost:>7.1f}  {key[1]:<18}{key[0]:>12} "
                   f"{len(pids[key]):>5} {execs.get(key[0], 0):>6}")
    out.append("  resent = lookups where poll timed out and the query was sent again; gave up = timed out, "
               "not sent again; lost s = time spent in lookups that timed out; "
               "pids, execs = more than one means the program restarted in the slice")
    hit = [r for r in rows if r[0] >= MIN_RETRIED and r[0] >= MIN_SHARE * r[1]]
    # A program that restarts loses lookups while it starts (measured on a crash-looping
    # service: 9-13% of its lookups, with a healthy resolver). So a restarting program is
    # reported, but not blamed on the resolver. Added after the sweep.
    steady = [r for r in hit if len(pids[r[5]]) == 1]
    if steady:
        retried, n, failed, worst, lost, key = steady[0]
        out.append(f"VERDICT: NAME LOOKUPS TIME OUT: {key[1]} (pid_ns {key[0]}) had {retried} of {n} lookups time out "
                   f"and be sent again ({retried / n:.0%}), slowest {worst:.1f} s, {lost:.1f} s lost in total")
    elif hit:
        retried, n, failed, worst, lost, key = hit[0]
        out.append(f"VERDICT: LOOKUPS TIME OUT IN A RESTARTING PROGRAM: {key[1]} (pid_ns {key[0]}) ran as "
                   f"{len(pids[key])} different processes in this slice; {retried} of {n} lookups timed out "
                   f"({retried / n:.0%}). Find out why it restarts first; lookups fail while a program starts")
    else:
        top = (f"most: {rows[0][0]} of {rows[0][1]} by {rows[0][5][1]}" if rows else "no lookups seen")
        out.append(f"VERDICT: NO LOOKUP TIMEOUTS ({top}; the bar is {MIN_RETRIED} resent lookups and "
                   f"{MIN_SHARE:.0%} of the program's lookups)")
    return out


def selftest():
    def ev(t, tid, what, body, nm="node"):
        return (f'[10:00:{t:012.9f}] (+0.0) h {what}: {{ cpu_id = 1 }}, {{ pid = 50, tid = {tid}, '
                f'procname = "{nm}", pid_ns = 77, net_ns = 1 }}, {{ {body} }}')

    def lookup(t, tid, fd, timeouts):
        ls = [ev(t, tid, "syscall_entry_sendto", f"fd = {fd}, buff = 1, len = 27, flags = 0, addr = 5, addr_len = 16")]
        for _ in range(timeouts):
            ls.append(ev(t + 0.0001, tid, "syscall_entry_poll", "timeout_msecs = 2500, nfds = 1"))
            t += 2.5
            ls.append(ev(t, tid, "syscall_exit_poll", "ret = 0, nfds = 1"))
            ls.append(ev(t + 0.0001, tid, "syscall_entry_sendto", f"fd = {fd}, buff = 1, len = 27, flags = 0, addr = 5, addr_len = 16"))
        ls.append(ev(t + 0.0002, tid, "syscall_entry_poll", "timeout_msecs = 2500, nfds = 1"))
        ls.append(ev(t + 0.001, tid, "syscall_exit_poll", "ret = 1, nfds = 1"))
        ls.append(ev(t + 0.002, tid, "syscall_entry_close", f"fd = {fd}"))
        return ls

    lines = []
    for i in range(20):
        lines += lookup(i * 0.5, 100 + i % 4, 20, 0)                     # fast lookups
    for i in range(4):
        lines += lookup(12 + i, 200 + i, 21, 1 + i % 2)                  # 4 lookups with 1-2 timeouts
    lines += [ev(30, 300, "syscall_entry_sendto", "fd = 9, buff = 1, len = 500, flags = 0, addr = 0, addr_len = 0", "web")]
    lines.sort(key=tsec)
    out = "\n".join(report(*read(lines), 60.0))
    assert "NAME LOOKUPS TIME OUT: node (pid_ns 77) had 4 of 24 lookups time out and be sent again (17%), slowest 5.0 s" in out, out
    out = "\n".join(report(*read([l for l in lines if "tid = 20" not in l]), 60.0))
    assert "NO LOOKUP TIMEOUTS (most: 0 of 20 by node" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("usage: dns_retry.py <slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        res = read(f)
    print("\n".join(report(*res, float(sys.argv[2]))))
