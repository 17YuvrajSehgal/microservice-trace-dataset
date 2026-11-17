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
#                  'sched_switch|sched_waking|sched_wakeup|mm_vmscan_|block_rq_|sched_process_|syscall_entry_mmap'
#                (syscall_entry_mmap is optional: with it the tool also lists who ASKED for
#                 a lot of memory in the slice - the way to name the consumer under host pressure)
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
direct = defaultdict(lambda: [0, 0, 0])  # pid -> [count, total ns, max ns] of host direct reclaims
direct_open = {}                       # tid -> start ns of an open direct reclaim
re_mmap = re.compile(r'len = (\d+), prot = (\d+), flags = (\d+), fd = (-?\d+)')
BIG_ALLOC_MB = 256                     # a "large request" is ONE mmap of this size or more (a JVM or
                                       # node makes thousands of 1 MB ones a second and frees them again)
allocs = defaultdict(lambda: [0, 0, 0])  # pid -> [calls, total bytes, largest bytes], writable anonymous mmap
mmap_seen = 0
BIG_REQUEST_GB = 4                     # one request of this size or more gets a VERDICT line. Measured on all
                                       # 304 v2 runs: the 16 host-memory runs ask for 22.0-34.5 GB, no other
                                       # run has a request of 256 MB or more in its first 30 s
re_cpu = re.compile(r'cpu_id = (\d+)')
last_sw = {}                           # cpu -> ns of the last sched_switch on it
big_t = {}                             # pid -> ns of its largest request
cpu_after = defaultdict(int)           # pid -> ns on CPU after its largest request (it is touching the pages)
kswapd_wakers = defaultdict(int)       # pid -> times it woke kswapd (it asked for memory the host lacked)
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
            direct_open[tid] = t
            direct[pid][0] += 1
        elif ' mm_vmscan_direct_reclaim_end:' in line:
            st = direct_open.pop(tid, None)
            if st is not None:
                r = direct[pid]
                r[1] += t - st
                r[2] = max(r[2], t - st)
        elif ' mm_vmscan_wakeup_kswapd:' in line:
            kswapd_wakers[pid] += 1
        elif ' syscall_entry_mmap:' in line:
            mmap_seen += 1
            mm = re_mmap.search(line)
            # anonymous (MAP_ANONYMOUS = 0x20, no file) and writable (PROT_WRITE = 2). A
            # PROT_NONE mapping is only an address-range reservation (Go and the JVM make
            # hundreds of GB of those and never touch them), so it is not counted.
            if mm and int(mm.group(3)) & 0x20 and int(mm.group(2)) & 2:
                a = allocs[pid]
                n = int(mm.group(1))
                a[0] += 1
                a[1] += n
                if n > a[2]:
                    a[2] = n
                    big_t[pid] = t
        elif ' sched_switch:' in line:
            # the context is the thread going out: the time since the last switch on this CPU is its
            cm = re_cpu.search(line)
            if cm:
                st = last_sw.get(cm.group(1))
                last_sw[cm.group(1)] = t
                if st is not None and pid in big_t:
                    cpu_after[pid] += t - max(st, big_t[pid])
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
        tot = sum(r[0] for r in direct.values())
        print(f"  HOST-pressure reclaim (direct): {tot} events - the MACHINE is short of "
              f"memory, not one container")
    if kswapd_seen:
        print(f"  kswapd active ({kswapd_seen} events) - also a host-pressure sign")
    # Who was asking for memory when the host ran out. The trace holds no per-process memory
    # size, so this is the closest thing to "who took it": the processes that had to reclaim
    # for themselves (direct reclaim) or that woke kswapd, grouped by name and container.
    askers = defaultdict(lambda: [0, 0, 0, 0])   # (name, pid_ns) -> [direct n, stalled ns, max ns, kswapd wakes]
    for pid, (n, tot_ns, mx) in direct.items():
        a = askers[(names.get(pid, '?'), pidns.get(pid, '?'))]
        a[0] += n
        a[1] += tot_ns
        a[2] = max(a[2], mx)
    for pid, n in kswapd_wakers.items():
        askers[(names.get(pid, '?'), pidns.get(pid, '?'))][3] += n
    if askers:
        print("  Who was allocating when the host ran short (direct reclaim / kswapd wake-ups):")
        print(f"  {'name':<16} {'pid_ns':>12}{'direct':>8}{'stalled s':>11}{'max ms':>8}{'kswapd wakes':>14}")
        for (nm, nsid), (n, tot_ns, mx, kw) in sorted(askers.items(), key=lambda kv: (-kv[1][1], -kv[1][3]))[:6]:
            print(f"  {nm:<16} {nsid:>12}{n:>8}{tot_ns/ns:>11.2f}{mx/1e6:>8.1f}{kw:>14}")
        print("  (every process that allocates under host pressure shows up here, victims too - this")
        print("   table shows who SUFFERS. To name who TOOK the memory, read 'Large memory requests'")
        print("   below on a slice cut at the START of the window, with syscall_entry_mmap kept)")

# ---- 1b. who asked for memory ----------------------------------------------
if mmap_seen:
    print()
    print(f"Large memory requests in the slice (one writable anonymous mmap of {BIG_ALLOC_MB} MB or more)")
    big = sorted(((a[2], pid, a) for pid, a in allocs.items() if a[2] >= BIG_ALLOC_MB * 2**20), reverse=True)[:5]
    if not big:
        print(f"  none. No process asked for {BIG_ALLOC_MB} MB or more in one request here. A consumer asks ONCE, when it")
        print("  starts - cut this slice at the START of the window to catch it.")
    else:
        print(f"  {'pid':>8} {'pid_ns':>12} {'name':<16}{'calls':>7}{'total MB':>10}{'largest MB':>12}")
        for tot_b, pid, (n, b, mx) in big:
            print(f"  {pid:>8} {pidns.get(pid, '?'):>12} {names.get(pid, '?'):<16}{n:>7}{b/2**20:>10.0f}{mx/2**20:>12.0f}")
        print("  (a request is not yet use: it becomes pressure when the pages are touched. One process")
        print("   asking for GBs right where host reclaim starts is the consumer - name it and its pid_ns)")
    tot_b, pid, _ = big[0] if big else (0, None, None)
    if tot_b >= BIG_REQUEST_GB * 2**30:
        # the same program asking again under a new pid = it was killed and started again
        same = [p for p, al in allocs.items() if al[2] >= BIG_REQUEST_GB * 2**30
                and names.get(p) == names.get(pid) and pidns.get(p) == pidns.get(pid)]
        again = f"; {len(same)} processes of that name made such a request, so it was restarted" if len(same) > 1 else ""
        print(f"VERDICT: ONE LARGE MEMORY REQUEST: {names.get(pid, '?')} (pid {pid}, pid_ns {pidns.get(pid, '?')}) asked for "
              f"{tot_b/2**30:.1f} GB in one request, then used {sum(cpu_after[p] for p in same)/ns:.1f} s of CPU in the rest of the slice{again}")
    else:
        print(f"VERDICT: NO LARGE MEMORY REQUEST (largest: {tot_b/2**20:.0f} MB; the bar is {BIG_REQUEST_GB} GB in one request)")

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
print("  Host reclaim comes in BURSTS (seconds on, seconds off): one quiet slice does not")
print("  clear the host - sample three or four slices across the window before saying 'none'.")
print("- Reads with NO reclaim at all: cold cache or plain disk work - not a")
print("  memory limit. Check the disk blueprint instead.")
