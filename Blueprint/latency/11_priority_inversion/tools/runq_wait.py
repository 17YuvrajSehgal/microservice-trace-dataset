#!/usr/bin/env python3
"""
runq_wait.py - is ONE thread starved of CPU, and by whom?

Usage:
    python3 runq_wait.py <slice.txt> <victim tid|name> [--top 15] [--min-ms 1] [--pidmap FILE]

Input:
    A slice made by extract_slice.sh (sched_switch and sched_waking/sched_wakeup lines),
    with or without a pid/procname context block. The victim is a tid, or a thread name
    (exact comm, or a prefix of it; every matching tid is counted and listed).

What it measures (the "run queue latency" of one thread, like bcc runqlat -L):
    woken wait     from sched_waking/sched_wakeup until the thread is switched IN
    preempted wait from being switched OUT while still runnable until it is switched IN
    For every wait it looks at the CPU the thread was waiting for (target_cpu of the
    wakeup, or the CPU it was switched out of) and lists who occupied that CPU meanwhile,
    with their priority relative to the victim. It also notes whether the OTHER CPUs were
    idle at the time: a thread that waits while other CPUs sit idle is held by placement
    (affinity, a crowd on its CPU), not by a full host.
    Shares are over the time the slice actually holds events (snapshot-style traces hold
    events for only part of the slice). Intervals that overlap a trace hole are not counted
    (a line says so).

Output:
    1. identity: name, tid(s), priority, CPUs it ran on, run and wait share.
    2. wait distribution: count, p50, p90, p99, max, total, share of the slice.
    3. the longest waits (>= --min-ms, top --top): when, how long, woken or preempted,
       which CPU, who occupied it ("name tid prio ms"), idle share of the other CPUs.
    4. competitors: who held the victim's CPU while it waited, ranked by ms, with
       same / better / worse priority than the victim.
    5. VERDICT lines (quote them):
       NOT STARVED | STARVED BY CROWD | STARVED BY HIGHER PRIORITY | MIXED
       plus OTHER CPUS WERE IDLE ... | HOST SATURATED ... and a fix hint.

Read it:
    STARVED BY CROWD = many threads of the same (or worse) priority share its CPU, and the
    time-share scheduler simply takes turns. Fix: raise the victim's priority (nice -10 is
    CFS weight 9548 against 1024 at nice 0, about 9x the share) or move the crowd away.
    STARVED BY HIGHER PRIORITY = one real-time or better-priority thread holds the CPU;
    the victim cannot win against it. Fix: tame or move that thread, or give the victim a
    real-time class too.
    NOT STARVED = its waits are small; look elsewhere (sleeping on a lock, a syscall, a
    device - see wait_chain.py / syscall_stall.py). A thread that already outranks the
    threads it waits behind is NOT helped by a higher priority: its remaining waits are
    the scheduler's slice granularity, a few ms at most.
"""
import sys
from collections import defaultdict, deque

from tracelib import (read_events, Sched, Cpus, prio_label, cpus_text, load_pidmap, hms,
                      SEC, MS)

SCHED = {'sched_switch', 'sched_waking', 'sched_wakeup', 'sched_wakeup_new',
         'sched_process_fork', 'lttng_statedump_process_state'}

# Calibration (partner line-card traces, Nov 2026). Starvation is relative to a deadline the
# trace does not know, so the bar for calling it THE fault is high: a wait of STARVED_MAX_MS
# or more AND a wait share of STARVED_SHARE or more. Below that, a wait >= MILD_MAX_MS or
# MILD_COUNT10 waits >= 10 ms is reported as PRESENT BUT MILD, for the operator to judge.
#   card A  commsTx prio 120: share 9.4%, max 33.0 ms, 7 waits >= 10 ms    -> STARVED
#           (engineers' fix: prio 120 -> 110)
#   card B  commsTx prio 120: share 10.2%, max 29.8 ms, 26 waits >= 10 ms  -> STARVED (same)
#   healthy control card, app thread: share ~5%, max 18-20 ms, 23 waits   -> MILD (no fault)
#   card C  bbbFLPO-type thread: share 5%, max 50 ms, 18 waits             -> MILD; those waits
#           were the consequence of a clone stall (its D-state blocks are bigger: D-state line)
#   card C  commsTx prio 100: share 4.6%, max 5.56 ms, 0 waits >= 10 ms    -> NOT STARVED
#           (already raised by the engineers; it did not help - the earlier false CROWD call)
STARVED_MAX_MS = 25
STARVED_SHARE = 0.06
MILD_MAX_MS = 10
MILD_COUNT10 = 3
# a victim whose priority already beats the occupants holding OUTRANK_SHARE of its waiting
# time is not held by a crowd: a higher priority cannot help it
OUTRANK_SHARE = 0.8
CROWD_SHARE = 0.6
IDLE_ELSEWHERE = 0.5


