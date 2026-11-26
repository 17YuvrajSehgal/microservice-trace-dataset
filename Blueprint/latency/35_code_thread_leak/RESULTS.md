# Blueprint 35 results (tool only, 26-11-2026)

Tested on the Trillium login node, 26-11-2026: one 10 s baseline slice (30 s before the injection) and one 10 s fault slice (40 s into it) per run, for the 20 group-2 runs (`code_spin_loop`, `code_regex_backtrack`, `code_large_payload`, `code_thread_leak`, 5 each). Every tool was run on all 20 runs and reversed (baseline as suspect). Slices in `work/v3bp_g2/` on Trillium. NOT yet run on the 349 runs of the earlier sweep (needs a SLURM job).

| run | `thread_growth.py` on `code_thread_leak` |
|---|---|
| r1 | catalogue (`app`) started 40 threads in 10 s, 0 ended, 0 in the baseline |
| r2 | 41 started, 0 ended, 0 before |
| r3 | 41, 0, 0 |
| r4 | 40, 0, 0 |
| r5 | 42, 0, 0 |

Quiet on the other 15 group-2 runs (largest net elsewhere: 11, short `docker exec` helpers; the
orders JVM starts 749-854 threads per slice, 75-85 per second, and ends all but 0-1). Reversed quiet in all 20.
Bars (net 30, at most 20% ended, baseline at most 20% of it) set before the first run.
