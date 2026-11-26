# Blueprint 37 results (tool only, 26-11-2026)

Tested on the Trillium login node, 26-11-2026: one 10 s baseline slice (30 s before the injection) and one 10 s fault slice (40 s into it) per run, for the 20 group-2 runs (`code_spin_loop`, `code_regex_backtrack`, `code_large_payload`, `code_thread_leak`, 5 each). Every tool was run on all 20 runs and reversed (baseline as suspect). Slices in `work/v3bp_g2/` on Trillium. NOT yet run on the 349 runs of the earlier sweep (needs a SLURM job).

| run | `bytes_per_call.py` on `code_large_payload` |
|---|---|
| r1 | catalogue (`app`) at port 80: 8.0 kB per answer, 0.4 kB before (18.1 times), 1.96 MB/s, 243 answers/s against 249 |
| r2 | 8.3 kB (19.0 times), 2.04 MB/s, 244 against 248 |
| r3 | 7.5 kB (16.8 times), 1.83 MB/s, 244 against 251 |
| r4 | 7.9 kB (17.2 times), 1.94 MB/s, 247 against 245 |
| r5 | 9.0 kB (20.6 times), 2.18 MB/s, 242 against 238 |

In every run 3 more servers are listed as ALSO LARGER: the front-end, the edge router and the
host's port forward, about 1.5 -> 6.2 kB per answer. The source's rise is about 17-21 times. Quiet on the other 15 group-2 runs (largest
rise 1.0-1.2 times); reversed quiet in all 20.

History: before the change after run 1 those 3 also got a verdict.
