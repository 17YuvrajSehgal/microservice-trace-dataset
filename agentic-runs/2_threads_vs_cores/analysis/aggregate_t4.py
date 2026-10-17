#!/usr/bin/env python3
"""Aggregate Part A (threads vs cores): medians per W.

Reuses analyze_run.py from problem #1. Reports the contention curve:
parallel-phase wall, per-worker on-CPU and runnable-wait, and the
scheduling-latency tail, vs worker count W (cores = 4 on the VM).
"""
import csv, json, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] /
                       '1_svc_cpu_cap/agentic-os-noise/analysis'))
from analyze_run import analyze

CORES = 4


def med(xs):
    return round(statistics.median(xs), 2) if xs else 0.0


def main(runs_dir):
    runs_dir = Path(runs_dir)
    rows = list(csv.DictReader(open(runs_dir / 'manifest.csv')))
    by_w = {}
    per_run = []
    for r in rows:
        d = runs_dir / r['run']
        if not d.exists():
            continue
        a = analyze(d)
        a['W'] = int(r['W'])
        per_run.append(a)
        by_w.setdefault(int(r['W']), []).append(a)

    print(f"\nPart A: {len(per_run)} runs, cores={CORES}\n")
    hdr = (f"{'W':<4}{'load':<7}{'n':<3}{'phase_wall_s':<14}"
           f"{'wkr_oncpu_s':<13}{'wkr_runnable_s':<16}{'stalls>=1ms':<12}{'stalls>=10ms':<13}")
    print(hdr); print('-' * len(hdr))
    summary = {}
    for w in sorted(by_w):
        rs = by_w[w]
        pw = med([x['workers']['phase_wall_s'] for x in rs])
        oc = med([x['workers']['worker_on_cpu_s_med'] for x in rs])
        rq = med([x['workers']['worker_runnable_s_med'] for x in rs])
        s1 = med([x['sched_latency']['ge_1ms'] for x in rs])
        s10 = med([x['sched_latency']['ge_10ms'] for x in rs])
        load = f"{w/CORES:.2f}x"
        print(f"{w:<4}{load:<7}{len(rs):<3}{pw:<14}{oc:<13}{rq:<16}{int(s1):<12}{int(s10):<13}")
        summary[w] = {'load': load, 'n': len(rs), 'phase_wall_s': pw,
                      'worker_on_cpu_s': oc, 'worker_runnable_s': rq,
                      'stalls_ge_1ms': s1, 'stalls_ge_10ms': s10}

    # dose-response vs the W=cores point (no contention baseline)
    base = summary.get(CORES, {}).get('phase_wall_s')
    if base:
        print(f"\n=== parallel-phase inflation vs W={CORES} (baseline {base}s) ===")
        for w in sorted(by_w):
            s = summary[w]
            infl = round(100 * (s['phase_wall_s'] - base) / base, 1)
            print(f"  W={w:<3} ({s['load']:<5}) phase {s['phase_wall_s']:<7} ({infl:+}%)"
                  f"  runnable {s['worker_runnable_s']}s")

    json.dump({'per_run': per_run, 'summary': {str(k): v for k, v in summary.items()}},
              open(runs_dir.parent / 'analysis/results_partA.json', 'w'), indent=2)
    print("\nfull per-run -> analysis/results_partA.json")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'runs')
