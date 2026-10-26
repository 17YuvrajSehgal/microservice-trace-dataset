# Blueprint: finding a slow database (or other slow dependency) from a kernel trace

|                                               |                                                                                                                                                               |
|-----------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Problem class                                 | Latency                                                                                                                                                       |
| Root cause this blueprint confirms or rejects | A dependency the service calls over a connection — a database, a cache, another service — answers slowly, and the service spends its time waiting for answers |
| Evidence                                      | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder                                                              |
| Also allowed                                  | The list of event types the trace holds (read from `metadata`), and the event rules you turned on when you recorded the trace, if you know them               |
| Not used                                      | Logs, request traces (spans), metrics, database settings                                                                                                      |

**How to use this blueprint.** Read Part 1 once, to learn what the fault is and what it looks like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

---

## Part 1. Background

### 1.1 What the fault is

A service asks a dependency for something over a network connection: it writes a request, then waits for the answer. When the answers come back slowly, every request the service handles stretches by that delay. Callers of the service stretch too, and the slowness spreads up the chain — load generator, gateway, front-end, service — while the real cause sits at the bottom.

The delay can live in two places, and they look different in the trace:

1. **In the dependency itself.** The database is overloaded, short of CPU, or stuck on its disk. Its own process shows the strain.
2. **In the path to it.** A proxy, the network, or an induced delay between the two. The dependency's process looks perfectly healthy — it answered quickly; the answer just arrived late.

### 1.2 What it looks like in a kernel trace

The victim does **not** wait for the CPU, and it does not wait for its own disk. It waits for an answer. That makes this fault quiet in all the places the CPU blueprints look:

- `sched_budget.py`'s wait table stays near zero for the victim.
- The trace often writes **less** data per second during the fault — the whole machine does less work because everything is waiting.

**And one trap makes it quiet even in the sleep table.** A threaded program (mysqld, java) blocks inside `read()` until the answer comes, so its sleep shows up there. But Go and Node use non-blocking sockets: `read()` returns instantly, the runtime parks in `epoll`, and reads only happen once the data has already arrived. Measured on a real victim: **every read took 0.0 ms while every request took 500 ms.** The wait is invisible in the calls themselves.

What is NOT quiet is the **request-to-answer gap**: on each connection, the time from writing a request to reading the answer. That is what `sock_lag.py` measures, and it works for both kinds of runtime. Measured on one solved case (Appendix B): the victim's database connection pool went from **0.9 ms to about 500 ms per answer**, while its CPU waits stayed at zero and the database process sat idle.

### 1.3 Problems that look similar

| Cause                            | What the kernel trace shows                                                                                                        | How it differs from a slow dependency                                                                      |
|----------------------------------|------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|
| **Slow dependency (this fault)** | The victim's request-to-answer gap jumps on the connections to ONE dependency; CPU waits stay low; answers still arrive, just late | —                                                                                                          |
| Dependency outage                | The same connections produce **no answers at all** (or only errors); requests hang to a timeout                                    | Slow = late answers; outage = no answers. Count the answers                                                |
| Lock waiting inside the victim   | The victim's threads sleep in `futex`, not on connections; its outgoing gaps stay fast                                             | The sleep is in locks (`sleep_where.py` shows it); no connection is slow                                   |
| CPU cap on the victim            | The victim **waits for the CPU** (long waits in `sched_budget.py`); the connection gaps grow only as a consequence                 | A dependency victim has near-zero CPU waits. If waits are high, use the CPU-cap blueprint                  |
| Noisy neighbor / busy host       | CPU waits across processes, busy CPUs                                                                                              | Same as above: the suffering is for the CPU, not for answers                                               |
| The victim's own slow disk       | The victim's `D` (disk sleep) goes up                                                                                              | A dependency victim's `D` stays near 0. (The DEPENDENCY's `D` going up is this fault — Step 6 checks that) |
| Host-wide network trouble        | Gaps jump on ALL connections of MANY processes, including unrelated ones                                                           | A slow dependency inflates one connection (or one pool) and the chain above it                             |
| The victim doing more work       | `run` goes up, throughput holds                                                                                                    | A dependency victim's `run` falls — it has nothing to do but wait                                          |

