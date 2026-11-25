# Blueprint 25 results (tool only, 25-11-2026)

Fault runs: the 5 v3 `code_lock_contended` runs (catalogue: a mutex held across its database
query, with a constant 5 ms database delay and 40 extra list requests per second).

| step | runs | result |
|---|---|---|
| `inside_wait.py`, own runs | 5 | 5 of 5 name the catalogue (`app`): 8.6-9.4 requests in flight, 4.5-5.4 waiting inside it, 0.50-0.59 in the baseline; 0.27-0.31 cores, 0.17-0.25 threads waiting for a core |
| `inside_wait.py`, reversed (baseline as suspect) | 5 | quiet in 5 |
| `wait_cause.py`, own runs | 5 | 5 of 5: NOTHING ELSE EXPLAINS IT |

False-alarm sweep: SLURM job 2931081 on Trillium (25-11-2026, one node, 34 min), all 349 runs (v2 Sock Shop 170, v2 Train Ticket 134, v3 Sock Shop 45); 2 runs gave no slice (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`), so 347 were judged. One baseline slice (20 s ending 20 s before the injection) and one fault slice (20 s from 30 s into it) per run; normal runs use 100 s after the trace start. Outputs: `work/dx_check/sweep_v3tools/` on Trillium.

| tool | other runs with a positive verdict |
|---|---|
| `inside_wait.py` alone | 68 runs in 13 other family groups (see blueprint 30 RESULTS for the list) |
| `inside_wait.py` + `wait_cause.py` | 12: `slow_db` 9 of 11 (Sock Shop) and 2 of 11 (Train Ticket), all naming toxiproxy, the proxy that holds the injected delay; `anomaly_mem` 1 of 7 |
| normal runs | 0 of 20 |

Final rule: 10 of 10 lock runs (this family and `db_table_lock`), 12 lookalike runs, 0 of 20 normal.

For comparison, `db_table_lock` (blueprint 30): 67.4-69.1 requests waiting inside `mysqld`.

History: the first version timed a call from the client's first sighting, and on the 5
`net_bandwidth` runs it named the database proxy for a rate limit on the catalogue. Calls are
timed at the server since 25-11-2026. The bars (1.0 request, 25%, 3 times) were lowered once
after seeing the 5 lock runs. `wait_cause.py`'s bars were set after seeing the sweep numbers.
