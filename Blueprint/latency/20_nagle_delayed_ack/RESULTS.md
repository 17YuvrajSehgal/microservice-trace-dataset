# Blueprint 20 results (tool only, 17-11-2026)

`ack_stall.py` on every v2 run of both applications: one 10 s `net_dev_queue` slice, 30 s
after the injection (normal runs: 100 s after the trace start). SLURM job 2877421 on Trillium,
one node, 4.5 minutes (the first pass, job 2877411, used the rule without the waiting-time
bar). Outputs: `work/dx_check/sweep/*.stall.out`, first pass in `work/dx_check/sweep_v1/`.

| runs | verdict |
|---|---|
| `nagle_delayed_ack`, Sock Shop, 5 | 5/5 NAGLE + DELAYED ACK SHAPE: `python3`, 41 ms, 1534-1587 stalls on 8 connections to port 18099, 8.1-8.2 of 10 s waiting on the worst one |
| `nagle_delayed_ack`, Train Ticket, 5 | 5/5 NAGLE + DELAYED ACK SHAPE: `python3`, 41 ms, 1024-1083 stalls on 8 connections, 5.5-5.9 of 10 s waiting |
| all other families + normal, 293 runs | 293/293 NO NAGLE + DELAYED ACK STALLS |
| 1 run | no result: the slice cut failed (`anomaly_mem_subtle_steady_r3`) |

First pass (rule: 10 stalls, 80% at one length): the same, plus 1 false alarm on
`svc_mem_cap_aggressive_steady_r3` (`node` to port 4317, 10 stalls of 40.6 ms, 0.41 s waiting).

Stalls outside the labelled runs (per run: median 5, 95th percentile 49, largest 325):

| where | worst connection | at one length | waiting |
|---|---|---|---|
| `svc_net`, `anomaly_net` (lossy or delayed path), both applications | 10-22 stalls | 0-60% | 0.8-1.4 s |
| everything else | 0-12 stalls | any | under 0.5 s |
