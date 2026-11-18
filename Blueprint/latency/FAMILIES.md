## Microservice hosts (containers, cgroup limits)

| Cause                        | Families                                                         |
|------------------------------|------------------------------------------------------------------|
| Too much work                | `code_n_plus_one`, `code_serial_awaits`, `code_event_loop_block` |
| Waiting for CPU              | `svc_cpu_cap`, `anomaly_cpu`, `noisy_neighbor`, `fork_storm`     |
| Waiting for disk             | `anomaly_disk`                                                   |
| Waiting for network          | `anomaly_net`, `svc_net`, `nagle_delayed_ack`, `dns_delay`       |
| Waiting for a lock           | `lock_contention`, `priority_inversion`, `code_lock_across_io`   |
| Waiting for a remote service | `slow_db`, `conn_pool_exhaustion`                                |

## Bare-metal hosts (switch and router line cards, embedded boxes)

No containers, no cgroup limits, one pid namespace. The thread is the unit of blame, and the
faults are about *which core*, *which priority* and *which kernel path*, not about a quota.
Built from three solved cases of an industry partner (telecom line cards; the traces and the
engineers' own RCA are under NDA and stay off git) plus our own labelled runs (03-11-2026); each
row names the blueprint folder under `Blueprint/latency/` and what it was calibrated on.

| Cause | Family (blueprint) | Kernel signal | Calibrated on |
|---|---|---|---|
| Waiting for CPU behind a crowd | `cpu_starvation` (8) | one thread runnable-but-waiting (wakeup -> switch-in, preempt -> resume) while same-or-higher-prio threads hold its core; other cores idle | partner case 1 (two cards): the comms Tx thread at prio 120 among 66-84 same-prio threads on its core, max waits 30 ms, other cores 45-63% idle; engineers' fix: prio 120 -> 110 |
| Frozen by a sibling's system call | `syscall_stall` (9) | one thread in one WORK-class syscall (clone / fork / mmap / ioctl) for tens of ms, on-CPU or in D; dependants blocked in D and released at its exit; repeats | partner case 2: a status thread's `clone` (flags 0x100011, a full fork) of 49-53 ms; the comms thread in D for 48 ms each time; engineers' fix: `posix_spawn` (1.9 ms) |
| Interrupt work piled on one core | `irq_imbalance` (10) | NET_RX softirq share on one CPU far above 1/ncpu; `ksoftirqd/N` busy; app threads on that CPU or its SMT sibling; baseline-vs-load diff | partner case 3 (with/without load pair): 100% of NET_RX on cpu 0, `ksoftirqd/0` 42% of a CPU (engineers measured 43.4%); fix: pin the SDK threads to other cores |
| Lock held by a thread that cannot run | `priority_inversion` (11) | few LONG futex waits ending with a wake (ret 0); the releaser was runnable-but-not-running, its CPU taken by middle-priority threads | our `priority_inversion_*` runs (nice-based, 50 ms hold); Train Ticket 5/5 (17-11) |
| Many threads on one lock | `lock_contention` (11, same tools) | MANY SHORT woken futex waits on one address; holders run while holding | our `lock_contention_*` runs; Train Ticket 5/5, but the 5 `tt_resource_abuse` runs also read LOCK CONTENTION (the injected Python workload queues on one lock) |
| A process out of file descriptors | `fd_exhaustion` (12, `fd_pressure.py`) | `ret = -24` (EMFILE) on `accept4`/`socket`/`openat` from ONE process, its highest fd at a flat ceiling, the same comm exec'd several times (restart loop) | our `fd_exhaustion_*` runs: 23 EMFILE + 9 restarts of the front-end in the window, 0 at baseline; Train Ticket 5/5, 0 false alarms in 129 (no restarts there) |
| A workload spawning processes at a runaway rate | `fork_storm` (13, `proc_spawn.py`) | one namespace's `sched_process_fork` with child_pid == child_tid at >= 20/s and >= 10x baseline (threads counted apart: a JVM makes 70-90 threads/s normally) | our `fork_storm_*` runs: 5/5, 0 false alarms in 20 other runs; Train Ticket 5/5, 0 in 129 |
| Threads deadlocked on each other's locks | `deadlock` (14, `futex_hang.py`) | threads CREATED in the slice enter an untimed futex wait within 1 s and never return, on >= 2 lock addresses (idle pool threads parked from before are excluded) | our `deadlock_*` runs: 5/5, 0 false alarms; Train Ticket 5/5, 0 in 129 |
| A dependency paused / frozen / dead | `dependency_outage` (15, `ns_silence.py` + `freeze_moment.py`) | one namespace goes from >= 20 events/s to < 1% of that, AND all its threads were scheduled out at one moment (>= 3 woken from sleep); thread exits = died | our `dependency_outage_*` runs on both applications: 10/10; silence alone has 80 false alarms in 288 other runs, with the freeze moment 0 |
| One process flooding the disk | `anomaly_disk` (16, `blk_pressure.py`) | one user-space issuer >= 50% of user-space block requests, >= 200 req/s, >= 10x baseline; others' latency and D state rise | our `anomaly_disk_*` runs: 5/5, 0 false alarms; Train Ticket 5/5, but 4 of 8 `tt_svc_mem_cap` runs also read DISK HOG (a memory-capped JVM reading its pages back) |
| A process that burns CPU and phones out on a timer | `resource_abuse` (18, `beacon.py`) | one pid with >= 0.5 cores AND >= 5 `connect()` calls to one destination at even gaps (>= 1 s, jitter <= 10%) | our `resource_abuse_*` runs on both applications: 10/10, 0 false alarms in 292 other runs |
| One process pushing bulk data out one way | `data_exfiltration` (19, `egress.py`) | one stream (source -> destination:port) with >= 5 MB/s of TCP payload, <= 1% payload coming back, flowing in >= 90% of the seconds | our `data_exfiltration_*` runs on both applications: 10/10, 0 false alarms in 293 other runs |
| Requests slow by one fixed timer, nothing busy | `nagle_delayed_ack` (20, `ack_stall.py`) | one connection with >= 10 stalls (data, >= 20 ms silence, bare ACK, data at once), >= 80% of them at one length, >= 20% of the slice spent waiting | our `nagle_delayed_ack_*` runs on both applications: 10/10, 0 false alarms in 293 other runs |
| Name lookups time out and are sent again | `dns_delay` (21, `dns_retry.py`) | one program (one pid) with >= 3 lookups where `poll` timed out and the query was sent again, >= 5% of its lookups; a program that restarted in the slice is reported as restarting, not as this fault | our `dns_delay_*` runs (Sock Shop only): 3/5 clean and found, 2/5 are a crash loop; 0 false alarms in 297 other runs. musl resolver only |
| A queue consumer paused, work piles up silently | `queue_backlog` (15, `ns_silence.py` + `freeze_moment.py`) | same as `dependency_outage`: one namespace goes silent AND all its threads were scheduled out at one moment, >= 3 of them woken from sleep | our `queue_backlog_*` runs: 5/5; with `dependency_outage` 15/15, 0 false alarms in 288 other runs. The trace cannot tell the two families apart |
| An uncapped workload takes every core | `anomaly_cpu` (2, `cpu_newcomer.py`) | one container with < 0.05 cores in the baseline slice holds >= 25% of all cores in the fault slice, and the machine is < 5% idle | our `anomaly_cpu_*` runs on both applications: 10/10, 0 false alarms in 294 other runs. Aggressive setting only. The other verdict (new CPU user, machine not full) fits all 16 `noisy_neighbor` runs and 66 runs of other families |
| One process takes the host's memory | `anomaly_mem` (4, `mem_pressure.py`) | one writable anonymous `mmap` of >= 4 GB in a slice cut at the start of the window, then CPU time while the pages are touched | our `anomaly_mem_*` runs on both applications: 16/16 (22.0-34.5 GB), 0 false alarms in 288 other runs (none reaches 256 MB) |
| A server side accepts connections and resets them | `error_storm` (22, `tcp_conns.py`) | one server address:port answers the SYN and then sends a RST on >= 5 new connections and >= 50% of those opened to it, counted over all clients | our `error_storm_*` runs on both applications: 16/16, 0 false alarms in 286 other runs. Aggressive setting only. "Refused" (no answer to the SYN) is a separate verdict: a dead or restarting service |
| One client holds the connections of a server | `conn_pool_exhaustion` (6, `tcp_conns.py`) | one client with >= 50 connections to one server that are open all slice with < 1 kB each (>= 90% of the pair), and the pair is absent from the baseline slice | our `conn_pool_exhaustion_*` runs on both applications: 10/10 (149 and 1,800 held), 0 false alarms in 292 other runs; 91 runs have a standing pool that is also in the baseline |
| A service makes more calls to a healthy dependency per request | `code_n_plus_one` (23, `call_fanout.py`) | calls from one service to one server, per request the service receives, up >= 1.35x against a baseline at the same steady load, answers not slower (<= 1.1x), >= 200 calls and >= 200 received requests | our `code_n_plus_one_*` runs: 6/6 (1.45-1.57x), 0 false alarms in the 175 other runs that could be judged; 123 runs not judged. Weak: the bar is fitted (nearest healthy pair 1.28x) and a baseline in the load ramp-up gives 1.6x for a healthy service |
| The memory of one process only grows | `code_unbounded_cache` (24, `mem_growth.py`) | one process takes >= 0.5 MB/s net (`brk` + anonymous `mmap` - `munmap`) in >= 80% of the seconds, keeps >= 10% of what it asked for, and the growth is more than 2 MB per thread it started | our `code_unbounded_cache_*` runs: 5/5 (14 MB/s), 0 false alarms in 297 other runs; the 5 `dependency_outage` runs get "grows with new threads" |

### Not built yet (needs a labelled trace first)

| Cause | Signal to look for | Why it waits |
|---|---|---|
| Kernel hot path that scales with a table (partner case 4: a label-space scan on every link event) | a syscall (`sendmsg`) that is 10-30 ms on-CPU inside the kernel | needs ftrace `function_graph` / kprobe durations; a count index cannot see inside a syscall |
| A lock held across a database call (`code_lock_across_io`) | calls to the dependency that stop overlapping; `futex` waits in the service | measured on our 5 runs (17-11): calls per request 0.97-1.01x, answer time unchanged, 2 or more calls in flight 62-66% (66-68% before), `futex` calls 0.98-1.03x. At this load the lock is not contended enough to show; needs a run at higher load |
| Periodic thread missing its period (timer jitter) | wakeup latency of a thread with a fixed period; period variance | partly covered by `runq_wait.py`; needs a thread with a known period to calibrate |
| Interrupt storm (one IRQ line flooding) | `irq_handler_entry` rate and time per irq per CPU | `irq_balance.py` prints it; no labelled storm yet |
| Uninterruptible I/O stall (D-state on a disk) | long D intervals + `block_rq_issue/complete` latency | the `anomaly_disk` family on microservice hosts; not seen on the line cards |
| CPU frequency / idle-state wake latency | `power_cpu_frequency`, `power_cpu_idle` | these events were not enabled on the partner captures |

### What the field does (the method behind the tools)

- **lttng-analyses** (the LTTng project's own analyses): scheduler latency = `sched_waking` ->
  `sched_switch` of the woken thread; IRQ and softirq durations from entry/exit plus softirq
  raise-to-entry latency; per-thread syscall durations; CPU top. `thread_top.py`,
  `runq_wait.py`, `irq_balance.py` and `syscall_stall.py` compute the same quantities from a
  slice, and add the per-CPU priority crowd, the occupants during a wait and the SMT-sibling check.
- **Trace Compass wait analysis** (Giraldeau & Dagenais, IEEE TPDS 2016; the "Critical Flow"
  view): for a blocked thread, find who woke it and what the waker was doing, recursively.
  `wait_chain.py` is that analysis one level deep - enough to print "thread A was released by
  thread B coming out of clone", which is the partner-case-2 finding.
- **bcc `runqlat` / off-CPU analysis** (Gregg): wakeup -> switch-in and preempt -> resume
  latency per thread; a per-thread histogram, because an aggregate hides one starved thread.
- **RSS / RPS / IRQ affinity** (kernel `networking/scaling.rst`): per-CPU `ksoftirqd/N` cannot
  be re-pinned; the lever is where the NIC queues' interrupts and RPS steer packets, and keeping
  latency-sensitive threads off that core and its SMT sibling.
- **`fork` and `mmap_lock`**: `dup_mmap` holds the parent's `mmap_lock` for the whole address
  space copy, so every sibling thread that touches memory blocks in D until it ends;
  `posix_spawn` / `vfork` (`CLONE_VM|CLONE_VFORK`, flags 0x4111) skips the copy.
- **CPU isolation on telecom boxes** (`isolcpus`, `nohz_full`, `irqaffinity`, `rcu_nocbs`,
  cpuset partitions; SUSE telco / kernel `cpu-isolation.rst`): the fixes these blueprints
  recommend are the standard ones - move the crowd, pin the IRQ, raise the thread.
