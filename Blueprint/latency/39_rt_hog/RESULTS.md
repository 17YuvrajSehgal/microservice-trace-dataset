# Blueprint 39 results (tool only, 27-11-2026)

Tested on the Trillium login node, 26/27-11-2026, on the 20 group-4 runs (`rt_hog`, `mtu_blackhole`, `login_bruteforce`, `unexpected_exec`, 5 each). Every tool was run on all 20 runs and reversed (baseline as suspect). Slices in `work/v3bp_g4/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job).

| run | `rt_cpu.py` on `rt_hog` |
|---|---|
| r1 | `python3` (priority -51) on CPU 11 for 90% of the slice, 0% before |
| r2 | 97% |
| r3 | 98% |
| r4 | 88% |
| r5 | 93% |

Quiet on the other 15 group-4 runs; reversed quiet in all 20. Bars (50% of the slice, at most 5%
before) set before the first run. Metric verification: the idle share of CPU 11 fell from
0.35-0.40 to 0.026-0.029.
