#!/usr/bin/env python3
"""Per-service thread wait-attribution over an LTTng kernel trace (Babeltrace2).

The novel analytical core of the MVP: for a target service's threads, classify
wall-time in a window into on-CPU / runnable-wait / blocked-in-<syscall-family>,
so we can say *why* a service was slow (e.g. "89% blocked reading the DB socket")
rather than just *that* it was slow.

Threads are identified by **comm/procname** (e.g. catalogue's Go binary is "app"),
discovered dynamically from the trace — robust to Go/Java runtimes that recycle OS
threads, which a static `docker top` snapshot misses.

Method (per tid of the target comm):
  - sched_switch(next_tid=T)  -> T comes ON-CPU
  - sched_switch(prev_tid=T)  -> T goes OFF-CPU; sleep state => BLOCKED in its open
       syscall; runnable state => RUNNABLE(preempted)
  - sched_waking/wakeup(T)    -> T becomes RUNNABLE (waiting for a CPU)
  - syscall_entry_X/exit_X    -> track T's currently-open syscall (why it blocks)

Reads kernel CTF via `babeltrace2` (subprocess), trimmed to the window, event names
pre-filtered by grep (fast, and it *is* the skill's scoped read). Stdlib only.
"""
import argparse, glob, json, os, re, subprocess, datetime as dt

# service -> process comm. Several Go services share comm "app" (catalogue, payment,
# user), so comm alone is ambiguous — prefer TGID identity via the container's main
# PID (main_pid). comm is the fallback for aggressors with no docker-top snapshot.
SERVICE_COMM = {
    "catalogue": "app", "catalogue-db": "mysqld", "front-end": "node",
    "payment": "app", "user": "app", "toxiproxy": "toxiproxy",
    "noisy-neighbor": "stress-ng", "anomaly-cpu": "stress-ng",
}
# service -> docker container basename used in meta/top_<container>_1_*.txt
SERVICE_CONTAINER = {
    "catalogue": "docker-compose_catalogue", "catalogue-db": "docker-compose_catalogue-db",
    "front-end": "docker-compose_front-end", "payment": "docker-compose_payment",
    "orders": "docker-compose_orders", "user": "docker-compose_user",
    "carts": "docker-compose_carts",
}

def main_pid(meta_dir, container):
    """Container main process PID (== TGID of all its threads) from the docker-top
    start snapshot. Stable across the run; unique per container."""
    for pat in (f"top_{container}_1_start.txt", f"top_{container}_1_*.txt", f"top_*{container}*start*.txt"):
        for path in sorted(glob.glob(os.path.join(meta_dir, pat))):
            with open(path, encoding="utf-8", errors="replace") as f:
                hdr = f.readline().split()
                try: c = [h.upper() for h in hdr].index("PID")
                except ValueError: continue
                for line in f:
                    p = line.split()
                    if len(p) > c and p[c].isdigit(): return int(p[c])
    return None

_TS  = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
_EVT = re.compile(r"\] (?:\(\+[^)]*\) )?\S+ (\w+): \{ cpu_id")
_CTX = re.compile(r"pid = (\d+), tid = (\d+), procname = \"([^\"]*)\"")  # tgid, tid, comm
_SS  = re.compile(r'prev_comm = "([^"]*)", prev_tid = (\d+), prev_prio = -?\d+, prev_state = (\d+),.*?next_comm = "([^"]*)", next_tid = (\d+)')
_WK  = re.compile(r'comm = "([^"]*)", tid = (\d+)')

SLEEP_STATES = {1, 2, 258, 130, 66, 129}  # S/D + common composite sleep masks; 0 = R (runnable)
FAMILY = {
    "recvfrom":"blocked_read_net","recvmsg":"blocked_read_net","recv":"blocked_read_net",
    "read":"blocked_read_net","readv":"blocked_read_net","pread64":"blocked_read_net",
    "sendto":"blocked_write_net","sendmsg":"blocked_write_net","write":"blocked_write_net",
    "writev":"blocked_write_net","pwrite64":"blocked_write_net",
    "epoll_pwait":"idle_epoll","epoll_wait":"idle_epoll","poll":"idle_epoll","ppoll":"idle_epoll",
    "futex":"blocked_futex",
    "fsync":"blocked_disk","fdatasync":"blocked_disk",
    "nanosleep":"idle_sleep","clock_nanosleep":"idle_sleep",
}

def _ns(m): return ((int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)))*1_000_000_000)+int(m.group(4))
def _bt(ts): return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S.000000")

