# Blueprint 53 results (tool only, 28-11-2026)

Tested on the Trillium login node, 28-11-2026, on the 70 runs of groups 5 to 8 (14 families, 5 runs each). Every tool was run on all 70 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 20 s of `net_dev_queue` and 10 s of `sched_switch`, from 30 s before the injection and from 40 s after it.

| run | `slow_answers.py` on `slow_query` (user-db, 172.18.0.11:27017, from the user service) |
|---|---|
| r1 | 235 of 5,326 answers took 10 ms or more (median 23.0 ms), 0 before; median of all 0.20 ms (0.19 before); user-db CPU 0.05 -> 0.26 cores; KIND: THE SERVER WORKS LONGER |
| r2 | 260 of 5,116 (23.6 ms); median 0.21 (0.20); CPU 0.05 -> 0.32 |
| r3 | 246 of 5,079 (22.8 ms); median 0.19 (0.19); CPU 0.05 -> 0.30 |
| r4 | 238 of 4,919 (23.3 ms); median 0.21 (0.20); CPU 0.05 -> 0.29 |
| r5 | 218 of 4,997 (23.9 ms); median 0.21 (0.21); CPU 0.05 -> 0.29 |

In r1, r3 and r5 a second verdict names the user service (from the front-end, 219-248 long answers;
its CPU 0.09 -> 0.08-0.09 cores; KIND: THE SERVER WAITS). That is the knock-on: it waits on user-db.

Quiet on the other 65 runs; reversed quiet in all 70. The largest group of long answers elsewhere
was the catalogue in `code_chatty_calls` (about 7,230-7,306), where every answer was slower.

Changed after the first 70-run test:
- The server of a connection is the side whose port is below 32768. The first version sometimes
  took the server for the client (on connections already open when the slice starts) and fired on
  `syn_flood` r1 and `slow_reader` r5, on ephemeral "server" ports.
- The median may rise by at most 25%. Reversed on `code_unbounded_queue` r3 the catalogue's
  answers all shifted with its load (median 1.68 -> 2.79 ms) and the tail passed the first version.
The other bars (20 long answers, 10 times the baseline, at most 50% of the calls) are as first set.
