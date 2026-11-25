#!/usr/bin/env python3
# cpu_starved.py - find one container whose threads wait for a core far more than before,
# while the other containers do not.
#
# A low CPU weight is a share, not a limit. On a busy host the scheduler serves the other
# containers first, and the threads of the low-weight container stay "ready" for a long time
# for every moment they run. Nothing is capped and no core is taken away.
#
# For each container (pid namespace), in a baseline slice and a fault slice:
#   cores      CPU it used
#   CPU wait   thread-seconds per second its threads were ready and waiting for a core
#   wait/core  CPU wait divided by cores: how long a thread waits per second it runs
# A starved container has a high wait/core now and a much lower one before.
#
# It reads the scheduling events (sched_switch, sched_waking, sched_wakeup), with the reader of
# cpu_confine.py (same folder).
#
# Usage:
#   python3 cpu_starved.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>
#   python3 cpu_starved.py --selftest
#
#   both slices cut with: extract_slice.sh TRACE DAY HH:MM:SS 20 out.txt 'sched_switch|sched_waking|sched_wakeup'
#
# THE SAME PICTURE HAS TWO OTHER CAUSES, and this tool cannot tell them apart:
#   - a CPU quota (svc_cpu_cap): threads of a throttled container also count as ready. On the
#     v2 runs the aggressive quota gives wait/core 29-31 (rise 54-58). Check for a quota with
#     the cpu-cap blueprint (a ceiling with a 100 ms period) before calling it a weight.
#   - a small cpuset (svc_cpuset): wait/core 1.9-2.4 there, below this tool's bar; cpu_confine.py
#     names it.
import os
import sys
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cpu_confine import read            # noqa: E402

MIN_CORES = 0.2        # the container must use at least this much CPU in both slices
MIN_THREADS = 8
MIN_WAIT_PER_CORE = 5.0    # its threads wait 5 s for every second they run
MIN_RISE = 4.0             # ... and that is 4 times the baseline
# Where the bars come from (25-11-2026): the wait/core numbers of every container in the 347
# runs of the sweep (job 2931081). cpu_weight: 10.6-19.9, rise 4.5-8.9. All 20 normal runs:
# at most 1.2, rise at most 2.0. Host-wide CPU stress (anomaly_cpu): 1.2-1.6. Set after seeing
# those numbers, so the 5 cpu_weight runs are not an independent test of the bars.


def rows_of(base, fault, secs):
    rows = []
    for ns, percpu in fault["oncpu"].items():
        if ns == '0' or ns not in base["oncpu"]:
            continue
        fc, bc = sum(percpu.values()) / secs, sum(base["oncpu"][ns].values()) / secs
        if min(fc, bc) < MIN_CORES or len(fault["tids"][ns]) < MIN_THREADS:
            continue
        fw, bw = fault["wait"].get(ns, 0.0) / secs, base["wait"].get(ns, 0.0) / secs
        now, before = fw / fc, bw / bc
        rows.append({"ns": ns, "name": max(fault["names"][ns], key=fault["names"][ns].get), "fc": fc, "bc": bc, "fw": fw, "bw": bw,
                     "now": now, "before": before, "rise": now / max(before, 0.02)})
    return sorted(rows, key=lambda r: -r["now"])


def report(base, fault, secs):
    rows = rows_of(base, fault, secs)
    ncpu = max(1, fault["ncpu"])
    idle = sum(fault["idle"].values()) / (fault["span"] * ncpu)
    out = [f"{ncpu} CPUs, {idle:.0%} idle in the fault slice. Containers with {MIN_THREADS}+ threads and {MIN_CORES}+ cores in both slices:",
           f"  {'pid_ns':>12} {'program':<16} {'cores before':>13} {'cores now':>10} {'CPU wait before':>16} {'CPU wait now':>13} "
           f"{'wait/core before':>17} {'wait/core now':>14} {'rise':>6}"]
    for r in rows[:12]:
        out.append(f"  {r['ns']:>12} {r['name']:<16} {r['bc']:>13.2f} {r['fc']:>10.2f} {r['bw']:>16.2f} {r['fw']:>13.2f} "
                   f"{r['before']:>17.2f} {r['now']:>14.2f} {r['rise']:>6.1f}")
    out.append("  CPU wait = thread-seconds per second its threads were ready and waiting for a core; wait/core = CPU wait / cores used")
    hits = 0
    for r in rows:
        if r["now"] < MIN_WAIT_PER_CORE or r["rise"] < MIN_RISE:
            continue
        others = [x["rise"] for x in rows if x["ns"] != r["ns"]]
        out.append(f"VERDICT: ONE CONTAINER IS STARVED OF CPU: {r['name']} (pid_ns {r['ns']}): its threads wait {r['fw']:.2f} thread-seconds "
                   f"per second for {r['fc']:.2f} cores of work (wait/core {r['now']:.1f}, {r['before']:.2f} in the baseline, {r['rise']:.1f} times); "
                   f"the other {len(others)} containers' wait/core changed {median(others) if others else 1.0:.1f} times (median); host {idle:.0%} idle. "
                   f"A low CPU weight on a busy host, OR a CPU quota - check for a quota before deciding")
        hits += 1
    if not hits:
        top = rows[0] if rows else None
        why = (f"highest: {top['name']} (pid_ns {top['ns']}) wait/core {top['now']:.2f}, {top['before']:.2f} before" if top
               else "no container is active in both slices")
        out.append(f"VERDICT: NO CONTAINER STARVED OF CPU ({why}; the bars are wait/core {MIN_WAIT_PER_CORE:.0f} and {MIN_RISE:.0f} times the baseline)")
    return out


def selftest():
    def data(carts_wait, others_wait, idle_share):
        d = {"oncpu": {}, "tids": {}, "names": {}, "wait": {}, "idle": {str(c): 20.0 * idle_share for c in range(4)}, "ncpu": 4, "span": 20.0}
        for ns, nm, cores, w in (("11", "java", 0.4, carts_wait), ("12", "node", 1.0, others_wait), ("13", "app", 0.5, others_wait)):
            d["oncpu"][ns] = {"0": cores * 20.0}
            d["tids"][ns] = set(range(10))
            d["names"][ns] = {nm: 1.0}
            d["wait"][ns] = w * 20.0
        return d
    base = data(0.4, 0.3, 0.5)
    out = "\n".join(report(base, data(6.0, 0.35, 0.0), 20))
    assert "ONE CONTAINER IS STARVED OF CPU: java (pid_ns 11): its threads wait 6.00 thread-seconds per second for 0.40 cores of work (wait/core 15.0, 1.00 in the baseline, 15.0 times)" in out, out
    assert out.count("VERDICT") == 1, out
    # everybody waits more (host-wide CPU stress): nobody reaches the bar
    out = "\n".join(report(base, data(0.9, 1.2, 0.0), 20))
    assert "NO CONTAINER STARVED OF CPU" in out, out
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: cpu_starved.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], errors="replace") as f:
        b = read(f)
    with open(sys.argv[2], errors="replace") as f:
        fa = read(f)
    print("\n".join(report(b, fa, float(sys.argv[3]))))
