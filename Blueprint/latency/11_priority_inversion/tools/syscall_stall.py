#!/usr/bin/env python3
"""
syscall_stall.py - find a thread stuck inside ONE system call for a long time, and what
that did to the threads around it.

Usage:
    python3 syscall_stall.py <slice.txt> [--min-ms 10] [--top 20] [--only clone,ioctl] [--pidmap FILE]

Input:
    A slice made by extract_slice.sh with this events regex (6th argument):
      'sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_'
    ('syscall_' also matches the compat_syscall_* names of a 32-bit userspace.) Works with
    or without a process-context block on the lines: a syscall event names no thread on a
    switch/router trace, so it is charged to whoever sched_switch put on that CPU.
    --pidmap FILE (from pidmap.py) tells the script which threads share a process.

What counts as a stall:
    Time a thread spends INSIDE one call while on the CPU or in D-state (uninterruptible: a
    kernel lock, a disk). That is the kernel working, or holding something, for that thread.
    Time asleep in S-state inside a call is not a stall even in a WORK-class call: drivers
    use ioctl() as a wait primitive (measured on a switch: ioctl "calls" of 1-30 s that were
    100% S-sleep). Such calls are reported as "sleeping inside ioctl" and left out, UNLESS a
    thread sat in D-state during the call and was woken by the caller - that is the
    memory-lock signature of fork, where the parent may sleep while the siblings are frozen.
    WAIT-class calls (poll, futex, read on a socket, nanosleep...) are always waits.

Output:
    1. per-syscall table: class, count, p50 / p99 / max wall ms, sleep% (WORK rows), unmatched
    2. the stalls, ranked by stall time = on-CPU + D inside the call (or by the longest
       D-state thread the call froze): wall, on-CPU, D, sleep%, who it froze, thread, args
       (clone_flags decoded)
    3. how often the top staller repeats
    4. impact of each top stall: sibling threads starved (same pid), threads released by the
       staller's wakeups during the call or 2 ms after it
    5. one verdict line in CAPS

Read it:
    - STALL in clone whose flags have no CLONE_VM (e.g. 0x100011 = a plain fork) from a
      thread of a big multithreaded process, with siblings starved / frozen in D during it:
      the fork is copying the address space under the memory lock. Fix: posix_spawn()/vfork
      (CLONE_VM|CLONE_VFORK, e.g. 0x4111), or move the spawn out of that process.
    - a long on-CPU ioctl / write / mmap: a driver or filesystem doing slow work for that thread.
    - only sleeping calls are long: nothing is stuck - see who wakes them (wait_chain.py).
"""
import sys
from array import array
from bisect import bisect_left
from collections import Counter, defaultdict, deque

from tracelib import Cpus, Sched, MS, SEC, hms, load_pidmap, prio_label, read_events

WAIT = {'poll', 'ppoll', 'select', 'pselect6', 'epoll_wait', 'epoll_pwait', 'epoll_pwait2',
        'futex', 'futex_waitv', 'nanosleep', 'clock_nanosleep', 'wait4', 'waitpid', 'waitid',
        'read', 'readv', 'recv', 'recvfrom', 'recvmsg', 'recvmmsg', 'accept', 'accept4',
        'mq_timedreceive', 'pause', 'sigwaitinfo', 'rt_sigtimedwait', 'sigsuspend',
        'sched_yield', 'msgrcv', 'semop', 'semtimedop', 'io_getevents', 'epoll_ctl_old'}
SCHED = {'sched_switch', 'sched_waking', 'sched_wakeup', 'sched_wakeup_new',
         'sched_process_fork', 'lttng_statedump_process_state'}
WAKES = ('sched_waking', 'sched_wakeup', 'sched_wakeup_new')
RELEASE_WINDOW = 2 * MS
SLEEPING = 0.9          # S-sleep share at or above which a WORK-class call is "sleeping inside"


class Names:
    """set-like filter for read_events: the sched events plus every syscall_* / compat_syscall_*."""
    def __contains__(self, n):
        return n in SCHED or n.startswith(('syscall_', 'compat_syscall_'))


NAMES = Names()


def sysname(evname):
    """'compat_syscall_entry_clone' -> ('entry', 'clone'); None for non-syscall events."""
    if evname.startswith('compat_'):
        evname = evname[7:]
    if evname.startswith('syscall_entry_'):
        return 'entry', evname[14:]
    if evname.startswith('syscall_exit_'):
        return 'exit', evname[13:]
    return None


