# Blueprint 41 results (tool only, 27-11-2026)

Tested on the Trillium login node, 26/27-11-2026, on the 20 group-4 runs (`rt_hog`, `mtu_blackhole`, `login_bruteforce`, `unexpected_exec`, 5 each). Every tool was run on all 20 runs and reversed (baseline as suspect). Slices in `work/v3bp_g4/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Logs: the per-container files in each run's `logs/`; 60 s from the injection against the 60 s before.

| run | `log_errors.py` on `login_bruteforce` (lines in 60 s, 0 before in every run) |
|---|---|
| r1 | user `err=Unauthorized` 1,160 (19.3/s); front-end `Error with log in` 1,160 |
| r2 | 851 (14.2/s) |
| r3 | 923 (15.4/s) |
| r4 | 797 (13.3/s) |
| r5 | 989 (16.5/s) |

Also a verdict on all 5 `mtu_blackhole` runs: the catalogue's `circuit breaker is open` and the
front-end's error answers (about 30 per second, 0 before) - real errors of that fault. Quiet on
the 10 `rt_hog` and `unexpected_exec` runs. Reversed (30 s before the injection against the 30 s
before that, inside the logged time) quiet in all 20.

History: the first version counted the Java agents' span-export lines (status codes in them); the
reversed check fired in all 4 families. They are left out since run 1. A window that starts
before the logs do is reported as NOT JUDGED.
