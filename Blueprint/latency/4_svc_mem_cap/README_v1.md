# Blueprint: finding a memory cap on one service from a kernel trace

|                                               |                                                                                                                                                 |
|-----------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| Problem class                                 | Latency (soft limit) and failure (hard limit)                                                                                                   |
| Root cause this blueprint confirms or rejects | One service (container) has a memory limit that is too small for its work                                                                       |
| Evidence                                      | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder                                                |
| Also allowed                                  | The list of event types the trace holds (read from `metadata`), and the event rules you turned on when you recorded the trace, if you know them |
| Not used                                      | Logs, request traces (spans), metrics, container settings                                                                                       |

**How to use this blueprint.** Read Part 1 once, to learn what the fault is and what it looks like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

---

## Part 1. Background

### 1.1 What the fault is

A container gets a memory limit that is too small for its work.

In cgroup v2 the limit is a number of bytes in one of two files, and they behave very differently:

```
memory.high = 512M     # the SOFT limit: slow down, never kill
memory.max  = 640M     # the HARD limit: reclaim, and kill if that fails
```

What happens when the container grows past the limit:

1. The kernel **reclaims**: it takes pages away from the container. File cache goes first, because it can be read back from disk.
2. With the cache gone, the container's next read of the same file must go **back to disk**. This is called a **refault**. The same file gets read over and over, and the work crawls.
3. Under `memory.high` that is the whole story: the container gets slower and slower, but nothing dies.
4. Under `memory.max`, if reclaim cannot free enough — because the memory is **anonymous** (heap, not file cache) and there is no swap — the kernel's OOM killer **kills** the biggest consumer. The process dies mid-work, with no warning and no error message of its own.

So one limit, two faces: a **slowdown** when the squeezed memory is file cache, a **kill** when it is heap.

The kernel trace does not record the limit itself. You find it from its effects.

### 1.2 What it looks like in a kernel trace

The key event is named `mm_vmscan_memcg_reclaim_begin/end`. **"memcg" means the reclaim happens because of a CGROUP limit** — the container's own wall. When the whole MACHINE is short of memory the kernel uses different events (`mm_vmscan_direct_reclaim_*`, and the `kswapd` kernel thread runs). The event name alone separates "this container's limit" from "the host is full".

For the squeezed container (the **victim**):

- **Reclaim, thousands of times.** Measured on one squeezed run: 9,224 memcg reclaims by one process in 32 seconds. The fault-free baseline had exactly zero.
- **The same data read from disk again and again.** The victim re-read 5.4 GB for a 1 GB working set — more than five times over. The baseline read 1.07 GB: once, plus read-ahead.
- **The work takes several times longer.** The same job: 8.5 s free, 32.4 s squeezed (and across five repeats the slowdown was about 4.7x).
- **Deaths, under the hard limit only.** The killed process exits INSIDE its own final reclaim — measured gap 0.02–0.37 ms on three kills. A process that merely finishes under pressure exits 8–48 ms after its last reclaim (five runs). The gap tells kill from finish.

One warning, measured: **the victim looks like a slow-disk victim.** Its threads sit in disk-type sleep (`D`) in both cases — 0.87 squeezed against 0.66 on a cold-cache baseline — because refaulting IS disk reading. `D` alone cannot tell a memory limit from plain disk work. The reclaim events and the re-read ratio can.

**Two traps that make readers miss a real cap — read these, they cause most misses:**

