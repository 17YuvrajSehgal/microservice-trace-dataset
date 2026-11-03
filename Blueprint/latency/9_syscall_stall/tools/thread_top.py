#!/usr/bin/env python3
"""
thread_top.py - name every thread that matters, and show how crowded each CPU is.

Usage:
    python3 thread_top.py <slice.txt> <slice_seconds> [--sort wait|run|max|wakeups]
                          [--top 25] [--cpu N] [--pidmap FILE]

Input:
    A slice made by extract_slice.sh (sched_switch and sched_waking/sched_wakeup lines).
    Works on traces with or without a pid/procname context block. Without one, a row is
    one thread (tid) named by its comm; a pid is printed only when the slice tells it
    (context block, sched_process_fork, or --pidmap FILE from pidmap.py).

Output:
    1. Header: CPUs, slice length, switch count, where thread identity came from, and the
       prev_state codes seen.
    2. Per-CPU table: busy%, how many threads ran there, how many of them sit in each
       priority class (RT / better than 120 / exactly 120 / worse than 120), the share
       taken by kernel helpers (ksoftirqd, kworker), and the top 3 occupants.
    3. Per-thread table (top N by --sort, default wait). run / wait / preempt / wakewait /
       S / D are average threads over the slice (1.00 = one thread the whole slice; same
       units as sched_budget.py). wait = ready to run but no CPU; preempt = the part of
       wait after being switched out while runnable; wakewait = the part after a wakeup.
       >=10ms and >=50ms count single waits that long; max_ms is the longest one.
       '*' marks a candidate victim: 3 or more waits >= 10 ms, or one wait >= 25 ms (the
       bars runq_wait.py uses). How much it ran does not matter. Test every '*' row.
       --cpu N keeps only threads that ran on CPU N.

Read it:
    A STARVED thread: small run, large wait, big max_ms, seen on one CPU only. Then read
    that CPU's row in table 2: many threads at its own priority = a crowd. Prove it with
    runq_wait.py <slice> <tid> - that names the competitors and gives the verdict.
    A HOG: large run. A SLEEPER: large S (waiting on events, locks, timers): not a CPU
    problem. wait is time READY to run; sleeping is never counted in it.
    Priorities: '120 (nice 0)' is the default time-share class. Lower numbers win.
    'RT n' is a real-time thread; it beats every time-share thread on its CPU.
"""
import sys
from collections import Counter, defaultdict

from tracelib import (read_events, Sched, prio_label, cpus_text, load_pidmap, effective_secs,
                      SEC, MS)
from runq_wait import MILD_COUNT10, STARVED_MAX_MS

SCHED = {'sched_switch', 'sched_waking', 'sched_wakeup', 'sched_wakeup_new',
         'sched_process_fork', 'lttng_statedump_process_state'}
SORT_KEY = {'wait': 'wait', 'run': 'run', 'max': 'max_ms', 'wakeups': 'wakeups'}


def prio_class(p):
    """LTTng prio -> 'rt' | 'better' (than 120) | 'p120' | 'worse' | '?'."""
    if p is None:
        return '?'
    if p < 0:
        return 'rt'
    if p < 20:
        return 'better'
    return 'p120' if p == 20 else 'worse'


def analyse(path, secs, pidmap=None):
    cpu_run = defaultdict(int)                                  # cpu -> busy ns
    cpu_tid_run = defaultdict(lambda: defaultdict(int))         # cpu -> tid -> ns

    def on_close(tid, kind, since, until, cpu):
        if kind == 'run':
            cpu_run[cpu] += until - since
            cpu_tid_run[cpu][tid] += until - since

    sc = Sched(on_close=on_close, pidmap=pidmap)
    nswitch, has_ctx, cpus = 0, False, set()
    for ev in read_events(path, SCHED):
        cpus.add(ev.cpu)
        if ev.name == 'sched_switch':
            nswitch += 1
            if not has_ctx and ev.has_ctx():
                has_ctx = True
        sc.feed(ev)
    sc.finish()
    # snapshot-style traces hold events for only part of the slice; divide by what is there
    eff, note = effective_secs(secs, sc)
    return {'sc': sc, 'secs': eff, 'given_secs': secs, 'note': note, 'cpus': sorted(cpus),
            'nswitch': nswitch, 'has_ctx': has_ctx, 'cpu_run': cpu_run,
            'cpu_tid_run': cpu_tid_run}


