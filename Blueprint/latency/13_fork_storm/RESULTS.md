# Results: fork_storm on our labelled runs (2026-11-11)

Tool: `tools/proc_spawn.py`. Data: Sock Shop v2 (StrataTrace), Trillium `data/stratatrace-v2/sockshop/`.
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
| r1 | `VERDICT: PROCESS STORM: python3 (ns 4026533601) created 1000 processes in 10 s (100/s; baseline 0.0/s); 1000 exits in that namespace` |
| r2 | `VERDICT: PROCESS STORM: python3 (ns 4026533601) created 1000 processes in 10 s (100/s; baseline 0.0/s); 1000 exits in that namespace` |
| r3 | `VERDICT: PROCESS STORM: python3 (ns 4026533601) created 1000 processes in 10 s (100/s; baseline 0.0/s); 1000 exits in that namespace` |
| r4 | `VERDICT: PROCESS STORM: python3 (ns 4026533601) created 1000 processes in 10 s (100/s; baseline 0.0/s); 1000 exits in that namespace` |
| r5 | `VERDICT: PROCESS STORM: python3 (ns 4026533601) created 1000 processes in 10 s (100/s; baseline 0.0/s); 1000 exits in that namespace` |

## How the bar was set (what failed first)
Passed on the first try. Threads (child_pid != child_tid) are counted apart from processes: a JVM makes 70-90 threads/s in every run, which is not a storm.
