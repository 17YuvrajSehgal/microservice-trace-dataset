# Candidate problems for the next collection (towards about 100)

**Updated 26-11-2026 (evening).** Status of every candidate, in one place:

| status | count | which |
|---|---|---|
| collected in v3 | 14 | A1, A2, A4, C1, D1, D4, E6, F1, F2, F4, F5, G1, H2, and `slow_client` (new, in place of E3) |
| parked | 7 | D7, and B1, B6, E1, E2, H5, H6 (reasons in "Parked") |
| removed (cancelled) | 8 | B3, B8, C2, C4, D12, E3, E13, G4 (reasons in "Removed") |
| left, not started | 42 | see "Left" below |

The 14 collected families have 5 aggressive runs each (Sock Shop, on Trillium) and three of
them also 3 subtle runs. Rows in the tables are marked with their status.

Written 17-11-2026. **Everything in the tables below is a prediction, not a measurement.**
Nothing here has been injected or traced. The "expected signal" and "best modality" columns
are guesses to be checked on data before any blueprint is written.

## Where we are

- 28 fault families in v2 (304 runs). 27 have a tool-level blueprint; `code_lock_across_io`
  has no kernel signal at the collected load.
- 3 more problems come from the partner traces (`cpu_starvation`, `syscall_stall`,
  `irq_imbalance`).
- Counted by mechanism it is about 25: `queue_backlog` equals `dependency_outage` in the
  trace, `anomaly_cpu` is close to `noisy_neighbor`, `code_serial_awaits` reads as
  `event_loop_block`.

## Rules for new families (lessons from the v2 blueprints)

1. **One family, one mechanism.** If two recipes leave the same trace, they are one problem.
   The "nearest existing family" column is there to catch this before collecting.
2. **Inject inside a real service when possible.** A helper `python3` or `stress-ng`
   container gives the fault a name and a new container to find. Blueprint 11 then fired on
   the helper of another family.
3. **Collect a subtle setting for every family**, not only the aggressive one.
4. **Make the baseline steady.** Start the load, let it settle, then open the baseline window
   (campaign issue 20). Blueprint 23 could not use the current baselines.
5. **Check that the target is on the request path** before each run (as done for `svc_net`).
6. **Enable the tracepoints the family needs** and verify they recorded (the `mm_vmscan_*`
   lesson). The last column of each table lists what is missing today.
7. **Add the family to `fault_catalog.md` through its section 7 amendment log** before
   collecting, with the predicted modality, so the prediction is on record.

Column "best": K = kernel trace, L = logs, M = metrics, T = distributed traces (spans).

## A. CPU and scheduler (8)

| # | Problem | How to inject | Expected kernel signal | Best | Nearest existing family | Needs |
|---|---|---|---|---|---|---|
| A1 | cpuset too small **(collected: `svc_cpuset`, blueprint 26)** | `docker update --cpuset-cpus` to 1 core on a busy service | service runs on one CPU only while others idle; run-queue waits | K | `svc_cpu_cap` (quota, has a period; this has none) | - |
| A2 | low CPU weight **(collected: `cpu_weight`, blueprint 33; also 3 subtle runs)** | `--cpu-shares 2` on one service plus a busy neighbour | waits only when the neighbour runs; no fixed period | K | `noisy_neighbor` | - |
| A3 | context-switch storm | thread pool of 2,000 in one service | very high `sched_switch` rate for one pid, short runs | K | `lock_contention` | - |
| A4 | spin loop **(collected: `code_spin_loop`, blueprint 36)** | a busy-wait in a handler (code flag) | one thread 100% on CPU with no system calls, requests still served | K | `event_loop_block` (there requests stop) | - |
| A5 | interrupt storm | flood one NIC queue with small packets from outside the stack | `irq_handler_entry` rate, softirq time on one CPU | K | `irq_imbalance` | irq events on the VM |
| A6 | timer jitter | a periodic thread plus CPU pressure on its core | wake-up latency of one periodic thread grows | K | `cpu_starvation` | - |
| A7 | CPU frequency drop | cap `scaling_max_freq` on the host | `power_cpu_frequency` falls; same work takes longer on CPU | K, M | `anomaly_cpu` | power events (now in the profile) |
| A8 | real-time thread hog | one `SCHED_FIFO` thread that never sleeps | one CPU never schedules normal threads | K | `cpu_starvation` | - |

