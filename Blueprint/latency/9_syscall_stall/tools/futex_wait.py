#!/usr/bin/env python3
"""
futex_wait.py - who waits on user-space locks (futexes), for how long, and whether the thread
that should release the lock was itself kept off the CPU (priority inversion) or simply held
it too long (lock contention).

Usage:
    python3 futex_wait.py <slice.txt> <slice_seconds> [--top 10] [--min-ms 1] [--pidmap FILE]

Input:
    A slice made by extract_slice.sh with this events regex:
      'sched_switch|sched_waking|sched_wakeup|syscall_entry_futex|syscall_exit_futex'
    (compat_syscall_* names are accepted too.) --pidmap is the file pidmap.py writes, used
    only to print pids next to tids on traces that carry no process context.

What counts as a lock wait:
    Programs also use futex as a timer: "wait up to 100 ms unless woken". Those waits end with
    ret = -110 (ETIMEDOUT) and nobody woke them - they are sleeps, not lock waits, and they
    are the commonest false alarm (measured: 100 ms, 1 s, 3 s and 5 s loops on real switch
    traces). EINTR (-4), EAGAIN (-11, the value had already changed) and restart (-512/-514)
    returns are not lock waits either.

    But a thread that wants a lock often polls for it: a pthread_cond_timedwait loop issues
    5 ms timed waits back to back until a wake finally arrives (measured on our own labelled
    priority-inversion run: 20 timed pieces, then one woken piece). So consecutive waits by
    the SAME thread, each at most 50 ms long and entered within 1 ms of the previous one's
    exit, with intermediate returns -110 or -11, are coalesced into ONE logical wait from the
    first entry to the last exit (a wake op the thread issues in between, e.g. on the other
    half of a condvar pair, does not break the run). Pieces longer than 50 ms are a timer
    loop (measured: 1 s database heartbeats) and stay individual. The logical wait is judged
    by its LAST exit:
      ret 0  with a wake op on that futex inside the window  -> a lock wait (see below)
      ret -110 / -11 after two or more pieces                 -> a poll-run: the thread kept
                                                                 re-waiting until it could go on
      a single timed wait                                      -> a timed sleep
    A lock wait whose releaser we could not watch (its scheduling state covers less than half
    of the wait, because it hardly appears in the slice) is "releaser unseen" and is counted
    but never judged. Waits by or released by the tracer's own threads (lttng-*) are left out.

Lock or signal? The HAND-OFF test:
    A mutex is passed between threads that all wait on it, so the thread that releases a
    lock wait is itself a thread that waited on the SAME futex somewhere in the slice. Such a
    wait is a lock wait whatever the releaser was doing - running (held), runnable (preempted
    while holding) or sleeping (held-asleep: the lock is held across a sleep or I/O, the
    shape of our labelled lock_contention run). A releaser that NEVER waited on that futex
    is a signaller (a condition variable, a queue): if it slept for most of the wait that is
    an event wait, not a lock problem; if it ran, it is a producer handing work over.

What the releasing thread was doing during the wait:
    inversion   runnable-but-not-running >= 30% of the wait with a WORSE priority than the
                waiter: priority inversion (needs >= 2 such waits, the longest >= 10 ms).
    held        running >= 50%: it held the lock and worked.
    preempted   runnable >= 30% with an equal or better priority: a CPU shortage, not a
                lock fault (see 8_cpu_starvation).
    held-asleep hand-off releaser that mostly slept: the lock is held across a sleep or I/O.
    event       non-hand-off releaser sleeping >= 50%: it signalled when it woke up.
    mixed       none of the above; shown in the table, never in a verdict.
    A 30-40 microsecond median with thousands of waits per second is normal signalling between
    threads; the number of waits never makes a verdict here, only time does.

Output:
    1. Per futex (uaddr): woken / hand-off / poll-run / timed-out / other logical waits, how
       many are coalesced runs, distinct waiters, lock waits per second, p50/p99/max lock
       wait, total, the wait pattern, and the threads that release it (wake ops) with their
       priority. For the busiest futex: how much of each waiter's time goes into waiting on
       it. Then one line each for poll-runs, timed sleeps, other returns, unseen releasers
       and the tracer's own waits.
    2. The longest lock waits with a releaser that was not sleeping (>= --min-ms, top N):
       waiter, futex, when, class (and run length); the wake that ended it and who issued it;
       what that releasing thread was doing DURING the wait and, when it was kept off the
       CPU, which threads had its CPU. Then the single longest event wait on its own line, so
       50 s condition-variable waits cannot hide 100 ms lock waits.
    3. A verdict line in CAPS.

The verdicts:
    PRIORITY INVERSION  >= 2 inversion-class waits, the longest >= 10 ms. Fix: priority
                        inheritance on the lock (PTHREAD_PRIO_INHERIT / FUTEX_LOCK_PI), or do
                        not hold the lock across a scheduling boundary.
    LOCK CONTENTION     on one futex, hand-off lock waits by >= 2 threads add up to >= 5% of
                        the slice or one waiter spends >= 20% of its time in them, their
                        median is >= 0.2 ms and their tail is bounded (p99/p50 <= 50; idle
                        parking has a p99/p50 of 150+). The state word says whether holders
                        run, are preempted, or sleep while holding. Fix: shrink the critical
                        section, split the lock, and never sleep or do I/O while holding it.
    NO LOCK PROBLEM     everything else that is long enough to look at: an event wait, a
                        held lock under the bars above, an idle worker (one waiter), a
                        signaller, a preempted equal-priority releaser, or inversion-class
                        waits below the 10 ms bar - each line says which.
    NO LONG FUTEX WAITS nothing reaches --min-ms (or no lock wait at all).

Read it:
    - Priorities print as kernel prio (nice): 120 (nice 0) is the default; a smaller number is
      better. RT N is a real-time priority, better than any nice value.
    - Per-second and share numbers use the seconds the slice actually holds events for (a note
      says so when that is shorter than the slice you cut).
"""
import sys
from array import array
from bisect import bisect_left
from collections import defaultdict, Counter

from tracelib import (read_events, Cpus, Sched, prio_label, hms, load_pidmap, SEC, MS, pct,
                      effective_secs)

WANTED = {'sched_switch', 'sched_waking', 'sched_wakeup', 'sched_wakeup_new',
          'syscall_entry_futex', 'syscall_exit_futex',
          'compat_syscall_entry_futex', 'compat_syscall_exit_futex'}

# Thresholds. Calibrated on five real switch/router traces (no lock fault: every branch below
# must stay quiet on them) and on our labeled Sock Shop runs (priority_inversion_* = poll-runs
# of timed waits ended by a preempted holder; lock_contention_* = 16 threads on one lock whose
# holder sleeps while holding; plus their baselines: a Node worker idling on one futex, a Go
# runtime parking threads on one, database heartbeats every second, 10 ms poll loops).
LONG_WAIT_MS = 1.0               # default --min-ms: waits shorter than this are not examined
INVERSION_RUNNABLE_SHARE = 0.30  # releaser runnable-but-not-running for >= this share of the wait
INVERSION_MIN_MS = 20.0          # the PRIORITY INVERSION verdict needs 2+ such waits, max >= this
# (the labelled fault's longest inversion-class wait is 34 ms; two healthy line cards show
#  10.1 / 10.5 ms ones between background threads)
HOLDER_RUNNING_SHARE = 0.50      # releaser running >= this share of the wait -> held
EVENT_SLEEP_SHARE = 0.50         # non-hand-off releaser sleeping >= this share -> an event wait
RELEASER_SEEN_SHARE = 0.50       # releaser's measured state must cover >= this share, else unseen
CONTENTION_TOTAL_SHARE = 0.05    # hand-off wait time on ONE futex >= this share of the slice ...
CONTENTION_WAITER_SHARE = 0.20   # ... or one waiter thread spends >= this share of its time in them
CONTENTION_MIN_P50_MS = 0.2      # ... and the median such wait is at least this (30-40 us = signalling)
CONTENTION_MIN_WAITERS = 2       # ... and at least this many threads wait on it (1 = an idle worker)
TAIL_RATIO_MAX = 50              # ... and p99/p50 at most this (a critical section has a bounded wait)
COALESCE_GAP_MS = 1.0            # a next wait entered within this of the previous exit continues a run
COALESCE_PIECE_MS = 50.0         # only pieces this short can form a run (longer ones = a timer loop)
PATTERN_MANY_PER_S = 20          # only the 'many short' pattern word in the table; never a trigger
ETIMEDOUT = -110                 # a wait that ran out its timeout: a timed sleep, not a lock wait
POLL_RETS = {ETIMEDOUT, -11}     # returns that keep a poll-run going (timed out / value changed)
# EINTR, EAGAIN (the value had already changed: no wait happened), restart: not lock waits either
NOT_LOCK_RET = {-4, -11, -512, -514}
TRACER_PREFIX = 'lttng'          # the tracer's own threads never reach a verdict

