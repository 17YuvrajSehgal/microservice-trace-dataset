# Blueprint 2: `cpu_newcomer.py` on all v2 runs (tool only, 17-11-2026)

Every v2 run of both applications (304): a 10 s scheduling slice 40 s before the injection
and one 30 s after it (normal runs: 60 s and 130 s after the trace start). SLURM job 2879026
on Trillium (one node, 16 min, shared with the blueprint 4 check). Outputs:
`work/dx_check/sweep_am/*.cpu.out`.

| runs | verdict | the newcomer |
|---|---|---|
| `anomaly_cpu`, 10 (both applications) | NEW CPU USER FILLS THE MACHINE | `stress-ng-cpu`, 24 processes at 6.4-6.6 of 12 cores (Sock Shop), 32 at 9.5-9.7 of 16 (Train Ticket); 0% idle |
| `noisy_neighbor`, 16 | NEW CPU USER, MACHINE NOT FULL | `stress-ng-cpu`, 2 processes at 1.0 cores or 4 at 2.0 cores (the cap); 11-25% idle on Sock Shop, 72-81% on Train Ticket |
| `anomaly_mem`, 15 | NEW CPU USER, MACHINE NOT FULL | `stress-ng-vm`, 0.9-1.0 cores |
| `lock_contention` 10, `priority_inversion` 10, `nagle_delayed_ack` 10, `resource_abuse` 10 | NEW CPU USER, MACHINE NOT FULL | the injected `python3` workload, 0.8-1.0 cores |
| `svc_mem_cap`, 10 of 16 | NEW CPU USER, MACHINE NOT FULL | a restarted JVM, 1.0-1.9 cores |
| `tt_svc_net` r3 | NEW CPU USER, MACHINE NOT FULL | a restarted JVM, 4.7 of 16 cores, 42% idle |
| all other runs, 211 | NO NEW CPU USER | |
| 1 run | no result: the slice cut failed (`anomaly_mem_subtle_steady_r3`) | |

FILLS THE MACHINE: 10 of 10, 0 false alarms in 294. The margin: the fault runs are at 0% idle
with 54-61% of all cores; the closest other run has 29% of the cores and 42% idle, and the
fullest other machine with a newcomer is 11% idle.

MACHINE NOT FULL is not a family verdict: 16 `noisy_neighbor` runs and 66 others.
