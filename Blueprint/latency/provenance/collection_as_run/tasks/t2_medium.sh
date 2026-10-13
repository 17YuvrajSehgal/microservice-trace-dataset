#!/bin/bash
# Medium bug-fix task (target ~60-120s uncapped). Three small modules,
# four independent bugs of different kinds, one test suite. Forces the
# agent to explore several files (Read/Grep), then iterate edit->test
# until green (repeated python subprocess + LLM round-trips = diverse,
# realistic trace). The suite's stress section burns bounded CPU on every
# invocation, so each test run is throttleable local work.
# Stdlib only, deterministic, always solvable - no pip/network/apt.
set -euo pipefail
DIR=$1
mkdir -p "$DIR" && cd "$DIR"
git init -q .

cat > stats.py <<'EOF'
def mean(xs):
    return sum(xs) / (len(xs) - 1)              # bug: wrong denominator

def variance(xs):
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / len(xs)

def median(xs):
    s = sorted(xs)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return s[n // 2]                              # bug: even case drops the pair average
EOF

cat > textproc.py <<'EOF'
def word_freq(text):
    freq = {}
    for w in text.split():
        w = w.lower().strip('.,!?;:')
        if w:
            freq[w] = freq.get(w, 0) + 1
    return freq

def top_words(text, k):
    freq = word_freq(text)
    ranked = sorted(freq.items(), key=lambda kv: kv[0])   # bug: by word, not count
    return [w for w, _ in ranked[:k]]
EOF

cat > seq.py <<'EOF'
def dedup(xs):
    # preserve first-seen order, drop later duplicates
    seen = set()
    out = []
    for x in xs:
        if x in seen:
            out.append(x)                        # bug: appends the duplicate instead of skipping
        else:
            seen.add(x)
    return out

def chunk(xs, n):
    return [xs[i:i + n] for i in range(0, len(xs), n)]
EOF

cat > test_all.py <<'EOF'
import time
from stats import mean, variance, median
from textproc import top_words, word_freq
from seq import dedup, chunk

# correctness
assert mean([2, 4, 6]) == 4
assert abs(variance([2, 4, 6]) - 8 / 3) < 1e-9
assert median([1, 3, 2]) == 2
assert median([1, 2, 3, 4]) == 2.5
assert word_freq("A a, b! a.")["a"] == 3
assert top_words("x x x y y z", 2) == ["x", "y"]
assert dedup([1, 2, 1, 3, 2]) == [1, 2, 3]
assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

# stress: bounded CPU, charged on every invocation (throttleable)
t0 = time.time()
data = [(i * 7919) % 1000 for i in range(4000)]
for _ in range(1200):
    mean(data); variance(data); median(data); dedup(data)
text = " ".join(str((i * 31) % 97) for i in range(15000))
for _ in range(120):
    top_words(text, 10)
print(f"stress {time.time() - t0:.1f}s")
print("ALL PASS")
EOF

printf 'python3 test_all.py | grep -q "ALL PASS"\n' > .check
cat > .prompt <<'EOF'
This small Python project has a failing test suite (test_all.py). There
are bugs spread across stats.py, textproc.py, and seq.py. Do NOT edit
test_all.py. Find and fix the bugs in the source files, re-running
`python3 test_all.py` after each change, until it prints ALL PASS.
EOF
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
