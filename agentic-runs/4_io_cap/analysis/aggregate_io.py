#!/usr/bin/env python3
"""Aggregate problem #4 (disk I/O cap). Reuses analyze_run.py.
Reports phase wall + io.stat rbytes vs rbps, plus the worker's own elapsed
time (from results/read.csv) as an independent cross-check.
"""
import csv, json, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent /
                       '1_svc_cpu_cap/agentic-os-noise/analysis'))
from analyze_run import analyze


def med(xs):
    return round(statistics.median(xs), 2) if xs else 0.0


def rbps_key(rbps):
    return float('inf') if rbps == 'none' else int(rbps)


def main():
    runs = HERE / 'runs'
    rows = list(csv.DictReader(open(runs / 'manifest.csv')))
    groups = {}
    for r in rows:
        d = runs / r['run']
        if not d.exists():
            continue
        a = analyze(d)
        groups.setdefault(r['rbps'], []).append(a)

    print(f"\n=== Part A: disk I/O cap (io.max rbps), read 1 GB once ===")
    h = f"{'io.max rbps':<14}{'n':<3}{'phase_wall_s':<14}{'io.stat rbytes':<16}{'eff MB/s':<10}"
    print(h); print('-' * len(h))
    for rb in sorted(groups, key=rbps_key, reverse=True):
        rs = groups[rb]
        pw = med([x['workers']['phase_wall_s'] for x in rs if x['workers']])
        rbytes = med([x['io']['rbytes'] for x in rs if x['io']])
        eff = round((rbytes / 1e6) / pw, 1) if pw else 0
        label = 'unlimited' if rb == 'none' else f"{int(rb)//1048576} MB/s"
        print(f"{label:<14}{len(rs):<3}{pw:<14}{int(rbytes):<16}{eff:<10}")

    # dose-response vs unlimited
    base = med([x['workers']['phase_wall_s'] for x in groups.get('none', []) if x['workers']])
    if base:
        print(f"\n=== phase inflation vs unlimited ({base}s) ===")
        for rb in sorted((g for g in groups if g != 'none'), key=rbps_key, reverse=True):
            pw = med([x['workers']['phase_wall_s'] for x in groups[rb] if x['workers']])
            print(f"  {int(rb)//1048576:>4} MB/s: phase {pw:<7} ({round(pw/base,1)}x slower)")


if __name__ == '__main__':
    main()
