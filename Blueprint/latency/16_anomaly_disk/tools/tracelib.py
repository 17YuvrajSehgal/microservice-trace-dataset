#!/usr/bin/env python3
"""
tracelib.py - one parser for babeltrace2 text lines, shared by the scheduling tools.

Why it exists: the first tools were written against one trace shape - a microservice host
whose every event carries a `{ pid = P, tid = T, procname = "X", *_ns = N }` context block
and whose prev_state is a plain number. Real switch/router traces differ: there is no context
block at all, or a `{ vtid = T, vpid = P, procname = "X", prio = 20 }` one, and prev_state
prints as an enum `( "TASK_INTERRUPTIBLE" : container = 1 )`. The old regexes matched
nothing there and the tools printed EMPTY tables, silently, on every call. Everything here
accepts all three shapes.

Line shape (babeltrace2 --clock-gmt):
  [HH:MM:SS.nnnnnnnnn] (+d.ddd) <host> <event>: { cpu_id = N }, [{ context }, ]{ payload }

Facts the tools lean on:
  - LTTng prints prio as kernel prio - 100: 20 = nice 0 (kernel 120), 10 = nice -10,
    negative = real-time (rt_priority = -1 - p). prio_label() spells it out.
  - sched_switch prev_state: 0 = still runnable, 1 = S (sleeping), 2 = D (disk sleep);
    the 0x100 flag = preempted while runnable. state_kind() maps it to R/S/D/O.
  - On a context-less trace only sched_* events name a thread. Cpus() tracks who is on each
    CPU from sched_switch, so irq / softirq / syscall events can be charged to a thread.
  - Enum fields keep their number (the `container = N` part), never the label.

Self-test:  python3 tracelib.py --selftest
"""
import re
import sys
from collections import defaultdict

RE_HEAD = re.compile(r'^\[(\d\d):(\d\d):(\d\d)\.(\d{1,9})\] \(\+[^)]*\) \S+ (\S+): '
                     r'\{ cpu_id = (\d+) \},? ?(.*)$')
# key = "string" | ( "ENUM" : container = N ) | integer | 0xhex
RE_KV = re.compile(r'(\w+) = (?:"((?:[^"\\]|\\.)*)"|\([^()]*?container = (-?\d+)\s*\)'
                   r'|(0x[0-9a-fA-F]+|-?\d+))')      # hex before decimal, else 0x.. reads as 0

SOFTIRQ_NAMES = ['HI', 'TIMER', 'NET_TX', 'NET_RX', 'BLOCK', 'IRQ_POLL', 'TASKLET',
                 'SCHED', 'HRTIMER', 'RCU']

SEC = 1_000_000_000
MS = 1_000_000
# A CPU with a runnable thread waiting for it cannot be silent: if it shows no event at all for
# this long during a wait, the trace lost data there (snapshot buffers, discarded events) or the
# CPU itself was stalled. Measured on real switch traces: 1-9 s "waits" that were holes.
GAP_NS = 500 * MS


def parse_kv(s):
    """'{ a = 1, b = "x", c = ( "L" : container = 3 ) }' -> {'a': 1, 'b': 'x', 'c': 3}."""
    out = {}
    for k, st, en, num in RE_KV.findall(s):
        if st or (not en and not num):
            out[k] = st
        elif en:
            out[k] = int(en)
        else:
            out[k] = int(num, 0)
    return out


