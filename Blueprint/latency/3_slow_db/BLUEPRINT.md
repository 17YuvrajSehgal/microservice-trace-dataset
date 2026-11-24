<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a slow database, or other slow dependency (db_latency)

| | |
|---|---|
| Problem class | Latency |
| Root cause this blueprint confirms or rejects | A dependency the service calls over a connection (a database, a cache, another service) answers slowly, and the service spends its time waiting for answers |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder. It needs system call events (`syscall_entry_*` / `syscall_exit_*`) with their `fd` and `ret` fields, plus `sched_*` |
| Not used | Logs, request traces (spans), metrics, database settings |

**When to use this.** A service is slow and its callers are slow too: the slowness spreads up the chain (load generator, gateway, front-end, service). The victim does not wait for the CPU, and it does not wait for its own disk. `sched_budget.py`'s wait table stays near zero for it. The trace often writes less data per second during the fault.

**Status.** The worked numbers come from ONE solved case (Appendix B of `README_v1.md`): a multi-CPU host running a web application, where a delay of several hundred milliseconds (with jitter) was injected for two minutes into the path between one service and its SQL database. There is no sweep on all labelled runs and no `RESULTS.md`, so this blueprint has no found and no false-alarm counts. Its tools print tables and no `VERDICT:` line. Agent (23-11-2026, graph harness, gpt-6-luna): one labelled `slow_db` run. The agent found the right window, the 500 ms gaps, the proxy and the database, but the verdict is inconclusive: two steps had no outcome that fits a Go victim (it sleeps in locks, and its connections change between slices).

## Part 1. Background

A service asks a dependency for something over a network connection: it writes a
request, then waits for the answer. When the answers come back slowly, every request the
service handles stretches by that delay. Callers of the service stretch too, and the
slowness spreads up the chain (load generator, gateway, front-end, service) while the
real cause sits at the bottom.

The delay can live in two places, and they look different in the trace:

1. **In the dependency itself.** The database is overloaded, short of CPU, or stuck on
   its disk. Its own process shows the strain.
2. **In the path to it.** A proxy, the network, or an induced delay between the two. The
   dependency's process looks perfectly healthy: it answered quickly; the answer just
   arrived late.

The victim does **not** wait for the CPU, and it does not wait for its own disk. It
waits for an answer. `sched_budget.py`'s wait table stays near zero for the victim. The
trace often writes **less** data per second during the fault, because everything is
waiting.

One trap makes it quiet even in the sleep table. A threaded program (mysqld, java)
blocks inside `read()` until the answer comes, so its sleep shows up there. But Go and
Node use non-blocking sockets: `read()` returns instantly, the runtime parks in `epoll`,
and reads only happen once the data has already arrived. Measured on a real victim:
**every read took 0.0 ms while every request took 500 ms.**

What is NOT quiet is the **request-to-answer gap**: on each connection, the time from
writing a request to reading the answer. `sock_lag.py` measures it, and it works for
both kinds of runtime. Measured on one solved case: the victim's database connection
pool went from **0.9 ms to about 500 ms per answer**, while its CPU waits stayed at zero
and the database process sat idle.

Problems that look similar:

