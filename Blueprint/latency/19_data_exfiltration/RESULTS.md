# Blueprint 19 results (tool only, 17-11-2026)

`egress.py` on every v2 run of both applications: one 10 s `net_dev_queue` slice, 30 s after
the injection (normal runs: 100 s after the trace start). SLURM job 2877421 on Trillium, one
node, 4.5 minutes. Outputs: `work/dx_check/sweep/*.egress.out`.

| runs | verdict |
|---|---|
| `data_exfiltration`, Sock Shop, 5 | 5/5 BULK ONE-WAY TRANSFER: `python3`, 41.9-42.0 MB/s to port 18097, 0.0% back, 87% of all TCP payload |
| `data_exfiltration`, Train Ticket, 5 | 5/5 BULK ONE-WAY TRANSFER: `python3`, 41.9-42.0 MB/s to port 18097, 0.0% back, 100% of all TCP payload |
| all other families + normal, 293 runs | 293/293 NO BULK ONE-WAY TRANSFER |
| 1 run | no result: the slice cut failed (`anomaly_mem_subtle_steady_r3`) |

Largest steady one-way streams outside the labelled runs:

| process | what it is | MB/s | back |
|---|---|---|---|
| `toxiproxy` (Train Ticket, normal runs) | database results relayed to a client | 2.0-2.96 | 0.0-0.1% |
| `node`, `java` (Sock Shop) | telemetry export to the collector, port 4317 | 0.9-1.35 | 0.1% |

The bar is 5 MB/s. The first-guess bars held, so none was changed after the sweep.
