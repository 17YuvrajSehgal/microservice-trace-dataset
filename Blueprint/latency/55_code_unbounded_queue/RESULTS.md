# Blueprint 55 results (tool only, 28-11-2026)

Tested on the Trillium login node, 28-11-2026, on the 70 runs of groups 5 to 8 (14 families, 5 runs each). Every tool was run on all 70 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 20 s of `net_dev_queue` from 30 s before the injection and from 40 s after it.

| run | `paced_calls.py` on `code_unbounded_queue` (the front-end, 172.18.0.5, to the catalogue, port 80) |
|---|---|
| r1 | 3,746 calls; 18% of the gaps are 8.0 to 11.0 ms, 4% before |
| r2 | 3,954 calls; 20%, 5% before |
| r3 | 3,991 calls; 20%, 4% before |
| r4 | 3,924 calls; 19%, 5% before |
| r5 | 3,858 calls; 17%, 4% before |

Quiet on the other 65 runs; reversed quiet in all 70. The nearest elsewhere: the load generator's
own calls (24-25% of gaps near 4.5 ms, 21% before).

From the collection's check: the front-end's p50 rose from about 65-74 ms to about 147 ms in all 5 runs.

History: the bars (12% of the gaps in one band, 3 times the baseline) were set after looking at
runs 1 and 2. The first 70-run test then missed r2 (the tool had taken an ephemeral port for a
server) and fired once reversed (traefik to the front-end: busy traffic, most gaps 1-4 ms). Two
changes: the server is the side with a port below 32768, and the clock is looked for from 4 ms
and must be a bump (twice the count 3 ms below it).