## B. Memory (6)

| # | Problem | How to inject | Expected kernel signal | Best | Nearest existing family | Needs |
|---|---|---|---|---|---|---|
| B1 | slow memory leak (parked as `memory_leak`) | leak 1 MB/s in a Go or Java service for 10 minutes | steady `brk`/`mmap` growth below today's 0.5 MB/s bar | M, K | `code_unbounded_cache` (14 MB/s) | long runs |
| B2 | swap thrash | lower `memory.high` on a JVM with swap on | swap-in faults, D-state on swap device | K | `svc_mem_cap` | swap + `mm_vmscan_*` |
| B4 | garbage-collection pauses | small `-Xmx` on a JVM service | all application threads stopped together for 100 ms+, GC threads busy | K, L | `dependency_outage` (freeze) | - |
| B5 | page cache stolen by a neighbour | a container reading a huge file repeatedly | others' file reads go to disk again | K | `anomaly_disk` | - |
| B6 | cold start (parked as `cold_start`) | restart one service under load | exec, burst of page faults and file reads, JIT threads busy | K, T | `svc_mem_cap` restart | page-fault events |
| B7 | kernel slab growth | create millions of files or sockets | host reclaim with small process memory | K, M | `anomaly_mem` | `mm_vmscan_*` |

## C. Disk and filesystem (6)

| # | Problem | How to inject | Expected kernel signal | Best | Nearest existing family | Needs |
|---|---|---|---|---|---|---|
| C1 | disk full **(collected: `disk_full`, blueprint 27)** | fill the volume of one database | `write` returns -28 (ENOSPC) | L, K | `fd_exhaustion` (error-return pattern) | - |
| C3 | `fsync` storm | a service that syncs after every write | very many `fsync` calls, journal thread in D-state | K | `anomaly_disk` | fsync syscalls |
| C5 | slow device | `dm-delay` under one database volume | block latency up for everyone on the device, few requests | K | `anomaly_disk` | - |
| C6 | blocking log writes | synchronous logging to a slow volume | request threads in D-state inside `write` to a log file | K, T | `slow_db` | - |
| C7 | writeback throttle | a writer over the dirty limit | writer sleeps in `balance_dirty_pages` | K | `anomaly_disk` | `writeback_*` |
| C8 | read errors | `dm-flakey` returning I/O errors | block completions with `error != 0` | L, K | `error_storm` | - |

## D. Network (11)

| # | Problem | How to inject | Expected kernel signal | Best | Nearest existing family | Needs |
|---|---|---|---|---|---|---|
| D1 | ephemeral port exhaustion **(collected: `port_exhaustion`, blueprint 28)** | shrink `ip_local_port_range` in one netns | `connect` returns -99 (EADDRNOTAVAIL) | K, L | `fd_exhaustion` | - |
| D2 | listen queue overflow | `somaxconn` 1 on a busy service | SYN retransmits to one port, slow accepts | K | `svc_net` (loss) | - |
| D3 | slow reader (zero window) | a client that reads slowly | zero-window advertisements, sender blocked in `sendmsg` | K | `nagle_delayed_ack` | - |
| D4 | bandwidth cap **(collected: `net_bandwidth`)** | `tc tbf` on one container | steady low throughput, queue drops at one device | K, M | `svc_net` | - |
| D5 | MTU blackhole | lower MTU on a path and drop ICMP | small packets pass, large ones retransmit forever | K | `svc_net` | - |
| D6 | connection churn | disable keep-alive in one client | one SYN per request, many short connections | K, T | `error_storm` (opens then resets) | - |
| D7 | conntrack table full **(PARKED: calibrated, a host-wide outage; see "Parked")** | tiny `nf_conntrack_max` | new connections dropped, old ones fine | K, L | `conn_pool_exhaustion` | - |
| D8 | pure latency | `netem delay` on one service | no loss, every exchange slower by one constant | T, K | `anomaly_net`, `nagle_delayed_ack` | - |
| D9 | packet reordering | `netem reorder` | duplicate ACKs without loss | K | `svc_net` | - |
| D10 | wrong DNS answer | resolver returns a dead address | connects to an address nothing answers on | L, T | `dependency_outage` | - |
| D11 | DNS slow on a glibc or JVM resolver | delay the resolver for a Java service | lookups slow in a resolver `dns_retry.py` cannot see today | K | `dns_delay` (musl only) | - |

