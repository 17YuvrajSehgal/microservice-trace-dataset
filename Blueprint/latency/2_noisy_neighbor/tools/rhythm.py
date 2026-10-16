"""
rhythm.py - how often the threads of one process get the CPU, in 10 ms buckets,
and whether that pattern repeats at a fixed period.

Usage:
    python3 rhythm.py <sched_events.txt> <pid> <slice_start HH:MM:SS> [seconds]

    <sched_events.txt>  a slice file made by extract_slice.sh
    <pid>               the process to look at
    <slice_start>       the start time of that slice (UTC), as given to extract_slice.sh
    [seconds]           how much of the slice to show (default 1.0)

Output:
    One line per 10 ms bucket: how many times a thread of <pid> was switched
    IN to a CPU, with a bar. Then a summary:
      quiet buckets  share of buckets with 0 or 1 switch-ins
      repeat         the period (in ms) at which the pattern repeats best, and
                     a score from -1 to 1 (1 = a perfect repeat)

How to read it:
    A CPU quota shows bursts, then quiet buckets, repeating at the quota
    period: a high share of quiet buckets and a high repeat score.
    A process that gets the CPU normally shows activity in most buckets, few
    quiet buckets, and a low repeat score.
    The thresholds below are rules of thumb, not tested limits.
"""
import re
import sys
from collections import defaultdict

BUCKET_NS = 10_000_000


def repeat_period(counts, min_lag=2, max_lag=50):
    """Best repeat lag (in buckets) and its score, by autocorrelation.
    Returns (None, 0.0) when the series is flat or too short."""
    n = len(counts)
    if n < 2 * min_lag + 2:
        return None, 0.0
    mean = sum(counts) / n
    d = [c - mean for c in counts]
    scores = {}
    for lag in range(min_lag, min(max_lag, n // 2) + 1):
        a, b = d[:-lag], d[lag:]
        num = sum(x * y for x, y in zip(a, b))
        den = (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5
        scores[lag] = num / den if den else 0.0
    if not scores:
        return None, 0.0
    best = max(scores.values())
    if best <= 0:
        return None, best
    # the shortest lag that is nearly as good as the best one (avoids picking 2x, 3x the period)
    lag = min(l for l, s in scores.items() if s >= 0.9 * best)
    return lag, scores[lag]


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    path, pid, start = sys.argv[1], sys.argv[2], sys.argv[3]
    span = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0

    re_t = re.compile(r'^\[(\d+):(\d+):(\d+)\.(\d+)\]')
    re_c = re.compile(r'pid = (\d+), tid = (\d+), procname')
    re_n = re.compile(r'next_tid = (\d+)')
    h, m, s = map(int, start.split(':'))
    t0 = ((h * 60 + m) * 60 + s) * 10**9

    tids, ins = set(), []
    with open(path) as f:
        for line in f:
            if ' sched_switch:' not in line:
                continue
            t = re_t.match(line)
            if not t:
                continue
            hh, mm, ss, fr = t.groups()
            ts = ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 10**9 + int(fr.ljust(9, '0'))
            c, n = re_c.search(line), re_n.search(line)
            if c and c.group(1) == pid:
                tids.add(c.group(2))
            if n:
                ins.append((ts, n.group(1)))

    if not tids:
        raise SystemExit(f"no thread of pid {pid} was seen in {path}")

    nb = int(span * 1e9 // BUCKET_NS)
    cnt = defaultdict(int)
    for ts, nt in ins:
        if nt in tids and t0 <= ts < t0 + span * 1e9:
            cnt[int((ts - t0) // BUCKET_NS)] += 1
    counts = [cnt[b] for b in range(nb)]

    for b, c in enumerate(counts):
        print(f"{b * 10:>5} ms {c:>5} {'#' * min(c // 2, 70)}")

    quiet = sum(1 for c in counts if c <= 1) / nb if nb else 0
    lag, score = repeat_period(counts)
    print()
    print(f"switch-ins     : {sum(counts)} in {span:g} s, {len(tids)} threads of pid {pid} seen in the file")
    print(f"quiet buckets  : {100 * quiet:.0f}% of 10 ms buckets have 0 or 1 switch-ins")
    if lag:
        strength = "strong" if score > 0.5 else "weak, probably no real beat"
        print(f"repeat         : every {lag * 10} ms (score {score:.2f}, {strength})")
    else:
        print("repeat         : no repeating pattern found")
    print("rule of thumb  : a quota beat usually shows quiet buckets above 50% and a repeat score above 0.5")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
