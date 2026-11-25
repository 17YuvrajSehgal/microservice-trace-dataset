# Blueprint 30 results (tool only, 25-11-2026)

Fault runs: the 5 v3 `db_table_lock` runs (a session write-locks the catalogue's three tables
2 s of every 3 s).

| step | runs | result |
|---|---|---|
| `inside_wait.py`, own runs | 5 | 5 of 5 name the database (`mysqld`): 67.5-69.2 requests in flight, 67.4-69.1 waiting inside it, 0.00 in the baseline; 0.09 cores, 0.01 threads waiting for a core |
| the chain | 5 | the catalogue has about 69 in flight and about 69 downstream; the proxy about 69 and 69 downstream; `mysqld` about 69 and 0 downstream: the wait is in the database |
| reversed | 5 | quiet in 5 |
| `wait_cause.py`, own runs | 5 | 5 of 5: NOTHING ELSE EXPLAINS IT |

False-alarm sweep: SLURM job 2931081 on Trillium (25-11-2026, one node, 34 min), all 349 runs (v2 Sock Shop 170, v2 Train Ticket 134, v3 Sock Shop 45); 2 runs gave no slice (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`), so 347 were judged. One baseline slice (20 s ending 20 s before the injection) and one fault slice (20 s from 30 s into it) per run; normal runs use 100 s after the trace start. Outputs: `work/dx_check/sweep_v3tools/` on Trillium.

`inside_wait.py` alone gave a positive verdict in 68 runs of 13 other family groups:
`slow_db` 11/11, `anomaly_net` 8/8, `svc_cpu_cap` 6/8, `anomaly_cpu` 5/5,
`code_event_loop_block` 5/5, `code_serial_awaits` 5/5, `dependency_outage` 5/5,
`fd_exhaustion` 5/5, `svc_net` 5/5, `cpu_weight` 5/5, `net_bandwidth` 5/5, `error_storm` 3/8,
`dns_delay` 2/5, `anomaly_mem` 1/7, Train Ticket `slow_db` 2/11. Quiet in 239.

With `wait_cause.py`: 12 lookalike runs left (`slow_db` 11, `anomaly_mem` 1), 0 of 20 normal.
