# Blueprint 32 results (tool only, 25-11-2026)

Fault runs: the 5 v3 `net_bandwidth` runs (catalogue limited to 2 Mbit/s).

| runs | result |
|---|---|
| `net_bandwidth`, 5 | 5 of 5: the catalogue (`app`) at 172.18.0.6: packets wait 62-76 ms (median) and 328-347 ms (p95) at its interface, 0.01 ms in the baseline; it sent 2,053-2,093 kbit/s; p95/median 4.5-5.3 |
| reversed, 5 | quiet |

False-alarm sweep: SLURM job 2931081 on Trillium (25-11-2026, one node, 34 min), all 349 runs (v2 Sock Shop 170, v2 Train Ticket 134, v3 Sock Shop 45); 2 runs gave no slice (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`), so 347 were judged. One baseline slice (20 s ending 20 s before the injection) and one fault slice (20 s from 30 s into it) per run; normal runs use 100 s after the trace start. Outputs: `work/dx_check/sweep_v3tools/` on Trillium.

| other runs with a verdict | median wait | p95 / median |
|---|---|---|
| `svc_net` Sock Shop 5/5 | 151-152 ms | 1.5-1.6 |
| `svc_net` Train Ticket 5/5 | 149-153 ms | 1.5-1.6 |
| `anomaly_net` Sock Shop 8/8 | 78-81 ms | about 1.4-1.6 |
| `anomaly_net` Train Ticket 3/8 | 80-81 ms | 1.4 |
| normal | 0 of 20 | |
