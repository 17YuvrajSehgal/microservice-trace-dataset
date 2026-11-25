#!/usr/bin/env python3
# new_errors.py - find a container whose system calls started to fail with an error they did
# not return before.
#
# Several faults are a limit being reached, and the kernel says so in the return value of one
# system call, in one container:
#   -28  ENOSPC         write / fallocate / fsync   the disk (or the volume) is full
#   -99  EADDRNOTAVAIL  connect                     no local port is free
#   -11  EAGAIN         clone                       the process/thread limit is reached
#   -24  EMFILE         open / socket / accept      the file-descriptor limit is reached
#   -12  ENOMEM         mmap / clone                no memory within the limit
# Programs also get errors all the time when nothing is wrong (a non-blocking connect returns
# -115, a missing file -2). So the tool does not look for errors; it looks for an error that
# is NEW: absent from a baseline slice and frequent in the suspect slice.
#
# Usage:
#   python3 new_errors.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 new_errors.py --selftest
#
#   both slices cut with (same length):
#     extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt "$ERREV"
#     ERREV='syscall_exit_(connect|write|pwrite64|writev|pwritev|fallocate|fsync|fdatasync|ftruncate|openat|socket|accept4|accept|clone|clone3|fork|vfork|mmap|bind|sendto|sendmsg)'
import re
import sys
from collections import defaultdict

MIN_NEW = 10           # failing calls of one kind, in one container, in the suspect slice
MAX_BASE = 0.1         # ... and at most this share of that count in the baseline slice
# Returns that are negative and are NOT failures: a non-blocking connect that is still in
# progress, and a non-blocking call that would have had to wait. They are left out. Measured on
# the disk-full runs: after the database crashed, its client reconnected with 111-124
# non-blocking connects (-115) that the baseline did not have, and the tool named the client.
# clone returning EAGAIN is NOT in this list: that one is a limit.
NOT_FAILURES = {("connect", 115), ("accept", 11), ("accept4", 11), ("write", 11), ("writev", 11),
                ("sendto", 11), ("sendmsg", 11), ("pwrite64", 11)}
NAMES = {28: ("ENOSPC", "no space left on the device"), 99: ("EADDRNOTAVAIL", "no local address or port is free"),
         11: ("EAGAIN", "a limit was reached or the call would block"), 24: ("EMFILE", "the process has too many open files"),
         23: ("ENFILE", "the system has too many open files"), 12: ("ENOMEM", "out of memory within the limit"),
         111: ("ECONNREFUSED", "nothing listens at the peer"), 110: ("ETIMEDOUT", "the peer did not answer"),
         104: ("ECONNRESET", "the peer reset the connection"), 32: ("EPIPE", "the peer closed the connection"),
         122: ("EDQUOT", "the disk quota is used up"), 5: ("EIO", "input/output error"), 30: ("EROFS", "the file system is read-only"),
         113: ("EHOSTUNREACH", "no route to the peer"), 101: ("ENETUNREACH", "the network is unreachable"),
         98: ("EADDRINUSE", "the address is already in use"), 13: ("EACCES", "permission denied"), 1: ("EPERM", "not permitted")}

re_ev = re.compile(r' syscall_exit_(\w+):')
re_ctx = re.compile(r'procname = "([^"]*)"')
re_pidns = re.compile(r'pid_ns = (\d+)')
re_ret = re.compile(r'ret = (-?\d+)')


def read(lines):
    fails = defaultdict(int)                 # (pid_ns, syscall, errno) -> failing calls
    calls = defaultdict(int)                 # (pid_ns, syscall) -> all calls
    comm = defaultdict(lambda: defaultdict(int))
    for line in lines:
        ev = re_ev.search(line)
        if not ev:
            continue
        r, pn = re_ret.search(line), re_pidns.search(line)
        if not r or not pn:
            continue
        ns, sc, ret = pn.group(1), ev.group(1), int(r.group(1))
        calls[(ns, sc)] += 1
        if -4096 < ret < 0 and (sc, -ret) not in NOT_FAILURES:   # an errno; other negative values are addresses
            fails[(ns, sc, -ret)] += 1
            cx = re_ctx.search(line)
            if cx:
                comm[(ns, sc, -ret)][cx.group(1)] += 1
    return fails, calls, comm