def decode_clone(flags):
    if flags & 0x10000:
        return f"0x{flags:x} = new thread (CLONE_THREAD|CLONE_VM)"
    if flags & 0x100 and flags & 0x4000:
        return f"0x{flags:x} = vfork-style (CLONE_VM|CLONE_VFORK): no address-space copy, fast"
    if flags & 0x100:
        return f"0x{flags:x} = shares memory (CLONE_VM)"
    return (f"0x{flags:x} = fork of the whole address space (no CLONE_VM) - slow for a big "
            f"multithreaded process, and it holds the memory lock the siblings need")


def args_text(name, fields):
    if name in ('clone', 'clone3') and 'clone_flags' in fields:
        return decode_clone(fields['clone_flags'])
    keep = [k for k in ('fd', 'cmd', 'len', 'count', 'size', 'flags', 'prot', 'addr')
            if k in fields]
    return ', '.join(f"{k}={fields[k]}" for k in keep[:3])


def pctl(a, q):
    return a[min(len(a) - 1, int(q * len(a)))]


def overlap_ms(runs, t0, t1):
    """on-CPU ms of one thread inside [t0, t1) from its (since[], until[]) arrays."""
    since, until = runs
    tot = 0
    i = bisect_left(until, t0)
    while i < len(since) and since[i] < t1:
        tot += min(until[i], t1) - max(since[i], t0)
        i += 1
    return tot / MS