def cpu_classes(r, cpu):
    sc = r['sc']
    return Counter(prio_class(sc.prio.get(t)) for t in sc.cpu_tids.get(cpu, ()))


def rows_for(r, sort='wait', cpu=None):
    rows = r['sc'].rows(r['secs'])
    if cpu is not None:
        rows = [x for x in rows if cpu in x['cpus']]
    rows.sort(key=lambda x: -x[SORT_KEY[sort]])
    return rows


def is_victim(x):
    # The same bars runq_wait.py uses (MILD needs MILD_COUNT10 waits of 10 ms, STARVED a wait of
    # STARVED_MAX_MS), so every row that tool could call MILD or STARVED carries the star. The
    # old rule (waited more than it ran) hid the comms thread on a line card: run 16%, wait 9%,
    # 7 waits >= 10 ms, longest 33 ms - STARVED BY CROWD, and the agent never tested it.
    return x['ge10ms'] >= MILD_COUNT10 or x['max_ms'] >= STARVED_MAX_MS


def report(r, sort='wait', top=25, cpu=None):
    sc, secs = r['sc'], r['secs']
    n = secs * SEC
    print(f"{len(r['cpus'])} CPUs ({cpus_text(r['cpus'])}), slice {r['given_secs']:g} s, "
          f"{r['nswitch']} sched_switch")
    if r['note']:
        print(r['note'])
    if sc.skipped_note():
        print(sc.skipped_note())
    print("identity: " + ("pid context present" if r['has_ctx'] else
                          "comm from sched_switch; no pid context (one row = one thread)"))
    print("prev_state codes seen:", dict(sorted(sc.codes.items())))
    print()
    print("Per CPU (threads = distinct threads that ran there; RT / <120 / =120 / >120 = how "
          "many of them in each priority class; kthr% = ksoftirqd + kworker share)")
    print(f"{'cpu':>4} {'busy%':>6} {'threads':>8} {'RT':>4} {'<120':>5} {'=120':>5} "
          f"{'>120':>5} {'kthr%':>6}  top occupants")
    for c in r['cpus']:
        cls = cpu_classes(r, c)
        tr = r['cpu_tid_run'][c]
        kthr = sum(ns for t, ns in tr.items()
                   if sc.name(t).startswith(('ksoftirqd', 'kworker')))
        top3 = sorted(tr.items(), key=lambda kv: -kv[1])[:3]
        occ = ', '.join(f"{sc.name(t)}({100 * ns / n:.0f}%)" for t, ns in top3)
        print(f"{c:>4} {100 * r['cpu_run'][c] / n:>6.0f} {len(sc.cpu_tids.get(c, ())):>8} "
              f"{cls['rt']:>4} {cls['better']:>5} {cls['p120']:>5} {cls['worse']:>5} "
              f"{100 * kthr / n:>6.0f}  {occ}")
    print()
    rows = rows_for(r, sort, cpu)
    where = f" that ran on cpu {cpu}" if cpu is not None else ""
    print(f"Threads{where}, top {min(top, len(rows))} of {len(rows)} by {sort} "
          f"('*' = candidate victim: >= {MILD_COUNT10} waits of 10 ms or a wait >= {STARVED_MAX_MS} ms; "
          f"test every '*' row with runq_wait.py)")
    print(f"  {'tid':>7} {'pid':>7} {'name':<16}{'prio':<15}{'cpus':<6}{'run':>6}{'wait':>6}"
          f"{'preempt':>8}{'wakewait':>9}{'S':>6}{'D':>5}{'>=10ms':>7}{'>=50ms':>7}"
          f"{'max_ms':>8}{'wakeups':>8}")
    for x in rows[:top]:
        mark = '*' if is_victim(x) else ' '
        pid = str(x['pid']) if x['pid'] is not None else '-'
        print(f"{mark} {x['tid']:>7} {pid:>7} {x['name'][:15]:<16}{prio_label(x['prio']):<15}"
              f"{cpus_text(x['cpus']):<6}{x['run']:>6.2f}{x['wait']:>6.2f}{x['preempt']:>8.2f}"
              f"{x['wakewait']:>9.2f}{x['S']:>6.1f}{x['D']:>5.1f}{x['ge10ms']:>7}"
              f"{x['ge50ms']:>7}{x['max_ms']:>8.1f}{x['wakeups']:>8}")
    print()
    print("Read it:")
    print("- starved: small run, large wait, big max_ms, one CPU only. Check that CPU's row")
    print("  above: many threads at the same priority = a crowd. Prove it with runq_wait.py.")
    print("- hog: large run. sleeper: large S - waiting on events/locks/timers, not on a CPU.")
    print("- wait is READY-to-run time; sleep is never counted in it.")


