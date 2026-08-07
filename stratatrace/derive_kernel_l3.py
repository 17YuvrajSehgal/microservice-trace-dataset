#!/usr/bin/env python3
"""
derive_kernel_l3.py — StrataTrace kernel representation ladder, **L3 (NL digest)**.

Turns L1 KPIs (per service, 1 s window) into a **deterministic, templated natural-language
summary** per (service, window) — the LLM-consumable form for the ablation study's RQ6
("how should kernel data be presented to an LLM?"). Templated, NOT model-generated, so it is
reproducible and cannot hallucinate (msr-research.md §4).

Method: for each service, establish a **baseline** from its first `--baseline-windows`
windows (the run's pre-injection phase), then for every later window emit a fixed-structure
sentence naming only the KPIs that deviate materially (ratio ≥ threshold, or a signal that
switches on/off). A fixed top-K cap bounds the token budget per window.

Example digest:
  "carts @ t=46s: syscall p95 latency 4.1x baseline (2.1->8.6 ms); runnable-wait 3.2x;
   reclaim events 0->104191 (NEW); block/net latency normal."

Input: a run dir containing `kernel_l1.parquet` (from derive_kernel_l1.py), or --l1 <path>.
Output: `<run_dir>/kernel_l3.jsonl`  (one row: {service, window_start_s, digest, deviations}).

Usage:
    python3 derive_kernel_l3.py <run_dir> [--l1 kernel_l1.parquet] [--out kernel_l3.jsonl]
                                          [--baseline-windows 15] [--ratio 1.5] [--top-k 6]
Pure-Python + pandas; no bt2 needed (consumes L1). Offline-testable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

# KPI -> (human label, unit, "higher is notable"). Latency/rate KPIs from L1.
_KPI_LABELS = {
    "sys_lat_p95_ms": ("syscall p95 latency", "ms"),
    "sys_lat_p99_ms": ("syscall p99 latency", "ms"),
    "blk_lat_p95_ms": ("block p95 latency", "ms"),
    "sched_switch": ("context-switch rate", ""),
    "sched_wakeup": ("wakeup rate", ""),
    "block_ops": ("block-I/O ops", ""),
    "block_sectors": ("block sectors", ""),
    "net_events": ("net events", ""),
    "net_bytes": ("net bytes", ""),
    "reclaim": ("reclaim (mm_vmscan) events", ""),
    "writeback": ("writeback events", ""),
    "pagefault": ("page-fault events", ""),
    "sys_io": ("io syscalls", ""),
    "sys_net": ("net syscalls", ""),
    "sys_futex": ("futex syscalls", ""),
    "events": ("total kernel events", ""),
}
# KPIs whose appearance-from-zero is itself the story (memory pressure signatures)
_ONSET_KPIS = ("reclaim", "writeback")


def log(msg):
    print(f"[L3] {msg}", file=sys.stderr, flush=True)


def _load_l1(run_dir, l1_path):
    path = l1_path or os.path.join(run_dir, "kernel_l1.parquet")
    if not os.path.exists(path):
        alt = path.rsplit(".", 1)[0] + ".csv"
        if os.path.exists(alt):
            path = alt
        else:
            raise FileNotFoundError(f"L1 not found: {path} (run derive_kernel_l1.py first)")
    import pandas as pd
    return pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)


def _baseline(rows, baseline_windows):
    """Per-KPI baseline (median over the service's first N windows)."""
    early = rows[:baseline_windows] if len(rows) > baseline_windows else rows
    base = {}
    for kpi in _KPI_LABELS:
        vals = [r.get(kpi, 0) or 0 for r in early]
        vals = sorted(vals)
        base[kpi] = vals[len(vals) // 2] if vals else 0
    return base


def _fmt_ratio(cur, base):
    if base and base > 0:
        return f"{cur / base:.1f}x"
    return "NEW" if cur > 0 else "0x"


def digest_service(rows, baseline_windows, ratio_thresh, top_k):
    """Yield (window_start_s, digest_text, deviations) for one service's windows."""
    rows = sorted(rows, key=lambda r: r.get("window_start_s", 0))
    base = _baseline(rows, baseline_windows)
    svc = rows[0].get("service", "?") if rows else "?"
    for r in rows:
        t = r.get("window_start_s", 0)
        devs = []
        for kpi, (label, unit) in _KPI_LABELS.items():
            cur = r.get(kpi, 0) or 0
            b = base.get(kpi, 0) or 0
            onset = kpi in _ONSET_KPIS and b == 0 and cur > 0
            ratio = (cur / b) if b > 0 else (float("inf") if cur > 0 else 1.0)
            if onset or ratio >= ratio_thresh:
                sev = ratio if ratio != float("inf") else 1e9
                u = f" {unit}" if unit else ""
                if onset:
                    piece = f"{label} 0->{int(cur)} (NEW)"
                else:
                    cs = f"{cur:.1f}" if isinstance(cur, float) else str(int(cur))
                    bs = f"{b:.1f}" if isinstance(b, float) else str(int(b))
                    piece = f"{label} {_fmt_ratio(cur, b)} ({bs}->{cs}{u})"
                devs.append((sev, piece))
        devs.sort(key=lambda x: -x[0])
        top = [p for _, p in devs[:top_k]]
        if top:
            digest = f"{svc} @ t={t:g}s: " + "; ".join(top) + "."
        else:
            digest = f"{svc} @ t={t:g}s: nominal (all KPIs within {ratio_thresh:g}x baseline)."
        yield t, digest, [p for _, p in devs[:top_k]]


def derive(run_dir, l1_path, baseline_windows, ratio_thresh, top_k):
    df = _load_l1(run_dir, l1_path)
    if len(df) == 0:
        return []
    run_id = df["run_id"].iloc[0] if "run_id" in df.columns else os.path.basename(run_dir.rstrip("/"))
    by_svc = defaultdict(list)
    for rec in df.to_dict("records"):
        by_svc[rec.get("service", "?")].append(rec)
    out = []
    for svc, rows in sorted(by_svc.items()):
        for t, digest, devs in digest_service(rows, baseline_windows, ratio_thresh, top_k):
            out.append({"run_id": run_id, "service": svc, "window_start_s": t,
                        "digest": digest, "deviations": devs})
    return out


def main():
    ap = argparse.ArgumentParser(description="Derive L3 NL kernel digest from L1 KPIs.")
    ap.add_argument("run_dir")
    ap.add_argument("--l1", default=None, help="path to kernel_l1.parquet (default: <run_dir>/kernel_l1.parquet)")
    ap.add_argument("--out", default=None, help="output jsonl (default: <run_dir>/kernel_l3.jsonl)")
    ap.add_argument("--baseline-windows", type=int, default=15)
    ap.add_argument("--ratio", type=float, default=1.5, help="deviation ratio threshold")
    ap.add_argument("--top-k", type=int, default=6, help="max KPIs named per window (token budget)")
    args = ap.parse_args()

    out = args.out or os.path.join(args.run_dir, "kernel_l3.jsonl")
    rows = derive(args.run_dir, args.l1, args.baseline_windows, args.ratio, args.top_k)
    with open(out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    log(f"wrote {len(rows)} digests -> {out}")


if __name__ == "__main__":
    main()