def analyse(path, min_ms=10.0, top=20, only=None, pidmap=None, out=print):
    min_ns = int(min_ms * MS)
    cp = Cpus()
    runs = defaultdict(lambda: (array('q'), array('q')))   # tid -> on-CPU intervals
    opened = {}             # tid -> [name, t_entry, ev_entry, cpu, {kind: ns inside the call}]
    durs = defaultdict(lambda: array('q'))                  # syscall -> wall durations
    wall_ns, sleep_ns = Counter(), Counter()                # per syscall, WORK rows' sleep%
    longest = {}            # syscall -> (wall, tid, t0, sleep share)
    hardest = {}            # syscall -> (on-CPU + D, tid, t0, wall)
    unmatched = Counter()
    stalls = []             # qualified WORK-class calls, in time order
    sleeping = defaultdict(lambda: [0, 0, 0])   # syscall -> [n, max wall, tid] reclassified calls
    tracer = defaultdict(lambda: [0, 0, 0, ''])  # syscall -> [n, max wall, max D, comm] by lttng-*
    pending = defaultdict(list)   # tid -> (wakee, blocked ns, state) woken inside its open long call
    recent = deque()        # (t_exit, tid, stall index) for the 2 ms after a stall
    released = defaultdict(list)  # stall index -> [(wakee tid, blocked ns, state)]

    def on_close(tid, kind, since, until, cpu):
        if kind == 'run':
            a, b = runs[tid]
            a.append(since)
            b.append(until)
        o = opened.get(tid)
        if o is not None and until > o[1]:
            o[4][kind] += until - max(since, o[1])

    sc = Sched(on_close=on_close, pidmap=pidmap)
    for ev in read_events(path, NAMES):
        n = ev.name
        if n in SCHED:
            if n in WAKES:
                t = ev.t
                while recent and t - recent[0][0] > RELEASE_WINDOW:
                    recent.popleft()
                waker = ev.tid_or(cp)
                o = opened.get(waker)
                inside = o is not None and o[0] not in WAIT and t - o[1] >= min_ns
                if recent or inside:
                    wk = ev.fields.get('tid')
                    st = sc.state.get(wk)
                    if wk and st and st[0] in ('S', 'D', 'O'):
                        rec = (wk, t - st[1], st[0])
                        if inside:
                            pending[waker].append(rec)
                        for te, tid, idx in recent:
                            if tid == waker:
                                released[idx].append(rec)
            sc.feed(ev)
            cp.feed(ev)
            continue
        sk = sysname(n)
        if sk is None:
            continue
        kind, name = sk
        tid = ev.tid_or(cp)
        if not tid:
            continue
        if ev.has_ctx():
            p = ev.ctx_pid()
            if p:
                sc.pid.setdefault(tid, p)           # a context block may name the pid too
        if kind == 'entry':
            if tid in opened:
                unmatched[opened[tid][0]] += 1
                pending.pop(tid, None)
            opened[tid] = [name, ev.t, ev, ev.cpu, defaultdict(int)]
            continue
        o = opened.pop(tid, None)
        if o is None or o[0] != name:
            unmatched[name] += 1
            pending.pop(tid, None)
            continue
        wall = ev.t - o[1]
        st = sc.state.get(tid)
        if st and ev.t > o[1]:
            o[4][st[0]] += ev.t - max(st[1], o[1])     # the still-open interval (normally run)
        split = o[4]
        hard = split['run'] + split['D']
        sleep = split['S'] + split['O']
        durs[name].append(wall)
        wall_ns[name] += wall
        sleep_ns[name] += sleep
        if wall > longest.get(name, (-1,))[0]:
            longest[name] = (wall, tid, o[1], sleep / wall if wall else 0.0)
        if hard > hardest.get(name, (-1,))[0]:
            hardest[name] = (hard, tid, o[1], wall)
        pend = pending.pop(tid, [])
        if name in WAIT or wall < min_ns or (only and name not in only):
            continue
        if sc.name(tid).startswith('lttng'):
            # the tracer's own flushes are instrumentation, never the system under test
            r = tracer[name]
            r[0] += 1
            r[1], r[2], r[3] = max(r[1], wall), max(r[2], split['D']), sc.name(tid)
            continue
        # a dependant counts only when its D-block is itself long: a 0.2 ms D wake is noise
        frozen = max((b for w, b, s in pend if s == 'D' and b >= min_ns), default=0)
        if hard < min_ns and not frozen:
            if wall and sleep >= SLEEPING * wall:
                r = sleeping[name]
                r[0] += 1
                if wall > r[1]:
                    r[1], r[2] = wall, tid
            continue
        idx = len(stalls)
        stalls.append({'tid': tid, 'name': name, 't0': o[1], 't1': ev.t, 'wall': wall,
                       'hard': hard, 'run': split['run'], 'D': split['D'], 'sleep': sleep,
                       'frozen': frozen, 'fields': o[2].fields})
        released[idx].extend(pend)
        recent.append((ev.t, tid, idx))
    sc.finish()
    for tid, o in opened.items():
        unmatched[o[0]] += 1
    span = sc.span_s() * SEC - sum(g1 - g0 for g0, g1 in sc.gaps)   # events-covered time

    def who(tid):
        return f"{sc.name(tid)} tid {tid} prio {prio_label(sc.prio.get(tid))}"

    note = sc.skipped_note()
    if note:
        out(note)
    # 1. per-syscall table
    out(f"syscalls paired: {sum(len(a) for a in durs.values())} calls, "
        f"{len(durs)} distinct; unmatched entry/exit: {sum(unmatched.values())}")
    out(f"{'syscall':<20}{'class':<6}{'count':>9}{'p50_ms':>9}{'p99_ms':>9}{'max_ms':>10}"
        f"{'sleep%':>7}{'unmatched':>10}")
    rows = sorted(durs.items(), key=lambda kv: -longest[kv[0]][0])
    for name, a in rows[:25]:
        a = sorted(a)
        sl = f"{100 * sleep_ns[name] / wall_ns[name]:.0f}" if name not in WAIT and wall_ns[name] else '-'
        out(f"{name:<20}{'WAIT' if name in WAIT else 'WORK':<6}{len(a):>9}"
            f"{pctl(a, .5) / MS:>9.2f}{pctl(a, .99) / MS:>9.2f}{a[-1] / MS:>10.1f}"
            f"{sl:>7}{unmatched.get(name, 0):>10}")
    if sleeping:
        out("WORK-class calls >= %g ms that were sleeping (>= %d%% S-state, left out as waits): "
            % (min_ms, SLEEPING * 100) + "; ".join(
                f"{nm} x{r[0]} (max {r[1] / MS:.1f} ms, {sc.name(r[2])})"
                for nm, r in sorted(sleeping.items(), key=lambda kv: -kv[1][1])[:6]))
    if tracer:
        out("tracer's own activity (left out): " + "; ".join(
            f"{nm} x{r[0]} (max {r[1] / MS:.0f} ms wall, {r[2] / MS:.0f} ms D) by {r[3]}"
            for nm, r in sorted(tracer.items(), key=lambda kv: -kv[1][1])[:6]))

    # 2. the stalls - a call that held other threads in D is what costs latency, so those
    # rank first; among the rest, the caller's own on-CPU + D time
    top_st = sorted(stalls, key=lambda s: (-s['frozen'], -s['hard']))[:top]
    out()
    out(f"stalls >= {min_ms:g} ms (on-CPU + D inside one WORK-class call, or a D-state thread "
        f"frozen by it >= {min_ms:g} ms), ranked by froze_ms then on-CPU + D: "
        f"top {len(top_st)} of {len(stalls)}")
    out(f"{'start':<14}{'wall':>7}{'on-CPU':>7}{'D':>6}{'sleep%':>7}{'froze_ms':>9}  thread | syscall | args")
    for s in top_st:
        out(f"{hms(s['t0']):<14}{s['wall'] / MS:>7.1f}{s['run'] / MS:>7.1f}{s['D'] / MS:>6.1f}"
            f"{100 * s['sleep'] / s['wall']:>7.0f}{s['frozen'] / MS:>9.1f}  {who(s['tid'])} | "
            f"{s['name']} | {args_text(s['name'], s['fields'])}")

    # 3. periodicity of the top staller
    period_txt = ''
    if top_st:
        key = (top_st[0]['tid'], top_st[0]['name'])
        starts = sorted(s['t0'] for s in stalls if (s['tid'], s['name']) == key)
        gaps = [(b - a) / SEC for a, b in zip(starts, starts[1:])]
        out()
        if len(starts) >= 3:
            mean = sum(gaps) / len(gaps)
            period_txt = f"{len(starts)} times, every ~{mean:.1f} s"
            out(f"repeat: {sc.name(key[0])} tid {key[0]} in {key[1]} repeats every ~{mean:.1f} s "
                f"({len(starts)} instances, gap min {min(gaps):.1f} max {max(gaps):.1f} s)")
        elif len(starts) == 2:
            period_txt = f"2 times, {gaps[0]:.1f} s apart"
            out(f"repeat: 2 instances, {gaps[0]:.1f} s apart")
        else:
            period_txt = "once"
            out("repeat: seen once in this slice")

    # 4. impact
    impact_bits = []
    if top_st:
        out()
        out("impact of the top stalls:")
    for s in top_st[:5]:
        t0, t1, tid = s['t0'], s['t1'], s['tid']
        out(f"- {hms(t0)} {sc.name(tid)} tid {tid} {s['name']} {s['wall'] / MS:.1f} ms "
            f"({s['run'] / MS:.1f} on-CPU, {s['D'] / MS:.1f} D, {s['sleep'] / MS:.1f} sleep)")
        pid = sc.pid.get(tid)
        sibs = [t for t, p in sc.pid.items() if p == pid and t != tid] if pid else []
        starved = []
        if sibs and span > 0:
            rowsib = []
            for sib in sibs:
                exp = sc.acc[sib]['run'] / span * s['wall'] / MS
                got = overlap_ms(runs[sib], t0, t1) if sib in runs else 0.0
                if exp >= 0.5 or got > 0:
                    rowsib.append((exp, got, sib))
            rowsib.sort(reverse=True)
            for exp, got, sib in rowsib[:8]:
                flag = "  <- STARVED" if exp >= 1.0 and got < 0.25 * exp else ""
                out(f"    sibling {sc.name(sib)} tid {sib}: {got:.1f} ms on-CPU during the stall "
                    f"vs {exp:.1f} ms expected{flag}")
                if flag:
                    starved.append(sc.name(sib))
            if not rowsib:
                out(f"    {len(sibs)} sibling threads of pid {pid}, none active enough to judge")
        elif not pid:
            out("    siblings: pid unknown on this slice (give --pidmap from pidmap.py, or include "
                "sched_process_fork / lttng_statedump_process_state in the slice)")
        rel = released.get(stalls.index(s), [])
        # D-state dependants were frozen by the call; S-state ones are timers / condvars that
        # happened to be woken by this thread - shown, but never counted as a freeze
        drel = sorted((r for r in rel if r[2] == 'D'), key=lambda r: -r[1])
        srel = sorted((r for r in rel if r[2] != 'D'), key=lambda r: -r[1])
        if drel:
            out("    frozen in D and released by the caller: " + "; ".join(
                f"{sc.name(w)} tid {w} blocked {b / MS:.1f} ms" for w, b, _ in drel[:6]))
        if srel:
            out("    also woken by the caller (S-state: their own timers / condvars, not freezes): "
                + "; ".join(f"{sc.name(w)} tid {w} blocked {b / MS:.1f} ms" for w, b, _ in srel[:6]))
        if not rel:
            out("    released by the caller: nobody woken by this thread during or just after the call")
        if s is top_st[0]:
            best = {}
            for w, b, _ in drel:
                if b >= min_ns and b > best.get(w, 0):
                    best[w] = b
            if best:
                names = [sc.name(w) for w in sorted(best, key=best.get, reverse=True)]
                impact_bits.append(f"it froze {len(best)} thread{'s' if len(best) > 1 else ''} in D "
                                   f"for up to {max(best.values()) / MS:.1f} ms ({', '.join(names[:4])})")
            if starved:
                impact_bits.append("siblings starved: " + ", ".join(starved[:4]))
            if drel:
                impact_bits.append("released at exit: " + ", ".join(
                    f"{sc.name(w)} ({b / MS:.0f} ms blocked)" for w, b, _ in drel[:3]))

    # 5. verdict
    out()
    if top_st:
        s = top_st[0]
        split = f"{s['run'] / MS:.1f} ms on-CPU + {s['D'] / MS:.1f} ms D"
        if s['sleep'] >= SLEEPING * s['wall']:
            split += f", {100 * s['sleep'] / s['wall']:.0f}% sleeping"
        out(f"STALL: {sc.name(s['tid'])} tid {s['tid']} spent {s['wall'] / MS:.1f} ms in "
            f"{s['name']} ({split}; {args_text(s['name'], s['fields']) or 'no args'}) - "
            + "; ".join([period_txt] + (impact_bits or ['no sibling or freeze effect measured'])))
    else:
        h = max(((v, n) for n, v in hardest.items() if n not in WAIT), default=None)
        if h:
            (hard, tid, t0, wall), n = h
            out(f"NO WORK-CLASS SYSCALL >= {min_ms:g} ms (longest on-CPU+D inside one call: "
                f"{n} {hard / MS:.1f} ms of a {wall / MS:.1f} ms call by {who(tid)})")
        else:
            out(f"NO WORK-CLASS SYSCALL >= {min_ms:g} ms (no WORK-class call seen at all)")
    stall_keys = {(s['name'], s['t0']) for s in stalls}
    waits = [(w, n, tid, sl) for n, (w, tid, t0, sl) in longest.items()
             if w >= min_ns and (n in WAIT or sl >= SLEEPING) and (n, t0) not in stall_keys]
    if waits:
        w, n, tid, sl = max(waits)
        what = "WAIT-class calls (poll/futex/...)" if n in WAIT else f"sleeping inside WORK-class calls ({n})"
        out(f"long waits are in {what} = normal sleeping, not a stall "
            f"(longest: {n} {w / MS:.1f} ms by {who(tid)}, {100 * sl:.0f}% asleep)")


