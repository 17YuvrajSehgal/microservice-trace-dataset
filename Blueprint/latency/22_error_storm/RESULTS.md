# Blueprint 22 results (tool only, 17-11-2026)

`tcp_conns.py` on every v2 run of both applications (304): one 20 s `net_dev_queue` slice
30 s after the injection and one 40 s before it as the baseline (normal runs: 130 s and 60 s
after the trace start). SLURM job 2879375 on Trillium (one node, 13 min), final rule. The
first rule ran in job 2879216 (6 min, no baseline). Outputs: `work/dx_check/sweep_ec2/`,
`work/dx_check/sweep_ec/`. The same job is the check for blueprint 6.

| runs | verdict (final rule) | numbers |
|---|---|---|
| `error_storm` Sock Shop, 8 | SERVER ACCEPTS AND THEN RESETS | the proxy at `:3306` reset 10-12 of 10-12 (100%), 1 client (`app`, the catalogue), 0 kB back |
| `error_storm` Train Ticket, 8 | SERVER ACCEPTS AND THEN RESETS | the proxy at `:3306` reset 10-50 of 10-50 (100%), 5-20 clients (`HikariPool-1 co`), 0 kB back |
| `conn_pool_exhaustion` Sock Shop, 5 | NEW CLIENT HOLDS CONNECTIONS | `python3` holds 149 connections to `:3306`, 40 bytes each, 0 in the baseline |
| `conn_pool_exhaustion` Train Ticket, 5 | NEW CLIENT HOLDS CONNECTIONS | `python3` holds 1,800 connections to `:3306`, 33 bytes each, 0 in the baseline |
| `svc_mem_cap` Sock Shop 7, `fd_exhaustion` Sock Shop 5, `dns_delay` r1 and r3 | SERVER PORT REFUSES | a killed or crash-looping service: 68-100% of 519-2,254 connections refused |
| every Train Ticket run, 134 | SERVER PORT REFUSES | `127.0.0.1:5672` refused 8 of 8, also in the 10 normal runs (no broker is deployed) |
| 90 Train Ticket runs, 1 Sock Shop run | NOTE: a standing pool, not new | the database proxy holds 159-200 idle connections to MySQL, also in the baseline; one `java` holds 83 to MongoDB |
| 2 runs | no result: the slice cut failed (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`) | |

Accepted-then-reset: 16 of 16, 0 false alarms in 286. New holder: 10 of 10, 0 in 292.

First rule (per client, no refused split, no baseline, job 2879216): `error_storm` 9 of 16;
reset verdicts on all 134 Train Ticket runs and 14 Sock Shop runs of other families; held
verdicts on 90 Train Ticket runs and 1 Sock Shop run.

Closest negatives with the final rule: `anomaly_net`, 13-32 accepted-then-reset of 92-127
(10-25%); idle held connections of one client without a verdict: up to 324 of 481 (under the
90% share bar).
