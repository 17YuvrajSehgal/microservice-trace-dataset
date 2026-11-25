# Blueprint 26 results (tool only, 25-11-2026)

Fault runs: the 5 v3 `svc_cpuset` runs (carts limited to the last of 12 cores).

| runs | verdict | numbers |
|---|---|---|
| `svc_cpuset`, 5 | CONTAINER CONFINED TO FEW CPUS, 5 of 5 | carts (`java`) on 1 CPU, 12 before; CPU wait about 0.1 before and 1.3 now |
| reversed, 5 | quiet in 5 | |
| other runs, 342 | 1 positive: `code_event_loop_block` (one run, `node`) | |
| normal, 20 | 0 | |

False-alarm sweep: SLURM job 2931081 on Trillium (25-11-2026, one node, 34 min), all 349 runs (v2 Sock Shop 170, v2 Train Ticket 134, v3 Sock Shop 45); 2 runs gave no slice (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`), so 347 were judged. One baseline slice (20 s ending 20 s before the injection) and one fault slice (20 s from 30 s into it) per run; normal runs use 100 s after the trace start. Outputs: `work/dx_check/sweep_v3tools/` on Trillium.