def _pct(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))]


def rel_class(vp, p):
    """competitor prio p against victim prio vp -> 'better' | 'same' | 'worse' | '?'."""
    if vp is None or p is None:
        return '?'
    return 'better' if p < vp else 'same' if p == vp else 'worse'


def analyse(path, victim, pidmap=None):
    vt = int(victim) if victim.isdigit() else None
    vname = None if vt is not None else victim
    cp = Cpus()
    since = {}                              # cpu -> time of its last sched_switch
    runs = defaultdict(deque)               # cpu -> closed (since, until, tid), recent only
    cpu_busy = defaultdict(int)             # cpu -> run ns over the slice
    cpus = set()
    vtids = set([vt]) if vt is not None else set()
    open_w = {}                             # victim tid -> start of its open wait
    waits = []                              # dicts, one per closed victim wait
    dstate = [0, 0]                         # victim D-state: [total ns, longest block ns]

    def overlap(dq, s, u):
        out = defaultdict(int)
        for a, b, t in dq:
            o = min(b, u) - max(a, s)
            if o > 0:
                out[t] += o
        return out

    def on_close(tid, kind, s, u, cpu):
        if kind == 'run':
            cpu_busy[cpu] += u - s
            dq = runs[cpu]
            dq.append((s, u, tid))
            lo = min(open_w.values(), default=None)
            if lo is None:
                while len(dq) > 1:
                    dq.popleft()
            else:
                while len(dq) > 1 and dq[0][1] < lo:
                    dq.popleft()
        elif kind == 'D' and tid in vtids:
            dstate[0] += u - s
            dstate[1] = max(dstate[1], u - s)
        elif kind in ('rqW', 'rqP') and tid in vtids:
            open_w.pop(tid, None)
            occ = overlap(runs[cpu], s, u)
            ct = cp.tid_on(cpu)                         # still-open run on this CPU (migration)
            if ct not in (0, tid) and cpu in since and since[cpu] < u:
                occ[ct] += u - max(since[cpu], s)
            busy_other = 0
            for c in cpus:
                if c == cpu:
                    continue
                busy_other += sum(overlap(runs[c], s, u).values())
                oc = cp.tid_on(c)
                if oc != 0 and c in since and since[c] < u:
                    busy_other += u - max(since[c], s)
            n_other = max(0, len(cpus) - 1)
            waits.append({'s': s, 'u': u, 'kind': kind, 'cpu': cpu, 'tid': tid,
                          'occ': dict(occ), 'idle_other': n_other * (u - s) - busy_other,
                          'n_other': n_other})

    sc = Sched(on_close=on_close, pidmap=pidmap)

    def match(tid, comm):
        if vname is not None and comm and tid != 0 and \
                (comm == vname or comm.startswith(vname)):
            vtids.add(tid)

    for ev in read_events(path, SCHED):
        cpus.add(ev.cpu)
        if ev.name == 'sched_switch':
            since[ev.cpu] = ev.t
            if vname is not None:
                f = ev.fields
                match(f.get('prev_tid'), f.get('prev_comm'))
                match(f.get('next_tid'), f.get('next_comm'))
        elif vname is not None and ev.name in ('sched_waking', 'sched_wakeup'):
            f = ev.fields
            match(f.get('tid'), f.get('comm'))
        cp.feed(ev)
        sc.feed(ev)
        for t in vtids:
            st = sc.state.get(t)
            if st is not None and st[0] in ('rqW', 'rqP'):
                open_w[t] = st[1]
            else:
                open_w.pop(t, None)
    sc.finish()
    return {'sc': sc, 'victim': victim, 'vtids': sorted(vtids), 'waits': waits,
            'cpus': sorted(cpus), 'cpu_busy': cpu_busy, 'span': int(sc.span_s() * SEC),
            'dstate': dstate}


