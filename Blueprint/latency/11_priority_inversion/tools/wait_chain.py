#!/usr/bin/env python3
"""
wait_chain.py - for one thread: why it was off the CPU. Who woke it from each block, and
what that waker was doing at that moment (the critical-path / wait analysis, one level).

Usage:
    python3 wait_chain.py <slice.txt> <victim tid|name> [--top 15] [--pidmap FILE]

Input:
    A slice made by extract_slice.sh with this events regex (6th argument):
      'sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_|irq_handler_|irq_softirq_'
    The sched trio is enough for "who woke it"; the syscall events add "what the waker was
    inside" and "what the victim was blocked in"; the irq / softirq events let a wakeup from
    an interrupt be named (softirq NET_RX, hardirq 27 eth5) instead of blamed on the idle
    thread. Works with or without a process-context block on the lines.

Why:
    A thread that sleeps is waiting for somebody. The kernel records who: the sched_waking
    event fires in the waker's context. So "commsTx was blocked 53 ms and was released by
    spawnerThr, 52.9 ms into a clone() call" is a fact the trace holds, not a guess. This is
    what Trace Compass calls the critical flow; this script does the first hop of it.

Output:
    1. the victim: name, tid, prio, pid; blocked time (total, share, count, p50, max) and the
       syscalls it was blocked in
    2. blocked time by waker: over all blocks and over the LONG blocks (>= 10 ms) - routine
       short waits (a packet, a timer tick) dominate the total and hide the problem
    3. the longest blocks one by one: when, how long, S/D, woken by whom, and what the waker
       was inside and for how long
    4. verdict lines in CAPS

Read it:
    - BLOCKED MOSTLY ON <thread> + THE WAKER WAS STUCK IN <syscall>: the victim's long waits
      end when that thread finishes that call - the call is the cause (syscall_stall.py
      measures it; a fork/clone without CLONE_VM is the classic one).
    - BLOCKED ON INTERRUPTS/SOFTIRQ: the victim is driven by packets or timers; its waits are
      the time between events, not a problem in itself. If the waits grew, look at the
      interrupt side (irq_balance.py).
    - BLOCKED MOSTLY ON <thread> in a WAIT-class call (futex, poll): a lock or a message
      from that thread - the victim's wait is that thread's own wait; run this script on
      the waker next.
    - NO LONG BLOCKS: the victim is not being held off the CPU by anyone; if it is slow, it
      is runnable-but-waiting (runq_wait.py) or simply busy.
"""
import re
import sys
from collections import defaultdict

from tracelib import (Cpus, Sched, MS, SEC, SOFTIRQ_NAMES, hms, load_pidmap, prio_label,
                      read_events)
from syscall_stall import SCHED, WAIT, sysname

LONG = 10 * MS
IRQ = {'irq_handler_entry', 'irq_handler_exit', 'irq_softirq_entry', 'irq_softirq_exit'}


class Names:
    def __contains__(self, n):
        return n in SCHED or n in IRQ or n.startswith(('syscall_', 'compat_syscall_'))


NAMES = Names()


def resolve(path, victim):
    """'7249' -> {7249}; 'commsTx' -> every tid the sched events call that (cheap text scan)."""
    if victim.isdigit():
        return {int(victim)}
    rx = re.compile(r'(?:prev_comm|next_comm|comm) = "%s", (?:prev_tid|next_tid|tid) = (\d+)'
                    % re.escape(victim))
    key = f'"{victim}"'
    tids = set()
    with open(path, errors='replace') as f:
        for line in f:
            if key in line:
                tids.update(int(t) for t in rx.findall(line))
    return tids


