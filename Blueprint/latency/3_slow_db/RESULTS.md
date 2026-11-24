# Blueprint 3 results (tool only, 23-11-2026)

Not a sweep on all runs. One question only: what do the victim's connections and its
sleep look like before and during the fault, on our labelled `slow_db` runs (Sock Shop,
delay added at the proxy in front of the catalogue database; the victim `app` is a Go
service). Asked because the first agent run ended inconclusive on two reading rules.

`sock_lag.py`, `sleep_where.py`, `sched_budget.py` on a 10 s slice 40 s before the
injection and a 10 s slice 50 s after it (`dep_slice.sh`). Trillium login node, one run at a
time. Outputs: `work/dx_check/sdb/*.v2`.

| | 5 aggressive runs (500 ms, jitter 100) | subtle r1 (60 ms, jitter 20) |
|---|---|---|
| victim, baseline: p50 of its 10 busiest connections | 0.5-15.3 ms | 0.8-18.5 ms |
| victim, baseline: p50 of all connections together | 1.0-1.1 ms | 1.3 ms |
| victim, fault: p50 of its 10 busiest connections | 467-553 ms, all 10 in that band | 59.6-65.5 ms, all 10 |
| victim, fault: p50 of all connections together | 413-421 ms | 50.6 ms |
| connection numbers (fd) seen in both slices | 0 or 1 of 10 | 3 of 10 |
| the database's own p50 in the fault slice | 494-505 ms | 61.2 ms |
| victim threads asleep in `locks`, baseline -> fault | 9.2-10.2 -> 8.6-10.5 | 10.21 -> 8.98 |
| victim threads asleep in `sock_read`, both slices | 0.00 | 0.00 |
| victim `wait` for the CPU, baseline -> fault | 0.17-0.20 -> 0.04 | 0.36 -> 0.32 |
| victim `D`, both slices | 0.00 | 0.00 |

What this means for the reading rules:

- **The connection numbers change.** The service opens new database connections while its
  old ones wait. "The same fd against its own baseline" cannot be checked. What holds: at
  baseline every busy connection is fast; in the fault a group of connections sits in one
  narrow band, and the band is the added delay.
- **A Go victim sleeps in `locks` all the time**, about 10 threads, and not in `sock_read`.
  The number does not rise in the fault. Sleep in `locks` is a sign against this fault only
  if it rises against the victim's own baseline.
- `sock_lag.py` lists the 10 connections with the most waiting time, and with `all` the 10
  processes with the highest p50. A victim that is fast at baseline is not in the baseline
  `all` table.

Not usable: subtle r2 and r3. The script picked the victim as the `app` process with the
most answers in the fault table, and at 60 ms the real victim was not in that table, so
another service was measured.