def summarise(r):
    sc, waits, span = r['sc'], r['waits'], r['span']
    out = {'lines': [], 'hint': None, 'note': None, 'dline': None}
    if not r['vtids'] or span <= 0:
        out['lines'].append(f"VERDICT: VICTIM NOT SEEN - '{r['victim']}' never appears in this slice")
        return out
    lens = [w['u'] - w['s'] for w in waits]
    total, mx = sum(lens), max(lens, default=0)
    p99 = _pct(lens, .99)
    count10 = sum(1 for d in lens if d >= 10 * MS)
    share = total / span
    vprio = sc.prio.get(r['vtids'][0])
    by_cls = defaultdict(int)
    comp = defaultdict(int)
    by_cpu = defaultdict(int)
    for w in waits:
        by_cpu[w['cpu']] += w['u'] - w['s']
        for t, ns in w['occ'].items():
            comp[t] += ns
            by_cls[rel_class(vprio, sc.prio.get(t))] += ns
    hot_cpu = max(by_cpu, key=by_cpu.get) if by_cpu else None
    sw = by_cls['same'] + by_cls['worse'] + by_cls['?']
    better = by_cls['better']
    same_tids = {t for t in comp if rel_class(vprio, sc.prio.get(t)) == 'same'}
    idle_den = sum((w['u'] - w['s']) * w['n_other'] for w in waits)
    idle_share = sum(w['idle_other'] for w in waits) / idle_den if idle_den else 0.0
    host_sat = bool(r['cpus']) and all(r['cpu_busy'][c] / span >= 0.9 for c in r['cpus'])
    out.update(total=total, max=mx, p99=p99, count10=count10, share=share, comp=comp,
               by_cls=by_cls, hot_cpu=hot_cpu, idle_share=idle_share, host_sat=host_sat,
               vprio=vprio, same_tids=same_tids)
    L = out['lines']
    d_total, d_max = r['dstate']
    if d_total > total or d_max > mx:
        out['dline'] = (f"D-state: {100 * d_total / span:.1f}% of its time, longest block "
                        f"{d_max / MS:.1f} ms - its biggest delays are D-state blocks, not "
                        f"runnable waits - run wait_chain.py (9_syscall_stall) before blaming "
                        f"the crowd")
    starved = mx >= STARVED_MAX_MS * MS and share >= STARVED_SHARE
    mild = not starved and (mx >= MILD_MAX_MS * MS or count10 >= MILD_COUNT10)
    outrank = bool(total) and by_cls['worse'] / total >= OUTRANK_SHARE
    if outrank:
        wp = max((t for t in comp if rel_class(vprio, sc.prio.get(t)) == 'worse'), key=comp.get)
        out['note'] = (f"NOTE: the victim already outranks the threads it waited behind (prio "
                       f"{prio_label(vprio)} vs {prio_label(sc.prio.get(wp))}): raising its "
                       f"priority will not help; the remaining waits are CFS slice granularity "
                       f"(max {mx / MS:.2f} ms)")
    if mild:
        L.append(f"VERDICT: STARVATION PRESENT BUT MILD - waits are {100 * share:.1f}% of its "
                 f"time, p99 {p99 / MS:.2f} ms, longest {mx / MS:.2f} ms, {count10} waits >= "
                 f"10 ms; the crowd on cpu {hot_cpu} is {len(same_tids)} distinct same-prio "
                 f"threads. Report it; call it the fault only if the operator named this "
                 f"thread or its deadline is under {mx / MS:.0f} ms")
    elif not starved:
        L.append(f"VERDICT: NOT STARVED - waits are {100 * share:.1f}% of the slice, p99 "
                 f"{p99 / MS:.2f} ms, longest {mx / MS:.2f} ms, {count10} waits >= 10 ms")
    elif not outrank and sw / total >= CROWD_SHARE:
        L.append(f"VERDICT: STARVED BY CROWD: same-or-worse-priority threads held cpu {hot_cpu} "
                 f"for {sw / MS:.1f} ms ({100 * sw / total:.0f}% of its waiting); "
                 f"{len(same_tids)} distinct threads at prio {prio_label(vprio)}")
        out['hint'] = ("FIX HINT: raise the victim's priority (nice -10 = CFS weight 9548 vs "
                       "1024 at nice 0, ~9x) or move the crowd off that CPU")
    elif better / total >= CROWD_SHARE:
        top = max((t for t in comp if rel_class(vprio, sc.prio.get(t)) == 'better'),
                  key=comp.get)
        L.append(f"VERDICT: STARVED BY HIGHER PRIORITY: {sc.name(top)} tid {top} prio "
                 f"{prio_label(sc.prio.get(top))} held cpu {hot_cpu} for {comp[top] / MS:.1f} ms "
                 f"({100 * comp[top] / total:.0f}%)")
        out['hint'] = ("FIX HINT: reduce or move the RT/higher-priority thread, or give the "
                       "victim a real-time class")
    else:
        L.append(f"VERDICT: MIXED - same-or-worse {100 * sw / total:.0f}%, higher-priority "
                 f"{100 * better / total:.0f}%, cpu idle/other "
                 f"{100 * max(0, total - sw - better) / total:.0f}% of its waiting "
                 f"({total / MS:.1f} ms, {100 * share:.1f}% of the slice, longest {mx / MS:.1f} ms)")
    if idle_share >= IDLE_ELSEWHERE:
        L.append(f"OTHER CPUS WERE IDLE {100 * idle_share:.0f}% OF THE TIME IT WAITED "
                 f"(placement/affinity, not a full host)")
    elif host_sat:
        L.append("HOST SATURATED: all CPUs busy >= 90%")
    else:
        busy = ', '.join(f"cpu{c} {100 * r['cpu_busy'][c] / span:.0f}%" for c in r['cpus'])
        L.append(f"other CPUs idle {100 * idle_share:.0f}% while it waited; busy over the slice: {busy}")
    return out