- **A heap-heavy workload reclaims but barely re-reads.** The "reads the same data many times over" signature is the **file-cache face only**. A service whose memory is mostly **anonymous** — a JVM or any managed runtime holds its heap as anonymous pages, not file cache — has almost nothing to refault from disk, so under a cap it **reclaims hard while disk reads stay LOW**. Low (or near-zero) reads *with* memcg reclaim is the **anonymous / hard face**, NOT evidence against a cap. The decisive signal is the reclaim itself, above baseline, in one container — never withhold the verdict because the re-read storm is missing.
- **The cap's cascade looks like a "scenario change".** When a cap bites hard the squeezed service stalls, or its process is killed, so it stops serving and its callers fall idle — producing a **broad drop in scheduling / network activity across the whole trace**. That collapse is the *consequence* of the cap, not a separate "workload teardown", "process-population change", or "scenario transition". Do not stop at "activity collapsed" and blame whichever cohort went quiet; find the container doing **memcg reclaim** and attribute the collapse to it. A container whose processes churn threads and **exit during, or within ~1 ms of, their own memcg reclaim** is the hard cap killing them — read that as the kill, not as the service shutting itself down.

### 1.3 Problems that look similar

| Cause                       | What the kernel trace shows                                                                                                   | How it differs from a memory cap                                                                |
|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| **Memory cap (this fault)** | memcg reclaim by one container's processes, the same processes re-reading many MB, `D` high; deaths only under the hard limit | —                                                                                               |
| Plain slow or busy disk     | Reads and `D` high, but **no reclaim at all**                                                                                 | A cap always reclaims. No `mm_vmscan_memcg_*` events, no cap                                    |
| Host out of memory          | `mm_vmscan_direct_reclaim_*` and `kswapd` activity; processes in DIFFERENT containers stall                                   | A cap uses memcg reclaim and hits one container                                                 |
| CPU cap                     | The victim is ready-but-WAITING for a CPU (`wait` high), not sleeping on disk                                                 | A memory cap's victim sleeps in `D`; hand CPU waits to the CPU-cap blueprint                    |
| Cold cache / first read     | One pass of reads, roughly the size of the data, no reclaim, then it stops                                                    | A cap re-reads the same data repeatedly and reclaims the whole time                             |
| A memory leak               | Usage grows until SOMETHING stops it. If that something is the container's limit, the trace shows exactly this fault          | The trace shows the limit biting; whether the growth was a leak needs the application's history |
| Writeback storm             | `writeback_*` events and WRITES dominate                                                                                      | A squeezed cache shows READS (refaults)                                                         |

---

## Part 2. What you need

| Input                                                                                                         | Why                                               |
|---------------------------------------------------------------------------------------------------------------|---------------------------------------------------|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/`                     | Everything comes from here                        |
| `mm_vmscan_*`, `block_rq_*`, and `sched_*` events in the trace                                                | Reclaim, refault reads, sleeps, and deaths        |
| A normal period to compare with: a normal stretch in the same trace, or a fault-free trace of the same system | Numbers only mean something when you compare them |
| `babeltrace2`, `python3`, GNU `date`                                                                          | To read the trace and run the scripts             |
| The eleven scripts below, all in one folder                                                                   | To read the index, cut slices, and measure        |

The scripts:

| Script                        | What it does                                                                                                                        |
|-------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| `idx_summary.py`              | Trace date, start, end, length, CPUs, health checks, and data written over time. Reads only the index, so it takes seconds          |
| `idx_dump.py`                 | Every field of one index file, one row per packet                                                                                   |
| `idx_slice.py`                | Copies only the packets that cover a time window into a small trace                                                                 |
| `extract_slice.sh`            | Cuts one time slice and keeps the events you name (default: scheduling only; this blueprint passes a memory pattern)                |
| `mem_pressure.py`             | The memory-cap check: who reclaims (container limit or host), who re-reads from disk, and who died doing it. The decisive tool here |
| `sched_budget.py`             | Time budget per process: running, waiting, sleeping (`S`), disk sleep (`D`)                                                         |
| `victim_info.py`              | Who a process is: PID, names, threads, container                                                                                    |
| `wake_graph.py`               | Which processes wake the victim, and which ones it wakes                                                                            |
| `cpu_hogs.py`                 | Who used the CPU; used here only to rule CPU problems out                                                                           |
| `rhythm.py`, `cpu_ceiling.py` | CPU-cap checks; used here only to hand a CPU case to the right blueprint                                                            |

The slice pattern this blueprint uses everywhere (scheduling + reclaim + disk + births/deaths):

```bash
MEMEV='sched_switch|sched_waking|sched_wakeup|mm_vmscan_|block_rq_|sched_process_'
```

---

## Part 3. Setup

Run this block first, in every new terminal. Put your own paths in the first three lines.

```bash
TRACE=/path/to/trace       # the folder that holds `metadata`, `index/` and the channel files
TOOLS=/path/to/scripts     # the folder that holds the eleven scripts
WORK=/path/to/scratch      # an empty folder for slices and notes
MEMEV='sched_switch|sched_waking|sched_wakeup|mm_vmscan_|block_rq_|sched_process_'

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,idx_dump.py,idx_slice.py,extract_slice.sh,mem_pressure.py,sched_budget.py,victim_info.py,wake_graph.py,cpu_hogs.py,rhythm.py,cpu_ceiling.py} > /dev/null && echo "all eleven scripts found"
```

Both lines must print OK.

---

## Part 4. Procedure

### Step 1. Check the trace

Same first moves as the CPU-cap blueprint: `idx_summary.py` for dates and health, then the event list.

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt
DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
TRACE_END=$(awk '/^trace end/ {print substr($4,1,8)}' $WORK/summary.txt)

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -c -E 'mm_vmscan_memcg' $WORK/event_names.txt
grep -c -E 'block_rq_issue'  $WORK/event_names.txt
```

