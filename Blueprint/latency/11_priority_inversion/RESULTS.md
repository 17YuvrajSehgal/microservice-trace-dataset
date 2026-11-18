# Blueprint 11 results

## Train Ticket check (17-11-2026)

Every Train Ticket v2 run (134), SLURM job 2881327 on Trillium (one node, 53 min, shared by
blueprints 11, 12, 13, 14 and 16). The tool is unchanged from the Sock Shop check. Outputs:
`work/dx_check/sweep_tt/`.
Slice: 20 s from 30 s after the injection (the README suggests 60 s; Train Ticket has 67
containers and its `futex` events are very large).

| runs | verdict | numbers |
|---|---|---|
| `tt_lock_contention`, 5 | LOCK CONTENTION, 5 of 5 | `python3`, 16 threads, about 3,600 held waits per second, p50 4.1 ms, lock-wait time 1,484-1,486% of the slice |
| `tt_priority_inversion`, 5 | PRIORITY INVERSION (chained), 5 of 5 | a `python3` thread at nice 0 or -5 waited 466-751 ms; its holder at nice 19 was blocked 51-100% of that wait on a second lock |
| `tt_resource_abuse`, 5 | LOCK CONTENTION, **wrong family** | `python3`, 7 threads, 99 held waits per second, almost all runs of 5 ms timed waits, p99 149-187 ms, lock-wait time 107-114% of the slice |
| all other Train Ticket runs, 119 | NO LOCK PROBLEM | |

10 of 10, each with the right one of the two verdicts; 5 false alarms in 124.

The 5 false alarms are the injected `resource_abuse` workload itself: a multi-threaded Python
program that burns CPU, so its threads queue on one lock in 5 ms timed waits. The contention
is real, but the family is `resource_abuse` (blueprint 18 names it by its CPU use and its
periodic connections). The tool was NOT changed.

Not checked: blueprint 11 has never been run on ALL Sock Shop runs (only on its own families,
`normal` and a few others), so the same verdict on the Sock Shop `resource_abuse` runs is
likely and unmeasured.

## All runs of both applications (17-11-2026)

`futex_wait.py`, unchanged, on the 170 Sock Shop runs (SLURM job 2881657, one Trillium node,
17 min); the Train Ticket outputs are those of job 2881327 (same tool, same slice: 20 s from
30 s after the injection). Outputs: `work/dx_check/sweep_1116/*.b11`.

| runs | verdict | numbers |
|---|---|---|
| `lock_contention`, 10 (both applications) | LOCK CONTENTION, 10 of 10 | `python3`, 16 threads, 3,345-3,630 held waits per second, p50 4.1-4.2 ms, lock-wait time 1,477-1,486% of the slice, top waiter 92-93% of its time |
| `priority_inversion`, 10 | PRIORITY INVERSION (chained), 10 of 10 | waiter at nice -5 or 0 waited 347-751 ms; holder at nice 19 blocked 51-100% of that wait on a second lock |
| `resource_abuse`, 10 | LOCK CONTENTION, **wrong family** | `python3`, 7 threads, 92-99 held waits per second, almost all runs of 5 ms timed waits, lock-wait time 107-114%, top waiter 28-34% |
| `svc_mem_cap_subtle_steady_r1` | LOCK CONTENTION, **wrong family** | `containerd-shim`, 2 waits of 5.9 s, 30% of the slice |
| all other runs, 271 | NO LOCK PROBLEM | |
| 2 runs | no result: the slice cut failed (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`) | |

20 of 20, each with the right one of the two verdicts; 11 false alarms in 282.

The tool was not changed. The 10 `resource_abuse` verdicts are real contention on the Python
interpreter lock inside the injected CPU burner; the README (Part 5) now tells the reader to
check blueprint 18 before reporting. A bar between the two groups (92-99 against 3,345 waits
per second) would separate these runs but would be fitted to two injected workloads.