# ---- self-test -------------------------------------------------------------------------
def _line(ms, cpu, ev, payload, ctx):
    ns = int(round(ms * MS))
    s, rem = divmod(ns, SEC)
    c = f'{{ pid = {ctx[0]}, tid = {ctx[0]}, procname = "{ctx[1]}" }}, ' if ctx else ''
    return ns, f'[00:00:{s:02d}.{rem:09d}] (+0.000000001) h {ev}: {{ cpu_id = {cpu} }}, {c}{{ {payload} }}'


def _sw(ms, cpu, prev, state, nxt, shape):
    ctx = (prev[0], prev[1]) if shape == 'ctx' else None
    if shape == 'ctx':
        st = str(state)
    else:
        st = ('( "TASK_INTERRUPTIBLE" : container = 1 )' if state == 1
              else '( "TASK_RUNNING" : container = 0 )' if state == 0 else str(state))
    return _line(ms, cpu, 'sched_switch',
                 f'prev_comm = "{prev[1]}", prev_tid = {prev[0]}, prev_prio = {prev[2]}, '
                 f'prev_state = {st}, next_comm = "{nxt[1]}", next_tid = {nxt[0]}, '
                 f'next_prio = {nxt[2]}', ctx)


def _wk(ms, cpu, who, tc, shape):
    return _line(ms, cpu, 'sched_waking',
                 f'comm = "{who[1]}", tid = {who[0]}, prio = {who[2]}, target_cpu = {tc}',
                 (0, 'swapper/0') if shape == 'ctx' else None)


def _scenario(shape):
    """cpu 1: five prio-120 threads crowd out a victim (waits ~12 ms, 5 times).
    cpu 0: one RT thread runs 50 ms."""
    idle0, idle1 = (0, 'swapper/0', 20), (0, 'swapper/1', 20)
    crowd = [(11 + i, f"crowd{i}", 20) for i in range(5)]
    victim, rt = (7, 'victim', 20), (99, 'rtthr', -64)
    L, t = [], 0.0
    for _ in range(5):
        L += [_sw(t, 1, idle1, 0, crowd[0], shape), _wk(t + 0.1, 1, victim, 1, shape),
              _sw(t + 4, 1, crowd[0], 0, crowd[1], shape), _sw(t + 8, 1, crowd[1], 0, crowd[2], shape),
              _sw(t + 12, 1, crowd[2], 0, victim, shape), _sw(t + 13, 1, victim, 1, crowd[3], shape),
              _sw(t + 17, 1, crowd[3], 0, crowd[4], shape), _sw(t + 21, 1, crowd[4], 1, idle1, shape)]
        t += 25
    L += [_sw(0, 0, idle0, 0, rt, shape), _sw(50, 0, rt, 1, idle0, shape)]
    L.sort(key=lambda x: x[0])
    return '\n'.join(l for _, l in L) + '\n'