def analyse(path, victim, top=15, pidmap=None, out=print):
    victims = resolve(path, victim)
    if not victims:
        out(f"no thread named or numbered '{victim}' appears in {path}")
        return
    cp = Cpus()
    opened = {}                 # tid -> [syscall, t_entry, {kind: ns inside the call}]
    irqname = {}                # irq -> name
    blocks = defaultdict(list)  # victim tid -> [(since, until, kind, waker, wsys, own)]
    cur = [None]                # the event being fed (so on_close can see the waker)

    def waker_of(ev):
        if ev.has_ctx():
            tid = ev.ctx_tid()
            if tid:
                return ('thread', tid)
        return cp.context(ev.cpu)

    def on_close(tid, kind, since, until, cpu):
        o = opened.get(tid)
        if o is not None and until > o[1]:
            o[2][kind] += until - max(since, o[1])      # the caller's own time inside its call
        if tid not in victims or kind not in ('S', 'D', 'O'):
            return
        ev = cur[0]
        waker = wsys = None
        if ev is not None and ev.name in ('sched_waking', 'sched_wakeup', 'sched_wakeup_new'):
            waker = waker_of(ev)
            if waker[0] == 'thread' and waker[1] in opened:
                nm, t0, sp = opened[waker[1]]
                hard = sp['run'] + sp['D']
                st = sc.state.get(waker[1])
                if st and st[0] in ('run', 'D') and until > max(st[1], t0):
                    hard += until - max(st[1], t0)      # the waker's still-open interval
                wsys = (nm, until - t0, hard)           # syscall, elapsed, on-CPU + D inside it
        own = opened.get(tid, (None,))[0]
        blocks[tid].append((since, until, kind, waker, wsys, own))

    sc = Sched(on_close=on_close, pidmap=pidmap)
    for ev in read_events(path, NAMES):
        n = ev.name
        if n in SCHED:
            cur[0] = ev
            sc.feed(ev)
            cp.feed(ev)
            cur[0] = None
            continue
        if n in IRQ:
            if n == 'irq_handler_entry':
                f = ev.fields
                irqname[f.get('irq')] = f.get('name', '?')
            cp.feed(ev)
            continue
        sk = sysname(n)
        if sk is None:
            continue
        tid = ev.tid_or(cp)
        if not tid:
            continue
        if ev.has_ctx() and ev.ctx_pid():
            sc.pid.setdefault(tid, ev.ctx_pid())
        if sk[0] == 'entry':
            opened[tid] = [sk[1], ev.t, defaultdict(int)]
        else:
            opened.pop(tid, None)
    sc.finish()
    span = sc.span_s() * SEC - sum(g1 - g0 for g0, g1 in sc.gaps)   # events-covered time
    note = sc.skipped_note()
    if note:
        out(note)

    def label(w):
        if w is None:
            return 'unknown (no wakeup event seen)'
        k, v = w
        if k == 'thread':
            return 'idle context' if v == 0 else \
                f"{sc.name(v)} tid {v} prio {prio_label(sc.prio.get(v))}"
        if k == 'softirq':
            return f"softirq {SOFTIRQ_NAMES[v] if v is not None and v < len(SOFTIRQ_NAMES) else v}"
        return f"hardirq {v} {irqname.get(v, '')}".rstrip()

    # pick the victim thread with the most blocked time when a name matched several
    totals = {t: sum(b[1] - b[0] for b in blocks.get(t, [])) for t in victims}
    vt = max(totals, key=totals.get)
    bl = sorted(blocks.get(vt, []), key=lambda b: b[0])
    if len(victims) > 1:
        out(f"{len(victims)} threads match '{victim}': " + ", ".join(
            f"tid {t} ({totals[t] / MS:.0f} ms blocked)" for t in sorted(totals, key=totals.get, reverse=True)[:8])
            + " - analysing the most blocked one")
    durs = sorted(b[1] - b[0] for b in bl)
    tot = sum(durs)
    pid = sc.pid.get(vt)
    out(f"victim: {sc.name(vt)} tid {vt} prio {prio_label(sc.prio.get(vt))}"
        + (f" pid {pid}" if pid else " (pid unknown)"))
    if not bl:
        out("no blocked interval of the victim in this slice (it never slept, or never ran)")
        out("NO LONG BLOCKS")
        return
    out(f"blocked: {tot / MS:.1f} ms = {100 * tot / span if span > 0 else 0:.1f}% of the events-covered time, "
        f"{len(bl)} blocks, p50 {durs[len(durs) // 2] / MS:.2f} ms, max {durs[-1] / MS:.1f} ms; "
        f"run {sc.acc[vt]['run'] / MS:.1f} ms, runnable-wait "
        f"{(sc.acc[vt]['rqP'] + sc.acc[vt]['rqW']) / MS:.1f} ms")
    own = defaultdict(int)
    for b in bl:
        own[b[5] or '(no syscall event)'] += b[1] - b[0]
    out("blocked inside: " + ", ".join(f"{k} {v / MS:.1f} ms" for k, v in
                                       sorted(own.items(), key=lambda kv: -kv[1])[:3]))

    # 2. by waker
    by_all, by_long, cnt = defaultdict(int), defaultdict(int), defaultdict(int)
    wsys_of = defaultdict(lambda: defaultdict(int))
    for since, until, kind, waker, wsys, _ in bl:
        d = until - since
        lb = label(waker)
        by_all[lb] += d
        cnt[lb] += 1
        if d >= LONG:
            by_long[lb] += d
        if wsys:
            wsys_of[lb][wsys[0]] += d
    long_tot = sum(by_long.values())
    out()
    out(f"blocked time by waker (long blocks = >= {LONG // MS} ms, {long_tot / MS:.1f} ms in "
        f"{sum(1 for d in durs if d >= LONG)} blocks):")
    out(f"{'all_ms':>9}{'all%':>6}{'long_ms':>9}{'long%':>7}{'n':>7}  waker | waker's syscall at wake time")
    for lb, d in sorted(by_all.items(), key=lambda kv: (-by_long[kv[0]], -kv[1]))[:top]:
        ws = wsys_of.get(lb)
        wtxt = ", ".join(f"{k} {v / MS:.0f} ms" for k, v in
                         sorted(ws.items(), key=lambda kv: -kv[1])[:2]) if ws else '-'
        out(f"{d / MS:>9.1f}{100 * d / tot:>6.0f}{by_long[lb] / MS:>9.1f}"
            f"{(100 * by_long[lb] / long_tot) if long_tot else 0:>7.0f}{cnt[lb]:>7}  {lb} | {wtxt}")

    # 3. longest blocks
    longest = sorted(bl, key=lambda b: b[0] - b[1])[:top]
    out()
    out(f"longest {len(longest)} blocks:")
    out(f"{'start':<14}{'ms':>8}  state  woken by | waker was inside (its on-CPU + D in that call)")
    for since, until, kind, waker, wsys, _ in longest:
        wt = f"{wsys[0]} for {wsys[1] / MS:.1f} ms ({wsys[2] / MS:.1f} ms on-CPU+D)" if wsys else '-'
        out(f"{hms(since):<14}{(until - since) / MS:>8.1f}  {kind:<5}  {label(waker)} | {wt}")

    # 4. verdict
    out()
    if durs[-1] < LONG:
        out(f"NO LONG BLOCKS (max {durs[-1] / MS:.1f} ms; the victim is not being held off the "
            f"CPU by anyone)")
    base = by_long if long_tot else by_all
    base_tot = long_tot if long_tot else tot
    lb, d = max(base.items(), key=lambda kv: kv[1])
    out(f"BLOCKED MOSTLY ON {lb} ({100 * d / base_tot:.0f}% of "
        f"{'long-block' if long_tot else 'blocked'} time; {100 * by_all[lb] / tot:.0f}% of all blocked time)")
    # "stuck in a call" only when there are long blocks AND the waker's call is a stall by
    # syscall_stall's rule (on-CPU or D inside it) - a driver sleeping in ioctl is not stuck
    top5 = longest[:5]
    top5_tot = sum(b[1] - b[0] for b in top5)
    stuck = defaultdict(int)
    for since, until, kind, waker, wsys, _ in top5:
        if long_tot and wsys and wsys[0] not in WAIT and wsys[2] >= 0.1 * wsys[1]:
            stuck[(label(waker), wsys[0])] += min(until - since, wsys[1])
    if stuck:
        (wl, sn), ov = max(stuck.items(), key=lambda kv: kv[1])
        if ov >= 0.5 * top5_tot:
            out(f"THE WAKER WAS STUCK IN {sn} FOR MOST OF THE LONGEST BLOCKS "
                f"({wl}; {100 * ov / top5_tot:.0f}% of the top-{len(top5)} block time overlaps that call)")
    n_irq = sum(c for lb, c in cnt.items() if lb.startswith(('softirq', 'hardirq')))
    if len(bl) and n_irq >= 0.6 * len(bl):
        out(f"BLOCKED ON INTERRUPTS/SOFTIRQ (network or timer driven): {100 * n_irq / len(bl):.0f}% "
            f"of {len(bl)} wakeups come from interrupt context")


