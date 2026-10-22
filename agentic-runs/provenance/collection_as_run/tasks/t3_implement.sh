#!/bin/bash
# Medium implement-from-spec task (target ~60-120s uncapped). Different
# agent behavior than t2: the agent WRITES new code to satisfy docstrings
# + a given test suite, rather than hunting bugs. Diversifies the trace
# set across task types (write-heavy vs read/fix-heavy).
# Stdlib only, deterministic, always solvable - no pip/network/apt.
set -euo pipefail
DIR=$1
mkdir -p "$DIR" && cd "$DIR"
git init -q .

cat > rle.py <<'EOF'
def encode(s):
    """Run-length encode a string: 'aaabbc' -> 'a3b2c1'.
    Empty string -> ''. Single run counts included (always a count)."""
    raise NotImplementedError

def decode(s):
    """Inverse of encode: 'a3b2c1' -> 'aaabbc'. Counts are 1+ digits."""
    raise NotImplementedError
EOF

cat > intervals.py <<'EOF'
def merge(ivals):
    """Merge overlapping [start, end] intervals (end inclusive touch
    merges: [1,2],[2,3] -> [1,3]). Input unsorted; return sorted by start."""
    raise NotImplementedError
EOF

cat > test_impl.py <<'EOF'
import time
from rle import encode, decode
from intervals import merge

assert encode("") == ""
assert encode("aaabbc") == "a3b2c1"
assert decode("a3b2c1") == "aaabbc"
assert decode(encode("xxxxxxxxxx yy")) == "xxxxxxxxxx yy"
assert merge([[1, 3], [2, 6], [8, 10]]) == [[1, 6], [8, 10]]
assert merge([[2, 3], [1, 2]]) == [[1, 3]]
assert merge([]) == []

# stress: bounded CPU, charged on every invocation (throttleable)
t0 = time.time()
base = "".join(chr(97 + (i * 7) % 5) for i in range(2000))
for _ in range(2500):
    assert decode(encode(base)) == base
print(f"stress {time.time() - t0:.1f}s")
print("ALL PASS")
EOF

printf 'python3 test_impl.py | grep -q "ALL PASS"\n' > .check
cat > .prompt <<'EOF'
Implement the functions in rle.py and intervals.py so that the test suite
test_impl.py passes. Follow the docstrings. Do NOT edit test_impl.py. Run
`python3 test_impl.py` after writing each function, and keep going until it
prints ALL PASS.
EOF
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