def attribute(kernel_dir, target_comm, begin_iso, end_iso, names, target_tgid=None):
    """Attribute a target's threads. Identity is by TGID (container main PID, unique
    and stable) when target_tgid is given — learned per-thread from the pid context —
    else by comm (for aggressors like stress-ng with no docker-top snapshot)."""
    bt = ["babeltrace2", kernel_dir, "--begin", _bt(begin_iso), "--end", _bt(end_iso)]
    p1 = subprocess.Popen(bt, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["grep","-E","|".join(names)], stdin=p1.stdout,
                          stdout=subprocess.PIPE, text=True, errors="replace")
    p1.stdout.close()
    st, blk, opsys, last, acc = {}, {}, {}, {}, {}
    tid2tgid = {}                      # learned from the pid context on every line
    matched_bytes = [0]
    def belongs(tid, comm):
        if target_tgid is not None: return tid2tgid.get(tid) == target_tgid
        return comm == target_comm
    def ensure(t):
        if t not in st: st[t], blk[t], opsys[t], last[t], acc[t] = "off", None, None, None, {}
    def add(t, cat, a, b):
        if a is not None and b is not None and b > a: acc[t][cat] = acc[t].get(cat,0)+(b-a)
    for line in p2.stdout:
        mt = _TS.match(line)
        if not mt: continue
        ts = _ns(mt)
        ctx = _CTX.search(line)                       # learn tid->tgid (container id)
        if ctx: tid2tgid[int(ctx.group(2))] = int(ctx.group(1))
        me = _EVT.search(line)
        if not me: continue
        ev = me.group(1)
        if ev == "sched_switch":
            m = _SS.search(line)
            if not m: continue
            pc, pt, pstate, nc, nt = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4), int(m.group(5))
            pb, nb = belongs(pt, pc), belongs(nt, nc)
            if pb or nb: matched_bytes[0] += len(line)
            if pb:
                ensure(pt)
                if st[pt] == "on": add(pt, "on_cpu", last[pt], ts)
                if pstate in SLEEP_STATES:
                    st[pt], blk[pt] = "blk", FAMILY.get(opsys[pt] or "", "blocked_other")
                else:
                    st[pt] = "run"
                last[pt] = ts
            if nb:
                ensure(nt)
                if st[nt] == "run": add(nt, "runnable_wait", last[nt], ts)
                elif st[nt] == "blk": add(nt, blk[nt] or "blocked_other", last[nt], ts)
                st[nt], last[nt] = "on", ts
        elif ev in ("sched_waking","sched_wakeup"):
            m = _WK.search(line)
            if not m or not belongs(int(m.group(2)), m.group(1)): continue
            matched_bytes[0] += len(line)
            t = int(m.group(2)); ensure(t)
            if st[t] == "blk": add(t, blk[t] or "blocked_other", last[t], ts)
            st[t], last[t] = "run", ts
        elif ev.startswith("syscall_entry_") or ev.startswith("syscall_exit_"):
            if not ctx or not belongs(int(ctx.group(2)), ctx.group(3)): continue
            matched_bytes[0] += len(line)
            t = int(ctx.group(2)); ensure(t)
            if ev.startswith("syscall_entry_"): opsys[t] = ev[len("syscall_entry_"):]
            elif opsys.get(t) == ev[len("syscall_exit_"):]: opsys[t] = None
    p2.wait(timeout=1800)
    total = {}
    for t in acc:
        for cat, v in acc[t].items(): total[cat] = total.get(cat,0)+v
    return total, len(acc), matched_bytes[0]

def summarize(total):
    # Rule-out buckets. For Go/Java runtimes the DB-wait is off-CPU I/O-readiness
    # parking (epoll/futex), NOT a blocked read() — so the decisive, robust claim
    # is the rule-out: low on_cpu => not compute-bound; low disk => not disk-bound;
    # high runnable_wait => CPU contention; high off_cpu_io_wait => external I/O /
    # dependency latency.
    g = lambda *ks: sum(total.get(k, 0) for k in ks)
    buckets = {
        "on_cpu": g("on_cpu"),
        "runnable_wait": g("runnable_wait"),
        "disk_wait": g("blocked_disk"),
        "off_cpu_io_wait": g("blocked_read_net","blocked_write_net","blocked_futex",
                             "idle_epoll","idle_sleep","blocked_other"),
    }
    denom = sum(buckets.values()) or 1
    pct = {k: round(100*v/denom, 1) for k, v in buckets.items()}
    # crude verdict hint the LLM can lean on (it still reasons over hypotheses)
    if pct["on_cpu"] >= 60: hint = "cpu_bound"
    elif pct["runnable_wait"] >= 30: hint = "cpu_contention (runnable but starved)"
    elif pct["disk_wait"] >= 30: hint = "disk_bound"
    elif pct["off_cpu_io_wait"] >= 60: hint = "external_io_or_dependency_wait"
    else: hint = "mixed"
    return {"rule_out_pct": pct, "verdict_hint": hint,
            "seconds": {k: round(v/1e9, 3) for k, v in buckets.items()},
            "family_seconds": {k: round(v/1e9, 3) for k, v in sorted(total.items(), key=lambda x:-x[1])}}

def _cap(begin, end, sec):
    if not sec: return end
    b = dt.datetime.strptime(begin,"%Y-%m-%dT%H:%M:%SZ"); e = dt.datetime.strptime(end,"%Y-%m-%dT%H:%M:%SZ")
    return min(e, b+dt.timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")

def attribute_run(run_dir, kernel_dir, service, names, max_seconds=0, comm=None, tgid=None):
    gt = json.load(open(os.path.join(run_dir,"ground_truth.json")))["fault"]
    comm = comm or SERVICE_COMM.get(service, service)
    if tgid is None:
        cont = SERVICE_CONTAINER.get(service)
        if cont: tgid = main_pid(os.path.join(run_dir, "meta"), cont)  # precise TGID identity
    begin = gt["injection_start_utc"]; end = _cap(begin, gt["injection_end_utc"], max_seconds)
    total, ntids, mbytes = attribute(kernel_dir, comm, begin, end, names, target_tgid=tgid)
    return {"service": service, "comm": comm, "tgid": tgid, "n_tids_seen": ntids,
            "window": [begin, end], "scoped_bytes": mbytes, **summarize(total), "raw_ns": total}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--service", default="catalogue")
    ap.add_argument("--comm", default=None, help="override process comm to match")
    ap.add_argument("--tgid", type=int, default=None, help="override target TGID (container main PID)")
    ap.add_argument("--names", default="sched_switch,sched_waking,sched_wakeup,syscall_entry_,syscall_exit_")
    ap.add_argument("--max-seconds", type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(attribute_run(a.run_dir, a.kernel, a.service, a.names.split(","), a.max_seconds, a.comm, a.tgid), indent=2))