def main():
    if '--selftest' in sys.argv:
        return _selftest()
    a = sys.argv[1:]
    if not a or a[0].startswith('--'):
        raise SystemExit(__doc__)

    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default
    only = opt('--only', None)
    analyse(a[0], float(opt('--min-ms', 10)), int(opt('--top', 20)),
            set(only.split(',')) if only else None, load_pidmap(opt('--pidmap', None)))


# ---- self-test ---------------------------------------------------------------------------
def _fmt(t):
    s, rem = divmod(t, SEC)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{rem:09d}"


def _mk(ctx):
    """Line builder for one shape. ctx=True: Sock-Shop style context block, numeric prev_state,
    syscall_entry_*; ctx=False: no context, enum prev_state, compat_syscall_*; ctx='name':
    a context block holding only procname (measured on a switch), enum, compat."""
    def L(t, cpu, ev, pay, tid=0, pid=0, name='swapper'):
        if ctx is True:
            return (f"[{_fmt(t)}] (+0.000000001) h {ev}: {{ cpu_id = {cpu} }}, "
                    f"{{ pid = {pid}, tid = {tid}, procname = \"{name}\" }}, {{ {pay} }}")
        if ev.startswith('syscall_'):
            ev = 'compat_' + ev
        pay = pay.replace('prev_state = 1,', 'prev_state = ( "TASK_INTERRUPTIBLE" : container = 1 ),') \
                 .replace('prev_state = 2,', 'prev_state = ( "TASK_UNINTERRUPTIBLE" : container = 2 ),')
        c = f'{{ procname = "{name}" }}, ' if ctx == 'name' else ''
        return f"[{_fmt(t)}] (+0.000000001) h {ev}: {{ cpu_id = {cpu} }}, {c}{{ {pay} }}"
    return L


