#!/bin/bash
# Problem #3 task: the agent runs a worker that reads a large file K times.
# Under a tight cgroup memory cap the page cache can't hold the file, so
# each pass re-reads from disk (refault I/O) - the recoverable memory-noise
# signal. The cap is set by collect_agent_run.sh (5th arg), NOT here; this
# task only fixes the workload (file size F, passes K), held constant across
# the dose-response. TASK_ARG = file size in MB (default 1024).
set -euo pipefail
DIR=$1
F_MB=${TASK_ARG:-1024}
K=5                      # passes, constant across the cap sweep
mkdir -p "$DIR" && cd "$DIR"
git init -q .

# Real zero-filled blocks on disk (not sparse) so reads cost real I/O when
# not cached. dd writes actual blocks; ext4/pd-balanced do not compress.
dd if=/dev/zero of=big.dat bs=1M count="$F_MB" status=none

cat > reader.py <<EOF
#!/usr/bin/env python3
# comm = ttmem (PR_SET_NAME=15) so the analyzer finds the workload phase.
# Reads big.dat sequentially K times in 1 MiB chunks, buffered (page cache).
import ctypes, time, os
try:
    ctypes.CDLL("libc.so.6").prctl(15, b"ttmem", 0, 0, 0)
except Exception:
    pass
K = $K
total = 0
t0 = time.time()
for p in range(K):
    with open("big.dat", "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            total += len(b)
os.makedirs("results", exist_ok=True)
with open("results/read.csv", "w") as out:
    out.write(f"{total},{K},{time.time()-t0:.3f}\n")
print(f"read {total} bytes over {K} passes in {time.time()-t0:.3f}s")
EOF
chmod +x reader.py

printf '#!/bin/bash\nset -e\n./reader.py\n' > touch_all.sh && chmod +x touch_all.sh

# success = worker read F_MB * K * 1048576 bytes (i.e. completed, not OOM-killed)
EXP=$(( F_MB * K * 1048576 ))
printf '[ "$(cut -d, -f1 results/read.csv 2>/dev/null)" = "%s" ]\n' "$EXP" > .check
cat > .prompt <<'EOF'
Run ./touch_all.sh and wait for it to finish. Then read results/read.csv
(format: total_bytes,passes,elapsed_seconds) and report the total bytes
read and the elapsed time.
EOF
printf 'big.dat\nresults/\n' > .gitignore
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
