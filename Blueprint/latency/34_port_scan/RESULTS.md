# Blueprint 34 results (tool only, 25-11-2026, login node)

Fault runs: the 5 v3 `port_scan` runs (200 connection attempts per second from the front-end's
network namespace to ports 1-1024 of the 15 other containers).

| runs | result |
|---|---|
| `port_scan`, 5 | 5 of 5: 172.18.0.3 (the front-end's address) tried 3,904-3,910 different address-and-port pairs in 20 s (262 ports on 15 addresses, 195-196 per second), 100% refused, 4 pairs in the baseline; the packets were sent by `python3` in the host's pid namespace |
| reversed, 5 | quiet in 5 |
| other v3 slices, 15 (`db_table_lock`, `slow_client`, `net_bandwidth`) | quiet; the most any other address tried was 4 pairs on 1 port |

Not yet run on the 347 sweep runs (the sweep kept no slices; needs a SLURM job). The bars
(200 pairs, 50 ports, 10 times) were set before the first run and not changed.
