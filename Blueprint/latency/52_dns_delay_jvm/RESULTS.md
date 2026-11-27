# Blueprint 52 results (tool only, 27-11-2026)

Tested on the Trillium login node, 27-11-2026, on the 50 runs of groups 5, 6 and 7 (10 families, 5 runs each). Every tool was run on all 50 runs and reversed (baseline as suspect). Slices in `work/v3bp_g567/` on Trillium. NOT yet run on the earlier runs (needs a SLURM job). Slices: 60 s of the DNS system calls from 2 s after the injection; the reversed test uses 60 s from 62 s before it.

| run | `dns_retry.py` on `dns_delay_jvm` (the orders service, `java`) |
|---|---|
| r1 | 8 of 8 lookups timed out and were sent again (100%), slowest 5.0 s, 40.0 s lost |
| r2 | 7 of 7 (100%), 35.0 s lost |
| r3 | 7 of 7 (100%), 32.5 s lost |
| r4 | 5 of 6 (83%), 25.0 s lost |
| r5 | 8 of 8 (100%), 40.0 s lost |

Quiet on the other 45 runs and on all 50 baseline slices; the most elsewhere was 1 timed-out lookup
of 95 by `node`. `dns_retry.py` is the tool of blueprint 21, used as it is. Its header says it reads
the C library's resolver; the JVM's lookups have the same shape here (a send, a poll that times out
after 5.0 s, the same thread sends again), so it works without a change.

From the collection's check: the front-end returned 968 to 1,547 failed requests per run, and in 4
of 5 runs errors went on in the recovery window (13 to 131 failed requests there). The orders
service's own metrics did not move.