def report(r, top=15, min_ms=1.0):
    sc, waits, span = r['sc'], r['waits'], r['span']
    s = summarise(r)
    if not r['vtids'] or span <= 0:
        print(s['lines'][0])
        return
    span_s = span / SEC
    print(f"victim '{r['victim']}' -> tid(s) {', '.join(str(t) for t in r['vtids'])}"
          + (f"  ({len(r['vtids'])} threads match the name; all are counted)"
             if len(r['vtids']) > 1 else ''))
    for t in r['vtids']:
        x = sc.row(t, span_s)
        place = (f"pinned or always placed on cpu {x['cpus'][0]}" if len(x['cpus']) == 1
                 else f"ran on cpus {cpus_text(x['cpus'])}")
        print(f"  {x['name']} tid {t} prio {prio_label(x['prio'])}: {place}; "
              f"run {100 * x['run']:.1f}%, wait {100 * x['wait']:.1f}% of the "
              f"{span_s:.1f} s that hold events")
    if s['dline']:
        print(s['dline'])
    if sc.skipped_note():
        print(sc.skipped_note())
    print()
    print("Wait distribution (ms)")
    print(f"{'kind':<10}{'count':>7}{'p50':>8}{'p90':>8}{'p99':>8}{'max':>8}{'total':>9}{'share':>7}")
    for kind, label in (('rqW', 'woken'), ('rqP', 'preempted'), (None, 'all')):
        v = [w['u'] - w['s'] for w in waits if kind is None or w['kind'] == kind]
        print(f"{label:<10}{len(v):>7}{_pct(v, .5) / MS:>8.2f}{_pct(v, .9) / MS:>8.2f}"
              f"{_pct(v, .99) / MS:>8.2f}{max(v, default=0) / MS:>8.2f}{sum(v) / MS:>9.1f}"
              f"{100 * sum(v) / span:>6.1f}%")
    print()
    longest = sorted((w for w in waits if w['u'] - w['s'] >= min_ms * MS),
                     key=lambda w: w['s'] - w['u'])[:top]
    print(f"Longest waits (>= {min_ms:g} ms, top {len(longest)} of "
          f"{sum(1 for w in waits if w['u'] - w['s'] >= min_ms * MS)})")
    print(f"{'start':<13}{'ms':>8}  {'kind':<10}{'cpu':>4}  {'idle-other':>10}  occupants of that cpu")
    for w in longest:
        occ = sorted(w['occ'].items(), key=lambda kv: -kv[1])[:4]
        who = '; '.join(f"{sc.name(t)} {t} {prio_label(sc.prio.get(t))} {ns / MS:.1f}ms"
                        for t, ns in occ) or '(cpu idle)'
        io = (100 * w['idle_other'] / (w['n_other'] * (w['u'] - w['s']))
              if w['n_other'] and w['u'] > w['s'] else 0)
        print(f"{hms(w['s']):<13}{(w['u'] - w['s']) / MS:>8.2f}  "
              f"{'woken' if w['kind'] == 'rqW' else 'preempted':<10}{w['cpu']:>4}  "
              f"{io:>9.0f}%  {who}")
    print()
    comp = s['comp']
    print(f"Competitors: who held the victim's CPU while it waited "
          f"(victim prio {prio_label(s['vprio'])})")
    print(f"{'ms':>9}{'share':>7}  {'class':<7}{'prio':<15}{'tid':>7}  name")
    for t, ns in sorted(comp.items(), key=lambda kv: -kv[1])[:top]:
        print(f"{ns / MS:>9.1f}{100 * ns / s['total']:>6.0f}%  "
              f"{rel_class(s['vprio'], sc.prio.get(t)):<7}{prio_label(sc.prio.get(t)):<15}"
              f"{t:>7}  {sc.name(t)}")
    bc = s['by_cls']
    print(f"by class: same {bc['same'] / MS:.1f} ms, worse {bc['worse'] / MS:.1f} ms, "
          f"better {bc['better'] / MS:.1f} ms, unknown {bc['?'] / MS:.1f} ms; "
          f"{len(s['same_tids'])} distinct same-priority competitors")
    print()
    if s['note']:
        print(s['note'])
    for line in s['lines']:
        print(line)
    if s['hint']:
        print(s['hint'])


