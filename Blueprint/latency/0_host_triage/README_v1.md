# Blueprint: triage of a bare-metal host from one kernel trace (which scheduling fault, if any)

| | |
|---|---|
| Problem class | Triage for a bare-metal host (a switch or router line card, an embedded box): one pid namespace, no containers, no cgroup limits |
| What this blueprint decides | Which of the scheduling-family faults the trace shows — a thread starved of CPU, a thread frozen by a sibling's system call, interrupt work piled on one CPU, a lock held by a thread that cannot run — or that none of them shows and the box looks normal. It names the threads either way, and names the deep-dive blueprint that confirms the finding |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder |
| Also allowed | The names of the threads the operator cares about (passed to `--watch`); the box's SMT pairs if known |
| Not used | Logs, metrics, application counters (packet drops, late replies), request traces |

**How to use this blueprint.** Read Part 1 once. Then do the steps in Part 4 in order: one slice, one screen per family, then the decision table in Appendix A. Quote the tools' verdict lines word for word; the decision is made from them, not from impressions.

**When to use this.** The trace comes from a host with **one `pid_ns` everywhere (or none)**, or you do not know which family to try. On a microservice host with containers, use blueprints 1–5 instead. If an operator already told you the family, go straight to that blueprint (8, 9, 10 or 11).

> **Honest status.** This screen was run on five line-card traces from an industry partner (traces and their own RCA stay under NDA): three real faults, which it routes to blueprints 8, 9 and 10 with the right thread names; one healthy baseline capture, which it calls normal; and one card where the suspected starvation is correctly rejected because the thread had already been given a high priority. The lock branch (blueprint 11) is being validated on our own labelled runs. The precedence rules in Step 5 are a first pass from those traces.

---

## Part 1. Background

A microservice host has a cgroup and a container to blame. A line card has neither: **the thread is the unit of blame**, and the question is which core, which priority, which kernel path. Four scheduling faults cover what the partner traces showed, plus one network fault:

- **`cpu_starvation` (blueprint 8).** One latency-sensitive thread is ready to run but keeps waiting, because many threads of the same or higher priority share its core. Other cores sit idle. Fix: raise its priority or move the crowd.
- **`syscall_stall` (blueprint 9).** One thread sits inside one system call (`clone`/`fork`, `ioctl`, `mmap`, `write`) for tens of ms, on-CPU or in D state, and the threads that depend on it freeze in D meanwhile. Fix: a cheaper call (`posix_spawn`), or move the call out of the latency-critical process.
- **`irq_imbalance` (blueprint 10).** Network receive softirqs (`NET_RX`) all land on one CPU; `ksoftirqd/N` eats that core, and the application threads placed on it or on its SMT sibling get slow. Fix: spread RX (RSS / IRQ affinity / RPS) and pin the threads elsewhere.
- **`priority_inversion` / `lock_contention` (blueprint 11).** A thread waits on a lock held by a thread that cannot run (its CPU is taken by middle-priority threads), or many threads queue on one lock. Fix: priority inheritance, or a shorter critical section.
- **`packet_drop` (blueprint 7).** The kernel itself drops packets (`skb_kfree` with a reason). Not part of this screen: on these boxes the drop counter usually lives in the application, and the kernel trace holds the scheduling cause, not the drop.

**Priorities in the trace.** LTTng prints `prio` as the kernel priority minus 100: `20` = nice 0 (kernel 120), `10` = nice −10, a negative number = a real-time thread. The tools print `120 (nice 0)`, `110 (nice -10)`, `RT 63`.

**Two things that are not faults.** A thread sleeping inside `ioctl`, `poll` or `futex` with a timeout is waiting for an event, not stalled; the tools leave those out and say so. A wait of seconds that overlaps a stretch where its CPU shows no event at all is lost trace data (snapshot buffers), not latency; the tools drop those and print a `trace holes:` line.

---

## Part 2. What you need

