#!/usr/bin/env python3
# cpu_ceiling.py - the per-period ceiling check for a CPU quota.
#
# A quota refills every period. When a capped process has more work than its
# quota, its on-CPU time PER PERIOD cannot exceed the quota, period after
# period - so the busy-period distribution sits at a ceiling BELOW the period.
# That sub-period ceiling is the quota's footprint.
#
# IMPORTANT - do not expect a FLAT line. A cgroup quota bounds the whole
# container (all its threads together), not one pid, and our 100 ms buckets do
# not align with the kernel's CFS periods. So a real cap on a multi-threaded or
# bursty victim (e.g. a JVM with several worker threads) shows a LOW but
# VARIABLE per-period value - it clusters below the period, it is not a razor
# line. Flatness is a bonus when you see it, never a requirement.
#
# Read a cap from the CONJUNCTION, not from this tool alone:
#   1. the busy-period ceiling here sits well BELOW the period, and (if you pass
#      a baseline slice) well below the same victim's baseline, AND
#   2. sched_budget.py shows the victim waiting runnable in those periods, AND
#   3. cpu_hogs.py shows the CPUs largely IDLE while it waits (CPU was available
#      but withheld - that is a quota; if the CPU went to other processes it is
#      competition, not a cap).
#
# Usage:
#   python3 cpu_ceiling.py <slice.txt> <victim_pid> [period_ms] [baseline_slice.txt]
#
#   <slice.txt>        scheduling events for the fault window (extract_slice.sh)
#   <victim_pid>       the victim's process id
#   [period_ms]        period from rhythm.py's repeat line, default 100
#   [baseline_slice]   optional: a quiet slice of the SAME victim, OUTSIDE the
#                      incident window. If given, the collapse (baseline ceiling
#                      -> fault ceiling) is printed - the clearest single sign.
import re
import sys

if len(sys.argv) < 3:
    print("usage: cpu_ceiling.py <slice.txt> <victim_pid> [period_ms] [baseline_slice.txt]",
          file=sys.stderr)
    sys.exit(1)
path, victim = sys.argv[1], sys.argv[2]
period_ms = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0
baseline_path = sys.argv[4] if len(sys.argv) > 4 else None
P = period_ms * 1e6                 # period in ns

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"')
re_sw = re.compile(r'prev_tid = (\d+), .*?next_tid = (\d+)')


def busy_periods(path, victim):
    """Return (name, vals, busy) for the victim's own activity window in one slice.
    vals = on-CPU ms per period across the window; busy = sorted vals with real work."""
    on = {}
    t0 = None
    buckets = {}
    first = last = None
    name = "?"

    def credit(since, until):
        nonlocal first, last
        if first is None or since < first:
            first = since
        if last is None or until > last:
            last = until
        i = int((since - t0) / P)
        while since < until:
            edge = t0 + (i + 1) * P
            end = min(until, edge)
            buckets[i] = buckets.get(i, 0) + (end - since)
            since = end
            i += 1

    with open(path, errors="replace") as f:
        for line in f:
            if ' sched_switch:' not in line:
                continue
            m = re_time.match(line)
            if not m:
                continue
            h, mi, s, fr = m.groups()
            t = ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1_000_000_000 + int(fr.ljust(9, '0'))
            if t0 is None:
                t0 = t
            c, sw = re_ctx.search(line), re_sw.search(line)
            if not c or not sw:
                continue
            prev_tid, next_tid = sw.groups()
            if prev_tid in on:
                if c.group(1) == victim:
                    credit(on[prev_tid], t)
                    name = c.group(2)
                del on[prev_tid]
            if next_tid != '0':
                on[next_tid] = t

    if not buckets or first is None:
        return name, [], []
    lo, hi = int((first - t0) / P), int((last - t0) / P)
    vals = [buckets.get(i, 0) / 1e6 for i in range(lo, hi + 1)]
    busy = sorted(v for v in vals if v > 0.05 * period_ms)
    return name, vals, busy


def pctile(busy, q):
    return busy[min(len(busy) - 1, int(q * len(busy)))]


name, vals, busy = busy_periods(path, victim)
if not vals:
    print(f"victim {victim}: no on-CPU time found in this slice. Wrong pid, or the victim "
          f"never ran here - pick a slice where it was active (sched_budget.py shows that).")
    sys.exit(0)

print(f"victim {victim} ({name}), period {period_ms:.0f} ms, "
      f"{len(vals)} periods in its active window ({len(busy)} busy)")
print(f"{'period':>7} {'on-CPU ms':>10}  (first 50 of the window)")
for i, v in enumerate(vals[:50]):
    bar = '#' * int(v / period_ms * 40)
    print(f"{i:>7} {v:>10.1f}  {bar}")

if not busy:
    print("\nno busy periods: the victim barely ran. No ceiling can be read from this slice.")
    sys.exit(0)

med, p90, mx = pctile(busy, 0.50), pctile(busy, 0.90), busy[-1]
ceiling = p90
near = sum(1 for v in busy if abs(v - ceiling) <= 0.15 * ceiling)
share = near / len(busy)
headroom = 1.0 - ceiling / period_ms          # how far the ceiling sits below the full period

print(f"\nbusy periods : median {med:.1f} ms, p90 {p90:.1f} ms, max {mx:.1f} ms "
      f"(out of {period_ms:.0f} ms)")
print(f"ceiling      : ~{ceiling:.1f} ms per {period_ms:.0f} ms  "
      f"(~{ceiling / period_ms:.2f} cores), sitting {headroom:.0%} below the full period")
print(f"flatness     : {share:.0%} of busy periods within 15% of the ceiling "
      f"(a bonus, NOT required - multi-threaded/bursty caps are not flat)")

if baseline_path:
    bname, bvals, bbusy = busy_periods(baseline_path, victim)
    if bbusy:
        bmed = pctile(bbusy, 0.50)
        print(f"baseline     : same victim, median {bmed:.1f} ms/period in the quiet slice")
        if med > 0 and bmed > med:
            print(f"collapse     : per-period ceiling FELL {bmed / med:.1f}x, from ~{bmed:.1f} ms "
                  f"(baseline) to ~{med:.1f} ms (fault) - a cap collapses it toward the quota.")
        else:
            print(f"collapse     : NONE - fault per-period (~{med:.1f} ms) is not below baseline "
                  f"(~{bmed:.1f} ms). No cap collapse here (check the baseline is truly quiet, "
                  f"or the victim is simply busier, not capped).")
    else:
        print("baseline     : victim had no busy periods in the baseline slice "
              "(it may have been idle there - try another quiet window).")

print()
print("Read it (combine with sched_budget + cpu_hogs; do NOT decide on flatness alone):")
print("- CAP footprint: the busy-period ceiling sits well BELOW the period (headroom high),")
print("  and - if you gave a baseline - well below the victim's own baseline. The quota in")
print("  cores is about ceiling / period. The periods need NOT be flat.")
print("- CONFIRM it is a quota and not competition: sched_budget shows the victim waiting")
print("  runnable in these periods, and cpu_hogs shows the CPUs IDLE while it waits.")
print("- NOT a cap: the ceiling reaches toward the full period, OR the victim is not waiting")
print("  runnable (it just had little work), OR the CPU went to other processes (competition).")
