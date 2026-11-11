# Results: dependency_outage on our labelled runs (2026-11-11)

Tool: `tools/ns_silence.py`. Data: Sock Shop v2 (StrataTrace), Trillium `data/stratatrace-v2/sockshop/`.
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
| r1 | `VERDICT: SERVICE FROZEN: ns 4026532822 (app) went from 406/s to 0.0 events/s with no process exit: its processes still exist but are never scheduled - paused or stopped, not crashed; affected (rate fell by half or more): 4026533815 (java) x0.38, 4026533389 (java) x0.40, 4026533886 (mysqld) x0.41` |
| r2 | `VERDICT: SERVICE FROZEN: ns 4026532822 (app) went from 383/s to 0.0 events/s with no process exit: its processes still exist but are never scheduled - paused or stopped, not crashed; affected (rate fell by half or more): 4026533815 (java) x0.40, 4026533389 (java) x0.41, 4026533886 (mysqld) x0.42` |
| r3 | `VERDICT: SERVICE FROZEN: ns 4026532822 (app) went from 392/s to 0.0 events/s with no process exit: its processes still exist but are never scheduled - paused or stopped, not crashed; affected (rate fell by half or more): 4026533815 (java) x0.43, 4026533886 (mysqld) x0.44, 4026533389 (java) x0.44` |
| r4 | `VERDICT: SERVICE FROZEN: ns 4026532822 (app) went from 324/s to 0.0 events/s with no process exit: its processes still exist but are never scheduled - paused or stopped, not crashed; affected (rate fell by half or more): 4026533886 (mysqld) x0.42, 4026533815 (java) x0.43, 4026533389 (java) x0.46` |
| r5 | `VERDICT: SERVICE FROZEN: ns 4026532822 (app) went from 347/s to 0.0 events/s with no process exit: its processes still exist but are never scheduled - paused or stopped, not crashed; affected (rate fell by half or more): 4026533886 (mysqld) x0.42, 4026533815 (java) x0.46, 4026533389 (java) x0.48` |

## How the bar was set (what failed first)
Passed on the first try. The paused service drops to exactly 0 events; the callers keep 37-87% of their rate, so the 1% bar has wide margins on both sides.
