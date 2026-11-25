# Blueprint 28 results (tool only, 25-11-2026)

Fault runs: the 5 v3 `port_exhaustion` runs.

| slice | runs | result |
|---|---|---|
| first 20 s | 5 | 5 of 5: `app` (catalogue) 927-1,902 `connect` calls returned -99, 46-56% of its connects, 0 in the baseline |
| 30-50 s | 5 | 5 of 5: 1,353-2,154 calls, 65-67% |
| sweep slice | 5 | 5 of 5 |
| reversed | 5 | quiet |

False-alarm sweep: SLURM job 2931081 on Trillium (25-11-2026, one node, 34 min), all 349 runs (v2 Sock Shop 170, v2 Train Ticket 134, v3 Sock Shop 45); 2 runs gave no slice (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`), so 347 were judged. One baseline slice (20 s ending 20 s before the injection) and one fault slice (20 s from 30 s into it) per run; normal runs use 100 s after the trace start. Outputs: `work/dx_check/sweep_v3tools/` on Trillium.

`new_errors.py`, limit errors only, other runs with a positive verdict: Train Ticket
`fd_exhaustion` 5/5 (the real fault: -24), and the edge router out of file descriptors in
`slow_client` 5/5, `anomaly_net` 3/8 and `dns_delay` 3/5 (a consequence: connections pile up
there when requests hang). Normal runs: 0 of 20.

History: until 25-11-2026 every new error gave a verdict. Then the tool fired in 4 of 10 normal
Train Ticket runs (`openat` returning -2 in node and python, and `docker exec` helpers) and in
22 other family groups. Since then only limit errors give a verdict. The counts above apply
that rule to the sweep's output lines; the tool's self-test covers the rule.
