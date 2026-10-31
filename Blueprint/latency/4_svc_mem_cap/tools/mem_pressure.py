#!/usr/bin/env python3
# mem_pressure.py - the memory-cap check: who is reclaiming, who is re-reading
# from disk, and who died doing it.
#
# A container with a memory limit that is too small shows three things, and
# this tool measures all three from one slice:
#
#   1. RECLAIM INSIDE THE CONTAINER. The kernel event is named
#      mm_vmscan_memcg_reclaim_begin/end - "memcg" means the reclaim happens
#      because of a CGROUP limit, not because the host is out of memory.
#      Host pressure uses different events (direct reclaim, kswapd). The
#      event NAME alone separates "this container's limit" from "the machine
#      is full".
#   2. RE-READING FROM DISK (refaults). The limit keeps evicting the
#      container's file cache, so the same file is read from disk again and
#      again. One process's disk reads grow far past the size of what it
#      works on.
#   3. DEATHS (hard limit only). memory.max kills when reclaim cannot free
#      enough. The victim exits suddenly, right after its own reclaim burst.
#      A soft limit (memory.high) stalls but never kills.
#
# Usage:
#   python3 mem_pressure.py <slice.txt> <slice_seconds> [victim_pid]
#
#   <slice.txt>  a slice that KEEPS memory events - cut it with:
#                extract_slice.sh TRACE DAY HH:MM:SS SECS out.txt \
#                  'sched_switch|sched_waking|sched_wakeup|mm_vmscan_|block_rq_|sched_process_'
import re
import sys
from collections import defaultdict

if len(sys.argv) < 3:
    print("usage: mem_pressure.py <slice.txt> <slice_seconds> [victim_pid]", file=sys.stderr)
    sys.exit(1)
path, secs = sys.argv[1], float(sys.argv[2])
victim = sys.argv[3] if len(sys.argv) > 3 else None

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
re_bytes = re.compile(r'bytes = (\d+)')
re_rwbs = re.compile(r'rwbs = (\d+)')
re_pidns = re.compile(r'pid_ns = (\d+)')   # the container id - one number per container

reclaim_open = {}                      # tid -> start ns of an open memcg reclaim
memcg = defaultdict(lambda: [0, 0, 0])   # pid -> [count, total ns, max ns]
direct = defaultdict(int)              # pid -> count of host direct reclaims
names = {}
kswapd_seen = 0
reads = defaultdict(lambda: [0, 0])    # pid -> [count, bytes]
writes = defaultdict(lambda: [0, 0])
forks = defaultdict(int)               # procname -> count
exits = []                             # (t, pid, procname)
last_reclaim_t = {}                    # pid -> ns of last memcg reclaim activity
pidns = {}                             # pid -> pid_ns (the container the pid lives in)

with open(path, errors="replace") as f:
    for line in f:
        m = re_time.match(line)
        c = re_ctx.search(line)
        if not m or not c:
            continue
        h, mi, s, fr = m.groups()
        t = ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1_000_000_000 + int(fr.ljust(9, '0'))
        pid, tid, pname = c.groups()
        names[pid] = pname
        pn = re_pidns.search(line)        # the reclaiming pid's container id, straight off the event
        if pn:
            pidns[pid] = pn.group(1)
        if 'kswapd' in pname:
            kswapd_seen += 1
        if ' mm_vmscan_memcg_reclaim_begin:' in line:
            reclaim_open[tid] = t
            last_reclaim_t[pid] = t
        elif ' mm_vmscan_memcg_reclaim_end:' in line:
            st = reclaim_open.pop(tid, None)
            last_reclaim_t[pid] = t
            if st is not None:
                d = t - st
                r = memcg[pid]
                r[0] += 1
                r[1] += d
                if d > r[2]:
                    r[2] = d
        elif ' mm_vmscan_direct_reclaim_begin:' in line:
            direct[pid] += 1
        elif ' block_rq_issue:' in line:
            rw = re_rwbs.search(line)
            by = re_bytes.search(line)
            if rw:
                flags = int(rw.group(1))
                n = int(by.group(1)) if by else 0
                if flags & 4:
                    reads[pid][0] += 1
                    reads[pid][1] += n
                elif flags & 1:
                    writes[pid][0] += 1
                    writes[pid][1] += n
        elif ' sched_process_fork:' in line:
            forks[pname] += 1
        elif ' sched_process_exit:' in line:
            # the event fires once per THREAD; a process death is the main
            # thread's exit (tid == pid), the rest is thread teardown noise
            if tid == pid:
                exits.append((t, pid, pname))

ns = 1e9

# ---- 1. reclaim ------------------------------------------------------------
print(f"Reclaim in this {secs:.0f} s slice")
if not memcg and not direct and not kswapd_seen:
    print("  none. Nobody reclaimed memory here - a memory limit is NOT biting in this slice.")
