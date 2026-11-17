# Blueprint 24 results (tool only, 17-11-2026)

`mem_growth.py` on every v2 run of both applications (304): one 30 s slice of memory system
calls, 30 s after the injection (normal runs: 130 s after the trace start). SLURM jobs
2879871 (first rule, 21 min) and 2880078 (with the kept-share rule and the thread count,
22 min), one Trillium node each, shared with blueprint 23. Outputs:
`work/dx_check/sweep_cd/*.mem`, `work/dx_check/sweep_cd2/*.mem`.

| runs | verdict (final rule) | numbers |
|---|---|---|
| `code_unbounded_cache`, 5 | MEMORY ONLY GROWS | `node` took 413-431 MB in 30 s (13.8-14.4 MB/s), 100% of the seconds, keeps 21-22%, 0 threads started |
| `dependency_outage` Sock Shop, 5 | MEMORY GROWS WITH NEW THREADS | one `java` took 312-344 MB, keeps 21%, started 1,470-1,616 threads |
| all other runs, 292 | NO STEADY MEMORY GROWTH | largest steady growth that keeps under 10%: one `java`, 17-29 MB of about 2 GB asked (1%) |
| 2 runs | no result: the slice cut failed (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`) | |

Leak verdict: 5 of 5, 0 false alarms in 297.

Rule history:

| rule | fault runs | false alarms |
|---|---|---|
| first: 0.5 MB/s, 80% of the seconds, at most 50% in one second | 5 of 5 | 97 other Sock Shop runs (one `java`, almost every family, also 9 of 10 `normal`), 0 on Train Ticket |
| + keeps 10% of what it asked for | 5 of 5 | 5 (`dependency_outage`) |
| + growth above 2 MB per thread started (applied to the saved outputs) | 5 of 5 | 0 |

Large one-off requests are rejected by the one-second rule: `stress-ng-vm` (22.5 and 35.3 GB,
100% in one second), restarted JVMs in `svc_mem_cap` (246-410 MB, 33-57% in one second,
growing in 33-50% of the seconds).
