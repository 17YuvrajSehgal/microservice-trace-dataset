#!/usr/bin/env python3
"""Recompute per-cell stats (median, min, max across reps) for all four
problems, for the paper's tables and PGFPlots figures. Prints a compact
report; numbers are copied into paper.tex by hand (evidence-first).
"""
import csv, json, statistics, sys
from pathlib import Path

LAT = Path(__file__).resolve().parents[1] / 'latency'
sys.path.insert(0, str(LAT / '1_svc_cpu_cap/agentic-os-noise/analysis'))
from analyze_run import analyze


def stat(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return (0, 0, 0)
    return (round(statistics.median(xs), 2), round(min(xs), 2), round(max(xs), 2))


def cell(runs, get):
    return stat([get(a) for a in runs])


def load(runs_dir, keyfield):
    rows = list(csv.DictReader(open(runs_dir / 'manifest.csv')))
    groups = {}
    for r in rows:
        d = runs_dir / r['run']
        if d.exists():
            groups.setdefault(r[keyfield], []).append(analyze(d))
    return groups


def gt(run_dir):
    return json.load(open(run_dir / 'meta/ground_truth.json'))


print("# ===== Problem 1: CPU cap (by task x cap) =====")
g = load(LAT / '1_svc_cpu_cap/agentic-os-noise/runs', 'cap_name')
# need task too; reload with both
rows = list(csv.DictReader(open(LAT / '1_svc_cpu_cap/agentic-os-noise/runs/manifest.csv')))
byc = {}
for r in rows:
    d = LAT / '1_svc_cpu_cap/agentic-os-noise/runs' / r['run']
    if d.exists():
        byc.setdefault((r['task'], r['cap_name']), []).append(analyze(d))
print(f"{'task':<16}{'cap':<9}{'wall med[min-max]':<22}{'on_cpu':<9}{'throttle med':<13}")
for (task, cap) in sorted(byc, key=lambda k: (k[0], ['nocap','cap100','cap50','cap25'].index(k[1]))):
    rs = byc[(task, cap)]
    w = cell(rs, lambda a: a['wall_s'])
    oc = cell(rs, lambda a: a['subtree_cpu_seconds']['on_cpu'])
    th = cell(rs, lambda a: a['cpu_stat']['throttled_s'])
    print(f"{task:<16}{cap:<9}{str(w):<22}{oc[0]:<9}{str(th):<13}")

print("\n# ===== Problem 2A: threads vs cores (by W) =====")
by = load(LAT / '2_threads_vs_cores/runs', 'W')
print(f"{'W':<4}{'phase med[min-max]':<22}{'oncpu/wkr':<11}{'runnable/wkr':<14}{'stalls>=1ms':<12}{'stalls>=10ms'}")
for w in sorted(by, key=int):
    rs = by[w]
    ph = cell(rs, lambda a: a['workers']['phase_wall_s'])
    oc = cell(rs, lambda a: a['workers']['worker_on_cpu_s_med'])
    rq = cell(rs, lambda a: a['workers']['worker_runnable_s_med'])
    s1 = cell(rs, lambda a: a['sched_latency']['ge_1ms'])
    s10 = cell(rs, lambda a: a['sched_latency']['ge_10ms'])
    print(f"{w:<4}{str(ph):<22}{oc[0]:<11}{rq[0]:<14}{int(s1[0]):<12}{int(s10[0])}")

print("\n# ===== Problem 3A: memory.high (by cap) =====")
rows = list(csv.DictReader(open(LAT / '3_memory_cap/runs/runs_t6/manifest.csv')))
bym = {}
for r in rows:
    if not r['run'].startswith('t6A_'):
        continue
    d = LAT / '3_memory_cap/runs/runs_t6' / r['run']
    if d.exists():
        bym.setdefault(r['mem_limit'], []).append(analyze(d))
order = {'high:max': 0, 'high:1536M': 1, 'high:1152M': 2, 'high:768M': 3}
print(f"{'memory.high':<14}{'phase med[min-max]':<22}{'refault med':<14}{'high_events':<12}")
for lim in sorted(bym, key=lambda k: order.get(k, 9)):
    rs = bym[lim]
    ph = cell(rs, lambda a: a['workers']['phase_wall_s'] if a['workers'] else None)
    rf = cell(rs, lambda a: a['memory']['stat_delta'].get('workingset_refault_file', 0))
    hi = cell(rs, lambda a: a['memory']['events'].get('high', 0))
    print(f"{lim:<14}{str(ph):<22}{int(rf[0]):<14}{int(hi[0]):<12}")

print("\n# ===== Problem 3B cliff: memory.max + anon (by cap) =====")
rows = list(csv.DictReader(open(LAT / '3_memory_cap/runs/runs_t7/manifest.csv')))
byx = {}
for r in rows:
    d = LAT / '3_memory_cap/runs/runs_t7' / r['run']
    if d.exists():
        byx.setdefault(r['mem_limit'], []).append((analyze(d), gt(d)))
print(f"{'memory.max':<12}{'n':<3}{'oom_kills':<11}{'task_fail':<11}")
for lim in sorted(byx, key=lambda k: int(k.split(':')[1].rstrip('M')), reverse=True):
    rs = byx[lim]
    oom = sum(1 for a, _ in rs if a['memory']['events'].get('oom_kill', 0) > 0)
    fail = sum(1 for _, g in rs if g['task_check_exit'] != 0)
    print(f"{lim:<12}{len(rs):<3}{oom:<11}{fail:<11}")

print("\n# ===== Problem 4: io.max rbps (by cap) =====")
by = load(LAT / '4_io_cap/runs', 'rbps')
print(f"{'rbps':<12}{'phase med[min-max]':<22}{'io.stat rbytes med':<20}")
for rb in sorted(by, key=lambda k: float('inf') if k == 'none' else int(k), reverse=True):
    rs = by[rb]
    ph = cell(rs, lambda a: a['workers']['phase_wall_s'] if a['workers'] else None)
    rby = cell(rs, lambda a: a['io']['rbytes'] if a['io'] else 0)
    label = 'unlimited' if rb == 'none' else f"{int(rb)//1048576}MB/s"
    print(f"{label:<12}{str(ph):<22}{int(rby[0]):<20}")
