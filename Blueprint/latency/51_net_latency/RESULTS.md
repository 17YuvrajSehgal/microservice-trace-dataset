# Blueprint 51 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 20 s of `net_dev_queue` from 30 s before the injection and from 40 s after it.

| run | `dev_delay.py` on `net_latency` (the catalogue, 172.18.0.2) |
|---|---|
| r1 | 33,001 packets waited 20 ms (median) and 20 ms (p95), 0.01 ms in the baseline; KIND: A FIXED DELAY |
| r2 | 32,170 packets, 20 ms and 20 ms; A FIXED DELAY |
| r3 | 33,571 packets, 20 ms and 20 ms; A FIXED DELAY |
| r4 | 32,377 packets, 20 ms and 20 ms; A FIXED DELAY |
| r5 | 33,209 packets, 20 ms and 20 ms; A FIXED DELAY |

Quiet on the other 45 runs; reversed quiet in all 50. `dev_delay.py` is the tool of blueprint 32,
used as it is; its bars were not changed. On `net_reorder` it stays quiet (the median wait is below
its bar; reordering is blueprint 46). This family and `net_bandwidth` get the same verdict line and differ in the KIND.

In the collection's check the catalogue's own span p50 went from 1.5 to 43 ms: the delay is on every
packet the catalogue sends, also to its database, so the service itself looks slow.
