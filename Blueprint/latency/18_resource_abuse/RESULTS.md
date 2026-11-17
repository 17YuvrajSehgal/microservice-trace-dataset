# Blueprint 18 results (tool only, 17-11-2026)

`beacon.py` on every v2 run of both applications: one 60 s connect slice and one 10 s
scheduling slice, 20 s / 30 s after the injection (normal runs: 90 s / 100 s after the trace
start). SLURM job 2875043 on Trillium, one node, 28 minutes. Outputs: `work/ra_check/sweep/`.

| runs | verdict |
|---|---|
| `resource_abuse`, Sock Shop, 5 | 5/5 RESOURCE ABUSE SHAPE: `python3`, 0.93-0.95 cores, every 5.2-5.3 s, 12 connects, jitter 1-2% |
| `resource_abuse`, Train Ticket, 5 | 5/5 RESOURCE ABUSE SHAPE: `python3`, 1.01 cores, every 5.2-5.5 s, 11 connects, jitter 2-5% |
| all other families + normal, 292 runs | 292/292 NO BEACON FROM A CPU-HEAVY PROCESS |
| 2 runs | no result: the slice cut failed (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`) |

Periodic connectors seen outside the labelled runs, and their CPU use:

| process | destination | period | cores |
|---|---|---|---|
| `HikariPool-1` (Train Ticket database pool) | MySQL | 10 s | 0.02-0.05 |
| `prometheus` | three scrape targets, port 80 | 5 s | under 0.01 |
| `python3` (load generator / recipe helpers) | unix socket | 9-12 s | 0.05-0.15 |
| `stress-ng-vm`, `containerd` | unix socket | 8-12 s | under 0.01 |

The highest is 0.15 cores (`dns_delay` r5); the bar is 0.5 and the smallest hog is 0.93.
