#!/usr/bin/env python3
# cpu_ceiling.py - the per-period ceiling check for a CPU quota.
#
# A quota refills every period. So when a capped process has more work than
# quota, its on-CPU time PER PERIOD sits at a flat ceiling near the quota,
# period after period. Without a cap it varies a lot. This is the direct
# quantitative signature of a cap, and it works even when the burst-and-freeze
# rhythm is weak (a bursty victim that idles between work spells shows little
# beat in wall-clock buckets, but its busy periods still hit the ceiling).
#
# Usage:
#   python3 cpu_ceiling.py <slice.txt> <victim_pid> [period_ms]
#
#   <slice.txt>   text file of scheduling events (made with extract_slice.sh)
#   <victim_pid>  the victim's process id
#   [period_ms]   the period from rhythm.py's repeat line, default 100
#
# Reads sched_switch only: a thread is on-CPU from the switch that brings it
# in (next_tid) to the switch that takes it out (prev_tid). The thread's pid
# is read from the event context at switch-out, same as sched_budget.py.
import re
import sys

if len(sys.argv) < 3:
    print("usage: cpu_ceiling.py <slice.txt> <victim_pid> [period_ms]", file=sys.stderr)
    sys.exit(1)
path, victim = sys.argv[1], sys.argv[2]
period_ms = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0
P = period_ms * 1e6                 # period in ns

re_time = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
re_ctx = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"')
re_sw = re.compile(r'prev_tid = (\d+), .*?next_tid = (\d+)')

on = {}          # tid -> since_ns, for threads currently on a CPU
t0 = None
buckets = {}     # period index -> victim on-CPU ns
first = last = None   # victim activity window
name = "?"


def credit(since, until):
    """Split one on-CPU interval across the fixed period grid."""
    global first, last
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
        # the context names the outgoing task: close its on-CPU interval
        if prev_tid in on:
            if c.group(1) == victim:
                credit(on[prev_tid], t)
                name = c.group(2)
            del on[prev_tid]
        if next_tid != '0':
            on[next_tid] = t

if not buckets:
    print(f"victim {victim}: no on-CPU time found in this slice. Wrong pid, or the victim "
          f"never ran here - pick a slice where it was active (sched_budget.py shows that).")
    sys.exit(0)

# only the periods inside the victim's own activity window count: a bursty victim
# is legitimately idle outside it, and those zeros are not evidence about a quota
lo, hi = int((first - t0) / P), int((last - t0) / P)
vals = [buckets.get(i, 0) / 1e6 for i in range(lo, hi + 1)]       # ms per period
busy = sorted(v for v in vals if v > 0.05 * period_ms)            # periods with real work
n = len(vals)

print(f"victim {victim} ({name}), period {period_ms:.0f} ms, "
      f"{n} periods in its active window ({len(busy)} busy)")
print(f"{'period':>7} {'on-CPU ms':>10}  (first 50 of the window)")
for i, v in enumerate(vals[:50]):
    bar = '#' * int(v / period_ms * 40)
    print(f"{i:>7} {v:>10.1f}  {bar}")

if not busy:
    print("\nno busy periods: the victim barely ran. No ceiling can be read from this slice.")
    sys.exit(0)


def pct(q):
    return busy[min(len(busy) - 1, int(q * len(busy)))]


med, p90, mx = pct(0.50), pct(0.90), busy[-1]
ceiling = p90
near = sum(1 for v in busy if abs(v - ceiling) <= 0.15 * ceiling)
share = near / len(busy)
print(f"\nbusy periods : median {med:.1f} ms, p90 {p90:.1f} ms, max {mx:.1f} ms "
      f"(out of {period_ms:.0f} ms)")
print(f"ceiling      : ~{ceiling:.1f} ms per {period_ms:.0f} ms  "
      f"(~{ceiling / period_ms:.2f} cores)")
print(f"flatness     : {share:.0%} of busy periods within 15% of the ceiling")
print()
print("Read it:")
print("- CAP: busy periods pile up at a flat ceiling well below the period")
print("  (flatness high, max ~ ceiling). The quota is about the ceiling;")
print("  the cap in cores is ceiling / period.")
print("- NO CAP: busy periods vary widely and the max runs toward the full")
print("  period (or beyond it, for a multi-threaded victim).")
