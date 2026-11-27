# Blueprint 43 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 10 s of `sched_switch` from 30 s before the injection and from 40 s after it.

| run | `switch_rate.py` on `code_ctxswitch_storm` (the catalogue, `app`) |
|---|---|
| r1 | 92,400 context switches per second over 415 threads, 4,573 before; median run 14 microseconds; 1.46 cores |
| r2 | 88,082 per second, 415 threads, 4,592 before; 14 microseconds; 1.40 cores |
| r3 | 85,970 per second, 415 threads, 4,615 before; 13 microseconds; 1.35 cores |
| r4 | 89,060 per second, 415 threads, 4,707 before; 14 microseconds; 1.41 cores |
| r5 | 92,483 per second, 420 threads, 4,550 before; 14 microseconds; 1.47 cores |

Quiet on the other 45 runs; reversed quiet in all 50. The nearest other process was toxiproxy with
16,407 switches per second over 17 threads. Bars (20,000 per second, 100 threads, runs of at most
200 microseconds, 5 times the baseline) set before the first run and not changed.

Caveat: in the collection's own check the catalogue's p95 was about 87 ms in these traced runs and
32 ms in the calibration without tracing. Tracing adds a cost to every context switch, so this
family is likely harsher under tracing than without it. Not checked.
