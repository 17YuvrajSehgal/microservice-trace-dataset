#!/usr/bin/env python3
"""
derive_kernel_l2.py — StrataTrace kernel representation ladder, **L2 (wait attribution)**.

For a service's threads over a window, classify wall-time into on-CPU / runnable-but-waiting
(contention) / blocked-in-<syscall-family> (disk / net / futex / epoll). This is the kernel's
unique semantic — *why* a request was slow, not just that it was — that no app-level modality
can produce (msr-research.md §4). L2 powers the RCA baselines in the ablation study.

Productionized from `agent-first-mvp/engine/wait_attribution.py` (the MVP's analytical core):
same TGID-identity method (container main PID from the docker-top snapshot → robust to Go/Java
thread recycling), made release-grade here — gz-CTF aware, multi-service per run, structured
Parquet/JSONL output.

Method per tid of the target (TGID): sched_switch next→ON-CPU, prev(sleep)→BLOCKED in its open
syscall, prev(runnable)→RUNNABLE; sched_wakeup→RUNNABLE; syscall entry/exit tracks the open
syscall (the reason it blocks). Rule-out buckets: on_cpu / runnable_wait / disk_wait /
off_cpu_io_wait, plus a verdict hint.

v1 granularity: **per (service, injection-window)**. Per-*request* attribution (join each span's
[start,end] × the service's tids) is the documented refinement — the same engine, sub-windowed
by span, once validated on the VM.

Usage:
    python3 derive_kernel_l2.py <run_dir> [--services carts,catalogue] [--out kernel_l2.jsonl]
                                          [--max-seconds 0] [--keep-temp]
Needs babeltrace2 (VM). Decompresses the gz CTF to temp first (bt2 can't read .gz).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from derive_kernel_l1 import prepare_ctf  # gz-aware CTF stage (shared)
from service_map import SERVICE_CONTAINER, SERVICE_COMM, container_pids  # profile-driven (STRATATRACE_APP)

_TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
_EVT = re.compile(r"\] (?:\(\+[^)]*\) )?\S+ (\w+): \{ cpu_id")
_CTX = re.compile(r"pid = (\d+), tid = (\d+), procname = \"([^\"]*)\"")
_SS = re.compile(r'prev_comm = "([^"]*)", prev_tid = (\d+), prev_prio = -?\d+, prev_state = (\d+),.*?next_comm = "([^"]*)", next_tid = (\d+)')
_WK = re.compile(r'comm = "([^"]*)", tid = (\d+)')
SLEEP_STATES = {1, 2, 258, 130, 66, 129}
FAMILY = {
    "recvfrom": "blocked_read_net", "recvmsg": "blocked_read_net", "recv": "blocked_read_net",
    "read": "blocked_read_net", "readv": "blocked_read_net", "pread64": "blocked_read_net",
    "sendto": "blocked_write_net", "sendmsg": "blocked_write_net", "write": "blocked_write_net",
    "writev": "blocked_write_net", "pwrite64": "blocked_write_net",
    "epoll_pwait": "idle_epoll", "epoll_wait": "idle_epoll", "poll": "idle_epoll", "ppoll": "idle_epoll",
    "futex": "blocked_futex",
    "fsync": "blocked_disk", "fdatasync": "blocked_disk",
    "nanosleep": "idle_sleep", "clock_nanosleep": "idle_sleep",
}


def log(msg):
    print(f"[L2] {msg}", file=sys.stderr, flush=True)


def _ns(m):
    return ((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) * 1_000_000_000) + int(m.group(4))


def _bt(ts):
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S.000000")


def attribute(ctf_root, target_comm, begin_iso, end_iso, names, target_tgids=None):
    bt = ["babeltrace2", ctf_root, "--begin", _bt(begin_iso), "--end", _bt(end_iso)]
    p1 = subprocess.Popen(bt, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["grep", "-E", "|".join(names)], stdin=p1.stdout,
                          stdout=subprocess.PIPE, text=True, errors="replace")
    p1.stdout.close()
    st, blk, opsys, last, acc = {}, {}, {}, {}, {}
    tid2tgid = {}

    def belongs(tid, comm):
        if target_tgids:
            return tid2tgid.get(tid) in target_tgids
        return comm == target_comm

    def ensure(t):
        if t not in st:
            st[t], blk[t], opsys[t], last[t], acc[t] = "off", None, None, None, {}

    def add(t, cat, a, b):
        if a is not None and b is not None and b > a:
            acc[t][cat] = acc[t].get(cat, 0) + (b - a)

    for line in p2.stdout:
        mt = _TS.match(line)
        if not mt:
            continue
        ts = _ns(mt)
        ctx = _CTX.search(line)
        if ctx:
            tid2tgid[int(ctx.group(2))] = int(ctx.group(1))
        me = _EVT.search(line)
        if not me:
            continue
        ev = me.group(1)
        if ev == "sched_switch":
            m = _SS.search(line)
            if not m:
                continue
            pc, pt, pstate, nc, nt = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4), int(m.group(5))
            pb, nb = belongs(pt, pc), belongs(nt, nc)
            if pb:
                ensure(pt)
                if st[pt] == "on":
                    add(pt, "on_cpu", last[pt], ts)
                if pstate in SLEEP_STATES:
                    st[pt], blk[pt] = "blk", FAMILY.get(opsys[pt] or "", "blocked_other")
                else:
                    st[pt] = "run"
                last[pt] = ts
            if nb:
                ensure(nt)
                if st[nt] == "run":
                    add(nt, "runnable_wait", last[nt], ts)
                elif st[nt] == "blk":
                    add(nt, blk[nt] or "blocked_other", last[nt], ts)
                st[nt], last[nt] = "on", ts
        elif ev in ("sched_waking", "sched_wakeup"):
            m = _WK.search(line)
            if not m or not belongs(int(m.group(2)), m.group(1)):
                continue
            t = int(m.group(2))
            ensure(t)
            if st[t] == "blk":
                add(t, blk[t] or "blocked_other", last[t], ts)
            st[t], last[t] = "run", ts
        elif ev.startswith("syscall_entry_") or ev.startswith("syscall_exit_"):
            if not ctx or not belongs(int(ctx.group(2)), ctx.group(3)):
                continue
            t = int(ctx.group(2))
            ensure(t)
            if ev.startswith("syscall_entry_"):
                opsys[t] = ev[len("syscall_entry_"):]
            elif opsys.get(t) == ev[len("syscall_exit_"):]:
                opsys[t] = None
    p2.wait(timeout=1800)
    total = {}
    for t in acc:
        for cat, v in acc[t].items():
            total[cat] = total.get(cat, 0) + v
    return total, len(acc)


def summarize(total):
    g = lambda *ks: sum(total.get(k, 0) for k in ks)
    buckets = {
        "on_cpu": g("on_cpu"),
        "runnable_wait": g("runnable_wait"),
        "disk_wait": g("blocked_disk"),
        "off_cpu_io_wait": g("blocked_read_net", "blocked_write_net", "blocked_futex",
                             "idle_epoll", "idle_sleep", "blocked_other"),
    }
    denom = sum(buckets.values()) or 1
    pct = {k: round(100 * v / denom, 1) for k, v in buckets.items()}
    if pct["on_cpu"] >= 60:
        hint = "cpu_bound"
    elif pct["runnable_wait"] >= 30:
        hint = "cpu_contention"
    elif pct["disk_wait"] >= 30:
        hint = "disk_bound"
    elif pct["off_cpu_io_wait"] >= 60:
        hint = "external_io_or_dependency_wait"
    else:
        hint = "mixed"
    return {"rule_out_pct": pct, "verdict_hint": hint,
            "seconds": {k: round(v / 1e9, 3) for k, v in buckets.items()},
            "family_seconds": {k: round(v / 1e9, 3) for k, v in sorted(total.items(), key=lambda x: -x[1])}}


def _cap(begin, end, sec):
    if not sec:
        return end
    b = dt.datetime.strptime(begin, "%Y-%m-%dT%H:%M:%SZ")
    e = dt.datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ")
    return min(e, b + dt.timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def derive(run_dir, services, max_seconds, tmp_root, names):
    gt = json.load(open(os.path.join(run_dir, "ground_truth.json")))["fault"]
    begin = gt["injection_start_utc"]
    end = _cap(begin, gt["injection_end_utc"], max_seconds)
    run_id = os.path.basename(run_dir.rstrip("/"))
    meta_dir = os.path.join(run_dir, "meta")
    ctf_root = prepare_ctf(os.path.join(run_dir, "kernel"), tmp_root)

    rows = []
    for svc in services:
        comm = SERVICE_COMM.get(svc, svc)
        tgids = container_pids(meta_dir, SERVICE_CONTAINER[svc]) if svc in SERVICE_CONTAINER else set()
        total, ntids = attribute(ctf_root, comm, begin, end, names, target_tgids=tgids)
        s = summarize(total)
        rows.append({"run_id": run_id, "service": svc, "comm": comm, "tgids": sorted(tgids),
                     "n_tids_seen": ntids, "window_begin_utc": begin, "window_end_utc": end,
                     "fault_name": gt.get("name"), "fault_target": gt.get("target_service"),
                     **s})
        log(f"{svc}: tids={ntids} hint={s['verdict_hint']} rule_out={s['rule_out_pct']}")
    return rows


def main():
    ap = argparse.ArgumentParser(description="Derive L2 per-service wait attribution from a run's CTF.")
    ap.add_argument("run_dir")
    ap.add_argument("--services", default=None,
                    help="comma list (default: the fault target + catalogue,carts,front-end)")
    ap.add_argument("--out", default=None, help="output jsonl (default: <run_dir>/kernel_l2.jsonl)")
    ap.add_argument("--names", default="sched_switch,sched_waking,sched_wakeup,syscall_entry_,syscall_exit_")
    ap.add_argument("--max-seconds", type=int, default=0)
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    # profile-appropriate default L2 targets (entry + a couple of core services); overridden by --services
    _DEFAULT_SVCS = {
        "sockshop": ["catalogue", "carts", "front-end"],
        "trainticket": ["ts-ui-dashboard", "ts-order-service", "ts-travel-service"],
    }.get(os.environ.get("STRATATRACE_APP", "sockshop").lower(), ["ts-ui-dashboard"])
    if args.services:
        services = [s.strip() for s in args.services.split(",") if s.strip()]
    else:
        gt = json.load(open(os.path.join(args.run_dir, "ground_truth.json")))["fault"]
        tgt = gt.get("target_service")
        services = list(dict.fromkeys([s for s in ([tgt] if tgt and tgt in SERVICE_CONTAINER else [])
                                       + _DEFAULT_SVCS]))
    out = args.out or os.path.join(args.run_dir, "kernel_l2.jsonl")
    tmp_root = tempfile.mkdtemp(prefix="stratatrace_l2_")
    try:
        rows = derive(args.run_dir, services, args.max_seconds, tmp_root, args.names.split(","))
        with open(out, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        log(f"wrote {len(rows)} service attributions -> {out}")
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