def main():
    if '--selftest' in sys.argv:
        return _selftest()
    a = sys.argv[1:]
    if len(a) < 2 or a[0].startswith('--'):
        raise SystemExit(__doc__)

    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default
    analyse(a[0], a[1], int(opt('--top', 15)), load_pidmap(opt('--pidmap', None)))


# ---- self-test ---------------------------------------------------------------------------
def _selftest():
    import os
    import tempfile
    from syscall_stall import _mk, _scenario_a, _sw

    def run(lines, victim):
        outl = []
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as tf:
            tf.write('\n'.join(lines) + '\n')
            p = tf.name
        try:
            analyse(p, victim, out=lambda *x: outl.append(' '.join(str(s) for s in x)))
        finally:
            os.unlink(p)
        return '\n'.join(outl)

    for ctx in (True, False, 'name'):
        r = run(_scenario_a(ctx), 'commsTx')
        assert 'victim: commsTx tid 7249 prio 120 (nice 0) pid 7087' in r, r
        assert 'BLOCKED MOSTLY ON spawnerThr tid 7231 prio 120 (nice 0) (100% of long-block time' in r, r
        assert 'THE WAKER WAS STUCK IN clone FOR MOST OF THE LONGEST BLOCKS' in r, r
        # the routine wakeups are interrupt-driven (true), the long blocks are spawnerThr (the
        # finding): both lines print, and the long-block one carries the verdict
        assert '1% of all blocked time' in r and 'INTERRUPTS/SOFTIRQ' in r, r
        assert 'clone for 52.9 ms (52.9 ms on-CPU+D)' in r, r
        assert run(_scenario_a(ctx), '7249').splitlines()[0] == r.splitlines()[0]
        # a timer-driven thread: 12 ms sleeps, every wakeup from softirq TIMER
        L = _mk(ctx)
        base = 12 * 3600 * SEC
        lines, t = [], base
        for _ in range(200):
            lines.append(L(t, 1, 'sched_switch', _sw(0, 'swapper/1', 20, 0, 600, 'tickThr'), 0, 0))
            lines.append(L(t + 100_000, 1, 'sched_switch', _sw(600, 'tickThr', 20, 1, 0, 'swapper/1'),
                           600, 600, 'tickThr'))
            lines.append(L(t + 12 * MS, 1, 'irq_softirq_entry', 'vec = 1', 0, 0))
            lines.append(L(t + 12 * MS + 1, 1, 'sched_waking',
                           'comm = "tickThr", tid = 600, prio = 20, target_cpu = 1', 0, 0))
            lines.append(L(t + 12 * MS + 2, 1, 'irq_softirq_exit', 'vec = 1', 0, 0))
            t += 12 * MS + 100_000
        r = run(lines, 'tickThr')
        assert 'BLOCKED ON INTERRUPTS/SOFTIRQ (network or timer driven): 100% of 200 wakeups' in r, r
        assert 'BLOCKED MOSTLY ON softirq TIMER (100%' in r, r
        assert 'NO LONG BLOCKS' not in r, r
        # a waker that is merely SLEEPING inside an ioctl (a driver's wait) is not "stuck":
        # appMain sleeps `nap` ms per cycle, hwPoll wakes it from inside a never-ending ioctl
        for nap, expect_long in ((5_700_000, False), (20 * MS, True)):
            lines, t = [], base
            lines.append(L(t, 1, 'sched_switch', _sw(0, 'swapper/1', 20, 0, 801, 'hwPoll'), 0, 0))
            lines.append(L(t + 10, 1, 'syscall_entry_ioctl', 'fd = 7, cmd = 3224433687, arg = 0', 801, 801, 'hwPoll'))
            lines.append(L(t + 20, 1, 'sched_switch', _sw(801, 'hwPoll', 20, 1, 0, 'swapper/1'), 801, 801, 'hwPoll'))
            for _ in range(200):
                lines.append(L(t + 100, 3, 'sched_switch', _sw(0, 'swapper/3', 20, 0, 800, 'appMain'), 0, 0))
                lines.append(L(t + 1 * MS, 3, 'sched_switch', _sw(800, 'appMain', 20, 1, 0, 'swapper/3'),
                               800, 800, 'appMain'))
                w = t + 1 * MS + nap
                lines.append(L(w - 20_000, 1, 'irq_softirq_entry', 'vec = 3', 0, 0))
                lines.append(L(w - 19_999, 1, 'sched_waking', 'comm = "hwPoll", tid = 801, prio = 20, target_cpu = 1', 0, 0))
                lines.append(L(w - 19_998, 1, 'irq_softirq_exit', 'vec = 3', 0, 0))
                lines.append(L(w - 10_000, 1, 'sched_switch', _sw(0, 'swapper/1', 20, 0, 801, 'hwPoll'), 0, 0))
                lines.append(L(w, 1, 'sched_waking', 'comm = "appMain", tid = 800, prio = 20, target_cpu = 3',
                               801, 801, 'hwPoll'))
                lines.append(L(w + 5_000, 1, 'sched_switch', _sw(801, 'hwPoll', 20, 1, 0, 'swapper/1'), 801, 801, 'hwPoll'))
                t = w + 100_000
            r = run(lines, 'appMain')
            assert 'STUCK' not in r, r
            assert 'BLOCKED MOSTLY ON hwPoll tid 801' in r, r
            assert ('NO LONG BLOCKS' not in r) == expect_long, r
        r = run(lines, 'nobody')
        assert "no thread named or numbered 'nobody'" in r, r
    print("wait_chain selftest OK")


if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
