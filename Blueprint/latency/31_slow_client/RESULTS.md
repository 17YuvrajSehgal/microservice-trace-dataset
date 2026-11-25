# Blueprint 31 results (tool only, 25-11-2026)

Fault runs: the 5 v3 `slow_client` runs.

| runs | result |
|---|---|
| `slow_client`, 5 | 5 of 5: carts (`java`) at port 80 has 301-310 connections with a request and no answer, 0 answered, 0 in the baseline; 220 of them send one small segment about every 1.0 s, all from 172.18.0.1 |
| reversed, 5 | quiet in 5 |
| `inside_wait.py` on the same runs | 0 of 5 (it cannot see a request with no answer) |

False-alarm sweep: SLURM job 2931081 on Trillium (25-11-2026, one node, 34 min), all 349 runs (v2 Sock Shop 170, v2 Train Ticket 134, v3 Sock Shop 45); 2 runs gave no slice (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`), so 347 were judged. One baseline slice (20 s ending 20 s before the injection) and one fault slice (20 s from 30 s into it) per run; normal runs use 100 s after the trace start. Outputs: `work/dx_check/sweep_v3tools/` on Trillium.

| verdict | other runs |
|---|---|
| with the SLOW CLIENTS clause | 0 of 342 |
| SERVICE DOES NOT ANSWER alone | 17: `dependency_outage` 5/5, `code_event_loop_block` 5/5, `fd_exhaustion` 5/5, `dns_delay` 2/5 - all services that do stop answering |
| normal | 0 of 20 |

History: the first version gave 2-3 verdicts per run (also the edge router and the host port
forward, which wait on carts); callers are now reported apart. The 30-51 'silent' connections
at the edge router in every baseline were a bug (one interface read); fixed.
