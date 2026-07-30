#!/usr/bin/env python3
"""Per-service thread wait-attribution over an LTTng kernel trace (Babeltrace2).

The novel analytical core of the MVP: for a target service's threads, classify
wall-time in a window into on-CPU / runnable-wait / blocked-in-<syscall-family>,
so we can say *why* a service was slow (e.g. "89% blocked reading the DB socket")
rather than just *that* it was slow.

Method (per tid):
  - sched_switch(next_tid=T)  -> T comes ON-CPU
  - sched_switch(prev_tid=T)  -> T goes OFF-CPU; if prev_state is a sleep state,
       T is BLOCKED in whatever syscall it currently has open; else RUNNABLE(preempted)
  - sched_waking/sched_wakeup(T) -> T becomes RUNNABLE (waiting for a CPU)
  - syscall_entry_X / syscall_exit_X (ctx tid=T) -> track T's currently-open syscall
Blocked time is attributed to the open syscall at switch-out, bucketed into families.

Reads the kernel CTF via `babeltrace2` (subprocess), trimmed to the window and
pre-filtered by event name with grep (fast, and it *is* the skill's scoped read).
Stdlib only. Run standalone to print the breakdown; import `attribute_run` elsewhere.
"""
import argparse, json, os, re, subprocess, sys, glob, datetime as dt

UTC = dt.timezone.utc

# ---- babeltrace2 line parsing -------------------------------------------------
# [HH:MM:SS.nnnnnnnnn] (+d) <host> <event>: { cpu_id = N }, { pid=..,tid=..,procname=".." }, { <args> }
_TS   = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
_EVT  = re.compile(r"\] (?:\(\+[^)]*\) )?\S+ (\w+): \{ cpu_id")
_CTX  = re.compile(r"procname = \"([^\"]*)\" \}")
_SS   = re.compile(r"prev_tid = (\d+),.*?prev_state = (\d+),.*?next_tid = (\d+)")
_WAKE = re.compile(r"\btid = (\d+)")

SLEEP_STATES = {1, 2, 258, 130, 66}  # S/D and common composite sleep masks; 0/R = runnable

# syscall family buckets (from the syscall name after syscall_entry_/exit_)
FAMILY = {
    "recvfrom":"blocked_read_net","recvmsg":"blocked_read_net","recv":"blocked_read_net",
    "read":"blocked_read_net","readv":"blocked_read_net","pread64":"blocked_read_net",
    "sendto":"blocked_write_net","sendmsg":"blocked_write_net","write":"blocked_write_net",
    "writev":"blocked_write_net","pwrite64":"blocked_write_net",
    "epoll_pwait":"idle_epoll","epoll_wait":"idle_epoll","poll":"idle_epoll","ppoll":"idle_epoll",
    "futex":"blocked_futex",
    "fsync":"blocked_disk","fdatasync":"blocked_disk","sync":"blocked_disk",
    "nanosleep":"idle_sleep","clock_nanosleep":"idle_sleep",
}

def _ns_of_day(m):
    h, mi, s, ns = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return ((h*3600 + mi*60 + s) * 1_000_000_000) + ns

def _iso_to_bt(ts):  # "2026-07-28T06:25:04Z" -> "2026-07-28 06:25:04.000000"
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S.000000")

# ---- meta: service -> tids ----------------------------------------------------
def service_tids(meta_dir, service, prefix="docker-compose"):
    tids = set()
    pats = glob.glob(os.path.join(meta_dir, f"top_{prefix}_{service}_1_*.txt"))
    for path in pats:
        with open(path, encoding="utf-8", errors="replace") as f:
            hdr = f.readline().split()
            try: c = [h.upper() for h in hdr].index("TID")
            except ValueError: continue
            for line in f:
                p = line.split()
                if len(p) > c and p[c].isdigit(): tids.add(int(p[c]))
    return tids

