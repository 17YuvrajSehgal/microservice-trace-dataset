#!/bin/bash
# Toy task (~10 s): one-line bug, one test. Plumbing checks only - too
# short for measurement runs.
set -euo pipefail
DIR=$1
mkdir -p "$DIR" && cd "$DIR"
git init -q .
printf 'def add(a, b):\n    return a - b\n' > calc.py
printf 'from calc import add\nassert add(2, 3) == 5\nprint("PASS")\n' > test_calc.py
printf 'python3 test_calc.py\n' > .check
cat > .prompt <<'EOF'
test_calc.py fails. Find the bug in calc.py, fix it, then run
python3 test_calc.py and confirm it prints PASS.
EOF
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
