#!/usr/bin/env python3
"""Time-budget analysis for one agentic OS-noise run.

Answers: where did the agent's time go - on-CPU (local compute),
runnable-but-not-running (CPU noise: throttled / waiting for a core), or
off-CPU blocked (waiting on the LLM API, I/O, locks)?

Input: a run dir with trace.txt.gz (babeltrace2 text dump) and
meta/{root.pid, cpu.stat.before, cpu.stat.after, clock_anchors.jsonl}.

Method: build the agent process subtree from root.pid via
sched_process_fork, then run a per-thread (tid) state machine over
sched_switch / sched_wakeup. Off-CPU time is attributed to whichever
syscall the thread was in when it blocked.

Validation: summed on-CPU should ~= cpu.stat usage_usec; computed
throttle/runnable-wait should be >= cpu.stat throttled_usec. Printed so a
bad parse is obvious rather than silent.
"""
import gzip, json, re, statistics, sys
from collections import defaultdict
from pathlib import Path

TS = re.compile(r'^\[(\d\d):(\d\d):(\d\d)\.(\d{9})\]')
CTX = re.compile(r'pid = (\d+), tid = (\d+), procname = "([^"]*)"')
SW = re.compile(r'prev_tid = (\d+), prev_prio = \d+, prev_state = (\d+), '
                r'next_comm = "[^"]*", next_tid = (\d+)')
WAKE = re.compile(r'\{ comm = "[^"]*", tid = (\d+),')
FORK = re.compile(r'parent_pid = (\d+),.*child_pid = (\d+)')
EVT = re.compile(r'([a-z0-9_]+): \{ cpu_id')

# off-CPU syscall -> bucket. node's event loop lives in epoll_wait, so that
# bucket is "waiting for any fd incl. the LLM socket"; see LLM-wait caveat.
SYSCALL_BUCKET = {
    'epoll_wait': 'wait_eventloop', 'epoll_pwait': 'wait_eventloop',
    'epoll_pwait2': 'wait_eventloop',
    'poll': 'wait_eventloop', 'ppoll': 'wait_eventloop', 'select': 'wait_eventloop',
    'pselect6': 'wait_eventloop',
    'futex': 'wait_lock',
    'read': 'wait_io', 'recvmsg': 'wait_io', 'recvfrom': 'wait_io',
    'write': 'wait_io', 'sendto': 'wait_io', 'sendmsg': 'wait_io',
    'wait4': 'wait_child', 'waitid': 'wait_child',
    'nanosleep': 'wait_sleep', 'clock_nanosleep': 'wait_sleep',
}


def ts_ns(h, m, s, frac):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1_000_000_000 + int(frac)


def load_lines(path):
    with gzip.open(path, 'rt', errors='replace') as f:
        for line in f:
            yield line


def read_stat(p):
    d = {}
    for line in Path(p).read_text().splitlines():
        k, _, v = line.partition(' ')
        d[k] = int(v)
    return d


def read_kv(p):
    """Parse a cgroup key-value file (memory.stat/events); {} if absent."""
    f = Path(p)
    if not f.exists():
        return {}
    d = {}
    for line in f.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip('-').isdigit():
            d[parts[0]] = int(parts[1])
    return d