---

## Part 2. What you need

| Input                                                                                                          | Why                                                                                                      |
|----------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/`                      | Everything comes from here                                                                               |
| **System call events** (`syscall_entry_*` / `syscall_exit_*`) with their `fd` and `ret` fields, plus `sched_*` | The request-to-answer gap is read from write and read calls. Without syscalls this blueprint cannot work |
| A normal period to compare with: a normal stretch in the same trace, or a fault-free trace of the same system  | Gaps only mean something against their own baseline                                                      |
| `babeltrace2`, `python3`, GNU `date`                                                                           | To read the trace and run the scripts                                                                    |
| The thirteen scripts below, all in one folder                                                                  | To cut slices and measure                                                                                |

The scripts (the ten from the CPU blueprints, plus three new ones):

| Script             | What it does                                                                                                                                                       |
|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `idx_summary.py`   | Trace date, start, end, health checks, and data written over time                                                                                                  |
| `idx_dump.py`      | Every field of one index file                                                                                                                                      |
| `idx_slice.py`     | Copies the packets that cover a time window into a small trace                                                                                                     |
| `extract_slice.sh` | Cuts a slice with only scheduling events (for the CPU checks)                                                                                                      |
| `dep_slice.sh`     | **New.** Cuts a slice with scheduling events AND the blocking system calls (reads, writes, polls, futex). The slices for this blueprint come from here             |
| `sock_lag.py`      | **New. The decisive tool.** Request-to-answer gap per process and per connection. Finds the victim, the slow connection, and the size of the delay                 |
| `sleep_where.py`   | **New.** Where each process's sleep time goes: socket reads, event loop, locks, timers, disk. Separates dependency waiting from lock waiting for threaded programs |
| `sched_budget.py`  | Time budget per process: running, waiting, sleeping. Used here to rule the CPU out                                                                                 |
| `rhythm.py`        | CPU access pattern. Not needed here unless the CPU checks fire                                                                                                     |
| `cpu_ceiling.py`   | Per-period CPU ceiling. Same                                                                                                                                       |
| `cpu_hogs.py`      | Who held the CPU. Used on the dependency in Step 6                                                                                                                 |
| `victim_info.py`   | Who a process is: PID, threads, container. Works on the dependency too                                                                                             |
| `wake_graph.py`    | Who wakes whom — the hint for who talks to whom over a connection                                                                                                  |

---

## Part 3. Setup

```bash
TRACE=/path/to/trace       # the folder that holds `metadata`, `index/` and the channel files
TOOLS=/path/to/scripts     # the folder that holds the thirteen scripts
WORK=/path/to/scratch      # an empty folder for slices and notes

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,idx_dump.py,idx_slice.py,extract_slice.sh,dep_slice.sh,sock_lag.py,sleep_where.py,sched_budget.py,rhythm.py,cpu_ceiling.py,cpu_hogs.py,victim_info.py,wake_graph.py} > /dev/null && echo "all thirteen scripts found"
```

Both lines must print OK.

---

## Part 4. Procedure

### Step 1. Check the trace

Same health checks as the CPU-cap blueprint (lost events, gaps, file sizes), plus one check this blueprint cannot live without:

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt
DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
TRACE_END=$(awk '/^trace end/ {print substr($4,1,8)}' $WORK/summary.txt)

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -c '^syscall_entry_read$' $WORK/event_names.txt     # must be 1
grep -x -E 'sched_(switch|waking|wakeup)' $WORK/event_names.txt
```

- If `syscall_entry_read` is missing, **stop**. The trace has no system calls, and the request-to-answer gap cannot be measured. Report that this blueprint needs a trace recorded with syscall events.
- If the scheduling events are missing, **stop**, as in the other blueprints.

