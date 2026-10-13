#!/usr/bin/env python3
"""Measure how much of an agent run is spent waiting on the LLM API.

Method (per run, from the kernel trace only):
  1. Find API sockets: fds the agent connect()ed to on port 443 (HTTPS).
     An fd is an API socket from that connect until the next close(fd).
  2. On those fds, pair syscall entry(fd) -> exit(ret) per thread to get
     outgoing writes and incoming reads (ret>0).
  3. A request is "in flight" from its first write on an API fd until the
     last streamed response read before the next request on that fd (the
     API streams tokens, so the model is working for the whole span).
     Union those intervals across all API fds = wall-clock time with an
     LLM request outstanding = model wait.
  4. Compare to subtree on-CPU time (local compute) and wall.

Reports model_wait / wall and model_wait / (wall - on_cpu). Validation:
model_wait must be <= (wall - on_cpu) + small slack.
"""
import gzip, json, re, sys
from pathlib import Path

TS = re.compile(r'^\[(\d\d):(\d\d):(\d\d)\.(\d{9})\]')
CTX = re.compile(r'pid = (\d+), tid = (\d+),')
EVT = re.compile(r'([a-z0-9_]+): \{ cpu_id')
FD = re.compile(r'\{ fd = (\d+)')
RET = re.compile(r'\{ ret = (-?\d+)')
DPORT = re.compile(r'dport = (\d+)')

LAT = Path(__file__).resolve().parents[1] / 'latency'
sys.path.insert(0, str(LAT / '1_svc_cpu_cap/agentic-os-noise/analysis'))
from analyze_run import analyze, ts_ns

IN_SYS = {'read', 'recvfrom', 'recvmsg', 'readv', 'recvmmsg'}
OUT_SYS = {'write', 'sendto', 'sendmsg', 'writev', 'sendmmsg'}


def union(intervals):
    if not intervals:
        return 0
    intervals.sort()
    total = 0
    cs, ce = intervals[0]
    for s, e in intervals[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            total += ce - cs
            cs, ce = s, e
    total += ce - cs
    return total


def measure(run_dir):
    run = Path(run_dir)
    api = {}                 # (pid, fd) -> True while an API socket is open
    pend = {}                # tid -> (syscall, fd) in flight
    # per API fd request state: start ts, last response-read ts, saw a read?
    st = {}                  # (pid,fd) -> [start_t, last_read_t or None]
    inflight = []            # list of [t_req_start, t_response_end] intervals
    t0 = t1 = None

    def close(key):
        s = st.pop(key, None)
        if s and s[1] is not None:
            inflight.append([s[0], s[1]])

    with gzip.open(run / 'trace.txt.gz', 'rt', errors='replace') as f:
        for line in f:
            m = TS.match(line)
            if not m:
                continue
            t = ts_ns(*m.groups())
            if t0 is None:
                t0 = t
            t1 = t
            ev = EVT.search(line)
            if not ev:
                continue
            name = ev.group(1)
            c = CTX.search(line)
            if not c:
                continue
            pid, tid = int(c.group(1)), int(c.group(2))

            if name == 'syscall_entry_connect':
                dp = DPORT.search(line); fdm = FD.search(line)
                if dp and fdm and dp.group(1) == '443':
                    api[(pid, int(fdm.group(1)))] = True
                continue
            if name == 'syscall_entry_close':
                fdm = FD.search(line)
                if fdm:
                    key = (pid, int(fdm.group(1)))
                    api.pop(key, None); close(key)
                continue
            if name.startswith('syscall_entry_'):
                s = name[len('syscall_entry_'):]
                if s in IN_SYS or s in OUT_SYS:
                    fdm = FD.search(line)
                    if fdm:
                        pend[tid] = (s, int(fdm.group(1)))
                continue
            if name.startswith('syscall_exit_'):
                s = name[len('syscall_exit_'):]
                p = pend.pop(tid, None)
                if not p or p[0] != s:
                    continue
                fd = p[1]
                key = (pid, fd)
                if key not in api:
                    continue
                if s in OUT_SYS:
                    cur = st.get(key)
                    if cur is None:
                        st[key] = [t, None]                # new request starts
                    elif cur[1] is not None:
                        close(key)                         # prior answered -> new req
                        st[key] = [t, None]
                    # else: more request bytes, same in-flight request
                elif s in IN_SYS:
                    rm = RET.search(line)
                    if rm and int(rm.group(1)) > 0 and key in st:
                        st[key][1] = t                     # extend response stream
                continue

    for key in list(st):         # close any requests still open at trace end
        close(key)
    wall = (t1 - t0) / 1e9 if t0 is not None else 0
    model_wait = union(inflight) / 1e9
    a = analyze(run)
    on_cpu = a['subtree_cpu_seconds']['on_cpu']
    anc = [json.loads(l) for l in (run / 'meta/clock_anchors.jsonl').read_text().splitlines()]
    wall_anchor = round(anc[-1]['realtime'] - anc[0]['realtime'], 2)
    return {
        'run': run.name,
        'wall_s': wall_anchor,
        'on_cpu_s': on_cpu,
        'model_wait_s': round(model_wait, 2),
        'n_requests': len(inflight),
        'model_pct_wall': round(100 * model_wait / wall_anchor, 1) if wall_anchor else 0,
        'oncpu_cpus': round(on_cpu, 2),   # CPU-seconds of local compute
    }


if __name__ == '__main__':
    for d in sys.argv[1:]:
        print(json.dumps(measure(d)))