# ---- self-test -------------------------------------------------------------------------
def _line(ms, cpu, ev, payload, ctx):
    ns = int(round(ms * MS))
    s, rem = divmod(ns, SEC)
    c = f'{{ pid = {ctx[0]}, tid = {ctx[0]}, procname = "{ctx[1]}" }}, ' if ctx else ''
    return ns, f'[00:00:{s:02d}.{rem:09d}] (+0.000000001) h {ev}: {{ cpu_id = {cpu} }}, {c}{{ {payload} }}'


def _sw(ms, cpu, prev, state, nxt, shape):
    ctx = (prev[0], prev[1]) if shape == 'ctx' else None
    st = (str(state) if shape == 'ctx' else
          '( "TASK_INTERRUPTIBLE" : container = 1 )' if state == 1 else
          '( "TASK_RUNNING" : container = 0 )' if state == 0 else str(state))
    return _line(ms, cpu, 'sched_switch',
                 f'prev_comm = "{prev[1]}", prev_tid = {prev[0]}, prev_prio = {prev[2]}, '
                 f'prev_state = {st}, next_comm = "{nxt[1]}", next_tid = {nxt[0]}, '
                 f'next_prio = {nxt[2]}', ctx)


def _wk(ms, cpu, who, tc, shape):
    return _line(ms, cpu, 'sched_waking',
                 f'comm = "{who[1]}", tid = {who[0]}, prio = {who[2]}, target_cpu = {tc}',
                 (0, 'swapper/0') if shape == 'ctx' else None)


def _scenario(kind, shape):
    """A: prio-120 victim behind 3 prio-120 threads (30 ms waits), cpu 0 idle -> CROWD.
    B: the same waits behind one RT thread -> HIGHER PRIORITY.
    C: 0.2 ms waits over a 1 s slice -> NOT STARVED.
    D: prio-100 victim behind prio-120 threads, 5 ms waits -> NOT STARVED + outrank note.
    E: prio-100 victim behind prio-120 threads, 15 ms waits -> MILD + outrank note.
    F: tiny waits but 30 ms D-state blocks -> NOT STARVED + D-state line.
    G: prio-120 victim behind the crowd, 15 ms waits -> MILD."""
    idle0, idle1 = (0, 'swapper/0', 20), (0, 'swapper/1', 20)
    victim = (7, 'victim', 0 if kind in 'DE' else 20)
    other = (50, 'other', 20)
    crowd = [(11, 'crowd0', 20), (12, 'crowd1', 20), (13, 'crowd2', 20)]
    rt = (99, 'rtthr', -64)
    L, t = [], 0.0
    if kind == 'F':
        for _ in range(4):
            L += [_wk(t, 1, victim, 1, shape), _sw(t + 0.1, 1, idle1, 0, victim, shape),
                  _sw(t + 1, 1, victim, 2, idle1, shape)]
            t += 31
        L += [_sw(0, 0, idle0, 0, other, shape), _sw(0.5, 0, other, 1, idle0, shape)]
    elif kind in 'ABDEG':
        step = {'A': 30, 'B': 30, 'D': 5, 'E': 15, 'G': 15}[kind]
        for _ in range(4):
            L.append(_wk(t + 0.1, 1, victim, 1, shape))
            if kind == 'B':
                L += [_sw(t, 1, idle1, 0, rt, shape), _sw(t + step, 1, rt, 1, victim, shape)]
            else:
                q = step / 3
                L += [_sw(t, 1, idle1, 0, crowd[0], shape), _sw(t + q, 1, crowd[0], 0, crowd[1], shape),
                      _sw(t + 2 * q, 1, crowd[1], 0, crowd[2], shape),
                      _sw(t + step, 1, crowd[2], 0, victim, shape)]
            L.append(_sw(t + step + 1, 1, victim, 1, idle1, shape))
            t += step + 5
        L += [_sw(0, 0, idle0, 0, other, shape), _sw(0.5, 0, other, 1, idle0, shape)]
    else:                                             # C: tiny waits, long quiet slice
        for _ in range(4):
            L += [_sw(t, 1, idle1, 0, crowd[0], shape), _wk(t + 0.1, 1, victim, 1, shape),
                  _sw(t + 0.3, 1, crowd[0], 1, victim, shape), _sw(t + 1, 1, victim, 1, idle1, shape)]
            t += 250
        L += [_sw(0, 0, idle0, 0, other, shape), _sw(1000, 0, other, 1, idle0, shape)]
    L.sort(key=lambda x: x[0])
    return '\n'.join(l for _, l in L) + '\n'


