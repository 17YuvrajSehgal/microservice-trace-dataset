#!/usr/bin/env python3
"""
irq_balance.py - where interrupt and softirq work lands, CPU by CPU, and whether network
receive (NET_RX) piles onto one CPU.

Usage:
    python3 irq_balance.py <slice.txt> <slice_seconds> [--baseline <slice2.txt> <secs2>]
                           [--siblings "0,1 2,3 4,5"] [--watch name[,name]] [--top 8]

Input:
    A slice made by extract_slice.sh with this events regex:
      'sched_switch|irq_handler_entry|irq_handler_exit|irq_softirq_entry|irq_softirq_exit|irq_softirq_raise'
    --baseline  a second slice of the same box when it was healthy (e.g. the capture without
                the load), with its own length in seconds. Per-second numbers are compared.
    --siblings  which logical CPUs share one physical core (SMT / hyper-threading), as pairs.
                The trace does not record this; read it on the box:
                  cat /sys/devices/system/cpu/cpu*/topology/thread_siblings_list   (or lscpu -e)
    --watch     thread names that must not share a core with the receive load (comma list,
                prefix match on the 15-char kernel name).

Output:
    1. One line per CPU: busy %, hardirq ms (and the top irq), softirq ms per kind, ksoftirqd
       ms, and the three threads that ran most on it.
    2. Concentration: for each softirq kind (and hardirq), the hottest CPU and its share of
       that kind's total time. Evenly spread work gives each CPU about 1/ncpu.
    3. Siblings and watched threads on the hot CPU and its sibling.
    4. With --baseline: the same per-CPU numbers per second, before -> after, and the threads
       that are new or much busier on the hot CPU.
    5. A verdict line in CAPS.

Why it matters:
    When a NIC steers every receive interrupt to one CPU, NET_RX softirq processing (and its
    helper thread ksoftirqd/N) eat that CPU. Any application thread pinned there - or on its
    SMT sibling, which shares the core's execution units - gets slow without ever looking
    busy itself. The fix is to spread receive work (RSS / multi-queue IRQ affinity, or RPS
    via /sys/class/net/<if>/queues/rx-*/rps_cpus) and to pin latency-sensitive threads away
    from that core and its sibling. ksoftirqd/N itself cannot be moved.

Read it:
    - NET_RX share on one CPU near 100% with that CPU busy: receive is not spread. Look at
      which application threads ran on that CPU and on its sibling.
    - raise->entry latency (how long a raised softirq waited before it ran) grows on a CPU
      that cannot keep up; a few ms here means the handler itself was delayed.
    - Spread shares of about 1/ncpu each: interrupt handling is not the problem.
    - With --baseline: the delta line shows what the load changed; threads that are NEW on
      the hot CPU or 3x busier are the ones that arrived with the problem.
"""
import os
import sys
from collections import defaultdict, Counter

from tracelib import read_events, Sched, prio_label, SOFTIRQ_NAMES, SEC, MS, pct, effective_secs

WANTED = {'sched_switch', 'irq_handler_entry', 'irq_handler_exit',
          'irq_softirq_entry', 'irq_softirq_exit', 'irq_softirq_raise'}
NET_RX = 3
# a kind is "concentrated" when one CPU carries at least this share of its total time
CONC_MIN_SHARE = 0.50
# only kinds that take at least this share of one CPU's time are judged
CONC_MIN_LOAD = 0.01
# baseline diff: a thread is "much busier" at this factor
BUSIER_X = 3.0
KERNELISH = ('swapper', 'ksoftirqd', 'kworker', 'migration', 'rcu', 'ktimer', 'irq/',
             'kthreadd', 'cpuhp', 'idle_inject', 'lttng', 'jbd2', 'kcompactd', 'kswapd')


def vec_name(v):
    return SOFTIRQ_NAMES[v] if isinstance(v, int) and 0 <= v < len(SOFTIRQ_NAMES) else f"vec{v}"


def is_app(name):
    return not any(name.startswith(k) for k in KERNELISH)