def _hole_scenario(shape):
    """The base scenario plus a thread on cpu 0 switched out runnable at 51 ms and back in at
    700 ms with no cpu-0 event between: a trace hole, not a 649 ms wait."""
    idle0, rt, holey = (0, 'swapper/0', 20), (99, 'rtthr', -64), (88, 'holey', 20)
    L = [_sw(50, 0, rt, 1, holey, shape), _sw(51, 0, holey, 0, idle0, shape),
         _sw(700, 0, idle0, 0, holey, shape), _sw(701, 0, holey, 1, idle0, shape)]
    base = _scenario(shape).replace(_sw(50, 0, rt, 1, idle0, shape)[1] + '\n', '')
    return base + '\n'.join(l for _, l in L) + '\n'


def _selftest():
    import os
    import tempfile
    for shape in ('ctx', 'noctx'):
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as tf:
            tf.write(_scenario(shape))
            p = tf.name
        try:
            r = analyse(p, 0.2)
            assert r['has_ctx'] == (shape == 'ctx'), shape
            # events span 0.121 s of the 0.2 s slice -> shares use the event span
            assert r['note'] and abs(r['secs'] - 0.121) < 0.002, (r['note'], r['secs'])
            assert r['sc'].skipped_note() == ''
            cls1, cls0 = cpu_classes(r, 1), cpu_classes(r, 0)
            assert cls1['p120'] == 6, (shape, cls1)
            assert cls0['rt'] == 1, (shape, cls0)
            rows = {x['tid']: x for x in rows_for(r)}
            v = rows[7]
            assert is_victim(v) and v['ge10ms'] == 5 and 11 < v['max_ms'] < 13, (shape, v)
            assert rows[99]['prio'] == -64 and rows[99]['cpus'] == [0]
            assert rows_for(r)[0]['tid'] in (7, 11, 12, 13, 14, 15)
            if shape == 'noctx':
                assert v['pid'] is None
                print(f"--- selftest report ({shape}) ---")
                report(r, top=8)
        finally:
            os.unlink(p)
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as tf:
        tf.write(_hole_scenario('noctx'))
        p = tf.name
    try:
        r = analyse(p, 0.8)
        sc = r['sc']
        assert sc.skipped[88][0] == 1 and sc.skipped_note(), dict(sc.skipped)
        rows = {x['tid']: x for x in rows_for(r)}
        assert rows[88]['max_ms'] < 10 and rows[88]['ge10ms'] == 0, rows[88]
    finally:
        os.unlink(p)
    print("thread_top selftest OK")


def main():
    args = sys.argv[1:]
    if '--selftest' in args:
        _selftest()
        return
    if len(args) < 2:
        raise SystemExit(__doc__)
    path, secs = args[0], float(args[1])
    opt = {'--sort': 'wait', '--top': '25', '--cpu': None, '--pidmap': None}
    i = 2
    while i < len(args):
        if args[i] in opt and i + 1 < len(args):
            opt[args[i]] = args[i + 1]
            i += 2
        else:
            raise SystemExit(f"unknown or incomplete option {args[i]}\n{__doc__}")
    if opt['--sort'] not in SORT_KEY:
        raise SystemExit("--sort must be one of wait|run|max|wakeups")
    r = analyse(path, secs, load_pidmap(opt['--pidmap']))
    if r['nswitch'] == 0:
        print(f"no sched_switch lines in {path}: wrong file, or the slice is empty")
        return
    report(r, opt['--sort'], int(opt['--top']),
           int(opt['--cpu']) if opt['--cpu'] is not None else None)


if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