# futex op & 0x7f -> command (0x80 PRIVATE and 0x100 CLOCK_REALTIME are flags)
WAIT_CMDS = {0: 'WAIT', 6: 'LOCK_PI', 9: 'WAIT_BITSET', 11: 'WAIT_REQUEUE_PI'}
WAKE_CMDS = {1: 'WAKE', 3: 'REQUEUE', 4: 'CMP_REQUEUE', 7: 'UNLOCK_PI', 10: 'WAKE_BITSET',
             12: 'CMP_REQUEUE_PI'}
CODE = {'run': 0, 'rqP': 1, 'rqW': 2, 'S': 3, 'D': 4, 'O': 5}

# field order of a judged lock wait
DUR, TID, T0, T1, HTID, HT, CLS, PIECES, RUN, RQ, SL, HO = range(12)
LOCK_CLASSES = ('inversion', 'held', 'preempted', 'held-asleep')   # hand-off = a real lock


def pctl(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


def nice_ms(ms):
    """100.37 -> '100 ms', 1046 -> '1 s', 5000.1 -> '5 s' (two significant digits)."""
    v = float(f"{ms:.2g}")
    return f"{v / 1000:g} s" if v >= 1000 else f"{v:g} ms"


def run_txt(pieces):
    return f" (a run of {pieces} timed waits)" if pieces >= 2 else ""


class Store:
    """Closed scheduling intervals, compact: per thread (code, since, until, cpu) and per CPU
    the run intervals (tid, since, until). Both arrive in order of 'until', so bisect works."""

    def __init__(self):
        self.iv = defaultdict(lambda: (array('q'), array('q'), array('q'), array('q')))
        self.run = defaultdict(lambda: (array('q'), array('q'), array('q')))

    def on_close(self, tid, kind, since, until, cpu):
        c, s, u, cp = self.iv[tid]
        c.append(CODE[kind]); s.append(since); u.append(until); cp.append(cpu if cpu is not None else -1)
        if kind == 'run':
            t, s2, u2 = self.run[cpu]
            t.append(tid); s2.append(since); u2.append(until)

    def during(self, tid, t0, t1, want_occ=True):
        """ns running / runnable-not-running / sleeping for tid in [t0, t1], plus who had its
        CPU (Counter tid -> ns) while it was runnable-not-running."""
        run = rq = sl = 0
        occ = Counter()
        if tid not in self.iv:
            return run, rq, sl, occ
        c, s, u, cp = self.iv[tid]
        i = bisect_left(u, t0)
        while i < len(u) and s[i] <= t1:
            a, b = max(s[i], t0), min(u[i], t1)
            if b > a:
                if c[i] == 0:
                    run += b - a
                elif c[i] in (1, 2):
                    rq += b - a
                    if want_occ:
                        self._occupants(cp[i], a, b, occ)
                else:
                    sl += b - a
            i += 1
        return run, rq, sl, occ

    def _occupants(self, cpu, a, b, occ):
        if cpu not in self.run:
            return
        t, s, u = self.run[cpu]
        i = bisect_left(u, a)
        while i < len(u) and s[i] <= b:
            d = min(u[i], b) - max(s[i], a)
            if d > 0:
                occ[t[i]] += d
            i += 1


def analyse(path, secs, pidmap=None):
    cp = Cpus()
    st = Store()
    sc = Sched(on_close=st.on_close, pidmap=pidmap)
    open_wait = {}                              # tid -> (uaddr, t0) of the wait in progress
    runs = {}                                   # tid -> [ua_first, ua_last, t0, t1, ret, pieces]
    waits = defaultdict(list)                   # ua_last -> [(dur, tid, t0, t1, ret, pieces, ua_first)]
    waited_on = defaultdict(set)                # uaddr -> tids that ever entered a wait on it
    wake_t, wake_tid = defaultdict(list), defaultdict(list)
    wakers = defaultdict(Counter)               # uaddr -> tid -> wake ops
    n_entry = n_exit = 0
    t_last = None
    gap, piece_max = int(COALESCE_GAP_MS * MS), int(COALESCE_PIECE_MS * MS)

    def flush(tid):
        rn = runs.pop(tid, None)
        if rn is not None:
            ua_first, ua_last, t0, t1, ret, pieces = rn
            waits[ua_last].append((t1 - t0, tid, t0, t1, ret, pieces, ua_first))

    for ev in read_events(path, WANTED):
        n = ev.name
        t_last = ev.t
        if n.startswith('sched_'):
            cp.feed(ev)
            sc.feed(ev)
            continue
        tid = ev.tid_or(cp)
        if tid is None:
            continue
        f = ev.fields
        if n.endswith('_entry_futex'):
            n_entry += 1
            cmd = f.get('op', 0) & 0x7f
            ua = f.get('uaddr', 0)
            if cmd in WAIT_CMDS:
                open_wait[tid] = (ua, ev.t)
                waited_on[ua].add(tid)
            elif cmd in WAKE_CMDS:
                wake_t[ua].append(ev.t)
                wake_tid[ua].append(tid)
                wakers[ua][tid] += 1
        else:
            n_exit += 1
            w = open_wait.pop(tid, None)
            if w is None:
                continue
            ua, t0 = w
            ret = f.get('ret', 0)
            if ev.t - t0 > piece_max:                      # a long piece never joins a run
                flush(tid)
                waits[ua].append((ev.t - t0, tid, t0, ev.t, ret, 1, ua))
                continue
            rn = runs.get(tid)
            if rn is not None and rn[4] in POLL_RETS and t0 - rn[3] <= gap:
                rn[1], rn[3], rn[4] = ua, ev.t, ret        # this piece continues the run
                rn[5] += 1
            else:
                flush(tid)
                runs[tid] = [ua, ua, t0, ev.t, ret, 1]
            if ret not in POLL_RETS:                       # woken (or an error): the run is over
                flush(tid)
    for tid in list(runs):
        flush(tid)
    sc.finish(t_last)
    return {'cp': cp, 'sc': sc, 'st': st, 'waits': waits, 'waited_on': waited_on,
            'wake_t': wake_t, 'wake_tid': wake_tid, 'wakers': wakers, 'open': len(open_wait),
            'n_entry': n_entry, 'n_exit': n_exit, 'secs': secs}


def releaser(r, ua, t0, t1, exclude=None):
    """The last wake op on ua inside [t0, t1] not issued by `exclude` -> (tid, t) or None."""
    ts = r['wake_t'].get(ua)
    if not ts:
        return None
    tids = r['wake_tid'][ua]
    i = bisect_left(ts, t1 + 1) - 1
    while i >= 0 and ts[i] >= t0:
        if tids[i] != exclude:
            return tids[i], ts[i]
        i -= 1
    return None


def classify(run, rq, sl, dur, worse_prio, handoff):
    """What the releaser's state during the wait says the wait was."""
    if dur <= 0:
        return 'mixed'
    if rq >= INVERSION_RUNNABLE_SHARE * dur and worse_prio:
        return 'inversion'
    if run >= HOLDER_RUNNING_SHARE * dur:
        return 'held'
    if handoff:                   # the releaser waits on this futex too: it is a lock, whatever
        return 'preempted' if rq >= INVERSION_RUNNABLE_SHARE * dur else 'held-asleep'
    if sl >= EVENT_SLEEP_SHARE * dur:
        return 'event'
    if rq >= INVERSION_RUNNABLE_SHARE * dur:
        return 'preempted'
    return 'mixed'


def report(r, top=10, min_ms=LONG_WAIT_MS):
    cp, st, sc = r['cp'], r['st'], r['sc']
    secs, note = effective_secs(r['secs'], sc)
    span = secs * SEC
    waits = r['waits']
    pid_of = sc.pid

    def who(tid):
        p = pid_of.get(tid)
        return f"{cp.name(tid)} tid {tid}" + (f" (pid {p})" if p is not None and p != tid else '')

    def prio(tid):
        return cp.prio.get(tid)

    def worse(htid, wtid):
        hp, wp = prio(htid), prio(wtid)
        return hp is not None and wp is not None and hp > wp

    def tracer(tid):
        return cp.name(tid).startswith(TRACER_PREFIX)

    n_waits = sum(len(v) for v in waits.values())
    n_pieces = sum(w[5] for v in waits.values() for w in v)
    print(f"futex syscalls: {r['n_entry']} entries, {r['n_exit']} exits; {n_pieces} completed "
          f"waits coalesced into {n_waits} logical waits on {len(waits)} futexes, {r['open']} "
          f"still open at the end; slice {r['secs']:g} s")
    for line in (note, sc.skipped_note()):
        if line:
            print(line)
    if n_waits == 0:
        print("\nVERDICT: NO FUTEX WAITS IN SLICE - check the events regex (see Usage).")
        return

    # Sort every logical wait by its last return value, then every lock wait by what its
    # releaser was doing. lock[ua] = [(dur, tid, t0, t1, htid, ht, cls, pieces, run, rq, sl, ho)]
    lock, polls, timed, other, unseen = (defaultdict(list) for _ in range(5))
    tracer_waits = Counter()
    for ua, ws in waits.items():
        for w in ws:
            dur, tid, t0, t1, ret, pieces, _ua0 = w
            rel = releaser(r, ua, t0, t1, exclude=tid) if ret == 0 else None
            if rel is not None:
                htid, ht = rel
                if tracer(tid) or tracer(htid):
                    tracer_waits[cp.name(tid) if tracer(tid) else cp.name(htid)] += 1
                    continue
                run, rq, sl, _ = st.during(htid, t0, t1, want_occ=False)
                if run + rq + sl < RELEASER_SEEN_SHARE * dur:
                    unseen[ua].append(w)
                else:
                    ho = htid in r['waited_on'].get(ua, ())
                    lock[ua].append((dur, tid, t0, t1, htid, ht,
                                     classify(run, rq, sl, dur, worse(htid, tid), ho), pieces,
                                     run, rq, sl, ho))
            elif ret in POLL_RETS and pieces >= 2:
                polls[ua].append(w)
            elif ret == ETIMEDOUT:
                timed[ua].append(w)
            else:
                other[ua].append(w)
    n_lock = sum(len(v) for v in lock.values())
    n_poll = sum(len(v) for v in polls.values())
    n_timed = sum(len(v) for v in timed.values())
    n_other = sum(len(v) for v in other.values())
    n_unseen = sum(len(v) for v in unseen.values())

    # 1. per-futex table (stats over lock waits; 'handoff' = released by a fellow waiter)
    rows = []
    for ua in waits:
        ws = lock.get(ua, [])
        ds = [w[DUR] for w in ws]
        tot = sum(ds)
        rate = len(ws) / secs
        p50, mx = (pctl(ds, .5), max(ds)) if ds else (0, 0)
        if not ds:
            pat = '-'
        elif rate >= PATTERN_MANY_PER_S and p50 < 5 * LONG_WAIT_MS * MS:
            pat = 'many short'
        elif rate < 5 and mx >= 10 * MS:
            pat = 'few long'
        else:
            pat = 'mixed'
        nho = sum(1 for w in ws if w[HO])
        nruns = sum(1 for w in waits[ua] if w[5] >= 2)
        rows.append((tot, len(waits[ua]), ua, ws, ds, rate, p50, mx, pat, nho, nruns))
    rows.sort(reverse=True)
    print()
    print(f"{'futex':<14}{'woken':>6}{'handoff':>8}{'poll':>5}{'timed':>6}{'other':>6}{'runs':>5}"
          f"{'waiters':>8}{'/s':>7}{'p50 ms':>8}{'p99 ms':>8}{'max ms':>8}{'total ms':>10}"
          f"  pattern     released by")
    for tot, _, ua, ws, ds, rate, p50, mx, pat, nho, nruns in rows[:top]:
        rel = ", ".join(f"{cp.name(t)} prio {prio_label(prio(t))}"
                        for t, _ in r['wakers'][ua].most_common(2)) or '-'
        print(f"{ua:#014x}{len(ws):>6}{nho:>8}{len(polls.get(ua, [])):>5}"
              f"{len(timed.get(ua, [])):>6}{len(other.get(ua, [])):>6}{nruns:>5}"
              f"{len({w[TID] for w in ws}):>8}{rate:>7.1f}{p50 / MS:>8.2f}"
              f"{(pctl(ds, .99) / MS) if ds else 0:>8.2f}{mx / MS:>8.1f}{tot / MS:>10.1f}  "
              f"{pat:<11} {rel}")
    print("woken = last return 0 with a wake op on that futex inside the wait (a lock wait); "
          "handoff = released by a thread that waits on this futex too (a real lock, not a "
          "signal); poll = a run of timed waits that ended by timeout; timed = one -110 "
          "ETIMEDOUT wait; other = EINTR/EAGAIN/restart or no wake found; runs = logical waits "
          "made of 2+ consecutive pieces")
    if rows and rows[0][3]:
        tot, _, ua, ws = rows[0][:4]
        per_waiter = Counter()
        for w in ws:
            per_waiter[w[TID]] += w[DUR]
        print(f"waiter shares on futex {ua:#x}: " + ", ".join(
            f"{cp.name(t)} tid {t}: {pct(ns, span):.0f}% of its time waiting on it"
            for t, ns in per_waiter.most_common(3)))
    if n_poll:
        pd = [w[0] for ws in polls.values() for w in ws]
        pieces = sum(w[5] for ws in polls.values() for w in ws)
        print(f"poll-runs: {n_poll} logical waits on {len(polls)} futexes, p50 "
              f"{pctl(pd, .5) / MS:.1f} ms, made of {pieces} timed pieces - the thread kept "
              f"re-waiting with a timeout until it could go on (not a woken lock wait)")
    if n_timed:
        tos = Counter(nice_ms(w[0] / MS) for ws in timed.values() for w in ws)
        print(f"timed sleeps: {n_timed} waits on {len(timed)} futexes (timeouts "
              + ", ".join(k for k, _ in tos.most_common(5)) + ") - not lock waits")
    if n_other:
        print(f"other returns: {n_other} waits on {len(other)} futexes (EINTR/EAGAIN/restart, or "
              "woken with no wake op found) - not lock waits")
    if n_unseen:
        print(f"releaser unseen: {n_unseen} logical waits on {len(unseen)} futexes (the releasing "
              f"thread's scheduling state covers < {pct(RELEASER_SEEN_SHARE, 1):.0f}% of the wait: "
              "it hardly appears in the slice) - counted, not judged")
    if tracer_waits:
        print("tracer's own futex waits (left out): " + ", ".join(
            f"{n} by {nm}" for nm, n in tracer_waits.most_common()))

    # 2. the longest lock waits with a non-sleeping releaser, then the longest event wait
    allw = sorted(((w[DUR], ua) + tuple(w[1:]) for ua, ws in lock.items() for w in ws),
                  reverse=True)
    longest = allw[0][0] / MS if allw else 0.0
    events = [w for w in allw if w[CLS + 1] == 'event']
    actionable = [w for w in allw if w[CLS + 1] != 'event']
    examined = [w for w in actionable if w[0] >= min_ms * MS][:top]
    print()
    if examined:
        print(f"Longest lock waits with a releaser that was not sleeping (>= {min_ms:g} ms, top {top}):")
    elif actionable:
        print(f"No lock wait with a non-sleeping releaser reaches {min_ms:g} ms "
              f"(longest {actionable[0][0] / MS:.2f} ms).")
    elif allw:
        print("No lock wait with a non-sleeping releaser in this slice.")
    else:
        print("No lock waits at all in this slice.")
    for dur, ua, tid, t0, t1, htid, ht, cls, pieces, _run, _rq, _sl, ho in examined:
        tag = cls + (f", run of {pieces}" if pieces >= 2 else "") + ("" if ho else ", no hand-off")
        print(f"  {dur / MS:8.1f} ms  {who(tid)} prio {prio_label(prio(tid))}  futex {ua:#x}  "
              f"{hms(t0)} -> {hms(t1)}  [{tag}]")
        run, rq, sl, occ = st.during(htid, t0, t1)
        print(f"            released by {who(htid)} prio {prio_label(prio(htid))} at {hms(ht)}; "
              f"during the wait it was running {run / MS:.1f} ms ({pct(run, dur):.0f}%), "
              f"runnable-but-not-running {rq / MS:.1f} ms ({pct(rq, dur):.0f}%), "
              f"sleeping {sl / MS:.1f} ms ({pct(sl, dur):.0f}%)")
        taken = [(t, ns) for t, ns in occ.most_common(4) if t != htid][:3]
        if rq >= INVERSION_RUNNABLE_SHARE * dur and taken:
            print("            its CPU was taken by: " + ", ".join(
                f"{cp.name(t)} prio {prio_label(prio(t))} {ns / MS:.1f} ms" for t, ns in taken))
    if events:
        dur, ua, tid, t0, t1, htid, ht, cls, pieces = events[0][:9]
        print(f"longest event wait: {dur / MS:.1f} ms{run_txt(pieces)} by {who(tid)} on futex "
              f"{ua:#x} {hms(t0)} -> {hms(t1)} (releaser {cp.name(htid)} slept until it "
              f"signalled) - {len(events)} event waits in all")

    # 3. verdict
    print()
    inv_all = [w for w in allw if w[CLS + 1] == 'inversion']
    inv_tot = ""
    if inv_all:
        t_all = sum(w[0] for w in inv_all)
        t_w = sum(w[0] for w in inv_all if w[2] == inv_all[0][2])
        inv_tot = (f"({len(inv_all)} such waits in all, {t_all / MS:.1f} ms = {pct(t_all, span):.0f}% "
                   f"of the slice; the waiter spends {pct(t_w, span):.0f}% of its time in them)")
    if len(inv_all) >= 2 and inv_all[0][0] >= INVERSION_MIN_MS * MS:
        dur, ua, tid, t0, t1, htid, ht, cls, pieces = inv_all[0][:9]
        _run, rq, _sl, occ = st.during(htid, t0, t1)
        taken = [(t, ns) for t, ns in occ.most_common(4) if t != htid][:3]
        by = ", ".join(f"{cp.name(t)} (prio {prio_label(prio(t))})" for t, _ in taken) or 'idle'
        print(f"VERDICT: PRIORITY INVERSION: {cp.name(tid)} tid {tid} (prio {prio_label(prio(tid))}) "
              f"waited {dur / MS:.1f} ms{run_txt(pieces)} on futex {ua:#x}; the thread that "
              f"released it, {cp.name(htid)} tid {htid} (prio {prio_label(prio(htid))}), was "
              f"runnable-but-not-running for {rq / MS:.1f} ms ({pct(rq, dur):.0f}%) of that wait, "
              f"its CPU taken by {by} {inv_tot}")
        print("FIX: priority inheritance on the lock (PTHREAD_PRIO_INHERIT / FUTEX_LOCK_PI), "
              "or raise the holder / do not hold the lock across a scheduling boundary")
        return
    small_inv = (f"{len(inv_all)} small inversion-class waits (max {inv_all[0][0] / MS:.1f} ms, "
                 f"{cp.name(inv_all[0][2])} tid {inv_all[0][2]} on futex {inv_all[0][1]:#x}) - "
                 f"below the {INVERSION_MIN_MS:g} ms bar {inv_tot}") if inv_all else ""
    # contention: time in hand-off lock waits on one futex, never the count
    cstat = {}
    for ua, ws in lock.items():
        hw = [w for w in ws if w[HO]]
        if not hw:
            continue
        ds = [w[DUR] for w in hw]
        tot = sum(ds)
        per_waiter = Counter()
        for w in hw:
            per_waiter[w[TID]] += w[DUR]
        wt, wns = per_waiter.most_common(1)[0]
        p50, p99 = pctl(ds, .5), pctl(ds, .99)
        cstat[ua] = (hw, tot, wt, wns, len(per_waiter), p50, p99)
    cands = []
    for ua, (hw, tot, wt, wns, nw, p50, p99) in cstat.items():
        if nw >= CONTENTION_MIN_WAITERS and p50 >= CONTENTION_MIN_P50_MS * MS \
                and p99 <= TAIL_RATIO_MAX * p50 \
                and (tot >= CONTENTION_TOTAL_SHARE * span or wns >= CONTENTION_WAITER_SHARE * span):
            cands.append((max(tot / span, wns / span), ua))
    if cands:
        _, ua = max(cands)
        hw, tot, wt, wns, nw, p50, p99 = cstat[ua]
        by_cls = Counter()
        for w in hw:
            by_cls['asleep' if w[CLS] == 'held-asleep' else 'run' if w[CLS] == 'held' else 'preempted'] += w[DUR]
        dom = by_cls.most_common(1)[0][0]
        state = {'run': "holders run while holding",
                 'preempted': "holders preempted while holding",
                 'asleep': "holders sleep while holding (a lock held across a sleep or I/O)"}[dom]
        names = Counter(cp.name(w[HTID]) for w in hw)
        nruns = sum(1 for w in hw if w[PIECES] >= 2)
        runs_txt = f", {nruns} of them runs of timed waits" if nruns else ""
        print(f"VERDICT: LOCK CONTENTION on futex {ua:#x}: {len(hw)} held lock waits "
              f"({len(hw) / secs:.0f}/s{runs_txt}) by {nw} threads, p50 {p50 / MS:.2f} ms, "
              f"p99 {p99 / MS:.1f} ms, max {max(w[DUR] for w in hw) / MS:.1f} ms; lock-wait time "
              f"{pct(tot, span):.0f}% of the slice, top waiter {cp.name(wt)} tid {wt} spends "
              f"{pct(wns, span):.0f}% of its time on it; {state} (release by "
              f"{', '.join(n for n, _ in names.most_common(3))})")
        if dom == 'asleep':
            print("FIX: do not sleep or do I/O while holding the lock - release it first, or "
                  "move the slow work out of the critical section")
        else:
            print("FIX: shorten the critical section, split the lock, or batch the work done "
                  "under it")
        return
    decide = [w for w in examined if w[CLS + 1] != 'mixed']
    if decide:
        dur, ua, tid, t0, t1, htid, ht, cls, pieces, run, rq, sl, ho = decide[0]
        head = f"VERDICT: NO LOCK PROBLEM: longest lock wait {dur / MS:.1f} ms{run_txt(pieces)} by {cp.name(tid)} tid {tid} on futex {ua:#x}"
        if cls == 'inversion':
            print(f"VERDICT: NO LOCK PROBLEM: {small_inv}")
            return
        tail = f"; also {small_inv}" if small_inv else ""
        if cls == 'preempted':
            print(f"{head} was released by {cp.name(htid)} which was preempted (equal priority) - "
                  f"a CPU-starvation effect, not a lock fault (see 8_cpu_starvation){tail}")
            return
        if not ho:                                   # 'held' with a releaser that never waits
            print(f"{head} was released by {cp.name(htid)}, which ran but never waited on that "
                  f"futex itself - a signaller (producer/consumer hand-over), not a contended "
                  f"lock{tail}")
            return
        hw, tot, wt, wns, nw, p50, p99 = cstat[ua]
        how = {'held': f"releaser {cp.name(htid)} ran while holding",
               'held-asleep': f"releaser {cp.name(htid)} slept while holding it"}[cls]
        if nw < CONTENTION_MIN_WAITERS:
            print(f"{head} was a held lock ({how}), but {cp.name(tid)} is the only thread waiting "
                  f"on it (an idle worker waiting for work, not contention){tail}")
        elif p50 > 0 and p99 > TAIL_RATIO_MAX * p50:
            print(f"{head} was a held lock ({how}), but its waits have an unbounded tail (p99/p50 "
                  f"= {p99 / p50:.0f}, bar {TAIL_RATIO_MAX}): threads parked until there is work, "
                  f"not a critical section{tail}")
        else:
            print(f"{head} was a held lock ({how}), but hand-off waits total only "
                  f"{pct(tot, span):.1f}% of the slice (bar {pct(CONTENTION_TOTAL_SHARE, 1):.0f}%) "
                  f"and the top waiter spends {pct(wns, span):.1f}% of its time on it (bar "
                  f"{pct(CONTENTION_WAITER_SHARE, 1):.0f}%){tail}")
        return
    if events and events[0][0] >= min_ms * MS:
        dur, ua, tid, t0, t1, htid, ht, cls, pieces = events[0][:9]
        print(f"VERDICT: NO LOCK PROBLEM: longest lock wait {dur / MS:.1f} ms{run_txt(pieces)} "
              f"by {cp.name(tid)} tid {tid} on futex {ua:#x} was an event wait (the releaser "
              f"{cp.name(htid)} slept until it signalled) - not a held lock"
              + (f"; also {small_inv}" if small_inv else ""))
        return
    if n_lock == 0:
        print(f"VERDICT: NO LONG FUTEX WAITS (no lock wait at all: {n_poll} poll-runs, "
              f"{n_timed} timed sleeps, {n_other} other returns, {n_unseen} releaser unseen)")
    else:
        print(f"VERDICT: NO LONG FUTEX WAITS (longest lock wait {longest:.2f} ms)")


def main(argv):
    if '--selftest' in argv:
        _selftest()
        return
    if len(argv) < 2:
        raise SystemExit(__doc__)
    path, secs = argv[0], float(argv[1])
    top, min_ms, pidmap = 10, LONG_WAIT_MS, None
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == '--top':
            top = int(argv[i + 1]); i += 2
        elif a == '--min-ms':
            min_ms = float(argv[i + 1]); i += 2
        elif a == '--pidmap':
            pidmap = load_pidmap(argv[i + 1]); i += 2
        else:
            raise SystemExit(f"unknown argument {a}\n{__doc__}")
    report(analyse(path, secs, pidmap), top, min_ms)


# ---- self-test ---------------------------------------------------------------------------
def _held_cycles(g, sys_, ua, waiters, holder, idle, n=100, period=10 * MS, handoff=True):
    """n cycles: a waiter enters a wait, sleeps; the holder (running on cpu 0 throughout)
    issues the wake 1.9 ms later; the waiter exits ret 0 at +2 ms. With handoff the holder
    itself waits on the futex once (EAGAIN), so it counts as a fellow waiter."""
    g.switch(0, 0, idle, holder)
    if handoff:
        g.ev(100_000, 0, f'{sys_}_entry_futex', f'uaddr = {ua:#x}, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
        g.ev(110_000, 0, f'{sys_}_exit_futex', f'ret = -11, uaddr = {ua:#x}, uaddr2 = 0')
    for k in range(n):
        t = k * period
        w = waiters[k % len(waiters)]
        g.switch(t, 1, idle, w)
        g.ev(t + 20_000, 1, f'{sys_}_entry_futex', f'uaddr = {ua:#x}, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
        g.switch(t + 30_000, 1, w, idle, 1)
        g.ev(t + 1_900_000, 0, f'{sys_}_entry_futex', f'uaddr = {ua:#x}, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
        g.ev(t + 1_905_000, 0, 'sched_waking', f'comm = "{w[1]}", tid = {w[0]}, prio = 20, target_cpu = 1')
        g.ev(t + 1_910_000, 0, f'{sys_}_exit_futex', f'ret = 1, uaddr = {ua:#x}, uaddr2 = 0')
        g.switch(t + 2 * MS, 1, idle, w)
        g.ev(t + 2 * MS + 20_000, 1, f'{sys_}_exit_futex', f'ret = 0, uaddr = {ua:#x}, uaddr2 = 0')
        g.switch(t + 2 * MS + 50_000, 1, w, idle, 1)
    g.switch(n * period - 1, 0, holder, idle, 1)


def _selftest():
    import os, tempfile
    from irq_balance import _Gen, _capture
    d = tempfile.mkdtemp()
    idle = (0, 'swapper/0', 20)
    W, H2 = (20, 'hp_waiter', 10), (31, 'holder2', 20)
    M1, M2 = (40, 'mid1', 20), (41, 'mid2', 20)
    ws = [(21 + k, f'w{k}', 20) for k in range(4)]
    for ctx in (True, 'name', False):
        sys_ = 'compat_syscall' if ctx is False else 'syscall'
        # A: inversion, twice. hp_waiter (prio 110) waits 40 ms; holder (prio 125) is preempted
        # by two prio-120 threads for 30 of those ms, then runs and wakes it.
        g = _Gen(ctx)
        H = (30, 'holder', 25)
        g.switch(0, 0, idle, H)
        g.switch(0, 1, idle, W)
        for o in (0, 100 * MS):
            g.ev(o + 2 * MS, 1, f'{sys_}_entry_futex', 'uaddr = 0xa000, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
            g.switch(o + 2 * MS + 10_000, 1, W, idle, 1)
            g.switch(o + 3 * MS, 0, H, M1, 256)
            g.switch(o + 18 * MS, 0, M1, M2, 256)
            g.switch(o + 33 * MS, 0, M2, H, 1)
            g.ev(o + 34 * MS, 0, f'{sys_}_entry_futex', 'uaddr = 0xa000, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
            g.ev(o + 34 * MS + 5_000, 0, 'sched_waking', 'comm = "hp_waiter", tid = 20, prio = 10, target_cpu = 1')
            g.ev(o + 34 * MS + 6_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xa000, uaddr2 = 0')
            g.switch(o + 41 * MS, 1, idle, W)
            g.ev(o + 42 * MS, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xa000, uaddr2 = 0')
        g.switch(300 * MS, 0, H, idle, 1)      # (a CPU silent >= 500 ms would be a trace hole)
        g.switch(300 * MS, 1, W, idle, 1)
        p = os.path.join(d, f'a{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 0.3))
        assert "VERDICT: PRIORITY INVERSION: hp_waiter tid 20 (prio 110 (nice -10)) waited 40.0 ms on futex 0xa000" in out, out
        assert "holder tid 30 (prio 125 (nice 5)), was runnable-but-not-running for 30.0 ms (75%)" in out, out
        assert ("its CPU taken by mid1 (prio 120 (nice 0)), mid2 (prio 120 (nice 0)) (2 such waits in "
                "all, 80.0 ms = 27% of the slice; the waiter spends 27% of its time in them)") in out, out
        assert "[inversion, no hand-off]" in out, out
        # B: contention. 100 x 2 ms held hand-off waits/s (20% of the slice) by 4 waiters.
        g = _Gen(ctx)
        _held_cycles(g, sys_, 0xb000, ws, H2, idle)
        p = os.path.join(d, f'b{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 1.0))
        assert ("VERDICT: LOCK CONTENTION on futex 0xb000: 100 held lock waits (100/s) by 4 threads, "
                "p50 2.00 ms, p99 2.0 ms, max 2.0 ms; lock-wait time 20% of the slice, top waiter w0 "
                "tid 21 spends 5% of its time on it; holders run while holding (release by holder2)") in out, out
        assert "waiter shares on futex 0xb000: w0 tid 21: 5% of its time waiting on it" in out, out
        assert "many short" in out and "FIX: shorten the critical section" in out, out
        # B2: the same without the hand-off: the releaser never waits on that futex itself, so
        # it is a signaller handing work over, not a contended lock.
        g = _Gen(ctx)
        _held_cycles(g, sys_, 0xb000, ws, H2, idle, handoff=False)
        p = os.path.join(d, f'b2{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 1.0))
        assert ("VERDICT: NO LOCK PROBLEM: longest lock wait 2.0 ms by w" in out and
                "on futex 0xb000 was released by holder2, which ran but never waited on that futex "
                "itself - a signaller (producer/consumer hand-over), not a contended lock") in out, out
        assert "[held, no hand-off]" in out and "LOCK CONTENTION" not in out, out
        # C: one 0.3 ms lock wait
        g = _Gen(ctx)
        g.switch(0, 0, idle, H2)
        g.switch(0, 1, idle, W)
        g.ev(10 * MS, 1, f'{sys_}_entry_futex', 'uaddr = 0xc000, op = 0, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
        g.switch(10 * MS + 10_000, 1, W, idle, 1)
        g.ev(10 * MS + 250_000, 0, f'{sys_}_entry_futex', 'uaddr = 0xc000, op = 1, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
        g.ev(10 * MS + 255_000, 0, 'sched_waking', 'comm = "hp_waiter", tid = 20, prio = 10, target_cpu = 1')
        g.ev(10 * MS + 260_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xc000, uaddr2 = 0')
        g.switch(10 * MS + 280_000, 1, idle, W)
        g.ev(10 * MS + 300_000, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xc000, uaddr2 = 0')
        g.switch(300 * MS, 0, H2, idle, 1)
        g.switch(300 * MS, 1, W, idle, 1)
        p = os.path.join(d, f'c{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 0.3))
        assert "VERDICT: NO LONG FUTEX WAITS (longest lock wait 0.30 ms)" in out, out
        # D: timed sleeps only - 5 x 100.3 ms and 1 x 400 ms waits ending in ETIMEDOUT (each
        # longer than COALESCE_PIECE_MS, so never a run even back to back), no wake ops - the
        # false alarm measured on real switch traces and on 1 s database heartbeats.
        g = _Gen(ctx)
        T = (50, 'timer_loop', 20)
        g.switch(0, 0, idle, H2)
        g.switch(0, 1, idle, T)
        for k in range(6):
            t = k * 150 * MS
            dur = 400 * MS if k == 5 else 100 * MS + 300_000
            g.ev(t + 1 * MS, 1, f'{sys_}_entry_futex', 'uaddr = 0xd000, op = 137, val = 0, utime = 1, uaddr2 = 0, val3 = 0')
            g.switch(t + 1 * MS + 10_000, 1, T, idle, 1)
            g.ev(t + 1 * MS + dur, 1, 'sched_waking', 'comm = "timer_loop", tid = 50, prio = 20, target_cpu = 1')
            g.switch(t + 1 * MS + dur + 10_000, 1, idle, T)
            g.ev(t + 1 * MS + dur + 20_000, 1, f'{sys_}_exit_futex', 'ret = -110, uaddr = 0xd000, uaddr2 = 0')
        g.switch(1300 * MS, 0, H2, idle, 1)
        g.switch(1300 * MS, 1, T, idle, 1)
        p = os.path.join(d, f'd{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 1.3))
        assert "timed sleeps: 6 waits on 1 futexes (timeouts 100 ms, 400 ms) - not lock waits" in out, out
        assert "VERDICT: NO LONG FUTEX WAITS (no lock wait at all: 0 poll-runs, 6 timed sleeps, 0 other returns, 0 releaser unseen)" in out, out
        assert "LOCK CONTENTION" not in out, out
        # E: fast signalling - 300 waits/s of 30 us by 4 threads (measured shape on a healthy
        # control card: 85-240/s, p50 30-40 us). The count must never make CONTENTION.
        g = _Gen(ctx)
        g.switch(0, 0, idle, H2)
        for k in range(300):
            t = k * 3 * MS
            w = ws[k % 4]
            g.switch(t, 1, idle, w)
            g.ev(t + 20_000, 1, f'{sys_}_entry_futex', 'uaddr = 0xe000, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
            g.switch(t + 25_000, 1, w, idle, 1)
            g.ev(t + 40_000, 0, f'{sys_}_entry_futex', 'uaddr = 0xe000, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
            g.ev(t + 42_000, 0, 'sched_waking', f'comm = "{w[1]}", tid = {w[0]}, prio = 20, target_cpu = 1')
            g.ev(t + 44_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xe000, uaddr2 = 0')
            g.switch(t + 46_000, 1, idle, w)
            g.ev(t + 50_000, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xe000, uaddr2 = 0')
            g.switch(t + 60_000, 1, w, idle, 1)
        g.switch(SEC - 1, 0, H2, idle, 1)
        p = os.path.join(d, f'e{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 1.0))
        assert "VERDICT: NO LONG FUTEX WAITS (longest lock wait 0.03 ms)" in out, out
        assert "LOCK CONTENTION" not in out, out
        # F: event wait - hp_waiter waits 3001 ms; the releaser evt_src (never a waiter on that
        # futex) slept the whole time, woke up and signalled: a condition variable.
        g = _Gen(ctx)
        E = (60, 'evt_src', 20)
        g.switch(0, 0, idle, E)
        g.switch(1 * MS, 0, E, idle, 1)
        g.switch(0, 1, idle, W)
        g.ev(2 * MS, 1, f'{sys_}_entry_futex', 'uaddr = 0xf000, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
        g.switch(2 * MS + 10_000, 1, W, idle, 1)
        # a real trace is never silent for 3 s (timer ticks); without these, tracelib rightly
        # calls the silence a trace hole and drops the releaser's sleep interval. Emitted in
        # time order: _Gen tracks the current thread at emit time.
        K0, K1 = (70, 'tick0', 20), (71, 'tick1', 20)
        for k in range(1, 30):
            t = k * 100 * MS
            g.switch(t, 0, idle, K0); g.switch(t + 50_000, 0, K0, idle, 1)
            g.switch(t, 1, idle, K1); g.switch(t + 50_000, 1, K1, idle, 1)
        g.ev(3000 * MS, 0, 'sched_waking', 'comm = "evt_src", tid = 60, prio = 20, target_cpu = 0')
        g.switch(3000 * MS + 10_000, 0, idle, E)
        g.ev(3001 * MS, 0, f'{sys_}_entry_futex', 'uaddr = 0xf000, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
        g.ev(3001 * MS + 5_000, 0, 'sched_waking', 'comm = "hp_waiter", tid = 20, prio = 10, target_cpu = 1')
        g.ev(3001 * MS + 10_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xf000, uaddr2 = 0')
        g.switch(3003 * MS, 1, idle, W)
        g.ev(3003 * MS + 100_000, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xf000, uaddr2 = 0')
        g.switch(3400 * MS, 0, E, idle, 1)
        g.switch(3400 * MS, 1, W, idle, 1)
        p = os.path.join(d, f'f{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 3.5))
        assert ("longest event wait: 3001.1 ms by hp_waiter tid 20 on futex 0xf000 00:00:00.002 -> "
                "00:00:03.003 (releaser evt_src slept until it signalled) - 1 event waits in all") in out, out
        assert ("VERDICT: NO LOCK PROBLEM: longest lock wait 3001.1 ms by hp_waiter tid 20 on futex "
                "0xf000 was an event wait (the releaser evt_src slept until it signalled) - not a "
                "held lock") in out, out
        assert "LOCK CONTENTION" not in out and "No lock wait with a non-sleeping releaser" in out, out
        # G: a condvar poll loop (the shape of our labelled priority_inversion run), twice: a
        # nice -5 waiter does 20 consecutive 5 ms timed waits (ret -110, 0.1 ms apart) and a
        # final wait that a nice 19 holder wakes; the holder was runnable-but-not-running for
        # ~70% of the whole 105 ms because two prio-120 threads had its CPU.
        g = _Gen(ctx)
        Wg, Hg = (20, 'hp_waiter', 15), (30, 'holder', 39)
        g.switch(0, 0, idle, Hg)
        g.switch(0, 1, idle, Wg)
        for o in (0, 150 * MS):
            g.switch(o + 5 * MS, 0, Hg, M1, 256)
            g.switch(o + 45 * MS, 0, M1, M2, 256)
            g.switch(o + 80 * MS, 0, M2, Hg, 1)
            for k in range(21):
                t = o + 2 * MS + k * 5_100_000
                g.ev(t, 1, f'{sys_}_entry_futex', 'uaddr = 0xa000, op = 137, val = 3, utime = 1, uaddr2 = 0, val3 = 4294967295')
                g.switch(t + 10_000, 1, Wg, idle, 1)
                if k < 20:
                    g.ev(t + 5 * MS, 1, 'sched_waking', 'comm = "hp_waiter", tid = 20, prio = 15, target_cpu = 1')
                    g.switch(t + 5 * MS + 10_000, 1, idle, Wg)
                    g.ev(t + 5 * MS + 20_000, 1, f'{sys_}_exit_futex', 'ret = -110, uaddr = 0xa000, uaddr2 = 0')
            g.ev(o + 106_900_000, 0, f'{sys_}_entry_futex', 'uaddr = 0xa000, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
            g.ev(o + 106_905_000, 0, 'sched_waking', 'comm = "hp_waiter", tid = 20, prio = 15, target_cpu = 1')
            g.ev(o + 106_910_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xa000, uaddr2 = 0')
            g.switch(o + 106_950_000, 1, idle, Wg)
            g.ev(o + 107 * MS, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xa000, uaddr2 = 0')
        g.switch(400 * MS, 0, Hg, idle, 1)
        g.switch(400 * MS, 1, Wg, idle, 1)
        p = os.path.join(d, f'g{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 0.4))
        assert ("VERDICT: PRIORITY INVERSION: hp_waiter tid 20 (prio 115 (nice -5)) waited 105.0 ms "
                "(a run of 21 timed waits) on futex 0xa000; the thread that released it, holder tid 30 "
                "(prio 139 (nice 19)), was runnable-but-not-running for 75.0 ms (71%) of that wait, "
                "its CPU taken by mid1 (prio 120 (nice 0)), mid2 (prio 120 (nice 0)) (2 such waits in "
                "all, 210.0 ms = ") in out, out
        assert "42 completed waits coalesced into 2 logical waits" in out, out
        assert "[inversion, run of 21, no hand-off]" in out and "timed sleeps" not in out, out
        # H: contention with a PREEMPTED holder (our labelled lock_contention run shape with a
        # CPU cap): 3 waiters take 9.6 ms each; the equal-priority holder (a fellow waiter) is
        # runnable-but-not-running for 83% of every wait. A lock, not inversion.
        g = _Gen(ctx)
        H3 = (32, 'holder3', 20)
        ws3 = ws[:3]
        g.switch(0, 0, idle, H3)
        g.ev(100_000, 0, f'{sys_}_entry_futex', 'uaddr = 0xb100, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
        g.ev(110_000, 0, f'{sys_}_exit_futex', 'ret = -11, uaddr = 0xb100, uaddr2 = 0')
        for k in range(100):
            t = k * 10 * MS
            w = ws3[k % 3]
            g.switch(t, 1, idle, w)
            g.ev(t + 200_000, 1, f'{sys_}_entry_futex', 'uaddr = 0xb100, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
            g.switch(t + 210_000, 1, w, idle, 1)
            g.switch(t + 1 * MS, 0, H3, M1, 256)
            g.switch(t + 9 * MS, 0, M1, H3, 1)
            g.ev(t + 9_500_000, 0, f'{sys_}_entry_futex', 'uaddr = 0xb100, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
            g.ev(t + 9_505_000, 0, 'sched_waking', f'comm = "{w[1]}", tid = {w[0]}, prio = 20, target_cpu = 1')
            g.ev(t + 9_510_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xb100, uaddr2 = 0')
            g.switch(t + 9_700_000, 1, idle, w)
            g.ev(t + 9_800_000, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xb100, uaddr2 = 0')
            g.switch(t + 9_900_000, 1, w, idle, 1)
        g.switch(SEC - 1, 0, H3, idle, 1)
        p = os.path.join(d, f'h{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 1.0))
        assert ("VERDICT: LOCK CONTENTION on futex 0xb100: 100 held lock waits (100/s) by 3 threads, "
                "p50 9.60 ms, p99 9.6 ms, max 9.6 ms; lock-wait time 96% of the slice, top waiter w0 "
                "tid 21 spends 33% of its time on it; holders preempted while holding (release by holder3)") in out, out
        assert "[preempted]" in out and "PRIORITY INVERSION" not in out, out
        # I: an idle worker - ONE thread spends its whole time waiting on one futex that a
        # running fellow waiter releases (measured: a Node.js worker in both fault and baseline).
        g = _Gen(ctx)
        _held_cycles(g, sys_, 0xb200, ws[:1], H2, idle)
        p = os.path.join(d, f'i{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 1.0))
        assert ("VERDICT: NO LOCK PROBLEM: longest lock wait 2.0 ms by w0 tid 21 on futex 0xb200 was a "
                "held lock (releaser holder2 ran while holding), but w0 is the only thread waiting on "
                "it (an idle worker waiting for work, not contention)") in out, out
        assert "LOCK CONTENTION" not in out, out
        # J: releaser unseen - the thread that issues the final wake first appears 0.3 ms before
        # it (no scheduling intervals for it during the 30 ms wait): counted, never judged.
        g = _Gen(ctx)
        R = (90, 'late_releaser', 20)
        g.switch(0, 1, idle, W)
        g.ev(10 * MS, 1, f'{sys_}_entry_futex', 'uaddr = 0xb300, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
        g.switch(10 * MS + 10_000, 1, W, idle, 1)
        g.switch(39_800_000, 0, idle, R)
        g.ev(39_900_000, 0, f'{sys_}_entry_futex', 'uaddr = 0xb300, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
        g.ev(39_905_000, 0, 'sched_waking', 'comm = "hp_waiter", tid = 20, prio = 10, target_cpu = 1')
        g.ev(39_910_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xb300, uaddr2 = 0')
        g.switch(40 * MS, 1, idle, W)
        g.ev(40_100_000, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xb300, uaddr2 = 0')
        g.switch(300 * MS, 0, R, idle, 1)
        g.switch(300 * MS, 1, W, idle, 1)
        p = os.path.join(d, f'j{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 0.3))
        assert "releaser unseen: 1 logical waits on 1 futexes" in out, out
        assert "VERDICT: NO LONG FUTEX WAITS (no lock wait at all: 0 poll-runs, 0 timed sleeps, 0 other returns, 1 releaser unseen)" in out, out
        # K: a small inversion (measured: an RT thread's 8.5 ms run of 2 timed waits released
        # by a nice-0 thread that was runnable 34% of it) - true in form, below the 10 ms bar.
        g = _Gen(ctx)
        Wk, Hk = (20, 'rt_waiter', -3), (30, 'holder', 20)
        g.switch(0, 0, idle, Hk)
        g.switch(0, 1, idle, Wk)
        g.ev(2 * MS, 1, f'{sys_}_entry_futex', 'uaddr = 0xa100, op = 137, val = 3, utime = 1, uaddr2 = 0, val3 = 4294967295')
        g.switch(2 * MS + 10_000, 1, Wk, idle, 1)
        g.switch(4 * MS, 0, Hk, M1, 256)
        g.ev(6 * MS, 1, 'sched_waking', 'comm = "rt_waiter", tid = 20, prio = -3, target_cpu = 1')
        g.switch(6 * MS + 10_000, 1, idle, Wk)
        g.ev(6 * MS + 20_000, 1, f'{sys_}_exit_futex', 'ret = -110, uaddr = 0xa100, uaddr2 = 0')
        g.ev(6 * MS + 100_000, 1, f'{sys_}_entry_futex', 'uaddr = 0xa100, op = 137, val = 3, utime = 1, uaddr2 = 0, val3 = 4294967295')
        g.switch(6 * MS + 110_000, 1, Wk, idle, 1)
        g.switch(6_900_000, 0, M1, Hk, 1)
        g.ev(10_400_000, 0, f'{sys_}_entry_futex', 'uaddr = 0xa100, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
        g.ev(10_405_000, 0, 'sched_waking', 'comm = "rt_waiter", tid = 20, prio = -3, target_cpu = 1')
        g.ev(10_410_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xa100, uaddr2 = 0')
        g.switch(10_450_000, 1, idle, Wk)
        g.ev(10_500_000, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xa100, uaddr2 = 0')
        g.switch(300 * MS, 0, Hk, idle, 1)
        g.switch(300 * MS, 1, Wk, idle, 1)
        p = os.path.join(d, f'k{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 0.3))
        assert ("VERDICT: NO LOCK PROBLEM: 1 small inversion-class waits (max 8.5 ms, rt_waiter tid 20 "
                "on futex 0xa100) - below the 20 ms bar (1 such waits in all, 8.5 ms = 3% of the "
                "slice; the waiter spends 3% of its time in them)") in out, out
        assert "[inversion, run of 2, no hand-off]" in out and "PRIORITY INVERSION" not in out, out
        # L: a 10 ms poll loop whose final wake comes from a thread that slept 60% of the run
        # and never waited on that futex (measured: 85-91 x 10 ms pieces, releaser asleep 69%)
        # - an event wait, not a lock.
        g = _Gen(ctx)
        P, S = (20, 'poller', 20), (80, 'signaller', 20)
        g.switch(0, 0, idle, S)
        g.switch(0, 1, idle, P)
        for k in range(10):
            t = 2 * MS + k * 10_100_000
            g.ev(t, 1, f'{sys_}_entry_futex', 'uaddr = 0xa200, op = 137, val = 3, utime = 1, uaddr2 = 0, val3 = 4294967295')
            g.switch(t + 10_000, 1, P, idle, 1)
            if k < 9:
                g.ev(t + 10 * MS, 1, 'sched_waking', 'comm = "poller", tid = 20, prio = 20, target_cpu = 1')
                g.switch(t + 10 * MS + 10_000, 1, idle, P)
                g.ev(t + 10 * MS + 20_000, 1, f'{sys_}_exit_futex', 'ret = -110, uaddr = 0xa200, uaddr2 = 0')
        g.switch(40 * MS, 0, S, idle, 1)
        g.ev(100 * MS, 0, 'sched_waking', 'comm = "signaller", tid = 80, prio = 20, target_cpu = 0')
        g.switch(100 * MS + 10_000, 0, idle, S)
        g.ev(101 * MS, 0, f'{sys_}_entry_futex', 'uaddr = 0xa200, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
        g.ev(101 * MS + 5_000, 0, 'sched_waking', 'comm = "poller", tid = 20, prio = 20, target_cpu = 1')
        g.ev(101 * MS + 10_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xa200, uaddr2 = 0')
        g.switch(101 * MS + 100_000, 1, idle, P)
        g.ev(101 * MS + 200_000, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xa200, uaddr2 = 0')
        g.switch(300 * MS, 0, S, idle, 1)
        g.switch(300 * MS, 1, P, idle, 1)
        p = os.path.join(d, f'l{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 0.3))
        assert "longest event wait: 99.2 ms (a run of 10 timed waits) by poller tid 20 on futex 0xa200" in out, out
        assert ("VERDICT: NO LOCK PROBLEM: longest lock wait 99.2 ms (a run of 10 timed waits) by poller "
                "tid 20 on futex 0xa200 was an event wait (the releaser signaller slept until it "
                "signalled) - not a held lock") in out, out
        assert "WITHOUT A SCHEDULING CAUSE" not in out, out
        # M: a lock held across a sleep (our labelled lock_contention run): 4 threads pass one
        # mutex around; each holder sleeps 7 ms (I/O) while holding it, then wakes the next.
        # Every releaser is a fellow waiter, so these are lock waits although the releaser slept.
        g = _Gen(ctx)
        for k in range(100):
            t = k * 10 * MS
            Hm, Wm = ws[k % 4], ws[(k + 1) % 4]
            g.switch(t, 0, idle, Hm)
            g.switch(t + 200_000, 1, idle, Wm)
            g.ev(t + 400_000, 1, f'{sys_}_entry_futex', 'uaddr = 0xb400, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
            g.switch(t + 410_000, 1, Wm, idle, 1)
            g.switch(t + 500_000, 0, Hm, idle, 1)
            g.ev(t + 7_500_000, 0, 'sched_waking', f'comm = "{Hm[1]}", tid = {Hm[0]}, prio = 20, target_cpu = 0')
            g.switch(t + 7_510_000, 0, idle, Hm)
            g.ev(t + 9_500_000, 0, f'{sys_}_entry_futex', 'uaddr = 0xb400, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
            g.ev(t + 9_505_000, 0, 'sched_waking', f'comm = "{Wm[1]}", tid = {Wm[0]}, prio = 20, target_cpu = 1')
            g.ev(t + 9_510_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xb400, uaddr2 = 0')
            g.switch(t + 9_700_000, 1, idle, Wm)
            g.ev(t + 9_800_000, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xb400, uaddr2 = 0')
            g.switch(t + 9_900_000, 1, Wm, idle, 1)
            g.switch(t + 9_950_000, 0, Hm, idle, 1)
        p = os.path.join(d, f'm{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 1.0))
        assert "VERDICT: LOCK CONTENTION on futex 0xb400: 100 held lock waits (100/s) by 4 threads, p50 9.40 ms" in out, out
        assert "holders sleep while holding (a lock held across a sleep or I/O) (release by" in out, out
        assert "FIX: do not sleep or do I/O while holding the lock" in out, out
        assert "[held-asleep]" in out, out
        # N: the tracer's own waits are left out even when they are the longest.
        g = _Gen(ctx)
        L, Hl = (95, 'lttng-consumerd', 20), (96, 'lttng-sessiond', 20)
        g.switch(0, 0, idle, Hl)
        g.switch(0, 1, idle, L)
        g.ev(2 * MS, 1, f'{sys_}_entry_futex', 'uaddr = 0xa300, op = 128, val = 2, utime = 0, uaddr2 = 0, val3 = 0')
        g.switch(2 * MS + 10_000, 1, L, idle, 1)
        g.ev(50 * MS, 0, f'{sys_}_entry_futex', 'uaddr = 0xa300, op = 129, val = 1, utime = 0, uaddr2 = 0, val3 = 0')
        g.ev(50 * MS + 5_000, 0, 'sched_waking', 'comm = "lttng-consumerd", tid = 95, prio = 20, target_cpu = 1')
        g.ev(50 * MS + 10_000, 0, f'{sys_}_exit_futex', 'ret = 1, uaddr = 0xa300, uaddr2 = 0')
        g.switch(51 * MS, 1, idle, L)
        g.ev(52 * MS, 1, f'{sys_}_exit_futex', 'ret = 0, uaddr = 0xa300, uaddr2 = 0')
        g.switch(300 * MS, 0, Hl, idle, 1)
        g.switch(300 * MS, 1, L, idle, 1)
        p = os.path.join(d, f'n{ctx}.txt'); g.write(p)
        out = _capture(report, analyse(p, 0.3))
        assert "tracer's own futex waits (left out): 1 by lttng-consumerd" in out, out
        assert "VERDICT: NO LONG FUTEX WAITS (no lock wait at all:" in out and "lttng" not in out.split("VERDICT")[1], out
    print("futex_wait selftest OK (three line shapes)")


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
