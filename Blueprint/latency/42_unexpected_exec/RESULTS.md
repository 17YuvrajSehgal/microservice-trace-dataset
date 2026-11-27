# Blueprint 42 results (tool only, 27-11-2026)

Tested on the Trillium login node, 26/27-11-2026, on the 20 group-4 runs (`rt_hog`, `mtu_blackhole`, `login_bruteforce`, `unexpected_exec`, 5 each). Every tool was run on all 20 runs and reversed (baseline as suspect). Slices in `work/v3bp_g4/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 60 s of `sched_process_exec` from 62 s before the injection and from 2 s after it.

| run | `new_programs.py` on `unexpected_exec` |
|---|---|
| r1-r5 | the front-end's namespace started 8 programs never started there before: cat, env, id, ls, ps, sh, uname, wc (24 starts, 3 rounds of the shell) |

Quiet on the other 15 group-4 runs (no container had a new program); reversed quiet in all 20.
The host's namespace starts about 1,280 programs per minute (the collection's own scripts) and is
left out. Bar (2 different new programs in one container) set before the first run.