def _selftest():
    import os
    import tempfile
    want = {'A': ('STARVED BY CROWD', '3 distinct threads at prio 120', 'OTHER CPUS WERE IDLE'),
            'B': ('STARVED BY HIGHER PRIORITY', 'rtthr tid 99 prio RT 63'),
            'C': ('NOT STARVED',),
            'D': ('NOT STARVED', 'OTHER CPUS WERE IDLE'),
            'E': ('STARVATION PRESENT BUT MILD', 'OTHER CPUS WERE IDLE'),
            'F': ('NOT STARVED',),
            'G': ('STARVATION PRESENT BUT MILD', '4 waits >= 10 ms',
                  'is 3 distinct same-prio threads', 'OTHER CPUS WERE IDLE')}
    for shape in ('ctx', 'noctx'):
        for kind in 'ABCDEFG':
            with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as tf:
                tf.write(_scenario(kind, shape))
                p = tf.name
            try:
                for victim in ('7', 'victim'):
                    r = analyse(p, victim)
                    assert r['vtids'] == [7], (kind, shape, victim, r['vtids'])
                    s = summarise(r)
                    text = '\n'.join(s['lines'])
                    for w in want[kind]:
                        assert w in text, (kind, shape, victim, text)
                    assert 'STARVED BY CROWD' not in text or kind == 'A', (kind, text)
                    if kind == 'A':
                        assert len(s['same_tids']) == 3 and s['hot_cpu'] == 1, s['same_tids']
                        assert all(w['n_other'] == 1 for w in r['waits'])
                        assert s['note'] is None
                    if kind == 'C':
                        assert s['max'] < 10 * MS and s['share'] < 0.01 and s['note'] is None
                    if kind in 'DE':
                        assert s['note'] and 'outranks' in s['note'] and \
                            'prio 100 (nice -20) vs 120 (nice 0)' in s['note'], s['note']
                    if kind == 'D':
                        assert s['share'] >= STARVED_SHARE and s['max'] < 10 * MS
                    if kind == 'F':
                        assert s['dline'] and 'longest block 30.0 ms' in s['dline'], s['dline']
                    else:
                        assert s['dline'] is None, (kind, s['dline'])
                    if kind == 'G':
                        assert s['max'] < STARVED_MAX_MS * MS and s['count10'] == 4
                if kind in 'AFG' and shape == 'noctx':
                    print(f"--- selftest report ({kind}, {shape}) ---")
                    report(analyse(p, 'victim'), top=4)
            finally:
                os.unlink(p)
    # a victim that is not there
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as tf:
        tf.write(_scenario('C', 'noctx'))
        p = tf.name
    try:
        assert 'VICTIM NOT SEEN' in summarise(analyse(p, 'nobody'))['lines'][0]
    finally:
        os.unlink(p)
    print("runq_wait selftest OK")


def main():
    args = sys.argv[1:]
    if '--selftest' in args:
        _selftest()
        return
    if len(args) < 2:
        raise SystemExit(__doc__)
    path, victim = args[0], args[1]
    opt = {'--top': '15', '--min-ms': '1', '--pidmap': None}
    i = 2
    while i < len(args):
        if args[i] in opt and i + 1 < len(args):
            opt[args[i]] = args[i + 1]
            i += 2
        else:
            raise SystemExit(f"unknown or incomplete option {args[i]}\n{__doc__}")
    r = analyse(path, victim, load_pidmap(opt['--pidmap']))
    report(r, int(opt['--top']), float(opt['--min-ms']))


if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