class Ev:
    """One parsed event line. Payload and context are parsed only when first read."""
    __slots__ = ('t', 'name', 'cpu', '_ctx_s', '_pay_s', '_ctx', '_pay')

    def __init__(self, t, name, cpu, ctx_s, pay_s):
        self.t, self.name, self.cpu = t, name, cpu
        self._ctx_s, self._pay_s = ctx_s, pay_s
        self._ctx = self._pay = None

    @property
    def fields(self):
        if self._pay is None:
            self._pay = parse_kv(self._pay_s)
        return self._pay

    @property
    def ctx(self):
        if self._ctx is None:
            self._ctx = parse_kv(self._ctx_s) if self._ctx_s else {}
        return self._ctx

    # the context block, when present, describes the thread that was running on the CPU
    def ctx_tid(self):
        c = self.ctx
        return c.get('tid', c.get('vtid'))

    def ctx_pid(self):
        c = self.ctx
        return c.get('pid', c.get('vpid'))

    def ctx_name(self):
        return self.ctx.get('procname')

    def has_ctx(self):
        return bool(self._ctx_s)

    def tid_or(self, cpus):
        """The thread this event belongs to: the context's tid when the block carries one, else
        whoever `cpus` says was on this CPU. A context block can exist without a tid (measured:
        a trace whose only context field was procname), so has_ctx() alone is not enough."""
        t = self.ctx_tid() if self._ctx_s else None
        return t if t is not None else cpus.tid_on(self.cpu)


def parse(line):
    """A babeltrace2 text line -> Ev, or None if it is not an event line."""
    m = RE_HEAD.match(line)
    if not m:
        return None
    h, mi, s, fr, name, cpu, rest = m.groups()
    t = ((int(h) * 60 + int(mi)) * 60 + int(s)) * SEC + int(fr.ljust(9, '0'))
    # Two blocks after cpu_id means the first is the context (it is flat; payloads can nest).
    j = rest.find('}, {')
    k = rest.find('{', 1)
    if j != -1 and (k == -1 or j < k):
        ctx_s, pay_s = rest[:j + 1], rest[j + 3:]
    else:
        ctx_s, pay_s = '', rest
    return Ev(t, name, int(cpu), ctx_s, pay_s)


def read_events(path, wanted=None):
    """Yield Ev for each line whose event name is in `wanted` (a set; None = all).
    The name check runs on the raw line before any parsing, so skipping is cheap."""
    with open(path, errors='replace') as f:
        for line in f:
            if wanted is not None:
                # event name sits between the host token and ': {'
                i = line.find(': { cpu_id')
                if i < 0:
                    continue
                j = line.rfind(' ', 0, i)
                if line[j + 1:i] not in wanted:
                    continue
            ev = parse(line)
            if ev is not None:
                yield ev


# ---- small helpers ----------------------------------------------------------------------
def prio_label(p):
    """LTTng prio -> readable. 20 -> '120 (nice 0)', 10 -> '110 (nice -10)', -64 -> 'RT 63'."""
    if p is None:
        return '?'
    k = p + 100
    if k < 100:
        return f"RT {99 - k}"
    return f"{k} (nice {p - 20})"


def is_rt(p):
    return p is not None and p < 0


def state_kind(code):
    """sched_switch prev_state -> 'R' (still wants the CPU), 'S', 'D' or 'O' (other)."""
    base = code & 0xFF
    if (code & 0x100) or base == 0:
        return 'R'
    return 'S' if base == 1 else 'D' if base == 2 else 'O'