## E. Dependency and application behaviour (12)

| # | Problem | How to inject | Expected kernel signal | Best | Nearest existing family | Needs |
|---|---|---|---|---|---|---|
| E1 | retry storm (parked) | short timeout plus retries against a slow service | calls per request up AND answers slower | T, K | `code_n_plus_one` (answers not slower) | - |
| E2 | wrong timeout (parked) | timeout far too long or too short in one client | waits end at one constant; or resets by the client | T, L | `nagle_delayed_ack` | - |
| E4 | cache stampede | flush a cache under load | sudden burst of identical calls to the store | T, K | `code_n_plus_one` | a cache in the app |
| E5 | slow query | drop an index | one statement type slow, database CPU up | T, M | `slow_db` (proxy delay, DB idle) | - |
| E6 | row lock wait **(collected as a TABLE lock: `db_table_lock`, blueprint 30; a row lock does nothing to a service that only reads)** | a long transaction holding a row lock | database threads sleep, queries hang then finish together | K, L | `lock_contention` | - |
| E7 | database deadlock | two transactions in opposite order | one is aborted with an error; no hang | L | `deadlock` (threads hang forever) | - |
| E8 | slow consumer | consumer sleeps per message | queue grows, consumer alive and slow | M, K | `queue_backlog` (consumer frozen) | - |
| E9 | poison message | one message that always fails | same message redelivered in a loop | L | `error_storm` | - |
| E10 | crash loop | service exits on start | exec and exit of one name, port refused in between | L, K | `fd_exhaustion` restarts | - |
| E11 | rate limiting | limit one upstream to N requests/s | fast error answers above N, nothing slow | L, T | `error_storm` | - |
| E12 | bad configuration | wrong address for one dependency after a restart | connects refused or to nowhere from the first request | L | `dependency_outage` | - |
| E14 | wrong results | handler returns wrong data, same speed | none expected | T, L | none | a correctness check in the load generator |

## F. Code defects inside a service (8)

| # | Problem | How to inject | Expected kernel signal | Best | Nearest existing family | Needs |
|---|---|---|---|---|---|---|
| F1 | lock across I/O at real load **(collected: `code_lock_contended`, blueprint 25)** | rerun `code_lock_across_io` at 4-8 times the load | calls to the dependency stop overlapping | K, T | `lock_contention` | higher load |
| F2 | thread leak **(collected: `code_thread_leak`, blueprint 35)** | a thread per request that never ends | thread count of one pid only grows | K, M | `dependency_outage` pile-up (blueprint 24 note) | - |
| F3 | slow descriptor leak | never close one file or socket per N requests | highest fd climbs for minutes, then EMFILE | K, M | `fd_exhaustion` (step) | long runs |
| F4 | regex backtracking **(collected: `code_regex_backtrack`, blueprint 38)** | a bad pattern on user input | one thread on CPU for seconds on some requests only | K, T | `event_loop_block` | - |
| F5 | large payloads **(collected: `code_large_payload`, blueprint 37)** | return the whole table | bytes per answer up, calls unchanged | K, T | `data_exfiltration` | - |
| F6 | chatty calls | N small calls where one would do, between services | calls per request up between two services | T, K | `code_n_plus_one` | - |
| F7 | unbounded queue | producer faster than an in-process worker | memory grows, latency grows with it | M, K | `code_unbounded_cache` | - |
| F8 | blocking call in async code | a sync file read in a Node or async Java handler | event thread in D-state or long syscall, requests stall | K | `event_loop_block` (on CPU) | - |

## G. Security (5)

