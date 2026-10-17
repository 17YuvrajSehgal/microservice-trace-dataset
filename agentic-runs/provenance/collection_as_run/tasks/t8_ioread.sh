#!/bin/bash
# Problem #4 task: the agent runs a worker that reads a large file ONCE from
# disk. Caches are dropped by the collector (IO run), so the whole read hits
# the block device and is rate-limited by the cgroup's io.max rbps. The cap
# is set by collect_agent_run.sh (6th arg), not here. TASK_ARG = file MB.
set -euo pipefail
DIR=$1
F_MB=${TASK_ARG:-1024}
mkdir -p "$DIR" && cd "$DIR"
git init -q .

dd if=/dev/zero of=big.dat bs=1M count="$F_MB" status=none

cat > reader.py <<'EOF'
#!/usr/bin/env python3
# comm = ttio; read big.dat once in 1 MiB chunks (buffered device reads).
import ctypes, time, os
try:
    ctypes.CDLL("libc.so.6").prctl(15, b"ttio", 0, 0, 0)
except Exception:
    pass
total = 0
t0 = time.time()
with open("big.dat", "rb") as f:
    while True:
        b = f.read(1 << 20)
        if not b:
            break
        total += len(b)
os.makedirs("results", exist_ok=True)
with open("results/read.csv", "w") as out:
    out.write(f"{total},{time.time()-t0:.3f}\n")
print(f"read {total} bytes in {time.time()-t0:.3f}s")
EOF
chmod +x reader.py
printf '#!/bin/bash\nset -e\n./reader.py\n' > read_once.sh && chmod +x read_once.sh

EXP=$(( F_MB * 1048576 ))
printf '[ "$(cut -d, -f1 results/read.csv 2>/dev/null)" = "%s" ]\n' "$EXP" > .check
cat > .prompt <<'EOF'
Run ./read_once.sh and wait for it to finish. Then read results/read.csv
(format: total_bytes,elapsed_seconds) and report the total bytes read and
the elapsed time.
EOF
printf 'big.dat\nresults/\n' > .gitignore
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