- Read the health checks (lost events, gaps). Avoid stretches with loss, or say so.
- If the trace has **no `mm_vmscan_memcg_*`** events, this blueprint loses its main evidence. You can still see refault-style re-reading (Step 6) and deaths, but say clearly in your report that reclaim itself was not recorded, and treat any verdict as weaker.
- If `block_rq_issue` is missing, you cannot see the refault reads. Say so.

### Step 2. Find when something changed

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```

A memory squeeze often makes the rate RISE — refault reads generate lots of block events — but the direction is only a hint. Write down the candidate window:

```bash
WINDOW_START=<HH:MM:SS>   # or TRACE_START if nothing stands out
WINDOW_END=<HH:MM:SS>     # or TRACE_END
```

### Step 3. Look for reclaim

**Goal:** find out whether a memory limit is biting at all, and whose. This is one tool call per slice, and it is the decisive measurement — run it before anything else.

Cut two or three slices inside the window and one before it, keeping the memory events:

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY <baseline_t> 10 $WORK/m_base.txt  "$MEMEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY <fault_t1>   10 $WORK/m_f1.txt   "$MEMEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY <fault_t2>   10 $WORK/m_f2.txt   "$MEMEV"

python3 $TOOLS/mem_pressure.py $WORK/m_base.txt 10
python3 $TOOLS/mem_pressure.py $WORK/m_f1.txt   10
python3 $TOOLS/mem_pressure.py $WORK/m_f2.txt   10
```

`mem_pressure.py` prints three sections: who reclaimed (container-limit or host), who read from disk, and which processes started or died.

Decide:

- **CONTAINER-LIMIT reclaim (memcg) on one container's processes, above the baseline:** this is the **decisive finding — a memory cap is confirmed.** You do NOT need any other signature to call it a cap; the remaining steps only tell you WHICH FACE (soft slowdown vs hard kill) and add supporting numbers. Commit to the memory-cap diagnosis now. `mem_pressure.py` prints a **`VICTIM CONTAINER = pid_ns N`** line — that pid_ns IS the capped container (memcg reclaim fires inside the cgroup that hit its own limit), so read the victim's container **straight off that line**, not from CPU-usage correlation. Write down the victim pid and its pid_ns. Go to Step 4.
- **HOST-pressure reclaim (direct reclaim, kswapd) instead:** the machine is short of memory, not one container. That is a different fault (host memory pressure); report it and **stop**.
- **No reclaim in the slices you sampled:** reclaim can be **intermittent** — a subtle cap reclaims in bursts, and a hard cap may burst once and then the victim stalls or dies. Before concluding anything, use Step 2's `--rate` view to find where the `mm_vmscan` events concentrate and **sample there**; reclaim above baseline in *any* in-window slice confirms the cap. Only after you have sampled where the events actually are, if there is still **no memcg reclaim anywhere**, report "no memory-limit pressure found" and **stop**. Do not write "no fault" — this blueprint does not look for other kinds of faults. If the victim you were asked about waits for the CPU instead, hand the case to the CPU-cap blueprint.