| Input | Why |
|---|---|
| The trace folder: `metadata`, the channel data files, `index/` | Everything comes from here |
| `sched_switch` + `sched_waking`/`sched_wakeup` | The scheduling screen (every family needs these) |
| `irq_softirq_entry/exit/raise`, `irq_handler_entry/exit` | The interrupt screen. Without them that screen is skipped |
| `syscall_entry_*` / `syscall_exit_*` (also `compat_syscall_*`) | The stall and lock screens. Without them those screens are skipped |
| `sched_process_fork`, `lttng_statedump_process_state` | To group threads into processes (siblings). Optional |
| `babeltrace2`, `python3`, GNU `date` | To read the trace and run the scripts |
| The scripts below, all in one folder | `tracelib.py` must sit next to the others: they import it |

The scripts:

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, start, end, length, CPUs, health checks; reads only the index | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time slice and keeps only the events you name | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> '<events regex>'` |
| `pidmap.py` | Thread → process map from the state dump | `pidmap.py <trace_dir> [--out FILE]` |
| `thread_top.py` | Every thread's run / runnable-wait / sleep with its priority and CPUs, and a per-CPU crowd table | `thread_top.py <slice> <secs> [--sort wait\|run\|max\|wakeups] [--top N] [--cpu N] [--pidmap FILE]` |
| `runq_wait.py` | One thread's runnable waits, who held its core, the verdict (starvation screen) | `runq_wait.py <slice> <victim tid\|name> [--top N] [--min-ms X] [--pidmap FILE]` |
| `syscall_stall.py` | Long system calls that burn CPU or sit in D, and the threads they froze (stall screen) | `syscall_stall.py <slice> [--min-ms 10] [--top 20] [--only name,name] [--pidmap FILE]` |
| `wait_chain.py` | One thread's blocked time: who woke it and what the waker was doing | `wait_chain.py <slice> <victim tid\|name> [--top N] [--pidmap FILE]` |
| `irq_balance.py` | Hardirq and softirq time per CPU, concentration, `ksoftirqd/N`, the threads on the hot CPU (interrupt screen) | `irq_balance.py <slice> <secs> [--baseline <slice2> <secs2>] [--siblings "0,1 2,3"] [--watch name,name] [--top N]` |
| `futex_wait.py` | Lock waits per futex, who released them and what the releaser was doing (lock screen) | `futex_wait.py <slice> <secs> [--top N] [--min-ms X] [--pidmap FILE]` |
| `tracelib.py` | The shared parser. Not run by hand | `tracelib.py --selftest` |

One slice serves every screen. Its event pattern:

```bash
ALLEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_|irq_handler_|irq_softirq_'
```

---

## Part 3. Setup

```bash
TRACE=/path/to/trace       # the folder that holds `metadata`, `index/` and the channel files
TOOLS=/path/to/scripts     # the folder that holds the scripts (tracelib.py included)
WORK=/path/to/scratch      # an empty folder for slices and notes
ALLEV='sched_switch|sched_waking|sched_wakeup|sched_process_fork|lttng_statedump_process_state|syscall_|irq_handler_|irq_softirq_'

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,extract_slice.sh,pidmap.py,thread_top.py,runq_wait.py,syscall_stall.py,wait_chain.py,irq_balance.py,futex_wait.py,tracelib.py} > /dev/null && echo "scripts found"
```

Both lines must print OK. If `metadata` is missing, look one or two levels deeper (`kernel/`, `kernel/kernel/`).

---

## Part 4. Procedure

### Step 1. Check the trace and what it can answer

**Goal:** the trace's date, span and health, and which screens the events allow.

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt
DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
SECS=$(awk '/^duration/ {print int($3)+2}' $WORK/summary.txt)
echo "DAY=$DAY TRACE_START=$TRACE_START SECS=$SECS"

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -c -E '^sched_switch$' $WORK/event_names.txt
grep -c -E '^irq_softirq_entry$' $WORK/event_names.txt
grep -c -E 'syscall_entry_' $WORK/event_names.txt
```

Read it:

