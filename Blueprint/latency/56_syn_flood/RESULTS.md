# Blueprint 56 results (tool only, 28-11-2026)

Tested on the Trillium login node, 28-11-2026, on the 70 runs of groups 5 to 8 (14 families, 5 runs each). Every tool was run on all 70 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 20 s of `net_dev_queue` from 30 s before the injection and from 40 s after it.

| run | `half_open.py` on `syn_flood` (172.18.0.250, a free address, to the front-end, 172.18.0.5:8079) |
|---|---|
| r1 | 201,280 attempts (10,064 per second), 0% completed, 0 before |
| r2 | 205,360 (10,268 per second) |
| r3 | 204,365 (10,218 per second) |
| r4 | 202,429 (10,121 per second) |
| r5 | 204,845 (10,242 per second) |

Each attempt is seen on the Docker bridge and on the front-end's interface, and counted once.
hping3 was set to 20,000 per second; the trace shows about 10,100.

Quiet on the other 65 runs; reversed quiet in all 70. The most attempts elsewhere: 7,796 in 20 s
from the catalogue to its database proxy, 100% completed. Bars (50 per second to one port, at most
5% completed, at most 5 ports, baseline at most 10%) set before the first run and not changed.
A port scan (many ports, refused) is blueprint 34. From the collection's check: the front-end's p95
rose 30-75 ms under tracing (0.22-0.23 s to 0.25-0.30 s).