else:
    if memcg:
        print("  CONTAINER-LIMIT reclaim (mm_vmscan_memcg_*), per process:")
        print(f"  {'pid':>8} {'pid_ns':>12} {'name':<16}{'reclaims':>9}{'stalled s':>11}{'max ms':>8}")
        for pid, (n, tot, mx) in sorted(memcg.items(), key=lambda kv: -kv[1][1])[:6]:
            print(f"  {pid:>8} {pidns.get(pid, '?'):>12} {names.get(pid, '?'):<16}{n:>9}{tot/ns:>11.2f}{mx/1e6:>8.1f}")
        # Roll up by container. The pid_ns doing the memcg reclaim IS the capped container -
        # memcg reclaim fires inside the cgroup that hit its own limit. Read the victim's
        # container straight off this; do NOT map it by CPU usage (that correlation is noisy).
        by_ns = defaultdict(int)
        for pid, (n, tot, mx) in memcg.items():
            by_ns[pidns.get(pid, '?')] += n
        top = sorted(by_ns.items(), key=lambda kv: -kv[1])
        # pid_ns 0 / '?' means the namespace could NOT be read for that event - it is not a real
        # container. The victim is the container with the most reclaim among READABLE namespaces;
        # never report 0 as the victim.
        real = [(nsid, c) for nsid, c in top if nsid not in ('0', '?')]
        if real:
            vns, vn = real[0]
            print(f"  -> VICTIM CONTAINER = pid_ns {vns}  ({vn} memcg reclaims by its processes here)")
            if top[0][0] in ('0', '?'):
                print(f"     (ignore the unreadable pid_ns {top[0][0]}:{top[0][1]} - 0 is not a "
                      "container, it is a context that could not be read; the readable namespace "
                      "above is the victim)")
        else:
            print("  -> reclaim IS present (a cap is biting) but every reclaimer's pid_ns is "
                  "unreadable (0) in THIS slice - sample another slice where reclaim concentrates "
                  "to read the victim container; do not give up on the cap")
        print("     reclaim by pid_ns: " + ", ".join(f"{nsid}:{c}" for nsid, c in top[:5]))
    if direct:
        tot = sum(direct.values())
        print(f"  HOST-pressure reclaim (direct): {tot} events - the MACHINE is short of "
              f"memory, not one container")
    if kswapd_seen:
        print(f"  kswapd active ({kswapd_seen} events) - also a host-pressure sign")

# ---- 2. disk reads ---------------------------------------------------------
print()
print("Disk reads issued in the slice (re-reading evicted cache shows up here)")
rows = sorted(reads.items(), key=lambda kv: -kv[1][1])[:6]
if not rows:
    print("  none seen (or the slice has no block_rq_ events - check how it was cut)")
else:
    print(f"  {'pid':>8} {'name':<16}{'reads':>8}{'MB':>9}")
    for pid, (n, b) in rows:
        print(f"  {pid:>8} {names.get(pid, '?'):<16}{n:>8}{b/1e6:>9.0f}")
wr = sorted(writes.items(), key=lambda kv: -kv[1][1])[:2]
if wr:
    print("  (top writers: " + ", ".join(f"{names.get(p,'?')} {b/1e6:.0f} MB" for p, (n, b) in wr) + ")")

# ---- 3. births and deaths --------------------------------------------------
print()
print("Process starts and ends in the slice")
if forks:
    print("  forks: " + ", ".join(f"{k} x{v}" for k, v in sorted(forks.items(), key=lambda kv: -kv[1])[:5]))
if exits:
    deaths_by_name = defaultdict(int)
    for t, pid, pname in exits:
        deaths_by_name[pname] += 1
    # the deaths that matter first: processes that were reclaiming (the
    # limit's candidates), then the rest, newest last
    shown = sorted(exits, key=lambda e: (e[1] not in memcg, e[0]))
    for t, pid, pname in shown[:12]:
        lr = last_reclaim_t.get(pid)
        gap = (t - lr) if lr is not None and t >= lr else None
        # The gap between a process's LAST reclaim and its exit tells kill
        # from finish. A killed process dies INSIDE the allocation that
        # triggered its final reclaim - the gap is well under 1 ms. A process
        # that finishes does its cleanup first - several ms or more.
        # Measured on 8 runs with known outcomes: kills 0.02-0.37 ms,
        # finishes 7.9-48.3 ms.
        tag = ""
        if gap is not None and gap < 1_000_000:
            tag = (f"  <- exited INSIDE its own reclaim ({gap/1e6:.2f} ms after "
                   "it): it did not finish, the hard limit killed it")
        elif gap is not None and gap < 1_000_000_000 and deaths_by_name[pname] >= 2:
            tag = (f"  <- died near its own reclaim and this name died "
                   f"{deaths_by_name[pname]} times in the slice: the "
                   "kill-and-respawn (thrash) pattern")
        elif gap is not None and gap < 1_000_000_000:
            tag = (f"  (exited {gap/1e6:.1f} ms after its last reclaim - a few "
                   "ms or more means it finished and cleaned up; a killed "
                   "process exits within about 1 ms of its reclaim)")
        print(f"  exit {pname} (pid {pid}, pid_ns {pidns.get(pid, '?')}) at +{t/ns % 86400:.3f}s{tag}")
if not forks and not exits:
    print("  none")

# ---- read it ---------------------------------------------------------------
print()
print("Read it:")
print("- SOFT LIMIT (memory.high) biting: one container's processes show memcg")
print("  reclaims with real stalled time, the SAME processes re-read many MB")
print("  from disk, nobody dies. The work crawls instead of failing.")
print("- HARD LIMIT (memory.max) killing: memcg reclaim bursts, then the biggest")
print("  memory user exits suddenly right after its own reclaim. Often repeats")
print("  (a supervisor restarts it and it dies again).")
print("- LOW disk reads + memcg reclaim is STILL a cap. A heap-heavy workload (a JVM or")
print("  other managed runtime) holds mostly ANONYMOUS memory, not file cache, so there is")
print("  little to refault from disk: reclaim stays high while reads stay low. Do NOT read")
print("  low/zero reads as 'not a cap' - the memcg reclaim above baseline is the proof. The")
print("  re-read storm is the file-cache face only; its absence means the anonymous face.")
print("- HOST pressure, not a container limit: direct reclaim / kswapd instead")
print("  of memcg reclaim, and processes in DIFFERENT containers all stall.")
print("- Reads with NO reclaim at all: cold cache or plain disk work - not a")
print("  memory limit. Check the disk blueprint instead.")
