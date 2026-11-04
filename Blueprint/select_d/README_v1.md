# Blueprint selector D — one router for container hosts and bare-metal hosts

You decide **which specialist blueprint takes this trace**, or that nothing is wrong. You do not
solve the fault. Output exactly one `fault_type` from this list and nothing else:

| branch | labels |
|---|---|
| container host (microservices, cgroups) | `svc_cpu_cap`, `noisy_neighbor`, `slow_db`, `svc_net`, `svc_mem_cap`, `lock_contention`, `priority_inversion`, `fd_exhaustion` |
| bare-metal host (a line card, an embedded box) | `cpu_starvation`, `syscall_stall`, `irq_imbalance`, `priority_inversion`, `lock_contention` |
| either | `normal` |

The two kinds of host fail in different ways and are read with different tools, so **Step 0 picks
the branch first**. Everything after that is the branch's own ladder; do not mix them.

## Step 0 — which kind of host is this? (mechanical, one minute)

Your briefing may already carry a **HOST PROFILE** paragraph ("every event carries the same
pid_ns"). If it does, this is a **bare-metal host → Branch A**. If it does not, measure it:

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '1,/^data written per/p'
bash $TOOLS/extract_slice.sh $TRACE $DAY $MID_START 10 $WORK/probe.txt
grep -o 'pid_ns = [0-9]*' $WORK/probe.txt | sort | uniq -c | sort -rn | head
```
(`MID_START` = any time in the middle of the recording.)

- **Three or more distinct `pid_ns` values**, each with many events → containers → **Branch B**.
- **No `pid_ns` field at all, or one value everywhere** → bare metal → **Branch A**. Line-card
  traces often have no context block (a line is `sched_switch: { cpu_id = 2 }, { prev_comm = ...`)
  or a `{ vtid, vpid, procname }` block; neither has a namespace.

Write the branch down. A verdict from the wrong branch is wrong even when its label sounds right:
there are no cgroup quotas on a line card and no 80-thread crowds on one core in a container host.

---

## Branch A — bare-metal host: four screens on one slice, then a decision table

These faults are **steady**: they are there as long as the load is. Do not hunt for a window.
Cut **one slice over the whole recording** with every event the screens need, map the threads,
run the four screens, decide from their verdict lines.

### A1. Orient and slice

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt; cat $WORK/summary.txt
DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
SECS=$(awk '/^duration/ {print int($3)+2}' $WORK/summary.txt)
ALLEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_|irq_handler_|irq_softirq_'
bash $TOOLS/extract_slice.sh $TRACE $DAY $TRACE_START $SECS $WORK/all.txt "$ALLEV"
python3 $TOOLS/pidmap.py $TRACE --out $WORK/pidmap.tsv
PM="--pidmap $WORK/pidmap.tsv"          # leave empty if pidmap.py mapped nothing
grep -c irq_softirq_entry $WORK/all.txt   # 0 -> skip the interrupt screen, say so
grep -c syscall_entry_    $WORK/all.txt   # 0 -> skip the stall and lock screens, say so
```

Read the health lines (`lost events`, `time gaps`) and the snapshot note (`events cover only X s
of the Y s slice`): the tools divide by the real span; quote the shares, not the slice length.

### A2. Name the threads and the crowded cores

```bash
python3 $TOOLS/thread_top.py $WORK/all.txt $SECS --sort wait --top 30 $PM
python3 $TOOLS/thread_top.py $WORK/all.txt $SECS --sort max  --top 15 $PM
```

- Per-CPU table: write down each CPU's `busy%`, its `=120` count (the crowd at nice 0) and
  `kthr%` (tens of percent on one CPU = the interrupt screen will matter).
- Per-thread table: the **candidates** are **every row marked `*`** (3 or more waits of 10 ms, or
  one wait of 25 ms or more — the bars `runq_wait.py` uses; how much the row ran does not matter)
  plus the two rows with the most `wakeups` if they have any wait of 10 ms. Do not pick by `wait`
  share and do not stop at two. Measured: the comms thread of a line card ran 16% and waited 9%
  (7 waits >= 10 ms, longest 33 ms); it was the victim, and a selector that tested only the
  biggest waiter missed it.

```bash
CANDIDATES="<tid> <tid> ..."           # every '*' row on the crowded core(s) + top wakeups
WATCH=<busiest app threads, comma-separated>
```

### A3. The four screens, same slice

```bash
python3 $TOOLS/irq_balance.py  $WORK/all.txt $SECS --watch $WATCH          # skip if no irq events
python3 $TOOLS/syscall_stall.py $WORK/all.txt --min-ms 10 --top 20 $PM     # skip if no syscalls
python3 $TOOLS/futex_wait.py   $WORK/all.txt $SECS --top 10 $PM            # skip if no syscalls
for V in $CANDIDATES; do python3 $TOOLS/runq_wait.py $WORK/all.txt $V --top 12 $PM; done
```

Quote each verdict line word for word:
- interrupt: `VERDICT: RX CONCENTRATED ON CPU N: ...` (+ `APP THREADS ON THAT CPU/ITS SIBLING:`)
  or `VERDICT: IRQ/SOFTIRQ SPREAD EVENLY`. A `(but <kind> on cpu N is concentrated ...)` tail is
  a note, not a verdict.
- stall: `STALL: <thread> tid N spent X ms in <syscall> (...) ...; it froze K threads in D for up
  to X ms (...)` or `NO WORK-CLASS SYSCALL >= 10 ms (...)`. A `STALL:` with `no sibling or
  freeze effect measured` and under 50 ms is a finding, never the verdict.
- lock: `VERDICT: PRIORITY INVERSION: ...`, `VERDICT: LOCK CONTENTION on futex 0x..: ...`, or a
  negative (`NO LONG FUTEX WAITS`, `NO LOCK PROBLEM: ...`, `FUTEX WAITS WITHOUT A SCHEDULING CAUSE`).
- starvation, once per candidate: `VERDICT: STARVED BY CROWD: ...`, `VERDICT: STARVED BY HIGHER
  PRIORITY: ...`, `VERDICT: MIXED - ...`, `VERDICT: STARVATION PRESENT BUT MILD - ...`,
  `VERDICT: NOT STARVED - ...`; second line `OTHER CPUS WERE IDLE K% ...` or `HOST SATURATED`.
  MILD is a finding, not a fault, unless the operator named that thread.

When a stall names a victim, or a starvation verdict surprises you, one
`python3 $TOOLS/wait_chain.py $WORK/all.txt <victim> --top 12 $PM` connects the two findings.

### A4. Decide (walk from the top; the first row that matches leads)

| # | verdict line | `fault_type` | blueprint |
|---|---|---|---|
| 1 | `VERDICT: RX CONCENTRATED ON CPU N: ...` | `irq_imbalance` | `10_irq_imbalance` |
| 2 | `STALL: ... it froze K threads in D ...` whose frozen or starved dependants include a candidate (or the operator's thread) | `syscall_stall` | `9_syscall_stall` |
| 3 | `VERDICT: PRIORITY INVERSION: ...` | `priority_inversion` | `11_priority_inversion` |
| 4 | `VERDICT: LOCK CONTENTION on futex ...` | `lock_contention` | `11_priority_inversion` |
| 5 | `VERDICT: STARVED BY CROWD: ...` or `STARVED BY HIGHER PRIORITY: ...` for any candidate | `cpu_starvation` | `8_cpu_starvation` |
| 6 | `HOST SATURATED: all CPUs busy >= 90%` | `noisy_neighbor` (cpu_saturation) | `2_noisy_neighbor` |
| 7 | only negatives, MILD lines, notes, and stalls that froze nobody | `normal` | — |

Two rules between hits: **who is affected decides** — a `STALL:` outranks a `STARVED` verdict only
when its frozen or starved dependants include a candidate; otherwise the starvation leads and the
stall is a second finding. **Explain one hit by the other when linked** — a thread starved on the
RX CPU while `RX CONCENTRATED` fires is `irq_imbalance` with the starvation as its effect.

### The bar for answering `normal` on a bare-metal host (read before you conclude)

`normal` means *"all four screens ran on the whole-span slice and every one came back negative"*.
It does NOT mean *"the rate plots and the per-second CPU series looked steady"* — a thread starved
behind a crowd leaves every aggregate flat; only `runq_wait.py` on that thread sees it. Before you
may output `normal`, ALL of these must be true:
1. `irq_balance.py`, `syscall_stall.py` and `futex_wait.py` ran on `$WORK/all.txt` (or the slice
   lacked the events and you said which).
2. **`runq_wait.py` ran once for EVERY `*` row** of the `thread_top` tables (`--sort wait` and
   `--sort max`), and each came back `NOT STARVED` or `MILD`. A `--help` call is not a run.
3. You quoted the negative lines word for word.
Measured: a selector that ran `thread_top`, then spent its steps on generic rate and per-second
tools and never called `runq_wait` on the starred comms thread (26 waits >= 10 ms, longest
30 ms) called a starved line card `normal`. The four screens are the investigation; the generic
tools only orient. If you cannot satisfy (2), you do not have a `normal`: say which candidates
were not tested and answer from the screens that did run.

---

## Branch B — container host: rule out the mechanism, never default to "slow"

### The trap (read twice)

A fault on one request-path service makes that service **answer its callers slowly**, and the
callers pile up asleep on sockets. **A CPU cap, a lossy network, a slow database and a contended
lock ALL look the same at the aggregate level — a broad drop in activity.** Three errors to avoid:

1. Do NOT reason from aggregate activity or total-CPU direction; a falling aggregate says a
   request-path service stalled, not why.
2. **A CPU cap LOWERS total CPU and leaves the CPUs IDLE** — that is its signature, not evidence
   against it. "CPUs are idle, so it is not a CPU problem" is the single most common error.
3. A degraded network collapses throughput too; what separates it from a slow dependency is
   retransmission (Check 1), and what separates both from a lock is `futex_wait` (Check 2).

Run the checks **in order** and commit to the FIRST that clearly fires. `slow_db` is decided last
by a positive test, not by elimination; reaching Check 6 with 1–5 silent is the expected path for a
slow dependency, not a sign of health.

### B0. Setup

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/fault.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/base.txt
```
`WINDOW_START` = where the rate shifts and stays shifted; `BASE_START` = a quiet stretch outside
it. A flat rate plot does NOT license `normal` (a slow dependency barely moves the event rate):
run the checks on a mid-recording slice. **A short dip is a window to investigate, never a reason
to dismiss**: slice the deepest dip and run every check on it; repetition at a cadence is evidence.

### B0b. Check 0 — resource errors (fd_exhaustion). Cheap; run it first.

A service that ran out of file descriptors fails every `accept4`/`socket`/`openat` with EMFILE
(`ret = -24`) and usually crash-loops; nothing else in this ladder produces that return code.
```bash
FDEV='sched_process_exec|sched_process_exit|syscall_exit_(accept4|accept|socket|socketpair|openat|open|creat|dup|dup2|dup3|pipe2|pipe|epoll_create1|epoll_create|eventfd2|memfd_create|timerfd_create|signalfd4|inotify_init1|connect)'
EARLY=$(date -u -d "$DAY $WINDOW_START UTC - 30 seconds" '+%H:%M:%S')   # the burst comes BEFORE the collapse
bash $TOOLS/extract_slice.sh $TRACE $DAY $EARLY 90 $WORK/fd.txt "$FDEV"
python3 $TOOLS/fd_pressure.py $WORK/fd.txt 90
```
FIRES on `VERDICT: FD EXHAUSTION: <comm> (ns N, pid P): K EMFILE returns ...` **in any slice you
cut, including one you meant as baseline** → **`fd_exhaustion`**. Measured: 23 EMFILE by the
front-end in the 6 s after the limit was applied, the stack-wide activity drop began ~4 s later,
and a selector that sliced at the drop saw `NO FD PRESSURE` there, saw the verdict in its
"baseline" slice, and still answered normal with "host-wide outage of unknown cause". A burst of
EMFILE from one service followed by everything going quiet is that service dying, and that is the
cause. `NO FD PRESSURE` in a slice that starts 30 s before the change means move on. A `NOTE:
CONNECTS REFUSED` line with no EMFILE is a finding to carry forward, not a verdict.

### B1. Check 1 — svc_net (retransmissions)

```bash
NETEV='sched_switch|sched_waking|sched_wakeup|net_dev_queue|skb_kfree'
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/nf.txt "$NETEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/nb.txt "$NETEV"
python3 $TOOLS/net_loss.py $WORK/nf.txt 10
python3 $TOOLS/net_loss.py $WORK/nb.txt 10
```
FIRES if one container's flows show retransmissions clearly above the baseline slice. Loss cannot
happen without retransmission and a slow dependency produces zero → **`svc_net`**. Low
retransmission decides nothing yet (delay-only impairment is split in Check 6).

### B2. Check 2 — locks (priority_inversion / lock_contention)

A lock fault also makes a service answer slowly, but its threads sleep in `futex`, not on a
socket. Cut a syscall slice of the window and run the lock screen:
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/lf.txt 'sched_switch|sched_waking|sched_wakeup|syscall_'
python3 $TOOLS/futex_wait.py $WORK/lf.txt 10 --top 10
```
FIRES on `VERDICT: PRIORITY INVERSION: ...` → **`priority_inversion`**, or `VERDICT: LOCK
CONTENTION on futex 0x..: N held lock waits by K threads ...` → **`lock_contention`**. The
negatives (`NO LONG FUTEX WAITS`, `NO LOCK PROBLEM: ...` — an event wait, a runtime parking
futex, an idle worker) mean "not a lock"; move on. If the slice has no `syscall_` events the
screen cannot run; say so.

### B3. Check 3 — svc_mem_cap (reclaim)

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/mf.txt 'mm_vmscan|sched_process_exit'
grep -c -E "mm_vmscan|memcg|reclaim" $WORK/mf.txt
```
FIRES if memcg-reclaim events are present (and a process re-reads heavily / high `D`). No memory
events in the trace → this fault is not visible here, ABSENT. → **`svc_mem_cap`**.

### B4. Check 4 — svc_cpu_cap (one service pinned at a flat sub-core ceiling)

THE check naive selectors skip. A quota caps the victim's CPU at a flat, sub-core plateau:
```bash
python3 $TOOLS/cpu_hogs.py     $WORK/fault.txt 10         # per-container CPU; is the host mostly IDLE?
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10         # the victim also has high RUNNABLE wait
python3 $TOOLS/cpu_ceiling.py  $WORK/fault.txt <victim_name_or_pid> 100 $WORK/base.txt   # never a pid_ns id
```
FIRES on the CONJUNCTION: one service's per-period CPU is lower than its own baseline AND bounded
below a sub-core value, it carries runnable waits the baseline lacks, and the CPUs are idle while
it waits. Read the fraction off the tool; do not expect any particular value; a moderate, wobbly
ceiling still counts. → **`svc_cpu_cap`**. Do not stop at "total CPU fell".

### B5. Check 5 — noisy_neighbor (CPU stolen)

```bash
python3 $TOOLS/cpu_hogs.py $WORK/fault.txt 10      # who holds the CPU; compare to base.txt
```
FIRES if the top runnable-waiter waits while the CPUs are **BUSY** and a process/group absent in
baseline now holds a large share, arriving with the window. → **`noisy_neighbor`**.

### B6. Check 6 — the slow-answer split: svc_net (delay) vs slow_db. MANDATORY.

If Checks 1–5 did not fire you have ruled out five mechanisms and identified nothing. **Run
`sock_lag` now. You may not answer `normal`, and you may not answer at all, until it has run.**
```bash
python3 $TOOLS/sched_budget.py $WORK/fault.txt 10         # expect S-dominated, runnable wait low
python3 $TOOLS/sock_lag.py     $WORK/fault.txt 10 all     # per-fd request-to-answer gaps
python3 $TOOLS/sock_lag.py     $WORK/base.txt  10 all     # the same on the quiet slice
```
- gaps jumped ONLY on the connections to one dependency (a few fds to one peer), the service's
  other flows stay fast → **`slow_db`**.
- gaps jumped on ALL or most of the service's flows/peers at once → its own network path is
  impaired (delay without loss) → **`svc_net`**, marked inferred.
- gaps indistinguishable from baseline on every flow → only now is nothing wrong.

A modest, consistent rise on one peer's fds counts. If `sock_lag` cannot run, say so and pick the
better-supported of `slow_db` / `normal` from the `sched_budget` row (S-dominated with little CPU
leans `slow_db`). Never report `normal` while silently skipping this check.

### The rule that decides cpu_cap vs slow_db

Read the slow service's OWN `sched_budget` row: dominant **runnable** wait + idle CPUs → denied
CPU → `svc_cpu_cap`; dominant **S** on sockets, low runnable wait, little CPU → waiting on its own
downstream → `slow_db`. Rank candidates by the runnable `wait` column for Checks 4–5; the sleeping
cascade victims top the `S` column and are not the cause.

### The bar for answering `normal` on a container host

All three, or you do not have a `normal`: Checks 1–5 ran and were clearly absent; `sock_lag`
actually ran and the per-fd gaps match baseline; if the rate plot had any dip, the checks ran on
the deepest one. "I did not find anything" is a report of your effort, not a finding.

---

## Output

One `fault_type` from the table at the top, the branch you took and why (the `pid_ns` count), and
in the evidence the check or screen that fired with its number (retransmission rate, futex verdict,
reclaim count, ceiling vs baseline, idle%, runq_wait share and longest wait, sock_lag gap vs
baseline). On Branch A name the culprit and victim threads as the tools print them
(`comm tid N (prio P)`); the culprit is what holds the victim back (the crowd's top competitors or
"the N nice-0 threads on cpu X", the staller, `ksoftirqd/N`, the lock holder) and is **never the
victim itself** (measured: a verdict put the starved comms thread in both fields). State explicitly whether `sock_lag` ran (Branch B) or which screens were
skipped and why (Branch A). Do not output `other`.