def pctl(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def measure(path, secs):
    """One pass: per-CPU hardirq / softirq / raise latency / run time per thread."""
    run = defaultdict(lambda: defaultdict(int))    # cpu -> tid -> ns

    def on_close(tid, kind, since, until, cpu):    # run time via Sched, so trace holes are dropped
        if kind == 'run':
            run[cpu][tid] += until - since
    sc = Sched(on_close=on_close)
    hard = defaultdict(lambda: defaultdict(int))   # cpu -> irq name -> ns
    soft = defaultdict(lambda: defaultdict(int))   # cpu -> vec -> ns
    lat = defaultdict(lambda: defaultdict(list))   # cpu -> vec -> [raise->entry ns]
    hstack, sstack = defaultdict(list), defaultdict(list)
    raised = defaultdict(dict)                     # cpu -> vec -> last raise t
    counts, cpus, t_last = Counter(), set(), None
    for ev in read_events(path, WANTED):
        n, c, t = ev.name, ev.cpu, ev.t
        cpus.add(c)
        counts[n] += 1
        t_last = t if t_last is None or t > t_last else t_last
        sc.feed(ev)                                # every event: it also finds trace holes
        if n == 'irq_handler_entry':
            hstack[c].append((ev.fields.get('name', '?'), t))
        elif n == 'irq_handler_exit':
            if hstack[c]:
                name, t0 = hstack[c].pop()
                hard[c][name] += t - t0
        elif n == 'irq_softirq_raise':
            raised[c][ev.fields.get('vec')] = t
        elif n == 'irq_softirq_entry':
            v = ev.fields.get('vec')
            sstack[c].append((v, t))
            r = raised[c].pop(v, None)
            if r is not None and t >= r:
                lat[c][v].append(t - r)
        elif n == 'irq_softirq_exit':
            if sstack[c]:
                v, t0 = sstack[c].pop()
                soft[c][v] += t - t0
    sc.finish(t_last)
    secs_eff, note = effective_secs(secs, sc)
    ncpu = max(len(cpus), 1)
    per = {}
    for c in sorted(cpus):
        r = run[c]
        busy = sum(ns for tid, ns in r.items() if tid != 0)
        ksoft = sum(ns for tid, ns in r.items() if sc.name(tid).startswith('ksoftirqd/'))
        top = sorted(((ns, tid) for tid, ns in r.items() if tid != 0), reverse=True)
        per[c] = {'busy': busy, 'ksoft': ksoft, 'hard': dict(hard[c]), 'soft': dict(soft[c]),
                  'lat': {v: xs for v, xs in lat[c].items()},
                  'top': [(tid, ns) for ns, tid in top], 'run': dict(r)}
    return {'per': per, 'cpus': sorted(cpus), 'ncpu': ncpu, 'secs': secs_eff, 'secs_given': secs,
            'note': note, 'holes': sc.skipped_note(), 'counts': counts, 'names': sc, 'path': path}


def concentration(m):
    """kind -> (hot cpu, share, total ns). kind is a vec int or 'hardirq'."""
    per, secs = m['per'], m['secs']
    out = {}
    kinds = set()
    for c in per:
        kinds.update(per[c]['soft'])
    for k in sorted(kinds, key=lambda v: (not isinstance(v, int), v)):
        tot = {c: per[c]['soft'].get(k, 0) for c in per}
        s = sum(tot.values())
        if s == 0 or max(tot.values()) < CONC_MIN_LOAD * secs * SEC:
            continue
        hot = max(tot, key=tot.get)
        out[k] = (hot, tot[hot] / s, s)
    tot = {c: sum(per[c]['hard'].values()) for c in per}
    s = sum(tot.values())
    if s and max(tot.values()) >= CONC_MIN_LOAD * secs * SEC:
        hot = max(tot, key=tot.get)
        out['hardirq'] = (hot, tot[hot] / s, s)
    return out


def is_conc(share, ncpu):
    return share >= max(CONC_MIN_SHARE, 2.0 / ncpu)


def parse_siblings(text):
    sib = {}
    for grp in (text or '').split():
        ids = [int(x) for x in grp.split(',') if x.strip().isdigit()]
        for i in ids:
            sib[i] = [j for j in ids if j != i]
    return sib


def report(m, base=None, siblings=None, watch=(), top=8):
    per, cp, secs, ncpu = m['per'], m['names'], m['secs'], m['ncpu']
    cnt = m['counts']
    print(f"{ncpu} CPUs ({', '.join(str(c) for c in m['cpus'])}), slice {secs:g} s. "
          f"events: sched_switch {cnt['sched_switch']}, hardirq {cnt['irq_handler_entry']}, "
          f"softirq {cnt['irq_softirq_entry']}, softirq raises {cnt['irq_softirq_raise']}")
    for line in (m['note'], m['holes']):
        if line:
            print(line)
    n_irq = cnt['irq_handler_entry'] + cnt['irq_softirq_entry']
    if n_irq == 0:
        print("\nVERDICT: NO IRQ EVENTS IN SLICE - re-cut it with the irq events regex "
              "(see Usage) before reading anything into this.")
        return
    tot_ns = secs * SEC
    print()
    print(f"{'cpu':>3} {'busy%':>6} {'hardirq ms':>10} {'top irq':<14}{'NET_RX':>8}{'NET_TX':>8}"
          f"{'TIMER':>8}{'SCHED':>8}{'RCU':>7}{'other':>7}{'ksoftirqd':>10}  top threads (ms)")
    for c in m['cpus']:
        p = per[c]
        hi = max(p['hard'].items(), key=lambda kv: kv[1])[0] if p['hard'] else '-'
        so = p['soft']
        other = sum(ns for v, ns in so.items() if v not in (3, 2, 1, 7, 9))
        tops = ", ".join(f"{cp.name(t)} {ns / MS:.0f}" for t, ns in p['top'][:3])
        print(f"{c:>3} {pct(p['busy'], tot_ns):>6.1f} {sum(p['hard'].values()) / MS:>10.1f} "
              f"{hi[:14]:<14}{so.get(3, 0) / MS:>8.1f}{so.get(2, 0) / MS:>8.1f}"
              f"{so.get(1, 0) / MS:>8.1f}{so.get(7, 0) / MS:>8.1f}{so.get(9, 0) / MS:>7.1f}"
              f"{other / MS:>7.1f}{p['ksoft'] / MS:>10.1f}  {tops}")

    conc = concentration(m)
    print()
    print(f"Concentration (expected share per CPU if spread evenly: {pct(1, ncpu):.0f}%)")
    for k, (hot, share, s) in conc.items():
        name = 'hardirq' if k == 'hardirq' else vec_name(k)
        flag = "  CONCENTRATED" if is_conc(share, ncpu) else ""
        line = f"  {name:<9} total {s / MS:>9.1f} ms, hottest cpu {hot} carries {pct(share, 1):.0f}%{flag}"
        if k == NET_RX:
            xs = per[hot]['lat'].get(NET_RX, [])
            if xs:
                line += (f"; raise->entry on cpu {hot}: p50 {pctl(xs, .5) / MS:.3f} ms, "
                         f"p99 {pctl(xs, .99) / MS:.3f} ms, max {max(xs) / MS:.3f} ms")
        print(line)
    if not conc:
        print("  (no softirq or hardirq kind reaches 1% of a CPU)")

    rx = conc.get(NET_RX)
    rx_hot = rx[0] if rx and is_conc(rx[1], ncpu) else None
    conc_hot = [h for k, (h, sh, _) in conc.items() if is_conc(sh, ncpu)]
    hot = rx_hot if rx_hot is not None else (conc_hot[0] if conc_hot else None)

    def watched(nm):
        return any(nm == w or nm.startswith(w) for w in watch)

    print()
    shared, app, sib = [], [], []
    if hot is None:
        # nothing is concentrated, so a watched thread on the busiest CPU means nothing here
        found = sorted(((nm, c, ns) for c in per for t, ns in per[c]['run'].items()
                        for nm in [cp.name(t)] if watched(nm)), key=lambda x: -x[2])
        print("no concentration; watched threads: " + (", ".join(
            f"{nm} on cpu {c} ({ns / MS:.0f} ms)" for nm, c, ns in found) if found
            else ("none of them ran in this slice" if watch else "none given")))
    else:
        load = "THE RX LOAD" if rx_hot is not None else "THE CONCENTRATED IRQ LOAD"
        sib = siblings.get(hot, []) if siblings else []
        if siblings is None:
            print("SMT pairing unknown: on the box read "
                  "/sys/devices/system/cpu/cpuN/topology/thread_siblings_list (or lscpu -e), "
                  "then pass --siblings \"0,1 2,3 ...\".")
        else:
            print(f"Siblings of cpu {hot}: {', '.join(map(str, sib)) if sib else 'none (no SMT pair given)'}")
            for s in sib:
                tops = ", ".join(f"{cp.name(t)} {ns / MS:.0f} ms" for t, ns in per[s]['top'][:3]) if s in per else '-'
                print(f"  cpu {s} top threads: {tops}")
        for c in [hot] + sib:
            if c not in per:
                continue
            for tid, ns in per[c]['run'].items():
                nm = cp.name(tid)
                if watched(nm):
                    shared.append((nm, c, ns))
        for nm, c, ns in shared:
            where = f"on cpu {c}" + (" (the hot cpu)" if c == hot else " (its SMT sibling)")
            print(f"  watched thread {nm} ran {ns / MS:.0f} ms {where}: "
                  f"SHARES THE PHYSICAL CORE WITH {load}")
        for c in [hot] + sib:
            if c in per:
                app += [(ns, cp.name(t), c) for t, ns in per[c]['top'] if is_app(cp.name(t))]
        app = sorted(app, reverse=True)[:top]

    if base is not None:
        bper, bsecs = base['per'], base['secs']
        print()
        print(f"Baseline {os.path.basename(base['path'])} ({bsecs:g} s of events, "
              f"{base['secs_given']:g} s given) -> this slice ({secs:g} s), per second "
              f"(ms of each second):")
        if base['note']:
            print("  baseline " + base['note'])
        for c in m['cpus']:
            p, b = per[c], bper.get(c)
            if b is None:
                print(f"  cpu {c}: not in baseline")
                continue
            def ps(x, s):
                return x / MS / s
            print(f"  cpu {c}: NET_RX {ps(b['soft'].get(3, 0), bsecs):.0f} -> "
                  f"{ps(p['soft'].get(3, 0), secs):.0f} ms/s, hardirq "
                  f"{ps(sum(b['hard'].values()), bsecs):.0f} -> {ps(sum(p['hard'].values()), secs):.0f} ms/s, "
                  f"ksoftirqd {ps(b['ksoft'], bsecs):.0f} -> {ps(p['ksoft'], secs):.0f} ms/s, "
                  f"busy {pct(b['busy'], bsecs * SEC):.0f}% -> {pct(p['busy'], secs * SEC):.0f}%")
        bnames = base['names']
        dh = hot if hot is not None else max(per, key=lambda c: per[c]['busy'])
        brun = {}
        if dh in bper:
            for t, ns in bper[dh]['run'].items():
                brun[bnames.name(t)] = brun.get(bnames.name(t), 0) + ns / bsecs
        changed = []
        for t, ns in per[dh]['top'][:top * 2]:
            nm = cp.name(t)
            now = ns / secs
            was = brun.get(nm)
            if was is None:
                changed.append(f"{nm} NEW ({now / MS:.0f} ms/s)")
            elif was > 0 and now >= BUSIER_X * was:
                changed.append(f"{nm} {was / MS:.0f} -> {now / MS:.0f} ms/s")
        print(f"  on cpu {dh}, new or >= {BUSIER_X:.0f}x busier than baseline: "
              + (", ".join(changed) if changed else "nothing"))

    print()
    if rx_hot is not None:
        p = per[rx_hot]
        ks = pct(p['ksoft'], tot_ns)
        print(f"VERDICT: RX CONCENTRATED ON CPU {rx_hot}: {pct(rx[1], 1):.0f}% of NET_RX time "
              f"(expected {pct(1, ncpu):.0f}%), ksoftirqd/{rx_hot} at {ks:.0f}% of a CPU, "
              f"cpu busy {pct(p['busy'], tot_ns):.0f}%")
        if app or shared:
            names = [nm for nm, _, _ in shared] + [nm for _, nm, _ in app if nm not in [s[0] for s in shared]]
            print(f"APP THREADS ON THAT CPU/ITS SIBLING: {', '.join(dict.fromkeys(names))}")
        print("FIX: spread RX with RSS/multi-queue IRQ affinity or RPS "
              "(/sys/class/net/<if>/queues/rx-*/rps_cpus), and pin latency-sensitive threads "
              "off that core and its SMT sibling")
    else:
        others = [f"{'hardirq' if k == 'hardirq' else vec_name(k)} on cpu {h}"
                  for k, (h, sh, _) in conc.items() if is_conc(sh, ncpu)]
        tail = f" (but {', '.join(others)} is concentrated - see above)" if others else ""
        print(f"VERDICT: IRQ/SOFTIRQ SPREAD EVENLY{tail}")


def main(argv):
    args = [a for a in argv]
    if '--selftest' in args:
        _selftest()
        return
    if len(args) < 2:
        raise SystemExit(__doc__)
    path, secs = args[0], float(args[1])
    base = siblings = None
    watch, top = [], 8
    i = 2
    while i < len(args):
        a = args[i]
        if a == '--baseline':
            base = measure(args[i + 1], float(args[i + 2]))
            i += 3
        elif a == '--siblings':
            siblings = parse_siblings(args[i + 1])
            i += 2
        elif a == '--watch':
            watch = [w for w in args[i + 1].split(',') if w]
            i += 2
        elif a == '--top':
            top = int(args[i + 1])
            i += 2
        else:
            raise SystemExit(f"unknown argument {a}\n{__doc__}")
    report(measure(path, secs), base, siblings, watch, top)


# ---- self-test ---------------------------------------------------------------------------
def _stamp(t):
    s, ns = divmod(t, SEC)
    return f"[{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}.{ns:09d}]"


class _Gen:
    """Builds a slice in one of the line shapes: ctx=True a pid/tid/procname context block,
    ctx='name' a procname-only one (measured on a real trace), ctx=False no context and an
    enum prev_state. Tracks who is on each CPU so the context is right."""

    def __init__(self, ctx):
        self.ctx, self.cur, self.rows, self.seq = ctx, {}, [], 0

    def _emit(self, t, cpu, name, pay):
        who = self.cur.get(cpu, (0, 'swapper/0', 20))
        if self.ctx == 'name':
            c = f'{{ procname = "{who[1]}" }}, '
        elif self.ctx:
            c = f'{{ pid = {who[0]}, tid = {who[0]}, procname = "{who[1]}" }}, '
        else:
            c = ''
        self.seq += 1
        self.rows.append((t, self.seq, f"{_stamp(t)} (+0.000000001) h {name}: "
                                       f"{{ cpu_id = {cpu} }}, {c}{{ {pay} }}"))

    def switch(self, t, cpu, prev, nxt, state=0):
        ps = str(state) if self.ctx else f'( "TASK_X" : container = {state} )'
        self._emit(t, cpu, 'sched_switch',
                   f'prev_comm = "{prev[1]}", prev_tid = {prev[0]}, prev_prio = {prev[2]}, '
                   f'prev_state = {ps}, next_comm = "{nxt[1]}", next_tid = {nxt[0]}, '
                   f'next_prio = {nxt[2]}')
        self.cur[cpu] = nxt

    def ev(self, t, cpu, name, pay):
        self._emit(t, cpu, name, pay)

    def write(self, path):
        with open(path, 'w') as f:
            for _, _, line in sorted(self.rows):
                f.write(line + '\n')


def _scenario(ctx, spread, path):
    g = _Gen(ctx)
    idle = (0, 'swapper/0', 20)
    ks0 = (10, 'ksoftirqd/0', 20)
    app = (500, 'appMain', 20)
    cpus = [0, 1, 2, 3]
    # appMain on cpu 1 all second; ksoftirqd/0 on cpu 0 for 0.45 s when concentrated
    g.switch(0, 1, idle, app)
    g.switch(SEC - 1, 1, app, idle, 1)
    if not spread:
        g.switch(0, 0, idle, ks0)
        g.switch(450 * MS, 0, ks0, idle, 1)
    for c in cpus:
        # concentrated: cpu 0 runs 800 x 1 ms of NET_RX (80%), the rest 2 x 0.1 ms;
        # spread: every cpu runs 200 x 1 ms (20% each)
        n = 800 if (not spread and c == 0) else (200 if spread else 2)
        dur = MS if (spread or c == 0) else 100_000
        step = SEC // max(n, 1)
        for i in range(n):
            t = i * step + 10
            g.ev(t, c, 'irq_softirq_raise', 'vec = 3')
            g.ev(t + 100_000, c, 'irq_softirq_entry', 'vec = 3')
            g.ev(t + 100_000 + dur, c, 'irq_softirq_exit', 'vec = 3')
        g.ev(SEC // 2, c, 'irq_handler_entry', 'irq = 27, name = "eth5"')
        g.ev(SEC // 2 + 50_000, c, 'irq_handler_exit', 'irq = 27, ret = 1')
        g.ev(SEC // 3, c, 'irq_softirq_entry', 'vec = 1')
        g.ev(SEC // 3 + 20_000, c, 'irq_softirq_exit', 'vec = 1')
    g.write(path)


def _capture(fn, *a, **kw):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a, **kw)
    return buf.getvalue()


def _selftest():
    import os, tempfile
    d = tempfile.mkdtemp()
    for ctx in (True, False):
        conc, even = os.path.join(d, f'c{ctx}.txt'), os.path.join(d, f'e{ctx}.txt')
        _scenario(ctx, False, conc)
        _scenario(ctx, True, even)
        out = _capture(report, measure(conc, 1.0), None, parse_siblings("0,1 2,3"), ['appMain'])
        assert "RX CONCENTRATED ON CPU 0" in out, out
        assert "SHARES THE PHYSICAL CORE WITH THE RX LOAD" in out, out
        assert "ksoftirqd/0 at 45% of a CPU" in out, out
        assert "APP THREADS ON THAT CPU/ITS SIBLING: appMain" in out, out
        out = _capture(report, measure(conc, 1.0), None, None, [])
        assert "SMT pairing unknown" in out, out
        # snapshot-style: 1 s of events cut over a 10 s slice must not dilute the shares
        out = _capture(report, measure(conc, 10.0), None, None, [])
        assert "events cover only 1.0 s of the 10 s slice" in out, out
        assert "ksoftirqd/0 at 45% of a CPU" in out, out
        # nothing concentrated: no sibling talk, just where the watched thread ran
        out = _capture(report, measure(even, 1.0), None, parse_siblings("0,1 2,3"), ['appMain'])
        assert "VERDICT: IRQ/SOFTIRQ SPREAD EVENLY" in out, out
        assert "no concentration; watched threads: appMain on cpu 1 (1000 ms)" in out, out
        assert "SHARES" not in out and "SMT pairing" not in out, out
        out = _capture(report, measure(conc, 1.0), measure(even, 1.0), None, [])
        assert "cpu 0: NET_RX 200 -> 800 ms/s" in out, out
        assert "ksoftirqd/0 NEW (450 ms/s)" in out, out
        assert f"Baseline e{ctx}.txt (1 s of events, 1 s given)" in out, out
        empty = os.path.join(d, 'empty.txt')
        open(empty, 'w').close()
        out = _capture(report, measure(empty, 1.0))
        assert "NO IRQ EVENTS IN SLICE" in out, out
    print("irq_balance selftest OK (both line shapes)")


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