# ---- the attribution ----------------------------------------------------------
def attribute(kernel_dir, tids, begin_iso, end_iso, names):
    tids = set(tids)
    bt = ["babeltrace2", kernel_dir, "--begin", _iso_to_bt(begin_iso), "--end", _iso_to_bt(end_iso)]
    grep = ["grep", "-E", "|".join(names)]
    p1 = subprocess.Popen(bt, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(grep, stdin=p1.stdout, stdout=subprocess.PIPE, text=True, errors="replace")
    p1.stdout.close()

    st = {t: "off" for t in tids}          # off | on | run | blk
    blk_sys = {t: None for t in tids}       # syscall family blocking t
    open_sys = {t: None for t in tids}      # currently open syscall name for t
    last = {t: None for t in tids}
    acc = {t: {} for t in tids}             # t -> {category: ns}
    span = [None, None]

    def add(t, cat, a, b):
        if a is None or b is None or b <= a: return
        acc[t][cat] = acc[t].get(cat, 0) + (b - a)

    for line in p2.stdout:
        mt = _TS.match(line)
        if not mt: continue
        ts = _ns_of_day(mt)
        if span[0] is None: span[0] = ts
        span[1] = ts
        me = _EVT.search(line)
        if not me: continue
        ev = me.group(1)

        if ev == "sched_switch":
            m = _SS.search(line)
            if not m: continue
            pt, pstate, nt = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if pt in tids:  # going OFF-CPU
                add(pt, "on_cpu", last[pt], ts) if st[pt] == "on" else None
                if pstate in SLEEP_STATES:
                    fam = FAMILY.get(open_sys[pt] or "", "blocked_other")
                    st[pt], blk_sys[pt] = "blk", fam
                else:
                    st[pt] = "run"
                last[pt] = ts
            if nt in tids:  # coming ON-CPU
                if st[nt] == "run": add(nt, "runnable_wait", last[nt], ts)
                elif st[nt] == "blk": add(nt, blk_sys[nt] or "blocked_other", last[nt], ts)
                st[nt], last[nt] = "on", ts
        elif ev in ("sched_waking", "sched_wakeup"):
            m = _WAKE.search(line)
            if not m: continue
            t = int(m.group(1))
            if t in tids and st[t] == "blk":
                add(t, blk_sys[t] or "blocked_other", last[t], ts)
                st[t], last[t] = "run", ts
        elif ev.startswith("syscall_entry_"):
            mc = _CTX.search(line)  # ctx tid is the running thread; use payload-free ctx
            # context tid is embedded as tid = T in the pid/tid/procname block:
            mtid = re.search(r"pid = \d+, tid = (\d+), procname", line)
            if mtid:
                t = int(mtid.group(1))
                if t in tids: open_sys[t] = ev[len("syscall_entry_"):]
        elif ev.startswith("syscall_exit_"):
            mtid = re.search(r"pid = \d+, tid = (\d+), procname", line)
            if mtid:
                t = int(mtid.group(1))
                if t in tids and open_sys[t] == ev[len("syscall_exit_"):]:
                    open_sys[t] = None

    p2.wait(timeout=1200)
    # aggregate across the service's tids
    total = {}
    for t in tids:
        for cat, v in acc[t].items():
            total[cat] = total.get(cat, 0) + v
    return total, span

def summarize(total):
    # request-relevant time excludes pure idle waits (epoll/sleep parking)
    idle = total.get("idle_epoll", 0) + total.get("idle_sleep", 0)
    active = {k: v for k, v in total.items() if k not in ("idle_epoll", "idle_sleep")}
    denom = sum(active.values()) or 1
    pct = {k: round(100 * v / denom, 1) for k, v in active.items()}
    return {"active_pct": pct,
            "active_seconds": {k: round(v/1e9, 3) for k, v in active.items()},
            "idle_seconds": round(idle/1e9, 3)}

def _cap_end(begin_iso, end_iso, max_seconds):
    if not max_seconds: return end_iso
    b = dt.datetime.strptime(begin_iso, "%Y-%m-%dT%H:%M:%SZ")
    e = dt.datetime.strptime(end_iso, "%Y-%m-%dT%H:%M:%SZ")
    capped = min(e, b + dt.timedelta(seconds=max_seconds))
    return capped.strftime("%Y-%m-%dT%H:%M:%SZ")

def attribute_run(run_dir, kernel_dir, service, names, max_seconds=0):
    gt = json.load(open(os.path.join(run_dir, "ground_truth.json")))["fault"]
    tids = service_tids(os.path.join(run_dir, "meta"), service)
    begin = gt["injection_start_utc"]
    end = _cap_end(begin, gt["injection_end_utc"], max_seconds)
    total, span = attribute(kernel_dir, tids, begin, end, names)
    return {"service": service, "n_tids": len(tids), "window": [begin, end],
            **summarize(total), "raw_ns": total}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)      # in ~/traces (read-only: meta/ground_truth)
    ap.add_argument("--kernel", required=True)        # decompressed copy in ~/mvp_work
    ap.add_argument("--service", default="catalogue")
    ap.add_argument("--names", default="sched_switch,sched_waking,sched_wakeup,syscall_entry_,syscall_exit_")
    ap.add_argument("--max-seconds", type=int, default=0, help="cap analysis to first N s of injection (fast dev)")
    a = ap.parse_args()
    names = a.names.split(",")
    out = attribute_run(a.run_dir, a.kernel, a.service, names, a.max_seconds)
    print(json.dumps(out, indent=2))
