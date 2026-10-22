# Blueprint: finding a CPU cap on one service from a kernel trace

|                                               |                                                                                                                                                 |
|-----------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| Problem class                                 | Latency                                                                                                                                         |
| Root cause this blueprint confirms or rejects | One service (container) has a CPU limit that is too small for its work                                                                          |
| Evidence                                      | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder                                                |
| Also allowed                                  | The list of event types the trace holds (read from `metadata`), and the event rules you turned on when you recorded the trace, if you know them |
| Not used                                      | Logs, request traces (spans), metrics, container settings                                                                                       |

**How to use this blueprint.** Read Part 1 once, to learn what the fault is and what it looks like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

---

## Part 1. Background

### 1.1 What the fault is

A container gets a CPU limit that is too small for its work.

Linux enforces the limit with a **quota** and a **period**. In cgroup v2 these are two numbers in the file `cpu.max`. For example:

```
cpu.max = 20000 100000
```

This means: in every 100,000 microsecond (100 ms) period, all threads of the container together may use 20,000 microseconds (20 ms) of CPU. That equals **0.2 cores**.

What happens:

1. The container's threads run and use up the quota.
2. The kernel stops them. This is called **throttling**.
3. They stay stopped until the next period starts and the quota is refilled.

A throttled thread is not sleeping. It is ready to run, but it is not allowed to. In a kernel trace it counts as **waiting for the CPU**.

If requests arrive faster than the capped service can handle them, a queue builds up. Every service that calls it also waits. So one small limit can make a whole application slow.

The kernel trace does not record the quota itself. You find it from its effects.

### 1.2 What it looks like in a kernel trace

For the throttled process (the **victim**):

- **Long waits for the CPU.** Many threads are ready but not running. Waits of 10 ms and 50 ms or more appear, many times per second.
- **Low, flat CPU use.** The victim uses about the size of the cap. It does not go up, even though it has work waiting.
- **A burst-and-freeze rhythm.** The victim runs for a short burst, then does almost nothing for the rest of the period. This repeats once per period (often 100 ms).
- **No disk wait.**

For the rest of the machine:

- **Other processes are fine.** Their waits for the CPU stay short.
- **The trace writes less data per second** while the fault lasts, because requests are stuck and less work happens.

### 1.3 Problems that look similar

Several causes make a process slow. This blueprint must tell them apart. You will use this table in Step 7.

| Cause                                | What the kernel trace shows                                                                          | How it differs from a cap                                                                                                                          |
|--------------------------------------|------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| **CPU cap (this fault)**             | Victim waits long for the CPU, `run` is low and flat, burst-and-freeze rhythm, other processes fine  | The rhythm and the per-period ceiling. One container is hit — which can be SEVERAL processes, because a cgroup limit covers the whole process tree |
| Whole machine overloaded             | Processes in DIFFERENT containers wait for the CPU at the same time, no regular rhythm, no idle CPUs | A cap hits one container only. Several waiters in the SAME container are still one cap                                                             |
| Noisy neighbor                       | The victim waits while one busy process takes the CPU; waits are irregular                           | A cap needs no busy neighbor                                                                                                                       |
| Too much work, or garbage collection | Victim `run` goes **up**, its waits stay low                                                         | In a cap, `run` goes down or stays flat                                                                                                            |
| Slow disk                            | Disk-type sleep (`D`) goes up                                                                        | In a cap, `D` stays near 0                                                                                                                         |
| Lock waiting                         | Threads sleep (`S`), waits for the CPU stay low                                                      | In a cap, threads are ready, not sleeping                                                                                                          |
| Slow network or slow dependency      | Threads sleep (`S`), waits for the CPU stay low                                                      | Same as above                                                                                                                                      |
| CPU pinning (cpuset)                 | Victim runs only on some CPUs while other CPUs are idle                                              | A cap is not tied to particular CPUs                                                                                                               |

---

## Part 2. What you need