def hms(ns):
    """ns since midnight -> 'HH:MM:SS.mmm'."""
    s, rem = divmod(int(ns), SEC)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{rem // MS:03d}"


def secs_of(hms_text):
    """'HH:MM:SS' or 'HH:MM:SS.fff' -> ns since midnight."""
    h, m, s = hms_text.split(':')
    return int(round((int(h) * 3600 + int(m) * 60 + float(s)) * SEC))


def pct(x, n):
    return 100.0 * x / n if n else 0.0


def load_pidmap(path):
    """pidmap.py output (tid<TAB>pid<TAB>ppid<TAB>name<TAB>type) -> {tid: (pid, ppid, name)}."""
    out = {}
    if not path:
        return out
    with open(path) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            p = line.rstrip('\n').split('\t')
            if len(p) >= 4 and p[0].isdigit():
                out[int(p[0])] = (int(p[1]), int(p[2]) if p[2].isdigit() else 0, p[3])
    return out


# ---- who is on each CPU ---------------------------------------------------------------
class Cpus:
    """Tracks the thread on each CPU (from sched_switch) and the irq / softirq nesting on it,
    so an event that names no thread can still be charged to one. context(cpu) answers
    ('thread', tid) | ('softirq', vec) | ('hardirq', irq)."""

    def __init__(self):
        self.cur = {}                    # cpu -> tid (0 = idle)
        self.comm = {}                   # tid -> name
        self.prio = {}                   # tid -> LTTng prio
        self.stack = defaultdict(list)   # cpu -> nesting of ('hardirq', n) / ('softirq', vec)

    def feed(self, ev):
        n = ev.name
        if n == 'sched_switch':
            f = ev.fields
            pt, nt = f.get('prev_tid'), f.get('next_tid')
            if pt is not None:
                self.comm[pt] = f.get('prev_comm', self.comm.get(pt))
                self.prio[pt] = f.get('prev_prio', self.prio.get(pt))
            if nt is not None:
                self.comm[nt] = f.get('next_comm', self.comm.get(nt))
                self.prio[nt] = f.get('next_prio', self.prio.get(nt))
                self.cur[ev.cpu] = nt
        elif n in ('sched_waking', 'sched_wakeup', 'sched_wakeup_new'):
            f = ev.fields
            t = f.get('tid')
            if t is not None:
                self.comm[t] = f.get('comm', self.comm.get(t))
                self.prio[t] = f.get('prio', self.prio.get(t))
        elif n == 'irq_handler_entry':
            self.stack[ev.cpu].append(('hardirq', ev.fields.get('irq')))
        elif n == 'irq_softirq_entry':
            self.stack[ev.cpu].append(('softirq', ev.fields.get('vec')))
        elif n in ('irq_handler_exit', 'irq_softirq_exit'):
            st = self.stack[ev.cpu]
            if st:
                st.pop()

    def context(self, cpu):
        st = self.stack.get(cpu)
        if st:
            return st[-1]
        return ('thread', self.cur.get(cpu, 0))

    def tid_on(self, cpu):
        return self.cur.get(cpu, 0)

    def name(self, tid):
        if tid == 0:
            return 'swapper (idle)'
        return self.comm.get(tid) or f"tid {tid}"

    def label(self, tid):
        return f"{self.name(tid)} tid {tid} prio {prio_label(self.prio.get(tid))}"


# ---- per-thread time budget ---------------------------------------------------------------
class Sched:
    """Per-thread state machine over sched_switch / sched_waking / sched_wakeup.

    kinds: run | rqP (switched out still runnable: preempted) | rqW (woken, waiting for a CPU)
           | S | D | O (other sleep)
    acc[tid][kind] = ns;  nwait[tid] = [>=1ms, >=10ms, >=50ms, max_ns] over rqP + rqW.
    on_close(tid, kind, since, until, cpu) fires for every closed interval when given.
    Learns tid -> comm / prio / pid / cpus-seen as it goes. pid comes from the context block,
    sched_process_fork, lttng_statedump_process_state or a pidmap - whichever the slice has.

    Trace holes: an interval that overlaps a silent period of its CPU (no event for GAP_NS) or of
    the whole trace is NOT counted and does not reach on_close; it goes to skipped[tid] = [n, ns]
    instead, and gaps / gap_cpu list the silent periods. skipped_note() says so in one line."""

    def __init__(self, on_close=None, pidmap=None):
        self.state = {}                                  # tid -> (kind, since, cpu)
        self.acc = defaultdict(lambda: defaultdict(int))
        self.nwait = defaultdict(lambda: [0, 0, 0, 0])
        self.comm, self.prio, self.pid = {}, {}, {}
        self.seen_cpu = defaultdict(set)                 # tid -> cpus it ran on
        self.cpu_tids = defaultdict(set)                 # cpu -> tids that ran on it
        self.nwake = defaultdict(int)                    # tid -> wakeups
        self.codes = defaultdict(int)                    # prev_state codes seen
        self.t_first = self.t_last = None
        self.on_close = on_close
        self.last_t = None                               # last event time, any cpu
        self.first_t = None                              # first event time, any cpu
        self.last_t_cpu = {}                             # cpu -> last event time there
        self.gaps = []                                   # (since, until): whole trace silent
        self.gap_cpu = defaultdict(list)                 # cpu -> [(since, until)] silent there
        self.skipped = defaultdict(lambda: [0, 0])       # tid -> [n, ns] intervals over a hole
        if pidmap:
            for tid, (pid, _ppid, name) in pidmap.items():
                self.pid[tid] = pid
                self.comm.setdefault(tid, name)

    def _over_gap(self, cpu, since, until):
        for lst in (self.gaps, self.gap_cpu.get(cpu, ())):
            for g0, g1 in lst:
                if g0 < until and g1 > since:
                    return True
        return False

    def _note_time(self, ev):
        """Record silent periods: per CPU and for the whole trace."""
        c, t = ev.cpu, ev.t
        lt = self.last_t_cpu.get(c)
        if lt is not None and t - lt >= GAP_NS:
            self.gap_cpu[c].append((lt, t))
        self.last_t_cpu[c] = t
        if self.last_t is not None and t - self.last_t >= GAP_NS:
            self.gaps.append((self.last_t, t))
        if self.last_t is None or t > self.last_t:
            self.last_t = t
        if self.first_t is None:
            self.first_t = t

    def _close(self, tid, t):
        st = self.state.get(tid)
        if st is None:
            return
        kind, since, cpu = st
        d = t - since
        if d < 0:
            return
        if d >= GAP_NS and self._over_gap(cpu, since, t):
            sk = self.skipped[tid]
            sk[0] += 1
            sk[1] += d
            return
        self.acc[tid][kind] += d
        if kind in ('rqP', 'rqW'):
            b = self.nwait[tid]
            if d >= 1 * MS:
                b[0] += 1
            if d >= 10 * MS:
                b[1] += 1
            if d >= 50 * MS:
                b[2] += 1
            if d > b[3]:
                b[3] = d
        if self.on_close is not None:
            self.on_close(tid, kind, since, t, cpu)

    def feed(self, ev):
        n = ev.name
        self._note_time(ev)
        if n == 'sched_switch':
            t = ev.t
            if self.t_first is None:
                self.t_first = t
            self.t_last = t
            f = ev.fields
            pt, nt = f.get('prev_tid'), f.get('next_tid')
            if pt is None or nt is None:
                return
            self.comm[pt] = f.get('prev_comm', self.comm.get(pt))
            self.prio[pt] = f.get('prev_prio', self.prio.get(pt))
            self.comm[nt] = f.get('next_comm', self.comm.get(nt))
            self.prio[nt] = f.get('next_prio', self.prio.get(nt))
            if ev.has_ctx():
                p = ev.ctx_pid()
                if p is not None and pt != 0:
                    self.pid[pt] = p
            if pt != 0:
                if self.state.get(pt, ('',))[0] == 'run':
                    self._close(pt, t)
                code = f.get('prev_state', 0)
                self.codes[code] += 1
                k = state_kind(code)
                self.state[pt] = ('rqP' if k == 'R' else k, t, ev.cpu)
            if nt != 0:
                if self.state.get(nt, ('',))[0] != 'run':
                    self._close(nt, t)
                self.state[nt] = ('run', t, ev.cpu)
                self.seen_cpu[nt].add(ev.cpu)
                self.cpu_tids[ev.cpu].add(nt)
        elif n in ('sched_waking', 'sched_wakeup', 'sched_wakeup_new'):
            f = ev.fields
            tid = f.get('tid')
            if tid is None or tid == 0:
                return
            self.comm[tid] = f.get('comm', self.comm.get(tid))
            self.prio[tid] = f.get('prio', self.prio.get(tid))
            st = self.state.get(tid)
            # waking and wakeup both fire for one wakeup; only the first one moves the state
            if st is None or st[0] in ('S', 'D', 'O'):
                self._close(tid, ev.t)
                self.state[tid] = ('rqW', ev.t, f.get('target_cpu', ev.cpu))
                self.nwake[tid] += 1
        elif n == 'sched_process_fork':
            f = ev.fields
            if 'parent_tid' in f:
                self.pid[f['parent_tid']] = f.get('parent_pid', f['parent_tid'])
                self.comm.setdefault(f['parent_tid'], f.get('parent_comm'))
            if 'child_tid' in f:
                self.pid[f['child_tid']] = f.get('child_pid', f['child_tid'])
                self.comm.setdefault(f['child_tid'], f.get('child_comm'))
        elif n == 'lttng_statedump_process_state':
            f = ev.fields
            if 'tid' in f:
                self.pid[f['tid']] = f.get('pid', f['tid'])
                self.comm.setdefault(f['tid'], f.get('name'))

    def finish(self, t_end=None):
        """Close every open interval at t_end (default: last switch seen)."""
        t = t_end if t_end is not None else self.t_last
        if t is None:
            return
        for tid in list(self.state):
            self._close(tid, t)
            self.state.pop(tid, None)

    def name(self, tid):
        return self.comm.get(tid) or f"tid {tid}"

    def span_s(self):
        """Seconds between the first and last event actually fed (any kind)."""
        if self.first_t is None or self.last_t is None:
            return 0.0
        return (self.last_t - self.first_t) / SEC

    def skipped_note(self):
        """One line about holes, or '' when the trace had none."""
        n = sum(v[0] for v in self.skipped.values())
        ns = sum(v[1] for v in self.skipped.values())
        if not n and not self.gaps and not self.gap_cpu:
            return ''
        per = ', '.join(f"cpu {c}: {len(g)}" for c, g in sorted(self.gap_cpu.items()))
        return (f"trace holes: {len(self.gaps)} whole-trace and per-CPU silent periods >= "
                f"{GAP_NS // MS} ms ({per or 'none per CPU'}); {n} intervals ({ns / SEC:.1f} s) "
                f"overlapped one and were NOT counted - lost trace data or a stalled CPU, not "
                f"scheduling latency")

    def pid_of(self, tid):
        """pid when the slice told us, else the tid itself (one thread = one row)."""
        return self.pid.get(tid, tid)

    def row(self, tid, secs):
        """Summary dict for one thread; averages are 'threads' (1.0 = the whole slice)."""
        a, b = self.acc[tid], self.nwait[tid]
        n = secs * SEC
        return {'tid': tid, 'name': self.name(tid), 'prio': self.prio.get(tid),
                'pid': self.pid.get(tid),
                'run': a['run'] / n, 'wait': (a['rqP'] + a['rqW']) / n,
                'preempt': a['rqP'] / n, 'wakewait': a['rqW'] / n,
                'S': a['S'] / n, 'D': a['D'] / n, 'O': a['O'] / n,
                'ge1ms': b[0], 'ge10ms': b[1], 'ge50ms': b[2], 'max_ms': b[3] / MS,
                'wakeups': self.nwake[tid], 'cpus': sorted(self.seen_cpu[tid])}

    def rows(self, secs):
        return [self.row(t, secs) for t in self.acc if t != 0]


def effective_secs(secs, sched):
    """The seconds to divide by. Snapshot-style traces hold events for only part of the span
    the slice was cut over (measured: 6.5 s of events inside a 69 s slice), which dilutes every
    per-second share. Returns (seconds, note); note is '' when the given value is fine."""
    span = sched.span_s()
    if span > 0 and span < 0.8 * secs:
        return span, (f"note: events cover only {span:.1f} s of the {secs:g} s slice "
                      f"(snapshot-style trace); shares below use {span:.1f} s")
    return secs, ''


def cpus_text(cpus):
    """[0, 1, 2, 3] -> '0-3'; [2] -> '2'; [0, 2] -> '0,2'."""
    if not cpus:
        return '-'
    cpus = sorted(cpus)
    if len(cpus) > 1 and cpus == list(range(cpus[0], cpus[-1] + 1)):
        return f"{cpus[0]}-{cpus[-1]}"
    return ','.join(str(c) for c in cpus)


# ---- self-test ---------------------------------------------------------------------------
def _selftest():
    # the three line shapes we meet
    sock = ('[03:17:26.282137741] (+0.000002893) host-a.internal sched_switch: { cpu_id = 0 }, '
            '{ pid = 600, tid = 699, procname = "java", cgroup_ns = 4026531835, pid_ns = 4026531836 }, '
            '{ prev_comm = "java", prev_tid = 699, prev_prio = 20, prev_state = 256, '
            'next_comm = "rcu_sched", next_tid = 16, next_prio = 20 }')
    wl = ('[21:13:28.027653772] (+0.000004213) 1-A-5 sched_switch: { cpu_id = 2 }, '
          '{ prev_comm = "commsTx", prev_tid = 7211, prev_prio = 20, '
          'prev_state = ( "TASK_INTERRUPTIBLE" : container = 1 ), next_comm = "baseThr", '
          'next_tid = 7238, next_prio = -64 }')
    ctm = ('[01:46:40.000000000] (+0.000000100) CM1 sched_switch: { cpu_id = 1 }, '
           '{ vtid = 0, vpid = 0, procname = "swapper/1", prio = 20 }, '
           '{ prev_comm = "swapper/1", prev_tid = 0, prev_prio = 20, prev_state = 0, '
           'next_comm = "ksoftirqd/1", next_tid = 17, next_prio = 20 }')
    nested = ('[01:46:40.000000000] (+0.000000100) CM1 net_dev_queue: { cpu_id = 1 }, '
              '{ skbaddr = 0xffff0000, len = 66, name = "eth5", network_header_type = '
              '( "_ipv4" : container = 1 ), network_header = { ipv4 = { version = 4, '
              'saddr = [ [0] = 10, [1] = 1 ] } } }')
    sysc = ('[19:42:41.612000000] (+0.000000100) 1-C-5 compat_syscall_entry_clone: { cpu_id = 2 }, '
            '{ clone_flags = 0x100011, newsp = 0, parent_tid = 0, child_tid = 0, tls = 0 }')
    e = parse(sock)
    assert e.name == 'sched_switch' and e.cpu == 0 and e.has_ctx()
    assert e.ctx_pid() == 600 and e.ctx_tid() == 699 and e.ctx_name() == 'java'
    assert e.fields['prev_state'] == 256 and e.fields['next_tid'] == 16
    e = parse(wl)
    assert not e.has_ctx() and e.fields['prev_state'] == 1, e.fields
    assert e.fields['next_prio'] == -64 and e.fields['prev_comm'] == 'commsTx'
    e = parse(ctm)
    assert e.has_ctx() and e.ctx_pid() == 0 and e.ctx_tid() == 0 and e.ctx_name() == 'swapper/1'
    assert e.fields['next_tid'] == 17 and e.fields['prev_state'] == 0
    e = parse(nested)
    assert not e.has_ctx() and e.fields['name'] == 'eth5' and e.fields['network_header_type'] == 1
    assert e.fields['version'] == 4            # nested fields are reachable too
    e = parse(sysc)
    assert e.fields['clone_flags'] == 0x100011 and e.name == 'compat_syscall_entry_clone'
    assert prio_label(20) == '120 (nice 0)' and prio_label(10) == '110 (nice -10)'
    assert prio_label(-64) == 'RT 63' and prio_label(39) == '139 (nice 19)'
    assert state_kind(0) == 'R' and state_kind(256) == 'R' and state_kind(257) == 'R'
    assert state_kind(1) == 'S' and state_kind(2) == 'D' and state_kind(128) == 'O'
    assert hms(secs_of('21:13:28') + 5 * MS) == '21:13:28.005'
    assert cpus_text([0, 1, 2, 3]) == '0-3' and cpus_text([2]) == '2' and cpus_text([0, 2]) == '0,2'

    # scheduler state machine: tid 7 woken at 0, on CPU at 5 ms, preempted at 8 ms (code 256),
    # back at 20 ms, sleeps at 25 ms (enum form), woken at 40 ms, on at 41 ms.
    def L(ms, ev, pay):
        return f'[00:00:00.{ms * MS:09d}] (+0.000000001) h {ev}: {{ cpu_id = 0 }}, {{ {pay} }}'
    lines = [
        L(0, 'sched_waking', 'comm = "v", tid = 7, prio = 20, target_cpu = 0'),
        L(0, 'sched_wakeup', 'comm = "v", tid = 7, prio = 20, target_cpu = 0'),
        L(5, 'sched_switch', 'prev_comm = "a", prev_tid = 3, prev_prio = 20, prev_state = 0, '
                             'next_comm = "v", next_tid = 7, next_prio = 20'),
        L(8, 'sched_switch', 'prev_comm = "v", prev_tid = 7, prev_prio = 20, prev_state = 256, '
                             'next_comm = "a", next_tid = 3, next_prio = 20'),
        L(20, 'sched_switch', 'prev_comm = "a", prev_tid = 3, prev_prio = 20, prev_state = 1, '
                              'next_comm = "v", next_tid = 7, next_prio = 20'),
        L(25, 'sched_switch', 'prev_comm = "v", prev_tid = 7, prev_prio = 20, '
                              'prev_state = ( "TASK_INTERRUPTIBLE" : container = 1 ), '
                              'next_comm = "swapper/0", next_tid = 0, next_prio = 20'),
        L(40, 'sched_wakeup', 'comm = "v", tid = 7, prio = 20, target_cpu = 0'),
        L(41, 'sched_switch', 'prev_comm = "swapper/0", prev_tid = 0, prev_prio = 20, '
                              'prev_state = 0, next_comm = "v", next_tid = 7, next_prio = 20'),
    ]
    closed = []
    sc = Sched(on_close=lambda *a: closed.append(a))
    cp = Cpus()
    for ln in lines:
        ev = parse(ln)
        assert ev is not None, ln
        sc.feed(ev)
        cp.feed(ev)
    sc.finish(secs_of('00:00:00') + 50 * MS)
    a = sc.acc[7]
    assert a['rqW'] == 5 * MS + 1 * MS, dict(a)          # 0->5 and 40->41
    assert a['run'] == 3 * MS + 5 * MS + 9 * MS, dict(a)  # 5-8, 20-25, 41-50
    assert a['rqP'] == 12 * MS, dict(a)                   # 8->20
    assert a['S'] == 15 * MS, dict(a)                     # 25->40
    assert sc.nwait[7][3] == 12 * MS and sc.nwait[7][1] == 1 and sc.nwake[7] == 2
    assert sc.acc[3]['S'] > 0 and sc.name(7) == 'v' and sc.seen_cpu[7] == {0}
    kinds = [c[1] for c in closed if c[0] == 7]
    assert kinds == ['rqW', 'run', 'rqP', 'run', 'S', 'rqW', 'run'], kinds
    assert cp.tid_on(0) == 7 and cp.name(7) == 'v' and cp.context(0) == ('thread', 7)
    cp.feed(parse(L(42, 'irq_softirq_entry', 'vec = 3')))
    assert cp.context(0) == ('softirq', 3)
    cp.feed(parse(L(42, 'irq_handler_entry', 'irq = 27, name = "eth5"')))
    assert cp.context(0) == ('hardirq', 27)
    cp.feed(parse(L(43, 'irq_handler_exit', 'irq = 27, ret = 1')))
    cp.feed(parse(L(43, 'irq_softirq_exit', 'vec = 3')))
    assert cp.context(0) == ('thread', 7)
    # trace holes: tid 8 woken at 100 ms for cpu 1, nothing at all happens on cpu 1 until it
    # switches in at 1300 ms -> that 1.2 s is a hole, not a wait; a normal 3 ms wait still counts
    def L1(ms, ev, pay):
        s, rem = divmod(ms * MS, SEC)
        return f'[00:00:{s:02d}.{rem:09d}] (+0.000000001) h {ev}: {{ cpu_id = 1 }}, {{ {pay} }}'
    hole = [
        L1(100, 'sched_waking', 'comm = "w", tid = 8, prio = 20, target_cpu = 1'),
        L1(1300, 'sched_switch', 'prev_comm = "swapper/1", prev_tid = 0, prev_prio = 20, '
                                 'prev_state = 0, next_comm = "w", next_tid = 8, next_prio = 20'),
        L1(1310, 'sched_switch', 'prev_comm = "w", prev_tid = 8, prev_prio = 20, prev_state = 1, '
                                 'next_comm = "swapper/1", next_tid = 0, next_prio = 20'),
        L1(1400, 'sched_waking', 'comm = "w", tid = 8, prio = 20, target_cpu = 1'),
        L1(1403, 'sched_switch', 'prev_comm = "swapper/1", prev_tid = 0, prev_prio = 20, '
                                 'prev_state = 0, next_comm = "w", next_tid = 8, next_prio = 20'),
    ]
    sh = Sched()
    for ln in hole:
        sh.feed(parse(ln))
    sh.finish()
    assert sh.gap_cpu[1] == [(100 * MS, 1300 * MS)] and sh.gaps == [(100 * MS, 1300 * MS)]
    assert sh.skipped[8] == [1, 1200 * MS] and sh.acc[8]['rqW'] == 3 * MS, (dict(sh.skipped), dict(sh.acc[8]))
    assert sh.nwait[8][3] == 3 * MS and 'NOT counted' in sh.skipped_note()
    assert sc.skipped_note() == ''
    s_eff, note = effective_secs(69, sh)
    assert abs(s_eff - 1.303) < 0.01 and 'snapshot' in note, (s_eff, note)
    assert effective_secs(1.4, sh) == (1.4, '')
    # attribution: ctx tid when there is one; the CPU's occupant otherwise (even with a
    # procname-only context block)
    cpz = Cpus()
    cpz.feed(parse(L(1, 'sched_switch', 'prev_comm = "a", prev_tid = 3, prev_prio = 20, '
                                        'prev_state = 0, next_comm = "v", next_tid = 7, next_prio = 20')))
    only_name = ('[00:00:00.002000000] (+0.000000001) h compat_syscall_entry_ioctl: { cpu_id = 0 }, '
                 '{ procname = "v" }, { fd = 5, cmd = 1, arg = 2 }')
    assert parse(only_name).has_ctx() and parse(only_name).ctx_tid() is None
    assert parse(only_name).tid_or(cpz) == 7 and parse(sock).tid_or(cpz) == 699
    assert parse(sysc).tid_or(cpz) == 0 and parse(sysc).fields['clone_flags'] == 0x100011
    # read_events name filter
    import tempfile, os
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as tf:
        tf.write('\n'.join(lines + [sock, wl, 'garbage line']) + '\n')
        p = tf.name
    try:
        got = [e.name for e in read_events(p, {'sched_switch'})]
        assert got == ['sched_switch'] * 7, got
        assert sum(1 for _ in read_events(p)) == len(lines) + 2
    finally:
        os.unlink(p)
    print("tracelib selftest OK")


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        _selftest()
    else:
        print(__doc__)
