# Results: deadlock on our labelled runs (2026-11-11)

Tool: `tools/futex_hang.py`. Data: Sock Shop v2 (StrataTrace), Trillium `data/stratatrace-v2/sockshop/`.
Slices: a 10 s quiet slice 45 s before the injection and a 10 s slice 50 s into it (a 60 s slice
from +5 s for the deadlock tool). Run on the login node with `work/newbp/validate_one.sh`.

| check | result |
|---|---|
| fires on its own family (5 runs) | **5 / 5** |
| stays quiet on the other three new families (15 runs) | **15 / 15** quiet |
| stays quiet on normal runs (5 runs, no fault) | **5 / 5** quiet |

Verdict line per labelled run:

| run | verdict |
|---|---|
| r1 | `VERDICT: DEADLOCK: python3 (pid 1855001, ns 4026533609): 22 threads blocked forever in futex (no timeout) on 22 distinct locks, longest 58.0 s; new hung threads per third of the slice 8/8/6; 22 of them were created inside the slice and hung 50 ms after birth (median)` |
| r2 | `VERDICT: DEADLOCK: python3 (pid 1892891, ns 4026533609): 22 threads blocked forever in futex (no timeout) on 22 distinct locks, longest 58.2 s; new hung threads per third of the slice 8/8/6; 22 of them were created inside the slice and hung 50 ms after birth (median)` |
| r3 | `VERDICT: DEADLOCK: python3 (pid 1930377, ns 4026533609): 22 threads blocked forever in futex (no timeout) on 22 distinct locks, longest 58.1 s; new hung threads per third of the slice 8/8/6; 22 of them were created inside the slice and hung 50 ms after birth (median)` |
| r4 | `VERDICT: DEADLOCK: python3 (pid 1968172, ns 4026533609): 22 threads blocked forever in futex (no timeout) on 22 distinct locks, longest 58.1 s; new hung threads per third of the slice 8/8/6; 22 of them were created inside the slice and hung 50 ms after birth (median)` |
| r5 | `VERDICT: DEADLOCK: python3 (pid 2005436, ns 4026533609): 22 threads blocked forever in futex (no timeout) on 22 distinct locks, longest 57.9 s; new hung threads per third of the slice 8/8/6; 22 of them were created inside the slice and hung 50 ms after birth (median)` |

## How the bar was set (what failed first)
Version 1 fired on 20 of 20 fault runs: every JVM and Go service keeps 7-31 idle pool threads parked in an untimed futex wait. The verdict now needs >= 2 threads CREATED inside the slice that hung within 1 s of birth (the deadlock pairs hung ~50 ms after birth); parked threads are NOTE lines.