```bash
VICTIM=<pid>             # the process doing memcg reclaim
BASE_START=<HH:MM:SS>
FAULT_START=<HH:MM:SS>
```

### Step 4. Soft limit or hard limit: did anything die?

**Goal:** tell the slowdown face (`memory.high`) from the killing face (`memory.max`). `mem_pressure.py` already printed the deaths; read them.

- **A process exited INSIDE its own reclaim — within about 1 ms of it:** it did not finish, the hard limit killed it. Measured on three known kills: 0.02–0.37 ms. A process that finishes under pressure exits 8–48 ms after its last reclaim (five known finishes) — the cleanup takes real time; a kill is instant.
- **The same name died several times in the window:** kill-and-respawn. A supervisor restarts the worker and the limit kills it again. This is the thrash pattern of a hard limit well below the service's needs.
- **Reclaim and re-reads but nobody died:** the soft-limit face (or a hard limit that reclaim is keeping up with). The service crawls instead of failing.

Write down which face you saw. **Next:** Step 5.

### Step 5. Measure the damage: the re-read ratio (the FILE-CACHE face only — optional)

**This step confirms the file-cache face; it is NOT required to confirm the cap.** The cap is already
confirmed by Step 3's reclaim. If the victim's memory is anonymous (a JVM / managed-runtime heap),
there is little file cache to refault, so reads stay low and this step shows little — that is the
**anonymous / hard face**, not a reason to doubt the cap. Only expect a big re-read ratio when the
squeezed memory is file cache. Never downgrade the diagnosis because this number is small.

**Goal (when it applies):** show the refault storm with a number. The squeezed container's cache keeps being evicted, so it reads the same data from disk again and again.

Read the "Disk reads" section of `mem_pressure.py` for the victim, in the fault slices and the baseline:

- **Squeezed (measured):** the victim read **5,369 MB** against a 1 GB working set — more than 5 passes — while reclaiming 9,224 times.
- **Baseline (measured):** the same job read **1,074 MB** — one pass of the 1 GB file, plus read-ahead — with zero reclaim.

The signature is reads **far past the size of the data being worked on**, together with reclaim. One pass of reads with no reclaim is just a cold cache.

If the job's data size is unknown, compare the victim's read MB per 10 s slice against the baseline slice: the squeezed case repeats, the healthy case reads once and stops.

### Step 6. Confirm what the victim's time went to

