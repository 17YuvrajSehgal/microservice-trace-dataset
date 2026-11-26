# Blueprint 36 results (tool only, 26-11-2026)

Tested on the Trillium login node, 26-11-2026: one 10 s baseline slice (30 s before the injection) and one 10 s fault slice (40 s into it) per run, for the 20 group-2 runs (`code_spin_loop`, `code_regex_backtrack`, `code_large_payload`, `code_thread_leak`, 5 each). Every tool was run on all 20 runs and reversed (baseline as suspect). Slices in `work/v3bp_g2/` on Trillium. NOT yet run on the 349 runs of the earlier sweep (needs a SLURM job).

`cpu_runs.py`, per run (fault slice against baseline slice):

| run | `code_spin_loop` | `code_regex_backtrack` |
|---|---|---|
| r1 | catalogue 0.40 cores, 38.3 stretches/s, 13 threads, median 10 ms | front-end 0.09 cores, 4 stalls of 100 ms+, longest 289 ms, 100% one thread |
| r2 | 0.43 cores, 40.6/s, 12 threads, median 10 ms | 0.11 cores, 4 stalls, longest 430 ms, 91% one thread |
| r3 | 0.42 cores, 38.8/s, 13 threads, median 11 ms | 0.10 cores, 3 stalls, longest 310 ms, 100% |
| r4 | 0.38 cores, 36.3/s, 13 threads, median 10 ms | 0.13 cores, 4 stalls, longest 431 ms, 100% |
| r5 | 0.41 cores, 38.5/s, 13 threads, median 10 ms | 0.09 cores, 3 stalls, longest 408 ms, 100% |

All 10 with the right KIND line (many threads, short stretches / one thread, long stalls); 0.00
cores in every baseline. The busiest container in stretches in every slice, fault or not, is the
MongoDB carts-db: 0.85-1.47 cores. Quiet on the 10 `code_large_payload` and `code_thread_leak` runs; the
reversed comparison quiet in all 20.

History: the bars (5 ms stretches, 0.1 cores, 5 times the baseline) were set before run 1. The
second rule (3 or more stalls of 100 ms with none before) was ADDED after run 1 of
`code_regex_backtrack`, which the first rule missed at 0.09 cores. Runs r3 and r5 have exactly 3
stalls, at that bar.