def _sw(prev, pname, pprio, state, nxt, nname, nprio=20):
    return (f'prev_comm = "{pname}", prev_tid = {prev}, prev_prio = {pprio}, prev_state = {state}, '
            f'next_comm = "{nname}", next_tid = {nxt}, next_prio = {nprio}')


def _scenario_a(ctx, with_fork=True, sleepy=False):
    """spawnerThr (7231, pid 7087) forks with clone 0x100011 for 53 ms, three times 7 s apart;
    its sibling commsTx (7249) freezes in D each time and is woken by spawnerThr 52.9 ms in.
    sleepy: the parent itself sleeps (S) for 51 of the 53 ms - only the frozen sibling tells."""
    L = _mk(ctx)
    PE, EC, PID = 7231, 7249, 7087
    base = 10 * 3600 * SEC
    lines = [L(base, 0, 'lttng_statedump_process_state',
               f'tid = {EC}, pid = {PID}, ppid = 7010, name = "commsTx", type = 0'),
             L(base + 1, 2, 'sched_switch', _sw(0, 'swapper/2', 20, 0, PE, 'spawnerThr'), 0, 0),
             L(base + 2, 1, 'sched_switch', _sw(0, 'swapper/1', 20, 0, 7738, 'hwPoll', 39), 0, 0),
             # hwPoll: an 80 ms fully on-CPU ioctl that freezes nobody - more on-CPU than the
             # clone, yet it must rank below it (froze_ms first)
             L(base + 5 * SEC + 1, 1, 'syscall_entry_ioctl', 'fd = 9, cmd = 7, arg = 0', 7738, 7738, 'hwPoll'),
             L(base + 5 * SEC + 80 * MS, 1, 'syscall_exit_ioctl', 'ret = 0', 7738, 7738, 'hwPoll'),
             # the tracer flushing its buffers: 175 ms in D - instrumentation, left out
             L(base + 6 * SEC, 3, 'sched_switch', _sw(0, 'swapper/3', 20, 0, 6942, 'lttng-consumerd'), 0, 0),
             L(base + 6 * SEC + 1000, 3, 'syscall_entry_sync_file_range2', 'fd = 12, flags = 2, offset = 0, nbytes = 4096',
               6942, 6942, 'lttng-consumerd'),
             L(base + 6 * SEC + 24 * MS, 3, 'sched_switch', _sw(6942, 'lttng-consumerd', 20, 2, 0, 'swapper/3'),
               6942, 6942, 'lttng-consumerd'),
             L(base + 6 * SEC + 199 * MS, 3, 'sched_waking', 'comm = "lttng-consumerd", tid = 6942, prio = 20, target_cpu = 3', 0, 0),
             L(base + 6 * SEC + 199 * MS + 100, 3, 'sched_switch', _sw(0, 'swapper/3', 20, 0, 6942, 'lttng-consumerd'), 0, 0),
             L(base + 6 * SEC + 199 * MS + 200, 3, 'syscall_exit_sync_file_range2', 'ret = 0', 6942, 6942, 'lttng-consumerd'),
             L(base + 6 * SEC + 200 * MS, 3, 'sched_switch', _sw(6942, 'lttng-consumerd', 20, 1, 0, 'swapper/3'),
               6942, 6942, 'lttng-consumerd')]
    stall_at = {base + k * SEC for k in (12, 19, 26)}
    flags = '0x100011' if ctx is not True else str(0x100011)
    t = base + 5 * MS
    end = base + 30 * SEC
    while t < end:
        if (t - base) % (200 * MS) == 100 * MS:
            # spawnerThr's cpu must not fall silent for 500 ms (that reads as a trace hole):
            # it naps 1 ms every 200 ms, woken by hwPoll, never inside a stall window
            lines.append(L(t, 2, 'sched_switch', _sw(PE, 'spawnerThr', 20, 1, 0, 'swapper/2'), PE, PID, 'spawnerThr'))
            lines.append(L(t + 1 * MS, 1, 'sched_waking',
                           f'comm = "spawnerThr", tid = {PE}, prio = 20, target_cpu = 2', 7738, 7738, 'hwPoll'))
            lines.append(L(t + 1 * MS + 1, 2, 'sched_switch', _sw(0, 'swapper/2', 20, 0, PE, 'spawnerThr'), 0, 0))
        if t in stall_at:
            T = t
            lines.append(L(T, 2, 'syscall_entry_clone',
                           f'clone_flags = {flags}, newsp = 0, parent_tid = 0, child_tid = 0, tls = 0',
                           PE, PID, 'spawnerThr'))
            lines.append(L(T + 200_000, 0, 'sched_switch', _sw(0, 'swapper/0', 20, 0, EC, 'commsTx'), 0, 0))
            lines.append(L(T + 400_000, 0, 'sched_switch', _sw(EC, 'commsTx', 20, 2, 0, 'swapper/0'),
                           EC, PID, 'commsTx'))
            if sleepy:
                lines.append(L(T + 1 * MS, 2, 'sched_switch', _sw(PE, 'spawnerThr', 20, 1, 0, 'swapper/2'),
                               PE, PID, 'spawnerThr'))
                lines.append(L(T + 52 * MS, 1, 'sched_waking',
                               f'comm = "spawnerThr", tid = {PE}, prio = 20, target_cpu = 2', 7738, 7738, 'hwPoll'))
                lines.append(L(T + 52 * MS + 100_000, 2, 'sched_switch',
                               _sw(0, 'swapper/2', 20, 0, PE, 'spawnerThr'), 0, 0))
            lines.append(L(T + 52_900_000, 2, 'sched_waking',
                           f'comm = "commsTx", tid = {EC}, prio = 20, target_cpu = 0', PE, PID, 'spawnerThr'))
            lines.append(L(T + 53_000_000, 2, 'syscall_exit_clone', 'ret = 9743', PE, PID, 'spawnerThr'))
            if with_fork:
                lines.append(L(T + 53_100_000, 2, 'sched_process_fork',
                               f'parent_comm = "spawnerThr", parent_tid = {PE}, parent_pid = {PID}, '
                               f'child_comm = "spawnerThr", child_tid = 9743, child_pid = 9743',
                               PE, PID, 'spawnerThr'))
            lines.append(L(T + 54_000_000, 0, 'sched_switch', _sw(0, 'swapper/0', 20, 0, EC, 'commsTx'), 0, 0))
            lines.append(L(T + 55_000_000, 0, 'sched_switch', _sw(EC, 'commsTx', 20, 1, 0, 'swapper/0'),
                           EC, PID, 'commsTx'))
            t = T + 60 * MS
            continue
        # normal cycle: run 1 ms, sleep 4 ms, woken by softirq NET_RX on cpu 0
        lines.append(L(t, 0, 'sched_switch', _sw(0, 'swapper/0', 20, 0, EC, 'commsTx'), 0, 0))
        lines.append(L(t + 1 * MS, 0, 'sched_switch', _sw(EC, 'commsTx', 20, 1, 0, 'swapper/0'),
                       EC, PID, 'commsTx'))
        lines.append(L(t + 4_900_000, 0, 'irq_softirq_entry', 'vec = 3', 0, 0))
        lines.append(L(t + 4_900_001, 0, 'sched_waking',
                       f'comm = "commsTx", tid = {EC}, prio = 20, target_cpu = 0', 0, 0))
        lines.append(L(t + 4_900_002, 0, 'irq_softirq_exit', 'vec = 3', 0, 0))
        t += 5 * MS
    lines.sort(key=lambda l: l[:20])      # a slice is in time order; the timestamp is fixed-width
    return lines