- **Health.** `lost events` and `time gaps` say where data is missing. The tools detect holes on their own and leave those stretches out; write the health lines down for the report.
- **Snapshot captures.** Line cards often record in snapshot mode: the trace spans 60–180 s but holds events for only the last 6–30 s. The tools print `note: events cover only X s of the Y s slice` and divide by the real span. Read the shares, not the slice length.
- If the metadata is older CTF 1.8 text, the `grep` prints nothing; cut the slice in Step 2 and count instead: `grep -c irq_softirq_entry $WORK/all.txt`, `grep -c syscall_entry_ $WORK/all.txt`.
- **No `sched_switch`:** stop; the trace cannot be triaged. **No `irq_softirq_entry`:** skip the interrupt screen in Step 4 and say so in the report. **No `syscall_entry_*`:** skip the stall and lock screens and say so.

**Next:** Step 2.

### Step 2. Cut one slice over the whole trace, and map the threads

**Goal:** one decoded slice with every event the four screens need, and a thread → process map.

Do **not** hunt for a window first. These faults are steady: they are there as long as the load is. One slice over the whole span sees everything.

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $TRACE_START $SECS $WORK/all.txt "$ALLEV"
python3 $TOOLS/pidmap.py $TRACE --out $WORK/pidmap.tsv
PM="--pidmap $WORK/pidmap.tsv"    # leave empty if pidmap.py mapped nothing
```

A 60 s trace of a busy 6-CPU box gives a few million lines; each tool reads it in well under a minute.

**Next:** Step 3.

### Step 3. Name the threads and the crowded cores

**Goal:** the candidate victims, and how each core is loaded.

```bash
python3 $TOOLS/thread_top.py $WORK/all.txt $SECS --sort wait --top 30 $PM
```

Read it:

- **Header:** the `identity:` line, the snapshot note, the `trace holes:` line if any. Write them down.
- **Per-CPU table** (`cpu busy% threads RT <120 =120 >120 kthr% top occupants`): write down each CPU's `busy%`, its `=120` count (the crowd at nice 0), and `kthr%`. A `kthr%` of tens of percent on one CPU means the interrupt screen will matter.
- **Per-thread table:** the **candidate victims** come from three columns, not one: (a) rows marked `*` (3 or more waits of 10 ms, or one wait of 25 ms or more — the bars `runq_wait.py` uses; how much the row ran does not matter); (b) the two or three rows with the **largest `>=10ms` count**; (c) the two rows with the **most `wakeups`** (a latency-sensitive thread wakes often and runs briefly). A thread that runs more than it waits can still be the starved one — measured on a line card: the comms thread had the most waits of 10 ms or more of any thread (26) and no `*`, and a screen that tested only `*` rows called the card normal. Write down up to four: `name tid prio cpu`. Also write down the three or four busiest application threads (large `run`); those go to `--watch` below.

```bash
CANDIDATES="<tid or name> <tid or name> <tid or name> <tid or name>"   # '*' rows + top >=10ms + top wakeups
WATCH=<app threads, comma-separated>                      # the busiest application threads, or the ones the operator named
```

**Next:** Step 4.

### Step 4. Run the four screens on the same slice

**Goal:** one verdict line per family. Quote each `VERDICT:` / `STALL:` / `NO ...` line word for word in your notes.

```bash
python3 $TOOLS/irq_balance.py $WORK/all.txt $SECS --watch $WATCH            # skip if no irq events
python3 $TOOLS/syscall_stall.py $WORK/all.txt --min-ms 10 --top 20 $PM       # skip if no syscalls
python3 $TOOLS/futex_wait.py $WORK/all.txt $SECS --top 10 $PM                # skip if no syscalls
for V in $CANDIDATES; do python3 $TOOLS/runq_wait.py $WORK/all.txt $V --top 12 $PM; done
```

Read it:

- **Interrupt screen.** `VERDICT: RX CONCENTRATED ON CPU N: ...` with the `APP THREADS ON THAT CPU/ITS SIBLING:` line, or `VERDICT: IRQ/SOFTIRQ SPREAD EVENLY`. A `(but <kind> on cpu N is concentrated ...)` tail is a different, smaller finding: name the kind.
- **Stall screen.** `STALL: <thread> tid N spent X ms in <syscall> (... on-CPU + ... D; ...) - n times, every ~Z s; it froze K threads in D for up to X ms (names); siblings starved: ...; released at exit: ...`, or `NO WORK-CLASS SYSCALL >= 10 ms (...)`. The lines `WORK-class calls >= 10 ms that were sleeping (...)` and `tracer's own activity (left out): ...` are not findings. A `STALL:` with `no sibling or freeze effect measured` and under 50 ms is a finding, never the verdict.
- **Lock screen.** `VERDICT: PRIORITY INVERSION: ...`, `VERDICT: LOCK CONTENTION on futex 0x..: ...`, or one of the negatives: `NO LONG FUTEX WAITS (...)`, `NO LOCK PROBLEM: ...`, `FUTEX WAITS WITHOUT A SCHEDULING CAUSE: ...`.
- **Starvation screen**, once per candidate. `VERDICT: STARVED BY CROWD: ...`, `VERDICT: STARVED BY HIGHER PRIORITY: ...`, `VERDICT: MIXED - ...`, `VERDICT: NOT STARVED - ...` or `VERDICT: VICTIM NOT SEEN - ...`; then the second line, `OTHER CPUS WERE IDLE K% OF THE TIME IT WAITED (...)` or `HOST SATURATED: all CPUs busy >= 90%`; and a `NOTE: the victim already outranks ...` line when it applies.
- When a stall names a victim, or a starvation verdict surprises you, one `wait_chain.py $WORK/all.txt <victim> --top 12 $PM` shows who releases that thread and what the releaser was doing (`BLOCKED MOSTLY ON ...`, `THE WAKER WAS STUCK IN ...`, `NO LONG BLOCKS`). Use it to connect two findings, not as a fifth screen.

