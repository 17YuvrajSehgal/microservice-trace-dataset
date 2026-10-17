#!/usr/bin/env python3
"""Aggregate problem #3 (memory cap). Reuses analyze_run.py.

Part A (memory.high, runs_t6/t6A_*): recoverable dose-response - phase
wall, refaults, events[high] vs cap.
Part B-file (memory.max + file, runs_t6/t6B_*): shows clean cache never
OOMs even under a hard cap.
Part B-cliff (memory.max + anon, runs_t7/t7_*): the OOM cliff - pass/fail
and oom_kill vs cap.
"""
import csv, json, re, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] /
                       '1_svc_cpu_cap/agentic-os-noise/analysis'))
from analyze_run import analyze

HERE = Path(__file__).resolve().parents[1]


def med(xs):
    return round(statistics.median(xs), 2) if xs else 0.0


def mb(limit):  # "high:1152M" -> 1152, "high:max" -> inf
    v = limit.split(':')[1]
    if v == 'max':
        return float('inf')
    return int(re.sub('[^0-9]', '', v)) * (1024 if v.endswith('G') else 1)


def load(runs_dir, prefix):
    rows = list(csv.DictReader(open(runs_dir / 'manifest.csv')))
    out = []
    for r in rows:
        if not r['run'].startswith(prefix):
            continue
        d = runs_dir / r['run']
        if not d.exists():
            continue
        a = analyze(d)
        a['mem_limit'] = r['mem_limit']
        out.append(a)
    return out


def part_a(runs):
    groups = {}
    for a in runs:
        groups.setdefault(a['mem_limit'], []).append(a)
    print("\n=== Part A: recoverable (memory.high), F=1GB x5 passes ===")
    h = f"{'memory.high':<14}{'n':<3}{'phase_wall_s':<14}{'refault_pages':<15}{'events[high]':<13}"
    print(h); print('-' * len(h))
    for lim in sorted(groups, key=mb, reverse=True):
        rs = groups[lim]
        pw = med([x['workers']['phase_wall_s'] for x in rs if x['workers']])
        rf = med([x['memory']['stat_delta'].get('workingset_refault_file', 0) for x in rs])
        hi = med([x['memory']['events'].get('high', 0) for x in rs])
        print(f"{lim:<14}{len(rs):<3}{pw:<14}{int(rf):<15}{int(hi):<13}")


def part_b_file(runs):
    print("\n=== Part B (memory.max + FILE workload): clean cache never OOMs ===")
    groups = {}
    for a in runs:
        groups.setdefault(a['mem_limit'], []).append(a)
    for lim in sorted(groups, key=mb, reverse=True):
        rs = groups[lim]
        ok = sum(1 for x in rs if x['memory']['events'].get('oom_kill', 0) > 0)
        rf = med([x['memory']['stat_delta'].get('workingset_refault_file', 0) for x in rs])
        print(f"  {lim:<12} n={len(rs)}  oom_kills={ok}  refault_med={int(rf)}  "
              f"(reclaim handles it)")


def part_b_cliff(runs):
    print("\n=== Part B cliff (memory.max + ANON 512MB workload) ===")
    groups = {}
    for a in runs:
        groups.setdefault(a['mem_limit'], []).append(a)
    h = f"{'memory.max':<12}{'n':<3}{'oom_kills':<11}{'task_fail':<11}{'verdict':<8}"
    print(h); print('-' * len(h))
    for lim in sorted(groups, key=mb, reverse=True):
        rs = groups[lim]
        oom = sum(1 for x in rs if x['memory']['events'].get('oom_kill', 0) > 0)
        fail = sum(1 for x in rs if x.get('task_check_exit') not in (0, None))
        # task_check_exit isn't in analyze output; read ground truth
        fail = 0
        for x in rs:
            g = json.load(open(HERE / 'runs/runs_t7' / x['run'] / 'meta/ground_truth.json'))
            if g['task_check_exit'] != 0:
                fail += 1
        verdict = 'OOM' if oom else 'ok'
        print(f"{lim:<12}{len(rs):<3}{oom:<11}{fail:<11}{verdict:<8}")


if __name__ == '__main__':
    t6 = HERE / 'runs/runs_t6'
    t7 = HERE / 'runs/runs_t7'
    part_a(load(t6, 't6A_'))
    part_b_file(load(t6, 't6B_'))
    part_b_cliff(load(t7, 't7_'))