| # | Problem | How to inject | Expected kernel signal | Best | Nearest existing family | Needs |
|---|---|---|---|---|---|---|
| G1 | port scan **(collected: `port_scan`, blueprint 34)** | one container connects to every port of every peer | many refused connects from one source to many ports | K | `resource_abuse` | - |
| G2 | login brute force | repeated failing logins at one endpoint | steady stream of fast error answers from one client | L, T | `error_storm` | - |
| G3 | unexpected program start | a service spawns a shell | `exec` of a program never seen in that container | K | `fork_storm` (rate; here once) | - |
| G5 | SYN flood | half-open connections from outside | SYNs with no third packet, listen queue full | K | D2 | - |
| G6 | unusual file access | read many files outside the service's normal set | `openat` on paths never seen before | K | `data_exfiltration` | `openat` with file names |

## H. Kernel and host (6)

| # | Problem | How to inject | Expected kernel signal | Best | Nearest existing family | Needs |
|---|---|---|---|---|---|---|
| H1 | kernel hot path | a table the kernel scans per event (large route or rule table) | one syscall long ON CPU inside the kernel | K | `syscall_stall` | function durations (kprobe or function_graph) |
| H2 | process limit reached **(collected: `pid_limit`, blueprint 29)** | `pids.max` on one container | `clone` returns -11 (EAGAIN) | K, L | `fd_exhaustion` | - |
| H3 | zombie build-up | a parent that never waits for children | exits with no reaping, process table grows | K | `fork_storm` | - |
| H4 | uninterruptible I/O stall | freeze the block device briefly | long D-state for all writers, no completions | K | `anomaly_disk` | - |
| H5 | clock step (parked as `clock_skew`) | step the clock on one container's host view | timers fire early or late; span times inconsistent | T | none | risky: can corrupt run timestamps |
| H6 | compound fault (parked) | two existing recipes at once | both signatures present | all | each of its parts | a wrapper that runs two recipes |

## Collected in v3 (Sock Shop)

| # | family | runs | tool, blueprint | note |
|---|---|---|---|---|
| F1 | `code_lock_contended` | 5 | `inside_wait.py` + `wait_cause.py`, 25 | needs a 5 ms database delay and extra load to show |
| A1 | `svc_cpuset` | 5 | `cpu_confine.py`, 26 | subtle (2 cores) had no effect, not collected |
| C1 | `disk_full` | 5 | `new_errors.py`, 27 | no metric signature; the tool needs a slice with a crash |
| D1 | `port_exhaustion` | 5 | `new_errors.py`, 28 | subtle (1,500 ports) had no effect, not collected |
| H2 | `pid_limit` | 5 | `new_errors.py`, 29 | subtle (8 tasks of headroom) had no effect |
| E6 | `db_table_lock` | 5 + 3 subtle | `inside_wait.py` + `wait_cause.py`, 30 | a table lock, not a row lock |
| (E3) | `slow_client` | 5 | `unanswered.py`, 31 | thread pool exhaustion without a restart |
| D4 | `net_bandwidth` | 5 + 3 subtle | `dev_delay.py`, 32 | |
| A2 | `cpu_weight` | 5 + 3 subtle | `cpu_starved.py`, 33 | its baseline is a busy host; kept for now, to look at again |
| G1 | `port_scan` | 5 | `scan_fanout.py`, 34 | no metric signature |
| A4 | `code_spin_loop` | 5 | `cpu_runs.py`, 36 | catalogue p95 3.4 -> 17.5 ms (spans), 0 errors |
| F5 | `code_large_payload` | 5 | `bytes_per_call.py`, 37 | catalogue sends about 7 times more bytes; answer times barely change |
| F4 | `code_regex_backtrack` | 5 | `cpu_runs.py`, 38 | front-end p95 about 0.09 -> 0.21 s, p50 barely moves |
| F2 | `code_thread_leak` | 5 | `thread_growth.py`, 35 | catalogue threads 16 -> about 300 in the fault, about 520 after (by design) |

Group 2 (code defects, images `catalogue-bugs:v3` and `frontend-bugs:v3`) collected 26-11-2026.

## Parked (may come back; not cancelled)

