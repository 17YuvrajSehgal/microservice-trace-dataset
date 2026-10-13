#!/bin/bash
# Problem #2 Part B (observation): the agent launches N sub-agents via its
# Task tool, each running the same CPU worker. Tests whether the HARNESS's
# parallelism (sub-agents) turns into concurrent OS load the way Part A's
# explicit `xargs -P` does - and whether the harness checks the core count.
# N from TASK_ARG. Reuses the ttworker CPU worker from t4.
set -euo pipefail
DIR=$1
N=${TASK_ARG:?t5_subagents.sh needs TASK_ARG=<number of sub-agents>}
mkdir -p "$DIR" && cd "$DIR"
git init -q .

cat > work.py <<'EOF'
#!/usr/bin/env python3
# Fixed pure-CPU work (prime count), comm = ttworker (PR_SET_NAME=15), and
# writes results/s<id>.csv. Same worker as t4 so the analyzer finds it.
import ctypes, sys, time, os
try:
    ctypes.CDLL("libc.so.6").prctl(15, b"ttworker", 0, 0, 0)
except Exception:
    pass
wid = sys.argv[1]
t0 = time.time()
count = 0
for n in range(2, 120000):
    d = 2
    while d * d <= n:
        if n % d == 0:
            break
        d += 1
    else:
        count += 1
os.makedirs("results", exist_ok=True)
with open(f"results/s{wid}.csv", "w") as f:
    f.write(f"{wid},{count},{time.time()-t0:.3f}\n")
print(f"subagent {wid}: {time.time()-t0:.3f}s")
EOF
chmod +x work.py

printf '[ "$(ls results/*.csv 2>/dev/null | wc -l)" -eq %s ]\n' "$N" > .check
cat > .prompt <<EOF
Use your Task tool to launch $N sub-agents IN PARALLEL - issue all $N Task
calls in a SINGLE message so they run at the same time, not one after
another. Sub-agent number K (for K from 1 to $N) must run exactly this
shell command: ./work.py K
Wait for all $N sub-agents to finish, then report how many results/*.csv
files exist.
EOF
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
