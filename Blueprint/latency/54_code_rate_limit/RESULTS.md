# Blueprint 54 results (tool only, 28-11-2026)

Tested on the Trillium login node, 28-11-2026, on the 70 runs of groups 5 to 8 (14 families, 5 runs each). Every tool was run on all 70 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Logs: the per-container files in each run's `logs/`; 60 s from the injection against the 60 s before. Reversed:
30 s from 30 s before the injection against the 30 s before that. `breaker_cause.py` was also run on the 20 group-4 runs.

| run | `log_errors.py` (catalogue) | `breaker_cause.py` |
|---|---|---|
| r1 | `circuit breaker is open` 2,049 lines (34.1 per second), 0 before | own rejections: `too many requests` 13, dependency errors 0 |
| r2 | 2,095 (34.9 per second) | 14, 0 |
| r3 | 1,960 (32.7 per second) | 15, 0 |
| r4 | 2,000 (33.3 per second) | 13, 0 |
| r5 | 2,048 (34.1 per second) | 20, 0 |

`log_errors.py` also gave a verdict on all 5 `dns_delay_jvm` runs (the orders service, `java.net.Socket.connect`,
526-1,514 lines): real errors of that fault. Quiet on the other 60 runs; reversed quiet in all 70.

`breaker_cause.py` on `mtu_blackhole` (group 4): THE BREAKER OPENED BECAUSE A DEPENDENCY FAILS in all 5
(`circuit breaker is open` 10,667-11,401, `database connection error` 21 in each). Quiet on the other 80
runs; reversed quiet in all 90. ITS BARS (100 breaker answers, 5 dependency errors, 5 rejections) WERE SET
AFTER LOOKING AT THESE 10 RUNS, so this is a fit, not a test.

Why two tools: in the first check run of this family the 429 rejections were few (27 in the run) and the
catalogue's own circuit breaker (gobreaker; opens after 5 failures in a row, stays open 30 s) answered
about 4,190 requests with 500. The same message appears when a dependency fails (`mtu_blackhole`,
blueprint 40; a reset database path is blueprint 22).