def analyze(run_dir):
    run = Path(run_dir)
    root_pid = int((run / 'meta/root.pid').read_text().split()[0])
    before = read_stat(run / 'meta/cpu.stat.before')
    after = read_stat(run / 'meta/cpu.stat.after')
    anchors = [json.loads(l) for l in (run / 'meta/clock_anchors.jsonl').read_text().splitlines()]
    wall = anchors[-1]['realtime'] - anchors[0]['realtime']

    subtree = {root_pid}          # process pids in the agent subtree
    tid2pid = {}                  # tid -> pid (learned from context)
    cur_syscall = {}              # tid -> syscall name it's currently inside
    state = {}                    # tid -> (kind, since_ns): RUN / RDY / BLK
    acc = defaultdict(lambda: defaultdict(int))   # pid -> kind -> ns
    blk = defaultdict(lambda: defaultdict(int))   # pid -> bucket -> ns (off-cpu)
    tacc = defaultdict(lambda: defaultdict(int))  # tid -> kind/bucket -> ns (for main-thread view)
    claude_main = None            # tid of the first claude main thread (pid==tid)
    names = {}
    tname = {}                    # tid -> procname (thread-level)
    w_first, w_last = {}, {}      # worker.py tids -> first/last event ts (phase window)
    lat = {'ge_1ms': 0, 'ge_10ms': 0, 'ge_50ms': 0, 'max_ns': 0}  # RDY durations, subtree
    active = set()                # subtree tids currently RUN or RDY
    max_active = [0]
    reclaim_start = {}            # tid -> ts of mm_vmscan reclaim_begin
    reclaim_ns = defaultdict(int) # tid -> total direct/memcg reclaim stall
    block_reads = [0]             # block_rq read completions during tt* phase
    last_t = [0]

    def close(tid, t):
        st = state.get(tid)
        if not st:
            return
        kind, since = st
        d = t - since
        pid = tid2pid.get(tid)
        bucket = SYSCALL_BUCKET.get(cur_syscall.get(tid), 'wait_other') if kind == 'BLK' else None
        if pid in subtree:
            acc[pid][kind] += d
            if bucket:
                blk[pid][bucket] += d
            if kind == 'RDY':     # scheduling-latency tail (contention signal)
                if d >= 1_000_000:  lat['ge_1ms'] += 1
                if d >= 10_000_000: lat['ge_10ms'] += 1
                if d >= 50_000_000: lat['ge_50ms'] += 1
                if d > lat['max_ns']: lat['max_ns'] = d
        key = bucket if kind == 'BLK' else kind
        tacc[tid][key] += d

    def set_state(tid, kind, t):
        close(tid, t)
        state[tid] = (kind, t)
        if tid2pid.get(tid) in subtree and kind in ('RUN', 'RDY'):
            active.add(tid)
            if len(active) > max_active[0]:
                max_active[0] = len(active)
        else:
            active.discard(tid)

    for line in load_lines(run / 'trace.txt.gz'):
        m = TS.match(line)
        if not m:
            continue
        t = ts_ns(*m.groups())
        last_t[0] = t

        c = CTX.search(line)
        if c:
            pid, tid, pname = int(c.group(1)), int(c.group(2)), c.group(3)
            tid2pid[tid] = pid
            names[pid] = pname
            tname[tid] = pname
            if pname.startswith('tt'):      # ttworker (t4) / ttmem (t6)
                if tid not in w_first:
                    w_first[tid] = t
                w_last[tid] = t
            if claude_main is None and pname == 'claude' and pid == tid and pid in subtree:
                claude_main = tid

        ev = EVT.search(line)
        evname = ev.group(1) if ev else ''

        # memory reclaim stalls (problem #3): bracket per task
        if 'reclaim_begin' in evname:
            if c:
                reclaim_start[int(c.group(2))] = t
            continue
        if 'reclaim_end' in evname:
            if c:
                tid = int(c.group(2))
                st = reclaim_start.pop(tid, None)
                if st is not None and tid2pid.get(tid) in subtree:
                    reclaim_ns[tid] += t - st
            continue
        if evname == 'block_rq_complete':
            block_reads[0] += 1        # block I/O completions (refault I/O proxy)

        if evname.startswith('syscall_entry_'):
            tid = int(c.group(2)) if c else None
            if tid is not None:
                cur_syscall[tid] = evname[len('syscall_entry_'):]
            continue
        if evname.startswith('syscall_exit_'):
            tid = int(c.group(2)) if c else None
            if tid is not None:
                cur_syscall.pop(tid, None)
            continue

        if evname == 'sched_process_fork':
            f = FORK.search(line)
            if f and int(f.group(1)) in subtree:
                subtree.add(int(f.group(2)))
            continue

        if evname == 'sched_switch':
            s = SW.search(line)
            if not s:
                continue
            prev_tid, prev_state, next_tid = int(s.group(1)), int(s.group(2)), int(s.group(3))
            # prev_state: 0 (TASK_RUNNING) or the 0x100 flag (TASK_REPORT_MAX,
            # "preempted while runnable", seen as 256 on kernel 7.0.0-gcp) both
            # mean the thread still wants a core -> RDY. Any other nonzero bit is
            # a real off-cpu sleep/dead state -> BLK. Before the 0x100 case was
            # added, CFS-throttle preemptions (256) were misfiled as BLK and the
            # runnable-wait / scheduling-latency tail was under-counted.
            runnable = prev_state == 0 or (prev_state & 0x100)
            set_state(prev_tid, 'RDY' if runnable else 'BLK', t)
            set_state(next_tid, 'RUN', t)
            continue

        if evname == 'sched_wakeup':
            w = WAKE.search(line)
            if w:
                tid = int(w.group(1))
                st = state.get(tid)
                if not st or st[0] == 'BLK':
                    set_state(tid, 'RDY', t)   # woken, now waiting for a core
            continue

    # close every still-open interval at trace end so no time is dropped
    for tid in list(state):
        close(tid, last_t[0])

    # --- aggregate over the subtree ---
    on_cpu = sum(acc[p]['RUN'] for p in subtree)
    runnable = sum(acc[p]['RDY'] for p in subtree)
    blocked = sum(acc[p]['BLK'] for p in subtree)
    buckets = defaultdict(int)
    for p in subtree:
        for b, v in blk[p].items():
            buckets[b] += v

    ns = 1e9
    # workers (t4_parallel): per-worker budgets + parallel-phase window
    worker_tids = [tt for tt, nm in tname.items() if tname[tt].startswith('tt')]
    workers = None
    if worker_tids:
        wrun = [tacc[tt].get('RUN', 0) for tt in worker_tids]
        wrdy = [tacc[tt].get('RDY', 0) for tt in worker_tids]
        workers = {
            'n': len(worker_tids),
            'phase_wall_s': round((max(w_last.values()) - min(w_first.values())) / ns, 2),
            'worker_on_cpu_s_med': round(statistics.median(wrun) / ns, 2),
            'worker_runnable_s_med': round(statistics.median(wrdy) / ns, 2),
            'worker_runnable_s_max': round(max(wrdy) / ns, 2),
        }

    # memory (problem #3): reclaim stall from the trace + cgroup ground truth
    ms_b = read_kv(run / 'meta/memory.stat.before')
    ms_a = read_kv(run / 'meta/memory.stat.after')
    me_b = read_kv(run / 'meta/memory.events.before')
    me_a = read_kv(run / 'meta/memory.events.after')
    peak = read_kv(run / 'meta/memory.peak')  # single-value file -> {} ; handled below
    peak_bytes = None
    pf = run / 'meta/memory.peak'
    if pf.exists() and pf.read_text().strip().isdigit():
        peak_bytes = int(pf.read_text().strip())
    # io (problem #4): cgroup io.stat delta (sum across devices)
    def io_sum(p, key):
        f = Path(p)
        if not f.exists():
            return 0
        total = 0
        for line in f.read_text().splitlines():
            for tok in line.split():
                if tok.startswith(key + '='):
                    total += int(tok.split('=')[1])
        return total
    io = None
    if (run / 'meta/io.stat.after').exists():
        io = {k: io_sum(run / 'meta/io.stat.after', k) - io_sum(run / 'meta/io.stat.before', k)
              for k in ('rbytes', 'rios', 'wbytes')}

    mem = None
    if ms_a or me_a:
        def d(a, b, k):
            return a.get(k, 0) - b.get(k, 0)
        mem = {
            'reclaim_stall_s': round(sum(reclaim_ns.values()) / ns, 2),
            'block_io_completions': block_reads[0],
            'peak_bytes': peak_bytes,
            'stat_delta': {k: d(ms_a, ms_b, k) for k in
                           ('workingset_refault', 'workingset_refault_file',
                            'pgscan', 'pgsteal', 'pgmajfault') if k in ms_a},
            'events': {k: me_a.get(k, 0) for k in
                       ('high', 'max', 'oom', 'oom_kill') if k in me_a},
        }

    # main-thread wall budget (sums to ~wall): the agent's-eye view, free of
    # the parallel-threads inflation that makes the subtree 'blocked' sum
    # exceed wall.
    mt = {k: round(v / ns, 2) for k, v in sorted(tacc.get(claude_main, {}).items(),
                                                 key=lambda kv: -kv[1])}
    return {
        'run': run.name,
        'wall_s': round(wall, 2),
        'cpu_stat': {
            'usage_s': round((after['usage_usec'] - before['usage_usec']) / 1e6, 2),
            'throttled_s': round((after['throttled_usec'] - before['throttled_usec']) / 1e6, 2),
            'nr_throttled': after['nr_throttled'] - before['nr_throttled'],
        },
        'subtree_pids': len(subtree),
        # resource-accurate (CPU state-seconds summed across all subtree threads)
        'subtree_cpu_seconds': {
            'on_cpu': round(on_cpu / ns, 2),
            'runnable_wait': round(runnable / ns, 2),
        },
        # agent main thread (claude), wall-time budget - should sum to ~wall_s
        'main_thread_wall_s': mt,
        'main_thread_sum_s': round(sum(mt.values()), 2),
        'workers': workers,
        'sched_latency': {'ge_1ms': lat['ge_1ms'], 'ge_10ms': lat['ge_10ms'],
                          'ge_50ms': lat['ge_50ms'],
                          'max_ms': round(lat['max_ns'] / 1e6, 1)},
        'max_concurrent_active': max_active[0],
        'memory': mem,
        'io': io,
        'validation': {
            'on_cpu_vs_cpustat_usage': f"{on_cpu/ns:.2f} vs {(after['usage_usec']-before['usage_usec'])/1e6:.2f}",
            'runnable_vs_cpustat_throttled': f"{runnable/ns:.2f} vs {(after['throttled_usec']-before['throttled_usec'])/1e6:.2f}",
        },
    }


if __name__ == '__main__':
    for d in sys.argv[1:]:
        print(json.dumps(analyze(d), indent=2))
