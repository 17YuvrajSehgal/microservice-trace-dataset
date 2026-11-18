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

## Train Ticket check (17-11-2026)

Every Train Ticket v2 run (134), SLURM job 2881327 on Trillium (one node, 53 min, shared by
blueprints 11, 12, 13, 14 and 16). The tool is unchanged from the Sock Shop check. Outputs:
`work/dx_check/sweep_tt/`.
Slices: 10 s 45 s before the injection and 10 s 50 s into it.

| runs | verdict |
|---|---|
| `tt_fork_storm`, 5 | PROCESS STORM, 5 of 5: `python3` created 1000 processes in 10 s (100/s; baseline 0.0/s) |
| all other Train Ticket runs, 129 | no verdict |

5 of 5, 0 false alarms in 129. Same numbers as on Sock Shop.

## All Sock Shop runs (17-11-2026)

Every Sock Shop v2 run (170), SLURM job 2882127 on Trillium (one node, 27 min, shared by
blueprints 12, 13 and 14). The tool is unchanged. Same slices as the Train Ticket check.
Outputs: `work/dx_check/sweep_ss/`.

`fork_storm` 5 of 5 (PROCESS STORM, 100/s against 0.0/s); no verdict in the other 165 runs.
With Train Ticket: 10 of 10, 0 false alarms in 294.