def _scenario_b(ctx):
    """a 200 ms poll and a 300 ms ioctl that is pure S-sleep (a driver waiting) by 'pollr',
    then a 6 us on-CPU ioctl - nothing here is a stall."""
    L = _mk(ctx)
    base = 11 * 3600 * SEC
    t = base
    lines = [L(t, 1, 'sched_switch', _sw(0, 'swapper/1', 20, 0, 500, 'pollr'), 0, 0),
             L(t + 1000, 1, 'syscall_entry_poll', 'ufds = 1, nfds = 1, timeout_msecs = 1000', 500, 500, 'pollr'),
             L(t + 2000, 1, 'sched_switch', _sw(500, 'pollr', 20, 1, 0, 'swapper/1'), 500, 500, 'pollr'),
             L(t + 200 * MS, 1, 'sched_waking', 'comm = "pollr", tid = 500, prio = 20, target_cpu = 1', 0, 0),
             L(t + 200 * MS + 1000, 1, 'sched_switch', _sw(0, 'swapper/1', 20, 0, 500, 'pollr'), 0, 0),
             L(t + 200 * MS + 2000, 1, 'syscall_exit_poll', 'ret = 1', 500, 500, 'pollr')]
    t += 201 * MS
    lines += [L(t, 1, 'syscall_entry_ioctl', 'fd = 7, cmd = 3224433687, arg = 0', 500, 500, 'pollr'),
              L(t + 1000, 1, 'sched_switch', _sw(500, 'pollr', 20, 1, 0, 'swapper/1'), 500, 500, 'pollr'),
              L(t + 300 * MS, 1, 'sched_waking', 'comm = "pollr", tid = 500, prio = 20, target_cpu = 1', 0, 0),
              L(t + 300 * MS + 1000, 1, 'sched_switch', _sw(0, 'swapper/1', 20, 0, 500, 'pollr'), 0, 0),
              L(t + 300 * MS + 2000, 1, 'syscall_exit_ioctl', 'ret = 0', 500, 500, 'pollr')]
    t += 301 * MS
    lines += [L(t, 1, 'syscall_entry_ioctl', 'fd = 3, cmd = 1, arg = 0', 500, 500, 'pollr'),
              L(t + 6000, 1, 'syscall_exit_ioctl', 'ret = 0', 500, 500, 'pollr'),
              L(t + 100 * MS, 1, 'sched_switch', _sw(500, 'pollr', 20, 1, 0, 'swapper/1'), 500, 500, 'pollr')]
    return lines


