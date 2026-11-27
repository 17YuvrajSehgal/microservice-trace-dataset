# Blueprint 46 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 20 s of `net_dev_queue` from 30 s before the injection and from 40 s after it.

| run | `pkt_order.py` on `net_reorder` (the catalogue, 172.18.0.10) |
|---|---|
| r1 | 193 of 15,677 data segments late (1.2%), 0 before; 56 sent more than once |
| r2 | 199 of 16,430 (1.2%); 67 |
| r3 | 179 of 16,057 (1.1%); 67 |
| r4 | 168 of 15,817 (1.1%); 69 |
| r5 | 165 of 15,869 (1.0%); 66 |

Quiet on the other 45 runs; reversed quiet in all 50. No other sender had more than 2 late segments.

Changed after run 1: the share bar went from 2% to 0.5%. Run 1 had 1.2% and every other sender
0 to 2 segments, so the first bar missed the fault. Runs 2-5 were tested with the new bar. The
other bars (100 late segments, baseline at most 10%) are as first set.

`dev_delay.py` (blueprint 32) does not fire on this family: 75% of the packets wait 10 ms and
25% do not, and its p95 bar is 20 ms. A constant delay is blueprint 51.