| Input                                                                                                         | Why                                                                                                                 |
|---------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/`                     | Everything comes from here. `metadata` holds the clock and the event types. `index/` makes cutting time slices fast |
| `sched_switch` and `sched_waking` (or `sched_wakeup`) events in the trace                                     | To measure running, waiting, and sleeping time                                                                      |
| A normal period to compare with: a normal stretch in the same trace, or a fault-free trace of the same system | Numbers only mean something when you compare them                                                                   |
| `babeltrace2`, `python3`, GNU `date`                                                                          | To read the trace and run the scripts                                                                               |
| The ten scripts below, all in one folder                                                                      | To read the index, cut slices, and measure                                                                          |

The scripts:

| Script             | What it does                                                                                                               |
|--------------------|----------------------------------------------------------------------------------------------------------------------------|
| `idx_summary.py`   | Trace date, start, end, length, CPUs, health checks, and data written over time. Reads only the index, so it takes seconds |
| `idx_dump.py`      | Every field of one index file, one row per packet                                                                          |
| `idx_slice.py`     | Copies only the packets that cover a time window into a small trace                                                        |
| `extract_slice.sh` | Cuts one time slice (using `idx_slice.py`) and keeps only the scheduling events                                            |
| `sched_budget.py`  | Time budget per process: running, waiting, sleeping, long waits                                                            |
| `rhythm.py`        | How often a process gets the CPU, in 10 ms buckets, and whether it repeats                                                 |
| `cpu_ceiling.py`   | The victim's on-CPU time per period: a flat ceiling below the period is the direct signature of a quota                    |
| `cpu_hogs.py`      | Who used the CPU, and who held it WHILE the victim waited. A cap leaves the CPUs idle during the waits; this proves it     |
| `victim_info.py`   | Who the victim is: PID, names, threads, container                                                                          |
| `wake_graph.py`    | Which processes wake the victim, and which ones it wakes                                                                   |

---

## Part 3. Setup

Run this block first, in every new terminal. Put your own paths in the first three lines. All later commands use these names.

```bash
TRACE=/path/to/trace       # the folder that holds `metadata`, `index/` and the channel files
TOOLS=/path/to/scripts     # the folder that holds the ten scripts
WORK=/path/to/scratch      # an empty folder for slices and notes

mkdir -p "$WORK"
ls "$TRACE/metadata" "$TRACE/index" > /dev/null && echo "trace folder OK"
ls $TOOLS/{idx_summary.py,idx_dump.py,idx_slice.py,extract_slice.sh,sched_budget.py,rhythm.py,cpu_ceiling.py,cpu_hogs.py,victim_info.py,wake_graph.py} > /dev/null && echo "all ten scripts found"
```

Both lines must print OK.

- If `metadata` is missing, `TRACE` points to the wrong folder. Look one or two levels deeper. LTTng often stores the trace in a subfolder named after the domain, for example `kernel/`.
- If `index/` is missing, the method still works, but cutting slices is slow.

---

## Part 4. Procedure

### Step 1. Check the trace

**Goal:** know when the trace starts and ends, whether it is healthy, and which events it holds.

**1a. Date, start, end, and health.**

```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt

DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
TRACE_END=$(awk '/^trace end/ {print substr($4,1,8)}' $WORK/summary.txt)
echo "DAY=$DAY TRACE_START=$TRACE_START TRACE_END=$TRACE_END"
```

Read the four health checks:

| Check       | Good result                         | If it is not good                                                                                                      |
|-------------|-------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| lost events | 0 in every row                      | Events are missing near those packets. Counts and waits there are too low. Avoid those times, or say so in your report |
| time gaps   | none, or only gaps under about 1 ms | Small gaps are harmless. A gap of many milliseconds means a stretch with no data on that CPU. Avoid it                 |
| seq gaps    | none                                | A packet is missing. Avoid that time                                                                                   |
| file sizes  | match                               | The index does not match the data. Do not trust the index. Read the trace without it                                   |

Two things to know about the times:

- `trace start` is when the first packet was opened. The first event can come up to about a second later. This does not matter for the steps below.
- If `TRACE_END` is earlier in the day than `TRACE_START`, the trace crosses midnight. Then use full dates in the slice loops below.

**1b. Which events the trace holds.**

```bash
grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt

wc -l < $WORK/event_names.txt                                       # how many event types
sed -E 's/^(compat_)?syscall_.*/syscall/; s/^([a-z0-9]+)_.*/\1/' $WORK/event_names.txt \
  | sort | uniq -c | sort -rn                                       # event types per group
grep -x -E 'sched_(switch|waking|wakeup)' $WORK/event_names.txt     # the ones this blueprint needs
```

This list shows which event types the trace **can** hold. A listed type may still never have happened.

- If `sched_switch` is missing, or both `sched_waking` and `sched_wakeup` are missing, **stop**. This blueprint cannot work on this trace. Report that the trace has no scheduling events.
- Note which other groups exist (`block`, `net`, `syscall`, and so on). Note which groups are missing. You cannot use a missing group as evidence.

**1c. (Optional) What you asked for versus what you got.** If you know which event rules were turned on when the trace was recorded, compare them with the groups in 1b. A rule that matches no group gave you nothing. For example, a `tcp_*` rule with no `tcp` group in 1b means the trace has no TCP events. Some events may be stored under another name, so search the list before you decide:

```bash
grep -E '^<prefix>' $WORK/event_names.txt      # for example ^tcp_ or ^irq_softirq
```

**Next:** Step 2.

### Step 2. Find when something changed

**Goal:** find the stretch of time where the system behaved differently. This is the candidate window. This step decodes no events, so it takes seconds.

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```

This prints how much trace data all CPUs wrote per 10 seconds. More work means more events, so this follows how busy the machine was.

Read it:

- Look for a long stretch where the rate moves to a clearly different level, and then often comes back. That stretch is the candidate window.
- The first and last rows are only partly covered. Ignore them.
- A long packet spreads over several rows, so the edges look a few seconds wide.
- To place an edge inside a row: if the row mixes a normal rate N and a changed rate C, the share of the row that was normal is (row − C) / (N − C). This is an estimate. It assumes the rate is even inside each packet.

A change in the rate does not prove a fault. The workload can also start, stop, or change. Step 4 decides.

If there is no clear change, the fault may cover the whole trace, or it may be too small to show here. Continue to Step 3 with slices spread evenly across the trace.

Write down:

```bash
WINDOW_START=<HH:MM:SS>   # first row where the rate changed (or TRACE_START if there is no clear change)
WINDOW_END=<HH:MM:SS>     # first row where it was back to normal (or TRACE_END)
```

**Next:** Step 3.

### Step 3. Find the victim

**Goal:** find the process that suffers inside the window.

Take 10-second slices before, inside, and after the window. Pick the times from Step 2: one or two before the window, three inside, one or two after.

```bash
SLICE_TIMES="<t1> <t2> <t3> <t4> <t5> <t6>"     # HH:MM:SS each, from Step 2
rm -f $WORK/s_*.txt                              # remove old slices first
for t in $SLICE_TIMES; do
  bash $TOOLS/extract_slice.sh $TRACE $DAY $t 10 $WORK/s_$t.txt
done
```

If Step 2 showed no clear window, spread the slices across the whole trace instead:

```bash
rm -f $WORK/s_*.txt
t=$TRACE_START
while [[ "$t" < "$TRACE_END" ]]; do
  bash $TOOLS/extract_slice.sh $TRACE $DAY $t 10 $WORK/s_$t.txt
  t=$(date -u -d "$DAY $t UTC + 30 seconds" +%H:%M:%S)
done
```

Then build a time budget for each slice. The table is sorted by waiting time, so the most-waiting processes come first:

```bash
for f in $WORK/s_*.txt; do
  echo "== $f"
  python3 $TOOLS/sched_budget.py "$f" 10 | head -n 6
done
```

Read it:

- Look at the columns `wait`, `>=10ms`, `>=50ms` and `max_ms` for the top rows.
- In a normal slice, no process has waits of 50 ms or more, and the longest wait is a few milliseconds.
- In a slice inside the window, look for one process that jumps to the top with many waits of 10 ms and 50 ms or more. That process is the **victim**. Write down its `pid`.
- The first slice where the victim jumps to the top marks the start of the fault. The first normal slice after it marks the end. The fault may have started before the trace, or ended after it.

**Discipline: six to eight slices are enough.** The moment one slice shows a clear victim, stop slicing and move on — one `cpu_ceiling.py` call on that slice (Step 6b) says more about a cap than ten more slices will. Cut more slices only if Step 4 cannot be answered with what you have.

```bash
VICTIM=<pid>             # the pid that jumped to the top
BASE_START=<HH:MM:SS>    # a slice time before the window, where everything was normal
FAULT_START=<HH:MM:SS>   # a slice time inside the window
```

**Next:** Step 4.

### Step 4. Decide whether there is a fault

**Goal:** decide, with evidence, whether something is wrong. Answer three questions in order.

1. **Did something change?** In Step 2, the data rate moved to a new level for a long stretch. One odd row is not enough.
2. **Did a process suffer during that stretch?** In Step 3, one process had many long waits for the CPU (10 ms and 50 ms or more) in the slices inside the window, and few or none in the slices outside it.
3. **Is it limited in time and place?** The suffering starts and stops with the change, and it hits one process, not all of them.

Decide:

- **All three are yes:** there is a CPU-related fault. Go to Step 5.
- **The rate changed, but no process suffered:** this is probably a change in the workload, for example the load starting or stopping. In that case the machine just becomes busier or quieter, and nothing waits. Report "no CPU starvation found" and **stop**.
- **Nothing changed, and no slice shows long waits:** report "no CPU starvation found" and **stop**. Do not write "no fault". This blueprint does not look for other kinds of faults, such as network or lock problems.
- **Several processes suffer at once:** do NOT conclude host overload yet. A cgroup limit covers a whole process tree, so a cap on one container makes ALL of that container's processes wait together — several victims is the normal look of a cap, not evidence against one. Run `victim_info.py` on each suffering pid and compare their namespaces (`pid_ns` and the other `*_ns` numbers), and check `wake_graph.py` for a parent/child relationship. **Same container (or same process tree): treat them as ONE victim group** — pick the busiest member as `VICTIM` and continue to Step 5. **Different containers, and no idle CPUs: the whole machine is short of CPU.** That is not a cap on one service; report it and **stop**.

How big must the change be? There is no fixed threshold. A useful rule of thumb: waits of 50 ms or more that are absent in normal slices and appear hundreds of times per 10 s in the window are a clear sign. A smaller change is harder to call. To learn what "normal" looks like for your system, run Steps 1 to 3 on a trace taken when everything was healthy.

If the fault covers the whole trace, there is no normal stretch to compare with. Then use a healthy trace of the same system as the baseline.

### Step 5. Compare the victim's time budget before and during the fault

**Goal:** show what the victim's threads were doing, and rule out the most common other causes.

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START  10 $WORK/baseline_slice.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $FAULT_START 10 $WORK/fault_slice.txt