**Next:** Step 5.

### Step 5. Decide

**Goal:** one fault family (or normal), with the threads named, from the verdict lines you quoted.

Walk Appendix A from the top; the first row that matches gives the lead verdict. Then apply two rules:

1. **Who is affected decides between two hits.** A `STALL:` outranks a `STARVED` verdict **only when its frozen or starved dependants include a candidate victim from Step 3 (or the operator's named thread)**. Otherwise the starvation leads and the stall is a second finding. Measured: on one card the comms thread was STARVED BY CROWD and, on the same slice, a logging thread spent 364 ms in `write` (all D state) six times and froze the journal daemon for 249 ms. The stall was real but touched nobody that mattered; the engineers' root cause was the starvation.
2. **Explain one hit by the other when they are linked.** A thread starved on the RX CPU while `RX CONCENTRATED ON CPU N` fires is a consequence of the interrupt imbalance: report `irq_imbalance`, and list the starvation as its effect. A victim `BLOCKED MOSTLY ON <thread>` that is itself the `STALL:` thread is one fault (`syscall_stall`), not two.

If no row matches, the verdict is **normal**: list every negative line you got, word for word, plus the screens you had to skip and why.

**Next:** Step 6.

### Step 6. Submit

- `fault_type`: one of `irq_imbalance`, `syscall_stall`, `priority_inversion`, `lock_contention`, `cpu_starvation`, `cpu_saturation`, `normal`, `other`.
- `culprit_kind`: `thread` when a thread (or a per-CPU kernel thread such as `ksoftirqd/0`) is the cause; `host` for saturation.
- `culprit_thread` and `victim_thread`: `comm tid N (prio P)`, exactly as the tools print them. Several victims: name the first, list the rest in the evidence.
- `incident_window`: the span of the slice that holds events. These faults are steady, not a step change; say so.
- `evidence`: the quoted verdict lines and their numbers, the per-CPU facts from Step 3, and the screens you skipped.
- One sentence naming the deep-dive blueprint that confirms the finding (Appendix A, last column).
- Add this sentence, always: the user-visible symptom (packet drops, late replies) usually lives in an application counter the kernel trace cannot show; the verdict is the scheduling cause behind it.

---

## Part 5. Limits of this blueprint

- It screens the four scheduling families and nothing else. A disk fault, a memory fault or a kernel hot path inside one system call (a syscall that is 10–30 ms on-CPU every time) needs other instruments.
- A snapshot trace that holds only a few seconds of events can miss a fault that comes every 7–8 s. Say how many seconds of events the tools reported.
- The trace does not know SMT pairs. Without `--siblings` the interrupt screen names the threads on the hot CPU only; read `/sys/devices/system/cpu/cpuN/topology/thread_siblings_list` on the box.
- Thresholds come from five traces of one vendor's boxes. A very different host (many cores, real-time threads everywhere) needs a baseline capture before a `normal` verdict means much.

---

## Appendix A. The decision table

Walk it from the top. "Victim-aware" rows follow rule 1 of Step 5.

| # | Tool | Verdict line (exact prefix) | `fault_type` | Culprit | Victim | Deep dive |
|---|---|---|---|---|---|---|
| 1 | `irq_balance.py` | `VERDICT: RX CONCENTRATED ON CPU N: P% of NET_RX time (expected E%), ksoftirqd/N at K% of a CPU, cpu busy B%` | `irq_imbalance` | the RX softirq load on cpu N (`ksoftirqd/N tid ..`) | the `APP THREADS ON THAT CPU/ITS SIBLING:` line | `10_irq_imbalance` |
| 2 | `syscall_stall.py` | `STALL: <thread> tid N spent X ms in <syscall> (...) - ...; it froze K threads in D for up to X ms (...)` — only when a frozen or starved dependant is a candidate victim or the operator's thread | `syscall_stall` | the staller | the frozen threads | `9_syscall_stall` |
| 3 | `futex_wait.py` | `VERDICT: PRIORITY INVERSION: <w> ... waited X ms on futex ...; the thread that released it, <h> ..., was runnable-but-not-running ...` | `priority_inversion` | the releaser `<h>` (and the threads that took its CPU) | the waiter `<w>` | `11_priority_inversion` |
| 4 | `futex_wait.py` | `VERDICT: LOCK CONTENTION on futex 0x..: N held lock waits ...` | `lock_contention` | the holders (`release by ...`) | the top waiter | `11_priority_inversion` |
| 5 | `runq_wait.py` | `VERDICT: STARVED BY CROWD: same-or-worse-priority threads held cpu X for M ms (P% of its waiting); N distinct threads at prio ...` | `cpu_starvation` | the crowd on cpu X (name the top competitors) | the thread you passed | `8_cpu_starvation` |
| 6 | `runq_wait.py` | `VERDICT: STARVED BY HIGHER PRIORITY: <name> tid T prio ... held cpu X for M ms (P%)` | `cpu_starvation` | `<name> tid T` | the thread you passed | `8_cpu_starvation` |
| 7 | `runq_wait.py` | second line `HOST SATURATED: all CPUs busy >= 90%` | `cpu_saturation` | `host` | every waiting thread | `2_noisy_neighbor` (cpu_saturation) |
| 8 | `syscall_stall.py` | `STALL: ...` whose dependants are **not** a candidate victim, or with `no sibling or freeze effect measured` | a second finding, not the verdict | — | — | `9_syscall_stall` if the operator cares about that thread |
| 9 | `irq_balance.py` | `VERDICT: IRQ/SOFTIRQ SPREAD EVENLY (but <kind> on cpu N is concentrated - see above)` | a second finding (`other` if alone) | the device in `top irq` / the kind | threads on that CPU | `10_irq_imbalance`, lookalikes table |
| 10 | all four | `VERDICT: IRQ/SOFTIRQ SPREAD EVENLY`; `NO WORK-CLASS SYSCALL >= 10 ms (...)`; `NO LONG FUTEX WAITS (...)` or `NO LOCK PROBLEM: ...`; `VERDICT: NOT STARVED - ...` for every candidate | `normal` | — | — | none; list the negatives word for word |
| 11 | not in this screen | kernel packet drops (`skb_kfree` with a reason, bursts) | `packet_drop` | — | — | `7_packet_drop` — run it when the question is "does the kernel drop packets" |

Rows 2 and 8 are the same tool: the difference is who got frozen. Rows 5–7 come from one `runq_wait.py` call per candidate; a `VERDICT: MIXED - ...` with a large idle-elsewhere share is reported as `cpu_starvation` with lower confidence, and `VERDICT: NOT STARVED - ...` (also with the `NOTE: the victim already outranks ...` line) closes that candidate.
