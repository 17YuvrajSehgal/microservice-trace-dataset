# Blueprint 49 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 10 s of `sched_switch` from 30 s before the injection and from 40 s after it.

| run | `busy_sleep.py` on `code_blocking_wait` (the front-end's main thread, `node`) |
|---|---|
| r1 | on the CPU 84% of the slice; 39 sleeps of 15 ms or more, all about 30 ms, 1.17 s lost; 0 in the baseline |
| r2 | 84%; 38 sleeps, 1.14 s |
| r3 | 83%; 38 sleeps, 1.13 s |
| r4 | 86%; 26 sleeps, 0.78 s |
| r5 | 85%; 30 sleeps, 0.90 s |

Quiet on the other 45 runs; reversed quiet in all 50.

How the rule came about:
- The bars (on the CPU 50% of the slice, 2 sleeps of 15 ms per second, baseline at most 10%) were
  set on run 1, where this thread had 39 sleeps of 25 to 40 ms and none in the baseline or under
  three other faults. Runs 2-5 were not looked at first.
- The 50-run test then found two false alarms in the reversed runs: in two healthy baselines of
  `dns_delay_jvm` a database connection thread (`conn57`, `conn66`) was on the CPU 52-56% of the
  slice and slept 44-51 times for 18 to 182 ms. It works on a query and waits for the next one.
  The verdict is now given only when the sleeps have one fixed length (the 90th percentile is at
  most 1.5 times the 10th). After that change: 5 of 5, 0 elsewhere, 0 reversed.
The injected wait is 30 ms on 2% of the requests, so the fixed length is what this fault looks like.
