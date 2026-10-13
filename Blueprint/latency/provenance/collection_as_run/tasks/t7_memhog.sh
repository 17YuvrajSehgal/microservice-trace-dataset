#!/bin/bash
# Problem #3 Part B (the real OOM cliff): a worker allocates and touches S MB
# of ANONYMOUS memory. Unlike file cache (reclaimable -> never OOMs), anon
# memory with no swap is unreclaimable, so under memory.max < agent+S the
# kernel OOM-kills the worker mid-task. TASK_ARG = anon MB (default 512).
set -euo pipefail
DIR=$1
S_MB=${TASK_ARG:-512}
mkdir -p "$DIR" && cd "$DIR"
git init -q .

cat > hog.py <<EOF
#!/usr/bin/env python3
# comm = ttmem; allocate S MB anonymous and touch every page (fault in).
# If OOM-killed, results/done.txt is never written -> .check fails = cliff.
import ctypes, os
try:
    ctypes.CDLL("libc.so.6").prctl(15, b"ttmem", 0, 0, 0)
except Exception:
    pass
S = $S_MB * 1024 * 1024
buf = bytearray(S)
for i in range(0, S, 4096):      # touch each page so it is really resident
    buf[i] = 1
os.makedirs("results", exist_ok=True)
with open("results/done.txt", "w") as f:
    f.write(f"allocated {S} bytes\n")
print(f"allocated and touched {S} bytes")
EOF
chmod +x hog.py

printf '#!/bin/bash\nset -e\n./hog.py\n' > run_hog.sh && chmod +x run_hog.sh
printf '[ -f results/done.txt ]\n' > .check
cat > .prompt <<'EOF'
Run ./run_hog.sh and wait for it to finish, then report whether
results/done.txt was created and what it says. If the command was killed,
report that instead.
EOF
printf 'results/\n' > .gitignore
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