| # | Problem | Why parked |
|---|---|---|
| D7 | conntrack table full | calibrated 25-11-2026: at the current entry count the whole host stops (site, metrics, name resolution) and the load generator does not recover; very likely the front-end crash loop after a restart under load (progress-notes 25-11). Needs a milder setting first. Recipe `faults/conntrack_full.sh` |
| B1 | slow memory leak | needs runs of 10 minutes or more |
| B6 | cold start | needs page-fault events and a restart that does not crash-loop the front-end |
| E1 | retry storm | needs a design that keeps the baseline clean (a start-up change) |
| E2 | wrong timeout | same |
| H5 | clock step | can corrupt the run's own timestamps |
| H6 | compound fault | needs a wrapper that runs two recipes |
| - | `io_cap` (C4) | kept as a possible kernel-only family: the limit holds the database's writes back (68.6 -> 16.0 KB/s) but no service notices. User decision 25-11: leave for now |

## Left, not started (42)

| group | candidates | what they need |
|---|---|---|
| ready with what we have | A3, A6, A8, B5, C3, C6, D3, D5, D6, D8, D9, D10, D11, E4, E5, E7, E8, E9, E11, E12, F3, F6, F7, F8, G2, G3, G5, H3, H4 | a recipe and a calibration; some need a code defect (F3, F6, F7, F8) or a new load pattern |
| need a start-up change | B4, D2, E10 | a design that keeps the baseline clean |
| need events we do not record yet | A5 (interrupts), A7 (CPU frequency, now in the profile: to check), B2 and B7 (memory reclaim, swap), C5 and C8 (a device mapper target on the VM), C7 (writeback), G6 (file names on `openat`), H1 (kernel function timing) | a tracing profile change, checked on a recorded trace |
| need a change to the application or load | E14 (a correctness check in the load generator) | |

Counted in "ready" are 29; "start-up change" 3; "events" 9; "application" 1.

## Removed (cancelled)

| # | Problem | Why removed |
|---|---|---|
| C4 | I/O cap on one container (kept as `io_cap`, see "Parked") | measured 25-11-2026: `io.max` at 16 KB/s and 5 operations/s on carts-db, orders-db and user-db changed no service's rate, errors or answer time. These databases acknowledge a write before it reaches the disk. Recipe kept in `faults/io_cap.sh` |
| E3 | thread pool exhaustion by a small pool | the pool size is a start-up option, so the fault would also be in the baseline. `slow_client` gives the same exhaustion at run time |
| G4 | slow-request flood | the same mechanism as `slow_client`, already collected |
| B8 | huge-page compaction stalls | the compaction tracepoints are absent on the GCP kernel |
| B3 | kill-and-restart loop | already in v2. Calibrated 25-11-2026: at 160 MB (the v2 `svc_mem_cap` aggressive limit) carts is killed and restarted 9 times in 2 minutes and serves nothing. The v2 logs agree: the subtle runs (300 MB) show 8-9 JVM start banners per run and the aggressive runs none until the limit is lifted. So `svc_mem_cap` IS a restart loop at both settings. Recipe kept in `faults/oom_restart_loop.sh` |
| C2 | inode exhaustion | measured 25-11-2026 with bpftrace: no program on the host created a file or a directory in 20 s of the 150-user load, so a volume with no free inodes changes nothing |
| D12 | TLS handshake storm | neither application uses TLS between services |
| E13 | certificate expiry | neither application uses TLS between services |

## Cost to plan for (rough)

- 70 families at 10 runs each (5 per application, where both apply) is about 700 runs. The
  first batch of 15 is about 150 runs, plus 3 subtle runs per family.
- v2 is 304 runs and about 8 TB extracted, so 150 more runs is about 4 TB and 700 is about
  18 TB. Check the scratch quota before a large batch.
- Each family also costs one full false-alarm sweep per new tool (one Trillium node for 15 to
  50 minutes on today's numbers), and group priority there fell from 71.7 to 14.2 in one day
  of sweeps.
- A fresh collection VM is needed (`vm_bootstrap.sh`, then `run_gate.sh gate01`).
