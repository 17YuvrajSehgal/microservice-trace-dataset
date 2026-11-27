# Blueprint 45 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 20 s of `net_dev_queue` from 30 s before the injection and from 40 s after it.

| run | `conn_rate.py` on `code_conn_churn` (front-end `node` to the catalogue, port 80) |
|---|---|
| r1 | 169 connections per second, 0.3 before; 1 data segment each; 100% closed normally, 0% reset |
| r2 | 158 per second, 0.1 before |
| r3 | 151 per second, 0.3 before |
| r4 | 157 per second, 0.2 before |
| r5 | 156 per second, 0.3 before |

Quiet on the other 45 runs; reversed quiet in all 50. The busiest other pair was the catalogue to
its database: 50-95 connections per second in most runs and 384 in `code_chatty_calls`, with 5 or 6
calls each. Bars (50 per second, 10 times the baseline, at most 2 calls each, 80% closed normally,
at most 10% reset) set before the first run and not changed. A port scan (blueprint 34) also
opens many connections, to many ports and refused.
