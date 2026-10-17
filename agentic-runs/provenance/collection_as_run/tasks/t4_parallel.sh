#!/bin/bash
# Problem #2 (threads vs cores) task: the agent launches W identical
# pure-CPU workers in parallel (xargs -P W) and reports the slowest.
# W comes from TASK_ARG (collect_agent_run.sh 4th arg). The worker runs
# as ./worker.py so its kernel comm is "worker.py" - the analyzer finds
# the parallel phase by that name.
set -euo pipefail
DIR=$1
W=${TASK_ARG:?t4_parallel.sh needs TASK_ARG=<number of workers>}
mkdir -p "$DIR" && cd "$DIR"
git init -q .

cat > worker.py <<'EOF'
#!/usr/bin/env python3
# Fixed pure-CPU work: trial-division prime count. Identical for every
# worker, so any elapsed-time spread between workers is scheduling.
import ctypes, sys, time

# Set kernel comm to "ttworker" so the trace tags the parallel phase
# distinctly (the shebang would otherwise make comm "python3", which
# collides with the agent's own python3). PR_SET_NAME = 15.
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
elapsed = time.time() - t0
with open(f"results/w{wid}.csv", "w") as f:
    f.write(f"{wid},{count},{elapsed:.3f}\n")
print(f"worker {wid}: {elapsed:.3f}s")
EOF
chmod +x worker.py

cat > run_all.sh <<EOF
#!/bin/bash
set -e
mkdir -p results
rm -f results/*.csv
seq 1 $W | xargs -P $W -n1 ./worker.py
echo "all $W workers done"
EOF
chmod +x run_all.sh

printf '[ "$(ls results/*.csv 2>/dev/null | wc -l)" -eq %s ]\n' "$W" > .check
cat > .prompt <<'EOF'
Run ./run_all.sh and wait for it to finish. Then read the results/*.csv
files (format: worker_id,prime_count,elapsed_seconds) and report which
worker was slowest and its elapsed time.
EOF
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
