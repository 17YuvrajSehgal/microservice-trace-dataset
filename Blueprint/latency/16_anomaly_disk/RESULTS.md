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
and it moves 5-7 MB/s against 26-145 MB/s. The tool was not changed for this job. The bar was
added afterwards and rerun on both applications: see the next section.

## All runs of both applications, with the disk-wait bar (17-11-2026)

`blk_pressure.py` with `D_MIN = 1.0` (the hog's own threads wait on the disk for 1
thread-second per second or more) on all 304 v2 runs. SLURM job 2881657 on Trillium (one
node, 17 min, shared with blueprint 11). Same slices as above. Outputs:
`work/dx_check/sweep_1116/*.b16`.

| runs | verdict | numbers |
|---|---|---|
| `anomaly_disk` Sock Shop, 5 | DISK HOG | `stress-ng-hdd`, 99-100%, 1,817-2,239 req/s, 118-145 MB/s, its D-state 11.80-11.85 s/s |
| `anomaly_disk` Train Ticket, 5 | DISK HOG | `stress-ng-hdd`, 100%, 398-911 req/s, 26-59 MB/s, its D-state 15.84-15.94 s/s |
| `svc_mem_cap` Sock Shop 7, Train Ticket 4 | NO DISK PRESSURE + NOTE (busy issuer that does not wait) | one `java`, 80-100% of the requests, 221-493 req/s, 2.8-7.4 MB/s, its D-state 0.07-0.14 s/s |
| `anomaly_mem_subtle_steady_r2` | NO DISK PRESSURE + NOTE | a host `grep`, 93%, 744 req/s, 97.4 MB/s, its D-state 0.35 s/s |
| all other runs, 282 | NO DISK PRESSURE | |

10 of 10, 0 false alarms in 294. No slice failed.

Without the bar the 12 rows in the middle read DISK HOG. The margin: 0.35 against 11.80.
