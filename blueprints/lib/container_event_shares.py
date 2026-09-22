#!/usr/bin/env python3
"""Provider for `kernel.container.event_shares`.

For each container in a kernel trace: what share of ITS OWN events went to each kind of work -
futex, scheduler churn, on-CPU time, softirq, network, ioctl, file operations.

Shares rather than rates, on purpose. Rates encode how hard the thing was pushed; a share does
not. Measured across our labelled runs, a contended lock spends 47% of its events on futex and
a deadlocked one 4.3%, whatever the thread count - while their absolute rates differ by a
factor of 800 and would transfer to nobody.

Container identity is `pid_ns`, the only thing in a kernel trace that tells one container's
`java` from another's. The host's own namespace is excluded: that is where collection runs.

    python container_event_shares.py --ctf <ctf> --window HH:MM:SS-HH:MM:SS --out shares.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

BT2 = os.environ.get("BT2", "babeltrace2")
_TIME = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d+)\]")
_EV = re.compile(r"\]\s+(?:\(\+[^)]*\)\s+)?\S+\s+([a-zA-Z0-9_]+):")
_PROC = re.compile(r'procname\s*=\s*"([^"]*)"')
_NS = re.compile(r"pid_ns\s*=\s*(\d+)")

GROUPS = {
    "futex": ("syscall_entry_futex", "syscall_exit_futex"),
    "sched_churn": ("sched_switch", "sched_waking", "sched_wakeup"),
    "migrate": ("sched_migrate_task",),
    "on_cpu": ("sched_stat_runtime",),
    "softirq": ("irq_softirq_raise", "irq_softirq_entry", "irq_softirq_exit"),
    "network": ("net_dev_queue", "net_dev_xmit", "net_if_receive_skb", "net_if_rx",
                "net_if_rx_entry", "net_if_rx_exit"),
    "ioctl": ("syscall_entry_ioctl", "syscall_exit_ioctl"),
    "file_ops": ("syscall_entry_close", "syscall_exit_close", "syscall_entry_fcntl",
                 "syscall_exit_fcntl", "syscall_entry_openat2", "syscall_exit_openat2"),
    "sleep": ("syscall_entry_nanosleep", "syscall_exit_nanosleep"),
    "socket_io": ("syscall_entry_sendto", "syscall_exit_sendto",
                  "syscall_entry_recvfrom", "syscall_exit_recvfrom"),
}
OF = {ev: g for g, evs in GROUPS.items() for ev in evs}
HOST_NS = "4026531836"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--window", default="", help="HH:MM:SS-HH:MM:SS; omit for the whole trace")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-events", type=int, default=2000)
    a = ap.parse_args()

    cmd = [BT2, "--clock-gmt", a.ctf]
    if a.window and "-" in a.window:
        b, e = a.window.split("-", 1)
        cmd += ["--begin", b.strip(), "--end", e.strip()]

    total = defaultdict(int)
    grouped = defaultdict(lambda: defaultdict(int))
    procs = defaultdict(lambda: defaultdict(int))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, bufsize=1 << 22)
    with p:
        for line in p.stdout:
            m = _EV.search(line)
            if not m:
                continue
            nm = _NS.search(line)
            ns = nm.group(1) if nm else "0"
            if ns in (HOST_NS, "0"):
                continue
            ev = m.group(1)
            total[ns] += 1
            g = OF.get(ev)
            if g:
                grouped[ns][g] += 1
            pm = _PROC.search(line)
            if pm:
                procs[ns][pm.group(1)] += 1

    out = []
    for ns, tot in sorted(total.items(), key=lambda kv: -kv[1]):
        if tot < a.min_events:
            continue
        out.append({
            "pid_ns": ns,
            "events": tot,
            "procnames": [p for p, _ in sorted(procs[ns].items(), key=lambda kv: -kv[1])[:5]],
            "shares_pct": {g: round(100.0 * grouped[ns].get(g, 0) / tot, 1) for g in GROUPS},
        })

    json.dump({"window": a.window or "whole trace",
               "note": ("shares are of each container's OWN events, so they do not move when "
                        "the machine gets busier. pid_ns identifies the container; the host "
                        "namespace is excluded because collection runs there."),
               "containers": out}, open(a.out, "w"), indent=1)
    print("wrote %s  (%d containers)" % (a.out, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
