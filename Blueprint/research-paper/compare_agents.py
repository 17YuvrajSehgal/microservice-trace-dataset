#!/usr/bin/env python3
"""Full Claude-vs-Codex comparison across all four problems.
Claude: original runs. Codex: runs_codex* under agentic-os-noise/.
Prints per-cell medians for both agents side by side."""
import csv, json, statistics, sys
from pathlib import Path

LAT = Path(__file__).resolve().parents[1] / 'latency'
AON = LAT / '1_svc_cpu_cap/agentic-os-noise'
sys.path.insert(0, str(AON / 'analysis'))
from analyze_run import analyze
sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_wait as LW


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else 0.0


def rows(runs_dir, keyfield, prefix=None):
    out = {}
    for r in csv.DictReader(open(runs_dir / 'manifest.csv')):
        if prefix and not r['run'].startswith(prefix):
            continue
        d = runs_dir / r['run']
        if d.exists():
            out.setdefault(r[keyfield], []).append(d)
    return out


def thr(d):
    rd = lambda p: {l.split()[0]: int(l.split()[1]) for l in (d/p).read_text().splitlines()}
    b, a = rd('meta/cpu.stat.before'), rd('meta/cpu.stat.after')
    return (a['throttled_usec'] - b['throttled_usec']) / 1e6


def gtv(d, k):
    return json.load(open(d/'meta/ground_truth.json'))[k]


print("=" * 64)
print("PROBLEM 1 — CPU cap (throttle s / wall s / model%wall), task t3")
print("=" * 64)
cl = rows(AON/'runs', 'cap_name')              # wait: claude #1 lives elsewhere
cl = {}
for r in csv.DictReader(open(LAT/'1_svc_cpu_cap/agentic-os-noise/runs/manifest.csv')):
    if r['task'] == 't3_implement.sh':
        d = LAT/'1_svc_cpu_cap/agentic-os-noise/runs'/r['run']
        if d.exists(): cl.setdefault(r['cap_name'], []).append(d)
cx = {}
for r in csv.DictReader(open(AON/'runs_codex/manifest.csv')):
    if r['task'] == 't3_implement.sh':
        d = AON/'runs_codex'/r['run']
        if d.exists(): cx.setdefault(r['cap_name'], []).append(d)
print(f"{'cap':<8}{'agent':<8}{'throttle':<10}{'wall':<8}{'model%'}")
for cap in ('nocap', 'cap100', 'cap50', 'cap25'):
    for label, g in (('claude', cl), ('codex', cx)):
        ds = g.get(cap, [])
        t = med([thr(d) for d in ds])
        w = med([LW.measure(d)['wall_s'] for d in ds])
        mp = med([LW.measure(d)['model_pct_wall'] for d in ds])
        print(f"{cap:<8}{label:<8}{t:<10}{w:<8}{mp}")

print("\n" + "=" * 64)
print("PROBLEM 2A — threads vs cores (phase s / runnable/wkr s)")
print("=" * 64)
cl = rows(LAT/'2_threads_vs_cores/runs', 'W')
cx = rows(AON/'runs_codex_t4', 'W')
print(f"{'W':<4}{'agent':<8}{'phase':<9}{'runnable/wkr'}")
for W in ('2', '4', '8', '16'):
    for label, g in (('claude', cl), ('codex', cx)):
        ds = g.get(W, [])
        ph = med([(analyze(d)['workers'] or {}).get('phase_wall_s') for d in ds])
        rq = med([(analyze(d)['workers'] or {}).get('worker_runnable_s_med') for d in ds])
        print(f"{W:<4}{label:<8}{ph:<9}{rq}")

print("\n" + "=" * 64)
print("PROBLEM 3A — memory.high (phase s / refault M)")
print("=" * 64)
cl = rows(LAT/'3_memory_cap/runs/runs_t6', 'mem_limit', 't6A_')
cx = rows(AON/'runs_codex_t6', 'mem_limit', 't6A_')
order = {'high:max':0,'high:1536M':1,'high:1152M':2,'high:768M':3}
print(f"{'mem.high':<12}{'agent':<8}{'phase':<9}{'refault(M)'}")
for lim in sorted(set(cl)|set(cx), key=lambda k: order.get(k,9)):
    for label, g in (('claude', cl), ('codex', cx)):
        ds = g.get(lim, [])
        ph = med([(analyze(d)['workers'] or {}).get('phase_wall_s') for d in ds])
        rf = med([(analyze(d)['memory'] or {}).get('stat_delta',{}).get('workingset_refault_file',0)/1e6 for d in ds])
        print(f"{lim:<12}{label:<8}{ph:<9}{round(rf,2)}")

print("\n" + "=" * 64)
print("PROBLEM 3 cliff — memory.max+anon (OOM / task-fail counts)")
print("=" * 64)
cl = rows(LAT/'3_memory_cap/runs/runs_t7', 'mem_limit')
cx = rows(AON/'runs_codex_t7', 'mem_limit')
print(f"{'mem.max':<10}{'agent':<8}{'n':<4}{'oom':<5}{'fail'}")
for lim in sorted(set(cl)|set(cx), key=lambda k: int(k.split(':')[1].rstrip('M')), reverse=True):
    for label, g in (('claude', cl), ('codex', cx)):
        ds = g.get(lim, [])
        oom = sum(1 for d in ds if (analyze(d)['memory'] or {}).get('events',{}).get('oom_kill',0) > 0)
        fail = sum(1 for d in ds if gtv(d,'task_check_exit') != 0)
        print(f"{lim:<10}{label:<8}{len(ds):<4}{oom:<5}{fail}")

print("\n" + "=" * 64)
print("PROBLEM 4 — io.max rbps (phase s)")
print("=" * 64)
cl = rows(LAT/'4_io_cap/runs', 'rbps')
cx = rows(AON/'runs_codex_t8', 'rbps')
key = lambda k: float('inf') if k == 'none' else int(k)
print(f"{'rbps':<12}{'agent':<8}{'phase'}")
for rb in sorted(set(cl)|set(cx), key=key, reverse=True):
    lbl = 'unlimited' if rb == 'none' else f"{int(rb)//1048576}MB/s"
    for label, g in (('claude', cl), ('codex', cx)):
        ds = g.get(rb, [])
        ph = med([(analyze(d)['workers'] or {}).get('phase_wall_s') for d in ds])
        print(f"{lbl:<12}{label:<8}{ph}")