### Step 2. Find when something changed

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```

- With a slow dependency the rate usually **falls** during the fault — everything is waiting, so the machine does less — and recovers after.
- Write down the candidate window, as in the other blueprints. If there is no clear change, spread Step 3's slices across the whole trace.

```bash
WINDOW_START=<HH:MM:SS>
WINDOW_END=<HH:MM:SS>
```

### Step 3. Find the victim with the gap census

**Goal:** find who is waiting for answers. The CPU tools cannot see this victim; the census can.

Cut one baseline slice and one or two slices inside the window — **with `dep_slice.sh`**, not `extract_slice.sh` (the gap needs the syscalls):

```bash
bash $TOOLS/dep_slice.sh $TRACE $DAY $BASE_START  10 $WORK/base.txt
bash $TOOLS/dep_slice.sh $TRACE $DAY $FAULT_START 10 $WORK/fault.txt

python3 $TOOLS/sock_lag.py $WORK/base.txt  10 all
python3 $TOOLS/sock_lag.py $WORK/fault.txt 10 all
```

**First, the CPU gate — do this before reading any gaps.** Run `sched_budget.py` on the fault slice and look at the whole table, not just your suspects:

```bash
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10 | head -n 8
```

If ANY process shows long CPU waits (many at 50 ms or more) that the baseline slice does not have, the CPU is the story, not a dependency: everything that talks to a CPU-starved process gets slow answers from it, so the gap census below will light up all over and mislead you. Hand the case to the CPU-cap blueprint and **stop**.

Read the two tables **against each other**, never alone:

- The victim is a process whose gap p50 **jumps** between baseline and fault. Measured on the solved case: the service went from about 1 ms to 419 ms; the load generator from 50 to 591 ms; the gateway from 114 to 367 ms.
- Several processes jumping at once is normal — slowness spreads up the call chain. Note all of them; Step 6 finds the bottom of the chain.
- Ignore processes whose gaps are large in BOTH slices. Monitoring tools long-poll (gaps of seconds, baseline and fault alike); that is their normal shape, not suffering.
- The CPU gate above already cleared the machine of CPU starvation; if you skipped it, go back — gaps on a CPU-starved machine do not mean what this blueprint says they mean.

```bash
VICTIM=<pid>             # the deepest jumped process you can see so far
```

### Step 4. Decide whether there is a fault

1. **Did the gaps jump?** Clearly above their own baseline — not "large", LARGER.
2. **Does the jump line up with the window?** Inside the window, not outside it.
3. **Are answers still arriving?** The `answers` column stays well above zero.

Decide:

- **All three yes:** there is a slow dependency somewhere. Go to Step 5.
- **Gaps jumped but answers fell to (nearly) zero:** the dependency is not slow, it is GONE — calls hang or fail. That is an outage, not this blueprint. Report "dependency produces no answers" and **stop**.
- **No jump anywhere:** report "no slow-dependency signature found" and **stop**. Do not write "no fault" — this blueprint does not look for CPU, memory, or lock problems.

### Step 5. Pin the slow connection

**Goal:** which of the victim's connections carries the delay.

```bash
python3 $TOOLS/sock_lag.py $WORK/fault.txt 10 $VICTIM
python3 $TOOLS/sock_lag.py $WORK/base.txt  10 $VICTIM
```

Read it:

- **One fd, or a pool of fds with the same numbers, is slow — the rest stay fast.** That pool is the connection to the slow dependency. A service keeps several connections to its database; all of them jump together. Measured: six pool fds, every one at p50 503–543 ms against a 0.9 ms baseline.
- **Every fd is slow:** the path or the host is the problem, not one dependency. Check other processes' unrelated connections (Step 3's census); if they are slow too, report host-wide network trouble and **stop**.
- Write down the added delay: fault p50 minus baseline p50 on the slow pool.

```bash
POOL_FDS=<the slow fds>
DELAY_MS=<fault p50 - baseline p50>
```

### Step 6. Find the dependency, and check WHOSE fault the delay is

**Goal:** name the process on the other end, then decide: is the dependency itself struggling, or is the path to it slow?

**6a. Who is on the other end.**

```bash
python3 $TOOLS/wake_graph.py $WORK/fault.txt $VICTIM
```

When the answer arrives, the kernel often wakes the victim while running as the sender — so the top wakers hint at the peer. On one host the peer is a process you can name (a database, a proxy); across hosts the waker is the network interrupt (pid 0) and you only get the connection, not the name. Say which you have. And use the census (Step 3) as the second witness: the other half of the victim's conversation shows the SAME jump from the other side — in the solved case the database's own gap p50 read 500 ms exactly while the victim's pool read 503–543 ms. A process whose gaps mirror the victim's like that, on a machine where the wakers also point at it, IS the peer. Name it; do not report 'cannot map the connection' when both witnesses agree.

```bash
DEP=<pid of the dependency process, if it is on this host>
```

**6b. Is the dependency itself struggling?** Run the health checks ON the dependency:

```bash
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10 $DEP
python3 $TOOLS/sleep_where.py  $WORK/fault.txt 10 $DEP
```

- **The dependency is the problem** if its own row shows strain: long CPU waits (then its CPU is the cause — CPU-cap blueprint, on the dependency), or `D` climbing (its disk), or its threads piling up in `locks`.
- **The path is the problem** if the dependency looks healthy — low `run`, no waits, no `D`, threads parked in `event_loop` — while the victim still waits half a second per answer. The delay then lives between them: a proxy, the network, an induced latency. Measured on the solved case: the database sat at `run` 0.06 with zero CPU waits and zero disk sleep, 99.9 threads parked — healthy — while every answer took 500 ms. The cause was a proxy in the path.

### Step 7. Rule out the lookalikes

| Check                          | Where to look                               | A slow dependency looks like this                                                            |
|--------------------------------|---------------------------------------------|----------------------------------------------------------------------------------------------|
| Is it locks inside the victim? | `sleep_where.py` on the victim, fault slice | The victim's sleep is not piling up in `locks`; the gaps on real connections carry the delay |
| Is it the victim's CPU?        | `sched_budget.py`, victim's `wait`          | Near zero. High CPU waits → CPU-cap blueprint                                                |
| Is it the victim's disk?       | `sched_budget.py`, victim's `D`             | Near zero                                                                                    |
| Is it an outage?               | `answers` count in `sock_lag.py`            | Answers keep arriving, late                                                                  |
| Is it the whole network?       | Step 3 census: unrelated processes' gaps    | Unchanged against their own baseline                                                         |
| Did it start with the window?  | Gap p50 in a slice before the window        | Fast before, slow inside                                                                     |

One honest wrinkle: a request-to-answer gap also contains any pause the REQUESTER took between writing and reading. That is why the check is a JUMP against the same connection's own baseline, and why the pool pattern matters — a dozen connections do not all invent the same pause.

### Step 8. Estimate the added delay

- The added delay is `DELAY_MS` from Step 5: the slow pool's fault p50 minus its baseline p50. On the solved case this read about 500 ms against an injected 500 ms (±100 jitter).
- The p90 minus p50 spread hints at jitter on top of the base delay.
- Write both as **Inferred** — the trace shows the victim's experience of the delay, not the dependency's own clock.

### Step 9. Identify the victim and the dependency

```bash
python3 $TOOLS/victim_info.py $WORK/fault.txt 10 $VICTIM
python3 $TOOLS/victim_info.py $WORK/fault.txt 10 $DEP
```

Name both as precisely as the trace allows: process name and PID always; the container (`pid_ns`) if recorded; who talks to whom from `wake_graph.py`. A namespace number of 0 means "could not be read", never a real namespace. The kernel trace never holds a service name — say what you saw.

### Step 10. Write the RCA statement

Template:

> From **[start]** to **[end]** (UTC), **[victim]** was slow because its dependency **[dependency, as named in Step 9]** answered in about **[DELAY_MS]** instead of **[baseline]**. The dependency's own process was **[healthy / struggling: say which and how]**, so the delay lives **[in the dependency / in the path to it]**. We know because of **[evidence 1: the gap jump on the pool]**, **[evidence 2: the dependency's health checks]**, and **[evidence 3: the chain above inflating with it]**. We ruled out **[locks, CPU, disk, outage, host network]** because **[reasons]**. We did not check **[what was not tested]**.

Rules:

- Name the victim, the dependency, the connections, the window, and the added delay.
- **Commit to the verdict the evidence earned.** If Steps 4–6 held (the gap jump on a pool, answers flowing, the chain inflating), this IS a slow dependency: use the `db_latency` label when the dependency is a datastore, and name the dependency (or "the path to <dependency>") as the root cause. "Other/unknown" is for evidence that did NOT hold, not for a complete case missing one nicety.
- Give at least two independent pieces of evidence. For this fault: the per-connection gap jump (Step 5), the dependency's health (Step 6b), and the chain inflation (Step 3).
- Mark each claim **Measured** or **Inferred**. The added delay and the "path vs dependency" call are **Inferred**.
- Say what you did not test.

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects one cause: a slow answer from a dependency reached over connections. If a step points elsewhere (CPU, locks, disk, outage), it stops and tells you so.
- **It needs system call events.** A trace recorded without them cannot show the request-to-answer gap, and Step 1 stops.
- A gap includes any pause the requester took between writing and reading. The defences are the baseline comparison and the pool pattern; a single slow fd with few answers is weak evidence.
- It can say the dependency's process was healthy or struggling. It CANNOT see inside the path — a proxy, the network and the dependency's own dispatch all look the same from the victim's socket. "In the path" is as precise as kernel-only evidence gets.
- Across hosts, the dependency's process is not in this trace at all; then only the victim's side and the connection can be named.
- Monitoring tools long-poll and always show gaps of seconds; only a change against their own baseline means anything.
- The worked numbers (0.9 ms to 500 ms, pool of six, database at `run` 0.06) come from ONE solved case. Use them for a feel of the sizes, not as thresholds.

---

## Part 6. References

The method, finding waits in kernel traces:

1. F. Giraldeau and M. Dagenais, *Wait analysis of distributed systems using kernel tracing*, IEEE TPDS 27(8), 2016. https://publications.polymtl.ca/3078/
2. B. Gregg, *Off-CPU Analysis*. https://brendangregg.com/offcpuanalysis.html
3. B. Gregg, *System Performance Analysis Methodologies*, EuroBSDcon 2017. https://www.brendangregg.com/Slides/EuroBSDcon2017_SystemMethodology.pdf

Why asynchronous runtimes hide their waiting (the Step-1.2 trap):

4. Linux man pages, `epoll(7)` — event notification for non-blocking I/O. https://man7.org/linux/man-pages/man7/epoll.7.html

The tools and the trace format:

5. LTTng documentation (system call tracing). https://lttng.org/docs/
6. Babeltrace 2, `source.ctf.fs` component. https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What the index files hold

The same as the CPU-cap blueprint's Appendix A: `index/*.idx` is a table of contents per CPU — where each packet sits and what time it covers. `idx_summary.py` reads only this, which is why Steps 1–2 take seconds. Decoding the events needs `babeltrace2`.

## Appendix B. One solved case

A multi-CPU host running a web application; one of its services talks to a SQL database. A delay of several hundred milliseconds (with jitter) was injected into the path between them for two minutes. Use the numbers for a feel of the sizes, not as thresholds.

- **Step 2:** the data rate fell during the fault window and recovered after.
- **Step 3 (census):** against baseline, the victim service's gap p50 went **0.9 ms → 419 ms**; the load generator **50 → 591 ms**; the gateway **114 → 367 ms**. The monitoring exporters sat at ~5 s gaps in BOTH slices — normal long-polling, ignored. `sched_budget.py` showed near-zero CPU waits for all of them.
- **Step 5:** the victim's connection pool — six fds — read p50 **503–543 ms, p90 580–620 ms** in the fault slice, against sub-millisecond baselines. Its other fds stayed fast. Added delay ≈ 500 ms.
- **The async trap, live:** every individual `read()` of the victim (a non-blocking runtime) completed in 0.0 ms in BOTH slices. Blocking-call duration showed nothing; only the request-to-answer gap carried the fault.
- **Step 6:** the database process was healthy: `run` 0.06 cores, zero long CPU waits, `D` 0.00, **99.9 threads parked in the event loop**. Healthy dependency + half-second answers = the delay lived in the path. (Ground truth: a proxy between them was injecting the latency.)
- **Step 8:** added delay ≈ 500 ms, jitter ≈ ±100 ms (p90 − p50). Both matched the injection.