python3 $TOOLS/sched_budget.py $WORK/baseline_slice.txt 10 $VICTIM
python3 $TOOLS/sched_budget.py $WORK/fault_slice.txt    10 $VICTIM
```

The victim's row is always shown, even if it is not in the top 12.

The columns:

| Column                      | Meaning                                                                                  |
|-----------------------------|------------------------------------------------------------------------------------------|
| `run`                       | Average number of CPU cores in use                                                       |
| `wait`                      | Average number of threads that were ready but had no CPU                                 |
| `preempt`                   | The part of `wait` that came from being switched out while still runnable                |
| `S`                         | Average number of threads asleep (waiting for an event, a lock, a timer, or the network) |
| `D`                         | Average number of threads in disk-type sleep                                             |
| `>=1ms`, `>=10ms`, `>=50ms` | How many single waits for a CPU lasted at least that long                                |
| `max_ms`                    | The longest single wait for a CPU                                                        |

The script reads the `prev_state` code of each `sched_switch`. It prints every code it saw on the first line. Check that the codes are ones it knows:

| Code   | Meaning                                            |
|--------|----------------------------------------------------|
| 0      | Runnable: gave up the CPU but still wants it       |
| 1      | `S`: sleeping                                      |
| 2      | `D`: disk-type sleep                               |
| 4, 8   | Stopped, traced                                    |
| 16, 32 | Exiting (dead, zombie)                             |
| 64     | Parked                                             |
| 128    | `I`: idle sleep (kernel worker threads)            |
| 256    | Flag: preempted while runnable. Counted as waiting |

Decide, by comparing the victim's two rows:

- **`wait` and the long-wait counts jump, while `run` stays low or falls:** the victim is starved of CPU. Go to Step 6.
- **`run` goes up a lot and `wait` stays small:** the victim is doing more work. This is not a cap. Report "the victim is busy, not starved" and **stop**.
- **`D` goes up a lot:** the victim waits on the disk. This is not a cap. Report it and **stop**.
- **`S` goes up a lot, while `wait` stays low:** the victim waits on locks, the network, or another service. This is not a cap. Report it and **stop**.
- **The waits are many but SHORT (a few ms each, hundreds of them, no 50 ms freezes) while the machine is busy:** that is CPU competition — processes sharing a full machine — not a cap. Report "slowed by CPU competition, not a quota" and hand the case to the noisy-neighbor blueprint. **Stop**.

### Step 6. Look for the rhythm, then measure the ceiling

**Goal:** tell a CPU cap apart from other kinds of CPU starvation. A cap makes the victim run in short bursts at a fixed period.

```bash
python3 $TOOLS/rhythm.py $WORK/fault_slice.txt    $VICTIM $FAULT_START 1.0
python3 $TOOLS/rhythm.py $WORK/baseline_slice.txt $VICTIM $BASE_START  1.0
```

Each run prints 100 lines, one per 10 ms bucket. The bar shows how many times a victim thread got the CPU in that bucket. At the end it prints a summary:

- `quiet buckets`: the share of buckets with 0 or 1 switch-ins.
- `repeat`: the period at which the pattern repeats best, and a score from −1 to 1.

Read it:

- **Cap:** bursts, then quiet buckets, repeating at a fixed period. Rule of thumb: quiet buckets above 50% and a repeat score above 0.5 in the fault slice, while the baseline has few quiet buckets and a low score. The repeat period is the quota period. Write it down. Do not assume 100 ms.
- **No beat:** do not stop yet. A victim that idles between spells of work (an interactive tool, an AI agent waiting on a network reply) shows little beat in wall-clock buckets even when it is capped. The ceiling check below decides.

```bash
PERIOD_MS=<period from the repeat line, or 100 if none was found>
```

**6b. Measure the per-period ceiling.** A quota refills every period, so a capped victim's on-CPU time **per period** sits at a flat ceiling near the quota, period after period — even when the rhythm is weak. Run this as soon as you have a victim and a period (use 100 if Step 6 found none): it is one call, and it is the decisive check — do not postpone it for more slicing.

```bash
python3 $TOOLS/cpu_ceiling.py $WORK/fault_slice.txt    $VICTIM $PERIOD_MS
python3 $TOOLS/cpu_ceiling.py $WORK/baseline_slice.txt $VICTIM $PERIOD_MS
```

It prints the victim's on-CPU milliseconds for each period in its active window, then the ceiling (median/p90/max of the busy periods) and how flat it is.

Read it:

- **Cap:** the busy periods pile up at a flat ceiling clearly **below** the period (high flatness, max about equal to the ceiling). The quota is about the ceiling; the cap in cores is ceiling ÷ period. In the baseline the same process runs free of it.
- **Ceiling at the full period:** the victim simply saturates one core. A single thread at 100 of 100 ms cannot be told apart from a cap of one full core; say so rather than claiming a cap.
- **A flat ceiling with BUSY CPUs is not a cap.** N equal busy threads sharing C cores each settle at a flat ~C/N of a core — fair sharing mimics a quota ceiling. A real cap leaves the CPUs IDLE while the victim waits. Decide with `cpu_hogs.py` (Step 7): if the CPU went to other processes rather than idle, this is competition, not a quota.
- **Low flatness? Check your slice before concluding.** Under a load that comes in waves, periods where the victim had little to do mix into the window and drag the flatness down. Re-cut one slice on the victim's BUSIEST stretch (the slice where `sched_budget.py` showed it waiting most) and measure again. Measured on one real capped service: one slice read "not flat" while another slice of the same fault read a clean flat ceiling — the fault had not changed, the slice had.
- **No flat ceiling and no beat, even on the busy stretch:** the victim is starved, but not by a quota. Report "the victim is starved of CPU, but there is no quota signature", then use the table in 1.3 (noisy neighbor, overload, pinning) to suggest a cause, and **stop**.

Validated on runs with known limits: the measured ceiling matched the real quota each time, and an uncapped baseline pegged at the full period — correctly no cap.

**Next:** Step 7.

### Step 7. Rule out lookalikes

**Goal:** check the other causes in the table in 1.3, using what you already have.

| Check | Where to look | A cap looks like this |
|---|---|---|
| Is the whole machine overloaded? | Step 5, fault slice: the other processes' `>=10ms`, `>=50ms` and `max_ms` | Other processes have no long waits. Their longest wait is a few milliseconds |
| Is it the disk? | Step 5, the victim's `D` | Near 0 in both slices |
| Is the victim just doing more work? | Step 5, the victim's `run` | Lower in the fault slice than in the baseline, or flat |
| Is the limit steady? | Step 3, the victim's `run` in every slice inside the window | About the same in every slice: a flat ceiling |

If all four look like a cap, go on. If one does not, say which one in your report. Treat the cap as unconfirmed.

One more check settles it, and `cpu_hogs.py` does it:

```bash
python3 $TOOLS/cpu_hogs.py $WORK/fault_slice.txt 10 $VICTIM
```

It says where every CPU-second went while the victim had a thread ready and waiting.

- **Cap: idle is a large share.** Nobody took the CPU; the kernel refused the victim. On a real capped run, idle took almost all of this time.
- **One name (or one group) takes most of it and idle is small: that is a noisy neighbor, not a cap.** Hand the case to the noisy-neighbor blueprint and **stop**.

**Next:** Step 8.

### Step 8. Estimate the limit

**Goal:** estimate how big the cap is. The trace does not hold the quota, so this is always an estimate.

- The best estimate is Step 6b's ceiling: the quota is about **ceiling ms per `PERIOD_MS`**, and the cap in cores is ceiling ÷ period. On runs with known limits the measured ceiling matched the real quota.
- Cross-check with the victim's `run` in the fault slice (Step 5): averaged over its busy stretch it should sit near the same number of cores. For a bursty victim the whole-slice average is diluted by idle time — trust the per-period ceiling over the average.
- Check that it is a ceiling: in the baseline the same workload runs past it. The victim wanted more CPU than it got.

Write this in your report as **Inferred**, not measured.

**Next:** Step 9.

### Step 9. Identify the victim

**Goal:** describe the victim as precisely as the trace allows.

```bash
python3 $TOOLS/victim_info.py $WORK/fault_slice.txt 10 $VICTIM
python3 $TOOLS/wake_graph.py  $WORK/fault_slice.txt $VICTIM
python3 $TOOLS/wake_graph.py  $WORK/baseline_slice.txt $VICTIM
```

`victim_info.py` prints:

1. **Identity:** the process ID (PID), the program name (the name of the main thread), the other thread names, and how many threads were seen.
2. **Container:** the namespace numbers recorded with the events, if the trace has them. If they differ from the host's, the process runs in a container. It also lists other processes in the same container.
3. **Threads:** the threads (thread ID, or TID, plus thread name) that waited longest for a CPU.

`wake_graph.py` counts which processes wake the victim, and which ones it wakes. When one process sends data to another on the same machine, the kernel often wakes the receiver while running as the sender. So the pairs hint at who talks to whom. A wakeup can also come from a timer, a lock, or an interrupt (shown as pid 0). Use it as a hint, not as proof. The baseline slice shows the normal pattern, because during the fault the victim does less.

How to name the victim in your report. Use the most specific thing you have, in this order:

1. **A service name,** but only if you have a list from the platform that maps PIDs or containers to service names. The kernel trace never holds service or container names.
2. **Process name and PID,** for example "process `<name>`, PID `<pid>`". Always include this.
3. **The threads that suffered most,** by TID and thread name, if one kind of thread stands out. For example, all request-handling threads.
4. **The container,** as "in a container (`pid_ns=<n>`)", if the namespace numbers were recorded.
5. **Who it talks to,** for example "called by process `<name>`, and calls a process with `<name>` threads", from `wake_graph.py`.

**Next:** Step 10.

### Step 10. Write the RCA statement

**Goal:** a short statement that another person can check.

Template:

> From **[start]** to **[end]** (UTC), **[victim, as named in Step 9]** was starved of CPU because **[mechanism]**. We know because of **[evidence 1]**, **[evidence 2]**, and **[evidence 3]**. We ruled out **[other causes]** because **[reason]**. We did not check **[what was not tested]**.

Rules:

- Name the victim, the time window, and the mechanism.
- Give at least two independent pieces of evidence. For a cap: the long waits for the CPU (Step 5), the rhythm (Step 6), and the flat per-period ceiling (Step 6b).
- Mark each claim **Measured** (seen in the trace) or **Inferred** (reasoned from what you saw).
- The size of the cap is always **Inferred** (Step 8).
- Say what you did not test.

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects one cause: a CPU cap on one service. If a step points to another cause, it stops and tells you so. It does not diagnose that other cause.
- It cannot read the quota or the period settings. It infers them from their effects.
- It cannot give the service name. That needs a list from the platform that ran the system.
- It needs scheduling events. A trace without `sched_switch` cannot be used.
- It needs a normal stretch to compare with: in the same trace, or a healthy trace of the same system.
- It samples 10-second slices, so a fault shorter than a few seconds can be missed.
- If tracing was limited to some processes, you cannot rule out a busy machine.
- The rhythm rules of thumb (quiet buckets above 50%, repeat score above 0.5) come from one solved case and are weak for bursty victims that idle between spells of work - that is why Step 6b exists. The ceiling check was validated on runs with known limits and read each one correctly.
- A cgroup cap covers a process tree, so several suffering processes in one container are one victim group (Step 4), not host overload.

---

## Part 6. References

How the CPU limit works:

1. Linux kernel documentation, *CFS Bandwidth Control* (quota, period, throttling). https://docs.kernel.org/5.16/scheduler/sched-bwc.html
2. Linux kernel documentation, *Control Group v2* (`cpu.max` and `cpu.stat`). https://docs.kernel.org/admin-guide/cgroup-v2.html

Real cases of CPU limits causing latency:

3. Indeed Engineering, *Unthrottled: Fixing CPU Limits in the Cloud* (2019). https://engineering.indeedblog.com/blog/2019/12/unthrottled-fixing-cpu-limits-in-the-cloud/
4. Linux kernel patch, *sched/fair: Fix low cpu usage with high throttling by removing expiration of cpu-local slices* (2019). https://lkml.iu.edu/hypermail/linux/kernel/1911.1/03669.html
5. Red Hat, *CFS quotas can lead to unnecessary throttling in OpenShift Container Platform*. https://access.redhat.com/node/5285071

The method, finding waits in kernel traces:

6. F. Giraldeau and M. Dagenais, *Wait analysis of distributed systems using kernel tracing*, IEEE Transactions on Parallel and Distributed Systems, 27(8), 2450–2461, 2016. https://publications.polymtl.ca/3078/
7. B. Gregg, *Off-CPU Analysis*. https://brendangregg.com/offcpuanalysis.html
8. B. Gregg, *System Performance Analysis Methodologies* (includes thread state analysis), EuroBSDcon 2017. https://www.brendangregg.com/Slides/EuroBSDcon2017_SystemMethodology.pdf

The tools and the trace format:

9. LTTng documentation. https://lttng.org/docs/
10. Babeltrace 2, `source.ctf.fs` component (reading CTF traces, including index files). https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What the index files hold

You do not need this to follow the steps. It explains what `idx_summary.py`, `idx_dump.py` and `idx_slice.py` read.

Each channel data file has a matching file in `index/` with the same name plus `.idx`. The index is a table of contents. It holds no events. It says where each **packet** sits in the data file and what time it covers.

A packet is one block of events from one CPU. A packet is closed when it is full, unless the tracer was set to also close packets on a timer (the "switch timer"). So a busy CPU fills packets faster. That is why the data rate in Step 2 follows how busy the machine was.

Each row has these fields:

| Field | Meaning | Used for |
|---|---|---|
| `offset` | Byte position of the packet in the data file | Cutting a time window fast |
| `packet_size` | Size of the packet (stored in bits) | Same |
| `content_size` | The part of the packet that holds events (stored in bits) | The data rate in Step 2 |
| `timestamp_begin` | When the packet was opened, in trace clock units | Trace start, data rate, finding the window |
| `timestamp_end` | When the packet was closed | Trace end, data rate |
| `events_discarded` | Events lost. Any non-zero value means events were lost | Lost-events check |
| `stream_id` | Stream number | Not used |
| `stream_instance_id` | Stream instance number | Not used |
| `packet_seq_num` | Packet counter. Goes up by 1 | Missing-packet check |

The index cannot tell you which process or which event is inside a packet. For that, the packet must be decoded with `babeltrace2`.

To see every row of one index file:

```bash
python3 $TOOLS/idx_dump.py $TRACE <channel file name> 1000 | less -S
```

## Appendix B. One solved case

This is how one investigation went. The numbers are deliberately described in rough terms: read your own slices by comparison with your own baseline, not against this story. PIDs, times and sizes will differ in your trace.

- **Trace:** many CPUs, a few minutes, no lost events.
- **Step 2:** the data rate fell to a fraction of its level for a long stretch, then came back.
- **Step 3:** in every slice inside the window, one service process was at the top, with hundreds of waits of 50 ms or more per 10 s and single waits several times longer still. In the slices before and after, no process had any wait of 50 ms or more.
- **Step 5:** the victim's `run` fell to a small fraction of a core and its `wait` rose to many threads. `D` stayed at zero.
- **Step 6:** fault slice: mostly quiet buckets, a strong repeat at one fixed period. Baseline: few quiet buckets, no repeat.
- **Step 7:** other processes' longest waits stayed in the low milliseconds. The victim's `run` sat at the same small value in every slice inside the window: a flat ceiling.
- **Step 8:** the ceiling divided by the period gave the cap in cores (Inferred).
- **Check afterwards:** the estimate matched the real limit that had been set.
