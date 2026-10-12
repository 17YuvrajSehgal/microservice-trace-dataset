import re, sys
from collections import defaultdict
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
bucket = 10_000_000
cnt = defaultdict(int)
for ts, nt in ins:
    if nt in tids and t0 <= ts < t0 + span * 1e9:
        cnt[int((ts - t0) // bucket)] += 1
for b in range(int(span * 1e9 // bucket)):
    print(f"{b*10:>5} ms {cnt[b]:>5} {'#' * min(cnt[b] // 2, 70)}")
