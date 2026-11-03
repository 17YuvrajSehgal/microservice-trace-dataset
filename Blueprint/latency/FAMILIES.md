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
| Lock held by a thread that cannot run | `priority_inversion` (11) | few LONG futex waits ending with a wake (ret 0); the releaser was runnable-but-not-running, its CPU taken by middle-priority threads | our `priority_inversion_*` runs (nice-based, 50 ms hold) |
| Many threads on one lock | `lock_contention` (11, same tools) | MANY SHORT woken futex waits on one address; holders run while holding | our `lock_contention_*` runs |

### Not built yet (needs a labelled trace first)

| Cause | Signal to look for | Why it waits |
|---|---|---|
| Kernel hot path that scales with a table (partner case 4: a label-space scan on every link event) | a syscall (`sendmsg`) that is 10-30 ms on-CPU inside the kernel | needs ftrace `function_graph` / kprobe durations; a count index cannot see inside a syscall |
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
