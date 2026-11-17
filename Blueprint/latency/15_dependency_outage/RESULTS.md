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

## Full check on all v2 runs (tool only, 17-11-2026)

`ns_silence.py` on all 304 runs (10 s baseline 40 s before the injection, 10 s fault slice
30 s after it; SLURM job 2877661, one node, 52 min). Then `freeze_moment.py` on the 95 runs
where it fired (one 80 s scheduling slice; job 2878303, 25 min). Outputs:
`work/dx_check/sweep_dq/*.sil.out`, `work/dx_check/sweep_frz/`.

| runs | `ns_silence.py` | `freeze_moment.py` on the named namespace |
|---|---|---|
| `dependency_outage`, Sock Shop, 5 | 5 SERVICE FROZEN (`app`, 631-824 events/s to 0) | 5 FROZEN: 19-25 threads within 0.1-1.5 ms, 13-21 woken from sleep |
| `dependency_outage`, Train Ticket, 5 | 5 SERVICE FROZEN (JVM, 281-320/s to 0) | 5 FROZEN: 90-105 of 97-118 threads within 0.4-0.5 ms, 63-71 woken from sleep |
| `queue_backlog`, Sock Shop, 5 | 5 SERVICE FROZEN (`java`, 271-361/s to 0) | 5 FROZEN: 141-143 threads within 0.7-1.7 ms, 121-133 woken from sleep |
| other Sock Shop runs, 159 | 12 false alarms: `error_storm` 5, `fd_exhaustion` 4, `svc_mem_cap` 3 | 9 NO FREEZE MOMENT, 3 EXITED (`java` killed by the memory limit, 67 thread exits) |
| other Train Ticket runs, 129 | 68 false alarms (idle `openresty` 85/s, `toxiproxy`, helpers that ended; 3 are normal runs) | 66 NO FREEZE MOMENT, 2 EXITED |
| 1 run | no result (`anomaly_mem_subtle_steady_r3`) | |

So the two steps together: 15 of 15, 0 false alarms in 288 other runs.

`freeze_moment.py` rule history: the first rule (80% of at least 3 threads in a 50 ms sweep)
called an idle `toxiproxy` frozen in 3 of the 80 runs. The rule now also needs 3 threads
woken from 1 s or more of sleep. Run on every namespace instead of the named one, it still
calls `toxiproxy` frozen in 3 Train Ticket runs (7 threads, 3-4 woken); real freezes wake 13-133.
