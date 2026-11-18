# Results: anomaly_disk on our labelled runs (2026-11-11)

Tool: `tools/blk_pressure.py`. Data: Sock Shop v2 (StrataTrace), Trillium `data/stratatrace-v2/sockshop/`.
Slices: a 10 s quiet slice 45 s before the injection and a 10 s slice 50 s into it (a 60 s slice
from +5 s for the deadlock tool). Run on the login node with `work/newbp/validate_one.sh`.

| check | result |
|---|---|
| fires on its own family (5 runs) | **5 / 5** |
| stays quiet on the other three new families (15 runs) | **15 / 15** quiet |
| stays quiet on normal runs (5 runs, no fault) | **5 / 5** quiet |

Verdict line per labelled run:

| run | verdict |
|---|---|
| r1 | `VERDICT: DISK HOG: stress-ng-hdd (ns 4026533601) issued 100% of user-space block requests (2239 req/s, 145.2 MB/s; baseline 0.0 req/s); its D-state 11.82 s/s; other issuers' latency p50 1.0 ms -> 4.7 ms; newly in D state: dockerd, python3` |
| r2 | `VERDICT: DISK HOG: stress-ng-hdd (ns 4026533601) issued 99% of user-space block requests (1817 req/s, 118.0 MB/s; baseline 0.0 req/s); its D-state 11.85 s/s; other issuers' latency p50 0.9 ms -> 5.6 ms; newly in D state: dockerd` |
| r3 | `VERDICT: DISK HOG: stress-ng-hdd (ns 4026533601) issued 99% of user-space block requests (1942 req/s, 125.8 MB/s; baseline 0.0 req/s); its D-state 11.82 s/s; other issuers' latency p50 1.0 ms -> 5.6 ms; newly in D state: dockerd` |
| r4 | `VERDICT: DISK HOG: stress-ng-hdd (ns 4026533601) issued 99% of user-space block requests (1929 req/s, 125.3 MB/s; baseline 0.0 req/s); its D-state 11.84 s/s; other issuers' latency p50 0.9 ms -> 4.7 ms; newly in D state: dockerd, WTJourn.Flusher` |
| r5 | `VERDICT: DISK HOG: stress-ng-hdd (ns 4026533601) issued 99% of user-space block requests (1984 req/s, 128.6 MB/s; baseline 0.0 req/s); its D-state 11.80 s/s; other issuers' latency p50 1.2 ms -> 5.6 ms; newly in D state: dockerd` |

## How the bar was set (what failed first)
Version 1 missed 5 of 5: the tracer's own writes (lttng-consumerd, ~1,500 req/s) diluted the culprit to 47%; the share is now taken among user-space issuers only. Version 2 then fired on fork_storm r5 (a Prometheus compaction: 25 req/s, 73% of a tiny user-space total); a floor of 200 req/s was added (the real hog: 1,800-2,200 req/s). The table below is from version 3, re-scored on the kept slices.

## Train Ticket check (17-11-2026)

Every Train Ticket v2 run (134), SLURM job 2881327 on Trillium (one node, 53 min, shared by
blueprints 11, 12, 13, 14 and 16). The tool is unchanged from the Sock Shop check. Outputs:
`work/dx_check/sweep_tt/`.
Slices: 10 s 45 s before the injection and 10 s 50 s into it.

| runs | verdict | numbers |
|---|---|---|
| `tt_anomaly_disk`, 5 | DISK HOG, 5 of 5 | `stress-ng-hdd`, 100% of user-space block requests, 398-911 req/s, 25.6-58.8 MB/s, its D-state 15.8-15.9 s/s |
| `tt_svc_mem_cap`, 4 of 8 (aggressive r1, subtle r1-r3) | DISK HOG, **wrong family** | one `java`, 80-88% of the requests, 357-493 req/s, 4.8-7.4 MB/s, its D-state 0.11-0.14 s/s |
| all other Train Ticket runs, 125 | no verdict | |

5 of 5, 4 false alarms in 129.

The 4 false alarms are a memory-capped JVM that reads its own pages back from disk. The disk
load is real, but the cause is the memory limit (blueprint 4 warns that its victim looks like
a disk problem). What separates them in these numbers: the true hog sits in disk wait for
11.8-15.9 thread-seconds per second (Sock Shop and Train Ticket), the capped JVM for 0.11-0.14,
and it moves 5-7 MB/s against 26-145 MB/s. The tool was NOT changed; a bar on the D-state
would be set after seeing this result and needs a rerun on both applications first. The
`svc_mem_cap` runs were not in the 25-run Sock Shop check either.