- Dependency outage: the same connections produce **no answers at all** (or only errors); requests hang to a timeout. Slow = late answers; outage = no answers. Count the answers.
- Lock waiting inside the victim: the victim's threads sleep in `futex`, not on connections; its outgoing gaps stay fast. `sleep_where.py` shows it; no connection is slow.
- CPU cap on the victim: the victim **waits for the CPU** (long waits in `sched_budget.py`); the connection gaps grow only as a consequence. A dependency victim has near-zero CPU waits. If waits are high, use the CPU-cap blueprint.
- Noisy neighbor / busy host: CPU waits across processes, busy CPUs. The suffering is for the CPU, not for answers.
- The victim's own slow disk: the victim's `D` (disk sleep) goes up. A dependency victim's `D` stays near 0. The DEPENDENCY's `D` going up is this fault.
- Host-wide network trouble: gaps jump on ALL connections of MANY processes, including unrelated ones. A slow dependency inflates one connection (or one pool) and the chain above it.
- The victim doing more work: `run` goes up, throughput holds. A dependency victim's `run` falls: it has nothing to do but wait.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, health checks, and data written over time | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `dep_slice.sh` | Cuts a slice with scheduling events AND the blocking system calls (reads, writes, polls, futex). The slices for this blueprint come from here | `dep_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file>` |
| `sock_lag.py` | The decisive tool. Request-to-answer gap per process and per connection. Finds the victim, the slow connection, and the size of the delay | `sock_lag.py <slice.txt> <slice_seconds> <pid|all> [top]` |
| `sleep_where.py` | Where each process's sleep time goes: socket reads, event loop, locks, timers, disk. Separates dependency waiting from lock waiting for threaded programs | `sleep_where.py <slice.txt> <slice_seconds> [pid]` |
| `sched_budget.py` | Time budget per process: running, waiting, sleeping. Used here to rule the CPU out | `sched_budget.py <sched_events.txt> <slice_seconds> [pid_to_always_show]` |
| `victim_info.py` | Who a process is: PID, threads, container. Works on the dependency too | `victim_info.py <sched_events.txt> <slice_seconds> <pid> [rows]` |
| `wake_graph.py` | Who wakes whom: the hint for who talks to whom over a connection | `wake_graph.py <sched_events.txt> <pid> [rows]` |

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find when something changed, pin both edges of the window, and choose a baseline time and a fault time. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. With a slow dependency the rate
usually **falls** during the fault (everything is waiting, so the machine does less)
and recovers after.
The injection is a minutes-long window inside a longer recording: pin BOTH edges.
Find the start and the recovery, so you know the elevated stretch and the quiet
stretch. A short burst fault (about 2 min) is easy to mislocate: the trace may open a
few seconds into the fault, so the very first slice is NOT a baseline. Take the
baseline from a stretch that is clearly **outside** the window: the opposite end of
the recording from the change, or well before or after it, never within a few
seconds of the edge. fault_start is a time inside the window.
If there is no clear change, spread the slices of the next step across the whole
trace.

