#!/usr/bin/env python3
"""Aggregate analyze_run over every campaign run -> by-cap summary.

Reads runs/manifest.csv, analyzes each run, and reports medians per
(task, cap) plus the headline cross-cap curve: wall-time inflation and
CFS throttle vs cap level.
"""
import csv, json, statistics, sys
from pathlib import Path
from analyze_run import analyze

CAP_ORDER = {'nocap': 0, 'cap100': 1, 'cap50': 2, 'cap25': 3}
CAP_LABEL = {'nocap': 'uncapped', 'cap100': '1 core', 'cap50': '0.5 core', 'cap25': '0.25 core'}


def med(xs):
    return round(statistics.median(xs), 2) if xs else 0.0


def main(runs_dir):
    runs_dir = Path(runs_dir)
    rows = list(csv.DictReader(open(runs_dir / 'manifest.csv')))
    results = []
    for r in rows:
        d = runs_dir / r['run']
        if not d.exists():
            continue
        a = analyze(d)
        a['task'] = r['task']
        a['cap_name'] = r['cap_name']
        results.append(a)

    # group by (task, cap)
    groups = {}
    for a in results:
        groups.setdefault((a['task'], a['cap_name']), []).append(a)

    print(f"\nAnalyzed {len(results)} runs\n")
    hdr = f"{'task':<16}{'cap':<11}{'n':<3}{'wall_s':<9}{'on_cpu_s':<10}{'throttled_s':<13}{'eventloop_s':<12}"
    print(hdr); print('-' * len(hdr))
    summary = {}
    for (task, cap), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], CAP_ORDER[kv[0][1]])):
        wall = med([x['wall_s'] for x in rs])
        oncpu = med([x['subtree_cpu_seconds']['on_cpu'] for x in rs])
        thr = med([x['cpu_stat']['throttled_s'] for x in rs])
        evl = med([x['main_thread_wall_s'].get('wait_eventloop', 0) for x in rs])
        print(f"{task:<16}{CAP_LABEL[cap]:<11}{len(rs):<3}{wall:<9}{oncpu:<10}{thr:<13}{evl:<12}")
        summary[f"{task}:{cap}"] = {'n': len(rs), 'wall_s': wall, 'on_cpu_s': oncpu,
                                    'throttled_s': thr, 'eventloop_wait_s': evl}

    # headline: wall inflation vs uncapped, per task
    print("\n=== wall-time inflation vs uncapped (median) ===")
    for task in sorted(set(t for t, _ in groups)):
        base = summary.get(f"{task}:nocap", {}).get('wall_s')
        if not base:
            continue
        print(f"\n{task}  (uncapped baseline {base}s)")
        for cap in ['cap100', 'cap50', 'cap25']:
            s = summary.get(f"{task}:{cap}")
            if s:
                infl = round(100 * (s['wall_s'] - base) / base, 1)
                print(f"  {CAP_LABEL[cap]:<10} wall {s['wall_s']:<7} (+{infl}%)  throttled {s['throttled_s']}s")

    json.dump({'per_run': results, 'summary': summary},
              open(runs_dir.parent / 'analysis/results/campaign.json', 'w'), indent=2)
    print("\nfull per-run output -> analysis/results/campaign.json")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'runs')
