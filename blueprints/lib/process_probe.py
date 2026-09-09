#!/usr/bin/env python3
"""Five signals no existing script measures, in one pass over the trace.

Written for the fault families that have no blueprint yet. Each signal below is recorded in
every run we collected - none of this needs new collection, only extraction.

    fork rate          sched_process_fork per second        -> fork_storm
    syscall errors     syscall_exit_* with a negative ret   -> fd_exhaustion, conn_pool
    bytes sent         net_dev_queue `len` per process      -> data_exfiltration
    DNS traffic        UDP packets on port 53               -> dns_delay
    priority spread    sched_switch prev_prio / next_prio   -> priority_inversion

EVERY REGEX BELOW WAS CHECKED AGAINST A REAL TRACE FIRST, not written from memory. Sampled from
`fork_storm_aggressive_steady_r1` on 9 Sept:

    sched_switch:        prev_prio = 20, prev_state = 0, next_comm = "dockerd", next_prio = 20
    syscall_exit_read:   ret = 0
    net_dev_queue:       len = 126 ... protocol = ( "tcp" ... source_port = N, dest_port = N
    sched_process_fork:  parent_comm = "..." child_comm = "..." child_tid = N

WHAT THIS SCRIPT DOES NOT DO
----------------------------
It does not decide anything. It reports rates in the baseline window and the incident window,
and the ratio between them. Which of these separates which fault is a question for
derive_v2_thresholds.py, measured across all families, and none of it should be written into a
blueprint before then.

Two of the five are expected to be easy and one is expected to fail:

  * fork_storm's own recipe says `sched_process_fork` "is unmistakable and nothing else in our
    dataset produces it in volume". If we cannot see this one, the fault is in our analysis.
  * fd_exhaustion's recipe says `accept` and `socket` "return EMFILE while the process keeps
    running", so the error counts should carry it.
  * data_exfiltration's recipe already doubts itself: "the honest answer may be 'not from volume
    alone'". Volume is measured here so that doubt can be settled either way.

    python3 process_probe.py --ctf <ctf_dir> --gt <ground_truth.json> --out process.json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctf_stream                                                      # noqa: E402

EVENT = re.compile(r"\] \([^)]+\) [^ ]+ ([a-z0-9_]+):")
PROC = re.compile(r'procname = "([^"]*)"')

FORK_CHILD = re.compile(r'child_comm = "([^"]*)"')
RET = re.compile(r"ret = (-?\d+)")
LEN = re.compile(r"(?<![a-z_])len = (\d+)")
PROTO = re.compile(r'protocol = \( "([a-z]+)"')
PORTS = re.compile(r"source_port = (\d+), dest_port = (\d+)")
PREV_PRIO = re.compile(r"prev_prio = (\d+)")
NEXT_PRIO = re.compile(r"next_prio = (\d+)")

# Only the ones a fault in this dataset can plausibly produce. Anything else is counted under
# "other" rather than guessed at.
ERRNO = {24: "EMFILE", 23: "ENFILE", 11: "EAGAIN", 111: "ECONNREFUSED", 110: "ETIMEDOUT",
         104: "ECONNRESET", 32: "EPIPE", 12: "ENOMEM", 105: "ENOBUFS"}

# Linux reports the default CFS priority as 20 in these events (nice 0). A fault that changes
# scheduling priority shows up as anything else.
DEFAULT_PRIO = 20


def hhmmss(ts):
    return ts.split("T")[1][:8] if "T" in ts else ts[:8]


def scan(ctf, begin, end):
    """One pass per family. Returns raw counters; rates are computed by the caller."""
    out = {
        "forks": 0, "fork_by_child": collections.Counter(),
        "errors": collections.Counter(),            # "EMFILE|accept" -> n
        "errors_by_name": collections.Counter(),    # "EMFILE" -> n
        "syscall_exits": 0,
        "tx_bytes": collections.Counter(),          # procname -> bytes
        "tx_packets": 0,
        "dns_packets": 0, "dns_bytes": 0,
        "prio_switches": 0, "prio_non_default": 0,
        "prio_seen": collections.Counter(),
    }

    # sched: forks and priorities
    with ctf_stream.stream(ctf, begin, end,
                           "sched_process_fork|sched_switch", family="sched") as src:
        for line in src:
            m = EVENT.search(line)
            if not m:
                continue
            if m.group(1) == "sched_process_fork":
                out["forks"] += 1
                c = FORK_CHILD.search(line)
                if c:
                    out["fork_by_child"][c.group(1)] += 1
                continue
            # sched_switch: what priorities are actually running
            for rx in (PREV_PRIO, NEXT_PRIO):
                mp = rx.search(line)
                if mp:
                    p = int(mp.group(1))
                    out["prio_seen"][p] += 1
                    out["prio_switches"] += 1
                    if p != DEFAULT_PRIO:
                        out["prio_non_default"] += 1

    # syscalls: failures. A negative ret is an errno.
    with ctf_stream.stream(ctf, begin, end, "syscall_exit_", family="syscall") as src:
        for line in src:
            m = EVENT.search(line)
            if not m or not m.group(1).startswith("syscall_exit_"):
                continue
            out["syscall_exits"] += 1
            mr = RET.search(line)
            if not mr:
                continue
            v = int(mr.group(1))
            if v >= 0:
                continue
            name = ERRNO.get(-v, f"errno{-v}")
            call = m.group(1)[len("syscall_exit_"):]
            out["errors_by_name"][name] += 1
            out["errors"][f"{name}|{call}"] += 1

    # network: bytes out, and DNS
    with ctf_stream.stream(ctf, begin, end, "net_dev_queue", family="net") as src:
        for line in src:
            m = EVENT.search(line)
            if not m or m.group(1) != "net_dev_queue":
                continue
            ml = LEN.search(line)
            if not ml:
                continue
            n = int(ml.group(1))
            mp = PROC.search(line)
            out["tx_bytes"][mp.group(1) if mp else "?"] += n
            out["tx_packets"] += 1
            mo, mports = PROTO.search(line), PORTS.search(line)
            if mo and mo.group(1) == "udp" and mports:
                if "53" in (mports.group(1), mports.group(2)):
                    out["dns_packets"] += 1
                    out["dns_bytes"] += n
    return out


def rates(raw, span):
    top_tx = raw["tx_bytes"].most_common(1)
    top_fork = raw["fork_by_child"].most_common(1)
    return {
        "forks_per_s": round(raw["forks"] / span, 2),
        "top_forking_comm": top_fork[0][0] if top_fork else None,
        "syscall_errors_per_s": round(sum(raw["errors_by_name"].values()) / span, 2),
        "emfile_per_s": round(raw["errors_by_name"].get("EMFILE", 0) / span, 3),
        "econnrefused_per_s": round(raw["errors_by_name"].get("ECONNREFUSED", 0) / span, 3),
        "etimedout_per_s": round(raw["errors_by_name"].get("ETIMEDOUT", 0) / span, 3),
        "errors_top": dict(raw["errors"].most_common(6)),
        "tx_bytes_per_s": round(sum(raw["tx_bytes"].values()) / span, 1),
        "top_tx_comm": top_tx[0][0] if top_tx else None,
        "top_tx_bytes_per_s": round(top_tx[0][1] / span, 1) if top_tx else 0.0,
        "dns_packets_per_s": round(raw["dns_packets"] / span, 3),
        "prio_non_default_pct": (round(100.0 * raw["prio_non_default"] / raw["prio_switches"], 3)
                                 if raw["prio_switches"] else None),
        "n_distinct_prio": len(raw["prio_seen"]),
        "prio_min": min(raw["prio_seen"]) if raw["prio_seen"] else None,
        "prio_max": max(raw["prio_seen"]) if raw["prio_seen"] else None,
    }


def ratio(b, i):
    if b is None or i is None:
        return None
    if b == 0:
        # A rate that was zero and is not any more. A ratio would be infinite, which says less
        # than the fact itself, so report the fact and let the caller decide.
        return None if i == 0 else "from_zero"
    return round(i / b, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", default="process.json")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    a = ap.parse_args()

    t0 = hhmmss(json.load(open(a.gt))["fault"]["injection_start_utc"])
    wins = ctf_stream.windows(t0, a.baseline_s, a.incident_s)

    result = {"ctf": a.ctf, "windows": {}}
    per = {}
    for name, (b, e) in wins.items():
        span = a.baseline_s if name == "baseline" else a.incident_s
        print(f"scanning {name}: {b} -> {e} ...", flush=True)
        per[name] = rates(scan(a.ctf, b, e), span)
        result["windows"][name] = {"range": [b, e], **per[name]}

    base, inc = per["baseline"], per["incident"]
    sig = {}
    for k in ("forks_per_s", "syscall_errors_per_s", "emfile_per_s", "econnrefused_per_s",
              "etimedout_per_s", "tx_bytes_per_s", "top_tx_bytes_per_s", "dns_packets_per_s",
              "prio_non_default_pct"):
        sig[f"{k}_baseline"] = base.get(k)
        sig[f"{k}_incident"] = inc.get(k)
        sig[f"{k}_x"] = ratio(base.get(k), inc.get(k))
    sig["top_forking_comm"] = inc.get("top_forking_comm")
    sig["top_tx_comm"] = inc.get("top_tx_comm")
    sig["n_distinct_prio_incident"] = inc.get("n_distinct_prio")
    sig["prio_min_incident"] = inc.get("prio_min")
    sig["prio_max_incident"] = inc.get("prio_max")
    sig["errors_top_incident"] = inc.get("errors_top")
    result["signature"] = sig

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}")
    print(f"  forks/s      {sig['forks_per_s_baseline']} -> {sig['forks_per_s_incident']}"
          f"  ({sig['forks_per_s_x']})")
    print(f"  errors/s     {sig['syscall_errors_per_s_baseline']} -> "
          f"{sig['syscall_errors_per_s_incident']}  ({sig['syscall_errors_per_s_x']})")
    print(f"  EMFILE/s     {sig['emfile_per_s_baseline']} -> {sig['emfile_per_s_incident']}")
    print(f"  tx bytes/s   {sig['tx_bytes_per_s_baseline']} -> {sig['tx_bytes_per_s_incident']}"
          f"  ({sig['tx_bytes_per_s_x']})  top: {sig['top_tx_comm']}")
    print(f"  dns pkts/s   {sig['dns_packets_per_s_baseline']} -> "
          f"{sig['dns_packets_per_s_incident']}")
    print(f"  non-default prio  {sig['prio_non_default_pct_baseline']}% -> "
          f"{sig['prio_non_default_pct_incident']}%  "
          f"(priorities seen: {sig['prio_min_incident']}..{sig['prio_max_incident']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