**Goal:** a second, independent view of the same story, from the scheduler.

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START  10 $WORK/baseline_slice.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $FAULT_START 10 $WORK/fault_slice.txt
python3 $TOOLS/sched_budget.py $WORK/baseline_slice.txt 10 $VICTIM
python3 $TOOLS/sched_budget.py $WORK/fault_slice.txt    10 $VICTIM
```

Read the victim's row:

- **`D` (disk-type sleep) is high, `wait` for the CPU is low.** The victim is sleeping on refault reads, not starved of CPU.
- **Careful — `D` is high on a cold-cache baseline too** (measured: 0.87 squeezed against 0.66 cold baseline). `D` supports the story; it does not prove it. The proof is Step 3's reclaim plus Step 5's re-read ratio.
- If instead `wait` is high and `D` is low, the victim's problem is the CPU — hand the case to the CPU-cap blueprint and **stop**.

### Step 7. Rule out lookalikes

| Check                       | Where to look                  | A memory cap looks like this                                                                                                |
|-----------------------------|--------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| Is it plain disk work?      | Step 3: reclaim                | Reads WITH memcg reclaim. Reads without any reclaim are not a memory limit — check the disk, not the memory                 |
| Is the host out of memory?  | Step 3: which reclaim events   | memcg reclaim only. Direct reclaim / kswapd means host pressure; also check whether processes in OTHER containers stall too |
| Is it the CPU?              | Step 6: `wait` against `D`     | `D` high, CPU `wait` low                                                                                                    |
| Did the work simply start?  | Step 2 + Step 5 baseline       | A fresh workload reads its data ONCE. The cap re-reads it for as long as the window lasts                                   |
| Is it writeback, not reads? | `mem_pressure.py` writers line | Refaults are READS. A write storm is a different story                                                                      |

**Weigh these correctly.** The one decisive test is Step 3's reclaim: memcg reclaim in one container
above baseline **is** the cap. The other rows only separate a cap from a *different* fault (plain
disk with **zero** reclaim, host pressure via direct/kswapd reclaim, a CPU wait). A small re-read
ratio (anonymous memory) or an exact kill-gap you could not pin down does **not** make the cap
unconfirmed — those classify the face, they do not overturn the reclaim. Downgrade to "unconfirmed"
only if a row shows a *competing mechanism* (reclaim is actually host-wide, or the victim is waiting
on CPU not sleeping on memory), or if there is **no memcg reclaim at all**.

### Step 8. Say what you can about the limit's size

The trace does not hold the limit, and unlike the CPU quota there is no per-period ceiling to read it from. Be honest about what the trace supports:

- **The limit is smaller than the victim's working set** — that is WHY it reclaims and re-reads. (Inferred.)
- Under the hard-limit face: **the limit is smaller than the victim's live (anonymous) memory** at the moment of the kill. (Inferred.)
- If a healthy stretch exists where the same workload ran clean, the limit sits between "fits" and "does not fit" — say both sides if you can see them.

Do not put a number on the limit unless the operator gives you the working-set size to compare against.

### Step 9. Identify the victim

```bash
python3 $TOOLS/victim_info.py $WORK/fault_slice.txt 10 $VICTIM
python3 $TOOLS/wake_graph.py  $WORK/fault_slice.txt $VICTIM
```

Same rules as the other blueprints: name the process and PID always; the container namespaces if recorded (a namespace number of 0 means "could not be read", not a real namespace); who it talks to as a hint. The kernel trace never holds a service or container NAME — report what you saw.

### Step 10. Write the RCA statement

Template:

> From **[start]** to **[end]** (UTC), **[victim]** was **[slowed / killed]** by a container memory limit that is too small for its work. We know because of **[evidence 1: memcg reclaim counts]**, **[evidence 2: the re-read ratio]**, and **[evidence 3: the kill gap / the slowdown against baseline]**. We ruled out **[plain disk, host pressure, CPU]** because **[reason]**. We did not check **[what was not tested]**.

Rules:

- **Commit — do not hedge.** If Step 3 found memcg reclaim in one container above baseline, the
  answer **is** a container memory cap on that container. Report it as the fault; name the victim by
  its pid_ns (the `VICTIM CONTAINER` line). Do **not** answer "other", "unconfirmed", "workload
  teardown", or "scenario change" merely because the broad activity collapse is unexplained or a
  secondary signature (re-read storm, exact kill-gap) is missing — the collapse is the cascade and
  the reclaim is the cause. The only honest non-commitments are: reclaim was host-wide (host
  pressure), the victim was CPU-waiting not memory-sleeping (CPU cap), or there was no memcg reclaim
  at all.
- Name the victim, the time window, and which face of the limit (soft slowdown or hard kill).
- Give at least two independent pieces of evidence: the reclaim (Step 3), the re-read ratio (Step 5), the kill gap (Step 4), the `D` budget (Step 6). The reclaim alone is sufficient to commit; the others strengthen it and name the face.
- Mark each claim **Measured** or **Inferred**. The limit's size is always **Inferred** (Step 8).
- Say what you did not test.

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects one cause: a cgroup memory limit on one container, in either face. It stops and says so when the evidence points at host pressure, plain disk, or the CPU.
- It needs `mm_vmscan_memcg_*` events. Without them the verdict is much weaker — only re-reading and deaths remain, and both have innocent explanations.
- It cannot read the limit's value. The CPU blueprint can estimate its quota from the ceiling; there is no memory equivalent in the trace.
- Swap changes the hard-limit face: with swap, anonymous memory is reclaimable and the kill becomes a slowdown. The measured numbers here come from machines with no swap.
- The kill-gap rule (under ~1 ms = killed, 8 ms or more = finished) was measured on 8 runs of one workload on one machine. Treat the 1 ms line as a rule of thumb, not a law.
- A single death with no reclaim nearby says nothing about memory. Processes exit all the time.
- The re-read ratio needs the working-set size, or a baseline slice, to mean anything.

---

## Part 6. References

How the memory limit works:

1. Linux kernel documentation, *Control Group v2* (`memory.high`, `memory.max`, the OOM killer). https://docs.kernel.org/admin-guide/cgroup-v2.html
2. Linux kernel documentation, *Memory Resource Controller*. https://docs.kernel.org/admin-guide/cgroup-v1/memory.html
3. Facebook/Meta, *cgroup2: memory controller and PSI* (why memory.high stalls instead of killing). https://facebookmicrosites.github.io/cgroup2/docs/memory-controller.html

Refaults and reclaim:

4. J. Weiner, *workingset: refault distance-based file cache sizing* (the kernel's own refault tracking). https://lwn.net/Articles/495543/
5. B. Gregg, *Systems Performance*, 2nd ed., chapter 7 (Memory). https://brendangregg.com/systems-performance-2nd-edition-book.html

The method, reading waits and sleeps from kernel traces:

6. F. Giraldeau and M. Dagenais, *Wait analysis of distributed systems using kernel tracing*, IEEE TPDS 27(8), 2016. https://publications.polymtl.ca/3078/
7. B. Gregg, *Off-CPU Analysis*. https://brendangregg.com/offcpuanalysis.html

The tools and the trace format:

8. LTTng documentation. https://lttng.org/docs/
9. Babeltrace 2, `source.ctf.fs` component. https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What the index files hold

The same as the CPU-cap blueprint's Appendix A: each channel file has an `index/*.idx` table of contents saying where each packet sits and what time it covers. `idx_summary.py` reads only this, which is why Steps 1 and 2 take seconds.

## Appendix B. Two solved cases

How the numbers looked on runs with known limits. Use them to get a feel for the sizes. Do not reuse them as thresholds.

**A soft limit (memory.high roughly half the working set):**

- Step 3: thousands of memcg reclaims by one process in a half-minute window. Baseline: zero.
- Step 5: the victim read about five times its file's size — the same data over and over. Baseline: one pass plus read-ahead.
- The job took several times longer than the free run (about 4-5x across repeats).
- Step 4: one exit, several milliseconds after its last reclaim, together with its launcher script — a finish, not a kill. Correct: memory.high never kills.

**A hard limit (memory.max below an anonymous allocation, no swap):**

- Step 3: hundreds of memcg reclaims — the kernel tried.
- Step 4: the allocating process exited **well under a millisecond** after its own reclaim — inside it. Killed. Across known kills the gap was a few hundredths to a few tenths of a millisecond; across known finishes, several milliseconds to tens of milliseconds.
- Step 5: modest reads (the memory was anonymous; there was nothing to refault from disk). The kill, not the re-reading, is the hard face's signature on heap memory.