Write down: `window_start` (the change begins (trace_start if no clear change), HH:MM:SS only (no date)), `window_end` (the rate recovers (trace_end if no clear change), HH:MM:SS only (no date)), `base_start` (start of a 10 s slice in a quiet stretch OUTSIDE the window, far from both edges, HH:MM:SS only (no date)), `fault_start` (start of a 10 s slice inside the window, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `window_found` | the rate changed for a stretch of time, and both edges are written down |  | go to `census` |
| `no_clear_change` | no clear change. Set window_start = trace_start and window_end = trace_end, and spread the slices of the next step across the whole trace |  | go to `census` |

### Step 3. Find who is waiting for answers (the gap census), and decide whether there is a slow dependency. The CPU tools cannot see this victim; the census can. (`census`)

```
dep_slice.sh $TRACE <day> <base_start> 10 $WORK/base.txt
dep_slice.sh $TRACE <day> <fault_start> 10 $WORK/fault.txt
sched_budget.py $WORK/fault.txt 10
sched_budget.py $WORK/base.txt 10
sock_lag.py $WORK/base.txt 10 all
sock_lag.py $WORK/fault.txt 10 all
```

Cut one baseline slice and one or two slices inside the window with dep_slice.sh,
not extract_slice.sh: the gap needs the syscalls. If sock_lag.py prints `no
request-to-answer pairs found` on these slices, the gap cannot be measured.
First, the CPU gate. Do this before reading any gaps. Look at the whole
sched_budget.py table of the fault slice, not just your suspects. If ANY process
shows long CPU waits (many at 50 ms or more) that the baseline slice does not have,
the CPU is the story, not a dependency: everything that talks to a CPU-starved
process gets slow answers from it, so the gap census lights up all over and misleads
you.
Verify the baseline is actually quiet BEFORE comparing. If base.txt shows the same
elevated gaps as fault.txt (for example both the database peer and the service pool
already sit at hundreds of ms), your baseline is inside the incident. Do not
conclude "no jump, so normal" from it: re-cut the baseline from a stretch that is
demonstrably quiet (gaps back near their sub-millisecond floor), trying the far ends
of the recording. A real slow-DB fault compared against a true baseline shows the
pool gap jump from about 1 ms to hundreds of ms.
Read the two sock_lag.py tables against each other, never alone:
- The victim is a process whose gap p50 **jumps** between baseline and fault.
  Measured on the solved case: the service went from about 1 ms to 419 ms; the load
  generator from 50 to 591 ms; the gateway from 114 to 367 ms.
- Several processes jumping at once is normal: slowness spreads up the call chain.
  Note all of them. victim_pid is the deepest jumped process you can see so far.
- Ignore processes whose gaps are large in BOTH slices. Monitoring tools long-poll
  (gaps of seconds, baseline and fault alike); that is their normal shape.
Then answer three questions. Did the gaps jump (clearly above their own baseline:
not "large", LARGER)? Does the jump line up with the window (inside it, not outside
it)? Are answers still arriving (the `answers` column stays well above zero)?

Write down: `victim_pid` (pid of the deepest process whose gap p50 jumped).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `gaps_jumped` | all three answers are yes. There is a slow dependency somewhere |  | go to `pin_connection` |
| `cpu_starved` | a process shows long CPU waits (many at 50 ms or more) in the fault slice that the baseline slice does not have |  | **Stop.** The CPU is the story, not a dependency. Everything that talks to a CPU-starved process gets slow answers from it. Hand the case to blueprint `1_svc_cpu_cap`. Root cause **rejected**. |
| `no_answers` | the gaps jumped but answers fell to (nearly) zero |  | **Stop.** The dependency is not slow, it is GONE. Calls hang or fail. That is an outage, not this blueprint. Report "dependency produces no answers". Hand the case to blueprint `15_dependency_outage`. Root cause **rejected**. |
| `no_jump` | no jump anywhere, against a baseline that is demonstrably quiet |  | **Stop.** Report "no slow-dependency signature found". Do not write "no fault". This blueprint does not look for CPU, memory, or lock problems. Root cause **rejected**. |
| `no_quiet_baseline` | the baseline shows the same elevated gaps as the fault slice, and no quiet stretch can be found at all, also at the far ends of the recording |  | **Stop.** The whole recording is affected. Say so rather than calling it normal. The gap census only means something against a fault-free baseline. Root cause **inconclusive**. |
| `no_syscalls` | sock_lag.py finds no request-to-answer pairs on slices cut with dep_slice.sh. The trace has no system calls | `no request-to-answer pairs found ...` | **Stop.** The request-to-answer gap cannot be measured. Report that this blueprint needs a trace recorded with syscall events. Root cause **inconclusive**. |

### Step 4. Find which of the victim's connections carries the delay, and estimate the added delay. (`pin_connection`)

```
sock_lag.py $WORK/fault.txt 10 <victim_pid>
sock_lag.py $WORK/base.txt 10 <victim_pid>
```

sock_lag.py with a pid prints one row per connection (fd): answers, p50, p90, max.
One fd, or a pool of fds with the same numbers, is slow and the rest stay fast: that
pool is the connection to the slow dependency. A service keeps several connections
to its database; all of them jump together. Measured: six pool fds, every one at p50
503-543 ms against a 0.9 ms baseline.
Every fd is slow: the path or the host is the problem, not one dependency. Check
other processes' unrelated connections in the census of the step before.
The added delay is the fault p50 minus the baseline p50 on the slow pool. On the
solved case this read about 500 ms against an injected 500 ms. The p90 minus p50
spread hints at jitter on top of the base delay. Both are Inferred: the trace shows
the victim's experience of the delay, not the dependency's own clock.
A single slow fd with few answers is weak evidence.

Write down: `pool_fds` (the slow fds of the victim (one fd, or a pool of fds with the same numbers)), `delay_ms` (the added delay, fault p50 minus baseline p50 on the slow pool. Always an estimate (Inferred)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `pool_slow` | one fd, or a pool of fds with the same numbers, is slow against its own baseline, and the victim's other fds stay fast |  | go to `dependency` |
| `host_network` | every fd of the victim is slow, and other processes' unrelated connections are slow too |  | **Stop.** Host-wide network trouble, not one slow dependency. Root cause **rejected**. |

### Step 5. Name the process on the other end, then decide whether the dependency itself is struggling or the path to it is slow. (`dependency`)

```
wake_graph.py $WORK/fault.txt <victim_pid>
sched_budget.py $WORK/fault.txt 10 <dep_pid>
sleep_where.py $WORK/fault.txt 10 <dep_pid>
```

Who is on the other end. When the answer arrives, the kernel often wakes the victim
while running as the sender, so the top wakers in wake_graph.py hint at the peer. On
one host the peer is a process you can name (a database, a proxy). Across hosts the
waker is the network interrupt (pid 0) and you only get the connection, not the
name. Say which you have.
Use the census as the second witness: the other half of the victim's conversation
shows the SAME jump from the other side. In the solved case the database's own gap
p50 read 500 ms exactly while the victim's pool read 503-543 ms. A process whose
gaps mirror the victim's like that, on a machine where the wakers also point at it,
IS the peer. Name it; do not report "cannot map the connection" when both witnesses
agree.
Then run the health checks ON the dependency. sched_budget.py: its `run`, its CPU
waits and its `D`. sleep_where.py: average sleeping threads split by where they
slept (`sock_read`, `event_loop`, `locks`, `D`). `event_loop` is a server parked
waiting for any work; it is normal.
Measured on the solved case: the database sat at `run` 0.06 with zero CPU waits and
zero disk sleep, 99.9 threads parked, while every answer took 500 ms. The cause was
a proxy in the path.
The trace cannot see inside the path: a proxy, the network and the dependency's own
dispatch all look the same from the victim's socket. "In the path" is as precise as
kernel-only evidence gets.

Write down: `dep_pid` (pid of the dependency process, if it is on this host; `not on this host` if the waker is pid 0), `delay_place` (in the dependency (say how it struggles) or in the path to it. Inferred).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `path_slow` | the dependency looks healthy (low `run`, no waits, no `D`, threads parked in `event_loop`) while the victim still waits for each answer. The delay lives between them (a proxy, the network, an induced latency) |  | go to `rule_out` |
| `dependency_struggles` | the dependency's own row shows strain. Long CPU waits (then its CPU is the cause; the CPU-cap blueprint applies to the dependency), or `D` climbing (its disk), or its threads piling up in `locks`. Say which |  | go to `rule_out` |
| `peer_not_on_host` | the top waker is the network interrupt (pid 0) and no process mirrors the victim's gaps. Only the victim's side and the connection can be named, and the health checks cannot run. Set dep_pid to `not on this host` |  | go to `rule_out` |

### Step 6. Rule out the lookalikes on the victim. (`rule_out`)

```
sleep_where.py $WORK/fault.txt 10 <victim_pid>
sched_budget.py $WORK/fault.txt 10 <victim_pid>
sock_lag.py $WORK/base.txt 10 <victim_pid>
```

A slow dependency looks like this:
- Locks inside the victim (sleep_where.py on the victim, fault slice): the victim's
  sleep is not piling up in `locks`; the gaps on real connections carry the delay.
- The victim's CPU (sched_budget.py, the victim's `wait`): near zero.
- The victim's disk (sched_budget.py, the victim's `D`): near zero.
- An outage (`answers` count in sock_lag.py): answers keep arriving, late.
- The whole network (the census: unrelated processes' gaps): unchanged against
  their own baseline.
- Did it start with the window (gap p50 in a slice before the window): fast before,
  slow inside.
A Go or Node victim parks in `epoll`, so its sleep can sit in `event_loop` and not
in `sock_read`. That is the trap of the background, not a sign against this fault.
One honest wrinkle: a request-to-answer gap also contains any pause the REQUESTER
took between writing and reading. That is why the check is a JUMP against the same
connection's own baseline, and why the pool pattern matters: a dozen connections do
not all invent the same pause.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `slow_dependency` | all six checks look like a slow dependency. The gap jump on a pool, answers flowing and the chain inflating all held |  | go to `identify` Root cause **confirmed**. |
| `check_does_not_fit` | one of the checks does not look like a slow dependency (the victim's sleep piles up in `locks`, or its `D` is up, or unrelated processes' gaps changed too, or the gaps were already slow before the window). Say which one |  | go to `identify` Root cause **unconfirmed**. |
| `victim_cpu` | the victim's `wait` for the CPU is high. The connection gaps grow only as a consequence |  | **Stop.** The victim waits for the CPU, not for answers. Use the CPU-cap blueprint. Hand the case to blueprint `1_svc_cpu_cap`. Root cause **rejected**. |

### Step 7. Name the victim and the dependency as precisely as the trace allows. (`identify`)

```
victim_info.py $WORK/fault.txt 10 <victim_pid>
victim_info.py $WORK/fault.txt 10 <dep_pid>
```

Name both: process name and PID always; the container (`pid_ns`) if recorded; who
talks to whom from wake_graph.py. A namespace number of 0 means "could not be read",
never a real namespace. The kernel trace never holds a service name: say what you
saw. If the dependency is not on this host, name the victim's side and the
connection only.

Write down: `victim_name` (program name of the victim, and its `pid_ns` if recorded), `dep_name` (program name of the dependency, and its `pid_ns` if recorded).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `identified` | the victim is named, and the dependency as far as the trace allows |  | go to `report` |

### Report

From [start] to [end] (UTC), [victim] was slow because its dependency [dependency] answered
in about [delay_ms] instead of [baseline]. The dependency's own process was [healthy /
struggling: say which and how], so the delay lives [in the dependency / in the path to
it]. We know because of [evidence 1: the gap jump on the pool], [evidence 2: the
dependency's health checks], and [evidence 3: the chain above inflating with it]. We
ruled out [locks, CPU, disk, outage, host network] because [reasons]. We did not check
[what was not tested].
Name the victim, the dependency, the connections, the window, and the added delay.
Commit to the verdict the evidence earned. If the gap jump on a pool, answers flowing
and the chain inflating held, this IS a slow dependency: use the `db_latency` label when
the dependency is a datastore, and name the dependency (or "the path to <dependency>")
as the root cause. "Other/unknown" is for evidence that did NOT hold, not for a complete
case missing one nicety.
Give at least two independent pieces of evidence. Mark each claim Measured or Inferred.
The added delay and the "path vs dependency" call are Inferred. Say what you did not
test.

## Part 4. Measured, and limits

- It confirms or rejects one cause: a slow answer from a dependency reached over connections. If a step points elsewhere (CPU, locks, disk, outage), it stops and tells you so.
- **It needs system call events.** A trace recorded without them cannot show the request-to-answer gap, and Step 1 stops.
- A gap includes any pause the requester took between writing and reading. The defences are the baseline comparison and the pool pattern; a single slow fd with few answers is weak evidence.
- It can say the dependency's process was healthy or struggling. It CANNOT see inside the path — a proxy, the network and the dependency's own dispatch all look the same from the victim's socket. "In the path" is as precise as kernel-only evidence gets.
- Across hosts, the dependency's process is not in this trace at all; then only the victim's side and the connection can be named.
- Monitoring tools long-poll and always show gaps of seconds; only a change against their own baseline means anything.
- The worked numbers (0.9 ms to 500 ms, pool of six, database at `run` 0.06) come from ONE solved case. Use them for a feel of the sizes, not as thresholds.