def _run(lines, **kw):
    import os
    import tempfile
    outl = []
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as tf:
        tf.write('\n'.join(lines) + '\n')
        p = tf.name
    try:
        analyse(p, out=lambda *a: outl.append(' '.join(str(x) for x in a)), **kw)
    finally:
        os.unlink(p)
    return '\n'.join(outl)


def _selftest():
    import os
    import tempfile
    for ctx in (True, False, 'name'):
        r = _run(_scenario_a(ctx))
        verdict = [l for l in r.splitlines() if l.startswith('STALL')]
        assert len(verdict) == 1, r
        v = verdict[0]
        assert 'spawnerThr tid 7231 spent 53.0 ms in clone (53.0 ms on-CPU + 0.0 ms D; ' in v, v
        assert '0x100011 = fork of the whole address space' in v, v
        assert ') - 3 times, every ~7.0 s; it froze 1 thread in D for up to 52.5 ms (commsTx); ' \
               'siblings starved: commsTx; released at exit: commsTx (52 ms blocked)' in v, v
        assert '<- STARVED' in r and 'vs 10.' in r, r         # ~20% duty -> ~10.6 ms expected
        assert 'repeats every ~7.0 s (3 instances' in r, r
        assert 'frozen in D and released by the caller: commsTx tid 7249 blocked 52.5 ms' in r, r
        assert 'long waits are in' not in r, r
        # ranking: hwPoll's 80 ms on-CPU ioctl froze nobody, so it sits below the clones
        tbl = [l for l in r.splitlines() if '| ioctl |' in l or '| clone |' in l]
        assert len(tbl) == 4 and all('| clone |' in l for l in tbl[:3]) and '| ioctl |' in tbl[3], tbl
        assert '   80.0   80.0   0.0      0      0.0  hwPoll tid 7738 prio 139 (nice 19) | ioctl | fd=9, cmd=7' in tbl[3], tbl
        # the tracer's own flush (175 ms D) is reported apart and never ranked
        assert "tracer's own activity (left out): sync_file_range2 x1 (max 199 ms wall, 175 ms D) " \
               "by lttng-consumerd" in r, r
        assert 'lttng' not in '\n'.join(tbl) and 'STALL: lttng' not in r, r
        # the parent sleeps through its own clone: only the frozen D-state sibling makes it a stall
        r = _run(_scenario_a(ctx, sleepy=True))
        v = [l for l in r.splitlines() if l.startswith('STALL')][0]
        assert 'spent 53.0 ms in clone (1.9 ms on-CPU + 0.0 ms D, 96% sleeping; 0x100011' in v, v
        assert ') - 3 times, every ~7.0 s; it froze 1 thread in D for up to 52.5 ms (commsTx); ' \
               'siblings starved: commsTx' in v, v
        assert 'long waits are in' not in r, r        # a qualified stall is not also "normal sleeping"
        # the froze floor: a dependant's D-block below --min-ms does not qualify the call
        r = _run(_scenario_a(ctx, sleepy=True), min_ms=60, only={'clone'})
        assert 'STALL' not in r and 'NO WORK-CLASS SYSCALL >= 60 ms' in r, r
        # no fork event and no statedump: siblings unknown unless the context or --pidmap says
        lines = [l for l in _scenario_a(ctx, with_fork=False) if 'statedump' not in l]
        r2 = _run(lines)
        if ctx is True:
            assert 'siblings starved: commsTx' in r2, r2       # the context block carries the pid
        else:
            assert 'pid unknown on this slice' in r2, r2
            with tempfile.NamedTemporaryFile('w', delete=False, suffix='.tsv') as tf:
                tf.write('# tid\tpid\tppid\tname\ttype\n7231\t7087\t7010\tspawnerThr\t0\n'
                         '7249\t7087\t7010\tcommsTx\t0\n')
                pm = tf.name
            try:
                r3 = _run(lines, pidmap=load_pidmap(pm))
            finally:
                os.unlink(pm)
            assert 'siblings starved: commsTx' in r3, r3
        # scenario B: a sleeping ioctl is a wait, not a stall
        r = _run(_scenario_b(ctx))
        assert 'NO WORK-CLASS SYSCALL >= 10 ms (longest on-CPU+D inside one call: ioctl 0.0 ms ' \
               'of a 0.0 ms call by pollr tid 500' in r, r
        assert 'long waits are in sleeping inside WORK-class calls (ioctl) = normal sleeping, not a ' \
               'stall (longest: ioctl 300.0 ms by pollr tid 500 prio 120 (nice 0), 100% asleep)' in r, r
        assert 'WORK-class calls >= 10 ms that were sleeping (>= 90% S-state, left out as waits): ' \
               'ioctl x1 (max 300.0 ms, pollr)' in r, r
        assert 'ioctl               WORK          2' in r and '    100         0' in r, r   # sleep% column
        r = _run(_scenario_b(ctx), min_ms=0.005)
        assert 'STALL: pollr tid 500 spent 0.0 ms in ioctl (0.0 ms on-CPU + 0.0 ms D; fd=3, cmd=1) - once' in r, r
    print("syscall_stall selftest OK")


if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
