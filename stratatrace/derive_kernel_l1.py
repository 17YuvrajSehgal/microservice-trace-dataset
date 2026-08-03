#!/usr/bin/env python3
"""
derive_kernel_l1.py — StrataTrace kernel representation ladder, **L1 (kernel KPIs)**.

Turns a run's raw kernel CTF (LTTng, gzipped channels) into a compact per-(service,
1-second-window) KPI table in Parquet — the form the ablation study and any tabular ML
method consume, and the one directly comparable to the metrics modality (M1). See
`msr-research.md` §4 (the representation ladder) and `RESULTS.md`.

What L1 computes, per 1 s window × service:
  - event volume (total kernel events)
  - syscall counts by family (io / net / futex / poll / mem / proc / other)
  - syscall latency percentiles (p50/p95/p99, ms) via entry/exit pairing per tid
  - scheduler rates: sched_switch, sched_wakeup
  - block I/O: op count (issue) + completion latency percentiles (ms) + bytes
  - net: dev xmit/recv event count + bytes
  - memory pressure: mm_vmscan_* (reclaim), writeback_*, page-fault counts

Service attribution (v1): keyed by `procname` (the kernel's comm), which is a robust proxy
but cannot split two same-binary services (e.g. two JVMs). The pid→container map for exact
service attribution is a documented refinement (needs the run's cgroup/pid snapshot in
meta/) — TODO below; the schema already carries a `service` column so the refinement slots in.

Storage: the kernel channels are gzipped for storage (v1 format). bt2 cannot read .gz
directly, so this deriver decompresses the channels into a temp dir, reads, and cleans up —
the raw run on disk is left untouched.

Usage:
    python3 derive_kernel_l1.py <run_dir> [--out kernel_l1.parquet] [--window-ms 1000]
                                          [--warmup-s 0] [--keep-temp]
    # run_dir is e.g. ~/traces/anomaly_mem/anomaly_mem_aggressive_steady_r1

Run on the VM (bt2 + the traces live there). Output is small (~KBs/run).
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict

try:
    import bt2
    BT2_AVAILABLE = True
except Exception:
    BT2_AVAILABLE = False

# Cap latency samples kept per (window, service) bucket so a 1 s window with millions of
# syscalls doesn't balloon RAM (the bt2-python run OOM-pressured the VM). Percentiles over a
# 20k first-sample are accurate enough for L1 KPIs.
_LAT_SAMPLE_CAP = 20000


def log(msg: str, prefix: str = "L1") -> None:
    print(f"[{prefix}] {msg}", file=sys.stderr, flush=True)


# ---- syscall family map (name has kernel:/syscall_/entry_/exit_ stripped) -----------------
_SYS_FAMILY = {
    # io
    "read": "io", "pread64": "io", "readv": "io", "write": "io", "pwrite64": "io",
    "writev": "io", "openat": "io", "open": "io", "close": "io", "fsync": "io",
    "fdatasync": "io", "lseek": "io", "stat": "io", "fstat": "io", "newfstatat": "io",
    # net
    "sendto": "net", "recvfrom": "net", "sendmsg": "net", "recvmsg": "net",
    "sendmmsg": "net", "recvmmsg": "net", "connect": "net", "accept": "net",
    "accept4": "net", "socket": "net", "bind": "net", "listen": "net",
    "epoll_wait": "poll", "epoll_pwait": "poll", "poll": "poll", "ppoll": "poll",
    "select": "poll", "pselect6": "poll",
    # sync
    "futex": "futex",
    # memory
    "mmap": "mem", "munmap": "mem", "mprotect": "mem", "brk": "mem", "madvise": "mem",
    # proc
    "clone": "proc", "fork": "proc", "execve": "proc", "exit": "proc", "exit_group": "proc",
    "wait4": "proc", "nanosleep": "proc", "clock_nanosleep": "proc",
}
_FAMILIES = ("io", "net", "futex", "poll", "mem", "proc", "other")


def find_ctf_root(base_dir: str) -> str | None:
    """Locate the dir containing a CTF `metadata` file under base_dir."""
    for root, _dirs, files in os.walk(base_dir):
        if "metadata" in files:
            return root
    return None


def prepare_ctf(kernel_dir: str, tmp_root: str) -> str:
    """Copy the CTF tree to tmp and gunzip any channel0_*.gz so bt2 can read it.
    Returns the CTF root (dir with `metadata`)."""
    ctf_src = find_ctf_root(kernel_dir)
    if ctf_src is None:
        raise FileNotFoundError(f"No CTF metadata found under {kernel_dir}")
    dst = os.path.join(tmp_root, "ctf")
    shutil.copytree(ctf_src, dst)
    for fn in os.listdir(dst):
        if fn.endswith(".gz"):
            src = os.path.join(dst, fn)
            with gzip.open(src, "rb") as fi, open(src[:-3], "wb") as fo:
                shutil.copyfileobj(fi, fo)
            os.remove(src)
    return dst


def _sf(ev, names, default=None):
    for n in names:
        try:
            return ev[n]
        except (KeyError, TypeError):
            continue
    return default


def _int_after(line, key, start=0):
    """Fast parse of an integer field `key = <digits>` from a babeltrace2 text line."""
    i = line.find(key, start)
    if i < 0:
        return 0
    i += len(key)
    j = i
    n = len(line)
    while j < n and (line[j].isdigit() or (j == i and line[j] == "-")):
        j += 1
    try:
        return int(line[i:j])
    except ValueError:
        return 0


def stream_events_cli(ctf_root: str, warmup_s: float):
    """FAST reader: babeltrace2 CLI (C decode) + minimal str parsing. ~5-10x the
    bt2-python object iterator, which is impractically slow on the big (60-80M-event)
    resource-stress traces. Yields the same event dicts as the bt2 reader."""
    p = subprocess.Popen(["babeltrace2", ctf_root], stdout=subprocess.PIPE,
                         text=True, errors="replace", bufsize=1 << 20)
    first_ts = None
    warmup_ns = int(warmup_s * 1e9)
    n = 0
    for line in p.stdout:
        if not line or line[0] != "[":
            continue
        rb = line.find("]")
        ts_str = line[1:rb]
        c1 = ts_str.find(":"); c2 = ts_str.find(":", c1 + 1); dot = ts_str.find(".")
        if c1 < 0 or c2 < 0 or dot < 0:
            continue
        try:
            ts = ((int(ts_str[:c1]) * 3600 + int(ts_str[c1 + 1:c2]) * 60 + int(ts_str[c2 + 1:dot]))
                  * 1_000_000_000) + int(ts_str[dot + 1:])
        except ValueError:
            continue
        if first_ts is None:
            first_ts = ts
        if ts - first_ts < warmup_ns:
            continue
        ci = line.find(": { cpu_id", rb)
        if ci < 0:
            continue
        raw = line[line.rfind(" ", 0, ci) + 1:ci]
        is_entry = raw.startswith("syscall_entry_")
        is_exit = raw.startswith("syscall_exit_")
        name = raw
        if is_entry:
            name = raw[len("syscall_entry_"):]
        elif is_exit:
            name = raw[len("syscall_exit_"):]
        out = {
            "raw": raw, "name": name, "ts": ts,
            "tid": _int_after(line, "tid = ", ci),
            "proc": _proc(line, ci),
            "is_entry": is_entry, "is_exit": is_exit,
        }
        if raw.startswith("block_"):
            out["nr_sector"] = _int_after(line, "nr_sector = ", ci)
        elif raw.startswith("net_dev_xmit") or raw.startswith("netif_receive"):
            out["len"] = _int_after(line, "len = ", ci)
        n += 1
        yield out
        if n % 2_000_000 == 0:
            log(f"read {n:,} events (cli)")
    p.stdout.close()
    p.wait()
    log(f"read {n:,} events (cli, total)")


def _proc(line, start):
    i = line.find('procname = "', start)
    if i < 0:
        return "unknown"
    i += len('procname = "')
    j = line.find('"', i)
    return line[i:j] if j > i else "unknown"


def stream_events_bt2(ctf_root: str, warmup_s: float):
    """Reference reader via the bt2 python bindings (correct but slow; use --reader bt2
    only for cross-checking the fast CLI reader)."""
    it = bt2.TraceCollectionMessageIterator(ctf_root)
    first_ts = None
    warmup_ns = int(warmup_s * 1e9)
    n = 0
    for msg in it:
        if type(msg) is not bt2._EventMessageConst:
            continue
        ev = msg.event
        ts = msg.default_clock_snapshot.ns_from_origin
        if first_ts is None:
            first_ts = ts
        if ts - first_ts < warmup_ns:
            continue
        n += 1
        raw = ev.name
        name = raw.replace("kernel:", "").replace("syscall_", "")
        is_entry = "entry" in name
        is_exit = "exit" in name
        name = name.replace("entry_", "").replace("exit_", "")
        out = {
            "raw": raw, "name": name, "ts": ts,
            "tid": int(_sf(ev, ("vtid", "tid"), 0) or 0),
            "proc": str(_sf(ev, ("procname",), "unknown")),
            "is_entry": is_entry, "is_exit": is_exit,
        }
        if raw.startswith("kernel:block_") or raw.startswith("block_"):
            out["nr_sector"] = int(_sf(ev, ("nr_sector",), 0) or 0)
        if "net_dev_xmit" in raw or "netif_receive" in raw:
            out["len"] = int(_sf(ev, ("len",), 0) or 0)
        yield out
        if n % 1_000_000 == 0:
            log(f"read {n:,} events (bt2)")
    log(f"read {n:,} events (bt2, total)")


def new_bucket():
    b = {
        "events": 0,
        "sched_switch": 0, "sched_wakeup": 0,
        "block_ops": 0, "block_sectors": 0,
        "net_events": 0, "net_bytes": 0,
        "reclaim": 0, "writeback": 0, "pagefault": 0,
        "_sys_lat": [],      # syscall latencies (ns) closed this window
        "_blk_lat": [],      # block issue->complete latencies (ns)
    }
    for f in _FAMILIES:
        b[f"sys_{f}"] = 0
    return b


def percentiles(vals_ns):
    if not vals_ns:
        return (0.0, 0.0, 0.0)
    s = sorted(vals_ns)
    def pct(p):
        k = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
        return s[k] / 1e6  # ns -> ms
    return (pct(50), pct(95), pct(99))


def derive(run_dir: str, window_ms: float, warmup_s: float, tmp_root: str, reader: str = "cli"):
    """Return a list of per-(service, window) KPI row dicts."""
    kernel_dir = os.path.join(run_dir, "kernel")
    ctf_root = prepare_ctf(kernel_dir, tmp_root)
    run_id = os.path.basename(run_dir.rstrip("/"))
    win_ns = int(window_ms * 1e6)

    # windows[(win_idx, service)] -> bucket ; pairing state per (service, tid)
    windows: dict = defaultdict(new_bucket)
    sys_open: dict = {}   # (service, tid) -> entry_ts   (syscall entry awaiting exit)
    blk_issue: dict = {}  # sector -> issue_ts           (block rq awaiting complete)
    base_ts = None

    stream = stream_events_bt2 if reader == "bt2" else stream_events_cli
    for e in stream(ctf_root, warmup_s):
        if base_ts is None:
            base_ts = e["ts"]
        widx = (e["ts"] - base_ts) // win_ns
        svc = e["proc"]
        b = windows[(widx, svc)]
        b["events"] += 1
        raw, name = e["raw"], e["name"]

        # syscalls: family counts + entry/exit latency pairing
        if e["is_entry"] and ("syscall" in raw or raw.startswith("kernel:sys")):
            b[f"sys_{_SYS_FAMILY.get(name, 'other')}"] += 1
            sys_open[(svc, e["tid"])] = e["ts"]
        elif e["is_exit"] and ("syscall" in raw or raw.startswith("kernel:sys")):
            t0 = sys_open.pop((svc, e["tid"]), None)
            if t0 is not None and len(b["_sys_lat"]) < _LAT_SAMPLE_CAP:
                b["_sys_lat"].append(e["ts"] - t0)
        # scheduler
        elif "sched_switch" in raw:
            b["sched_switch"] += 1
        elif "sched_wakeup" in raw:
            b["sched_wakeup"] += 1
        # block I/O
        elif "block_rq_issue" in raw:
            b["block_ops"] += 1
            b["block_sectors"] += e.get("nr_sector", 0)
            blk_issue[e.get("nr_sector", -1)] = e["ts"]  # coarse; refined via (dev,sector) later
        elif "block_rq_complete" in raw:
            t0 = blk_issue.pop(e.get("nr_sector", -1), None)
            if t0 is not None and len(b["_blk_lat"]) < _LAT_SAMPLE_CAP:
                b["_blk_lat"].append(e["ts"] - t0)
        # net
        elif "net_dev_xmit" in raw or "netif_receive" in raw:
            b["net_events"] += 1
            b["net_bytes"] += e.get("len", 0)
        # memory pressure
        elif raw.startswith("kernel:mm_vmscan_") or "mm_vmscan_" in raw:
            b["reclaim"] += 1
        elif "writeback_" in raw:
            b["writeback"] += 1
        elif "page_fault" in raw or name in ("mmap", "brk"):
            b["pagefault"] += 1

    rows = []
    for (widx, svc), b in sorted(windows.items()):
        p50, p95, p99 = percentiles(b.pop("_sys_lat"))
        bp50, bp95, bp99 = percentiles(b.pop("_blk_lat"))
        row = {
            "run_id": run_id,
            "service": svc,
            "window_start_s": round(widx * window_ms / 1000.0, 3),
            "sys_lat_p50_ms": round(p50, 4),
            "sys_lat_p95_ms": round(p95, 4),
            "sys_lat_p99_ms": round(p99, 4),
            "blk_lat_p50_ms": round(bp50, 4),
            "blk_lat_p95_ms": round(bp95, 4),
            "blk_lat_p99_ms": round(bp99, 4),
        }
        row.update(b)
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser(description="Derive L1 kernel KPIs (Parquet) from a run's CTF.")
    ap.add_argument("run_dir")
    ap.add_argument("--out", default=None, help="output parquet (default: <run_dir>/kernel_l1.parquet)")
    ap.add_argument("--window-ms", type=float, default=1000.0)
    ap.add_argument("--warmup-s", type=float, default=0.0)
    ap.add_argument("--reader", choices=("cli", "bt2"), default="cli",
                    help="cli = fast babeltrace2 subprocess (default); bt2 = slow python bindings (cross-check)")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    if args.reader == "bt2" and not BT2_AVAILABLE:
        log("ERROR: --reader bt2 needs the bt2 python bindings (VM-only).")
        sys.exit(2)
    if args.reader == "cli" and not shutil.which("babeltrace2"):
        log("ERROR: babeltrace2 CLI not found (VM-only).")
        sys.exit(2)

    out = args.out or os.path.join(args.run_dir, "kernel_l1.parquet")
    tmp_root = tempfile.mkdtemp(prefix="stratatrace_l1_")
    try:
        rows = derive(args.run_dir, args.window_ms, args.warmup_s, tmp_root, args.reader)
        try:
            import pandas as pd
            df = pd.DataFrame(rows)
            df.to_parquet(out, index=False)
            log(f"wrote {len(df)} rows x {len(df.columns)} cols -> {out}")
        except ImportError:
            import csv
            out_csv = out.rsplit(".", 1)[0] + ".csv"
            with open(out_csv, "w", newline="") as fh:
                if rows:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                    w.writeheader(); w.writerows(rows)
            log(f"pandas/pyarrow missing -> wrote CSV fallback: {out_csv} ({len(rows)} rows)")
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