def report(base, fault, secs):
    bf, _, _ = base
    ff, fc, fcomm = fault
    rows = []
    for k, n in ff.items():
        b = bf.get(k, 0)
        rows.append((n - b, n, b, k))
    rows.sort(reverse=True)
    out = [f"Failing system calls per container, {secs:.0f} s slices (largest rise first)",
           f"  {'pid_ns':>12} {'program':<16} {'call':<12} {'error':<22} {'now':>7} {'before':>7} {'of calls':>9}"]
    for _, n, b, (ns, sc, e) in rows[:12]:
        nm = max(fcomm[(ns, sc, e)], key=fcomm[(ns, sc, e)].get) if fcomm[(ns, sc, e)] else "?"
        out.append(f"  {ns:>12} {nm:<16} {sc:<12} {'-%d %s' % (e, NAMES.get(e, ('?',))[0]):<22} {n:>7} {b:>7} "
                   f"{n / max(1, fc[(ns, sc)]):>8.0%}")
    out.append("  of calls = share of that container's calls of this kind that failed with this error in the suspect slice")
    hits = 0
    for _, n, b, (ns, sc, e) in rows:
        if ns == '0' or n < MIN_NEW or b > MAX_BASE * n:        # pid_ns 0 = namespace could not be read
            continue
        nm = max(fcomm[(ns, sc, e)], key=fcomm[(ns, sc, e)].get) if fcomm[(ns, sc, e)] else "?"
        name, meaning = NAMES.get(e, ("?", "see errno(3)"))
        out.append(f"VERDICT: NEW ERROR RETURNS: {nm} (pid_ns {ns}): {n} calls to {sc} returned -{e} ({name}: {meaning}) in "
                   f"{secs:.0f} s, {b} in the baseline; that is {n / max(1, fc[(ns, sc)]):.0%} of its {sc} calls")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"largest rise: {top[1]} against {top[2]} for {top[3][1]} -{top[3][2]} in pid_ns {top[3][0]}" if top
               else "no failing call in the suspect slice")
        out.append(f"VERDICT: NO NEW ERROR RETURNS ({why}; a new error has {MIN_NEW}+ failing calls and at most "
                   f"{MAX_BASE:.0%} of that in the baseline)")
    return out


def selftest():
    def ex(t, nm, ns, sc, ret):
        return (f'[10:00:{t:012.9f}] (+0.0) h syscall_exit_{sc}: {{ cpu_id = 1 }}, {{ pid = 7, tid = 7, '
                f'procname = "{nm}", pid_ns = {ns} }}, {{ ret = {ret} }}')

    common = [ex(i * 0.01, "node", 5, "connect", -115) for i in range(300)]          # normal: non-blocking connects
    common += [ex(i * 0.01, "app", 4, "connect", 0) for i in range(200)]
    common += [ex(i * 0.1, "java", 6, "mmap", 140000000000000 + i) for i in range(50)]  # addresses, not errors
    base = read(common)
    fault = read(common + [ex(5 + i * 0.01, "app", 4, "connect", -99) for i in range(150)])
    out = "\n".join(report(base, fault, 20))
    assert "NEW ERROR RETURNS: app (pid_ns 4): 150 calls to connect returned -99 (EADDRNOTAVAIL: no local address or port is free) in 20 s, 0 in the baseline; that is 43% of its connect calls" in out, out
    assert out.count("VERDICT") == 1, out
    out = "\n".join(report(base, base, 20))
    assert "NO NEW ERROR RETURNS (no failing call in the suspect slice" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: new_errors.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
