# Blueprint: finding a noisy neighbor from a kernel trace

| | |
|---|---|
| Problem class | Latency |
| Root cause this blueprint confirms or rejects | Another workload on the same machine is eating the CPU, and the victim waits for it |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder |
| Also allowed | The list of event types the trace holds (read from `metadata`), and the event rules you turned on when you recorded the trace, if you know them |
| Not used | Logs, request traces (spans), metrics, container settings |

**How to use this blueprint.** Read Part 1 once, to learn what the fault is and what it looks like. Then do the steps in Part 4 in order. Each step says what to run, how to read the output, and which step comes next. Some steps can end the investigation. If a step tells you to stop, write down what you found and stop.

---

## Part 1. Background

### 1.1 What the fault is

A machine is shared. Another workload on it (a co-tenant container, a batch job, a backup, a runaway script) starts using a lot of CPU. Your service now has to compete for cores it used to get at once. It is ready to run, but the scheduler keeps picking the other workload too.

The other workload is called the **aggressor** (or the noisy neighbor). Your service is the **victim**. Nobody set a limit, and nothing is broken in the victim itself. The machine is simply full, and the fullness has a name.

Two things make this different from a CPU cap:

1. **There is an aggressor.** Someone else is on the CPU during the victim's waits. Under a cap, nobody is - the kernel just refuses the victim, and the CPU often sits idle.
2. **There is no rhythm.** A cap throttles on a fixed period. A neighbor takes the CPU whenever it runs, so the victim's waits are irregular.

The kernel trace does not record who "should" get the CPU. You find the aggressor from who actually got it.

### 1.2 What it looks like in a kernel trace

For the victim:

- **Many waits for the CPU, mostly short and irregular.** Each wait is a few milliseconds — the scheduler does share — but there are hundreds of them per second, and they add up. This is different from a cap, where single waits run to 50 ms and more.
- **`run` drops but does not go to a flat ceiling.** The victim gets whatever is left over, which varies moment to moment.

For the machine:

- **The CPUs are busy, not idle.** This is the opposite of a cap.
- **One process, or one group of processes with the same name, takes a clearly visible share of CPU time — and it is NEW.** That is the aggressor. In a heavy case it dominates the machine. In a subtle case its share is modest (15–25% on a big machine), and what gives it away is that it was absent before the waits began and arrived exactly when they did.
- **The trace often writes MORE data per second** when the aggressor arrives, because the machine is doing more work. (Under a cap it writes less.)

### 1.3 Problems that look similar

Several causes make a process wait for the CPU. This blueprint must tell them apart. You will use this table in Step 7.

| Cause                              | What the kernel trace shows                                                                                                                          | How it differs from a neighbor                                       |
|------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| **Noisy neighbor (this fault)** | Victim waits often and irregularly; a NEW process or named group is on the CPU, arriving with the waits; idle does not dominate during the waits | — |
| CPU cap on the victim              | Victim's single waits are long (50 ms+), repeat at a fixed period, and the CPU is largely IDLE during them; on-CPU per period sits at a flat ceiling | A neighbor needs a busy aggressor; a cap needs nobody                |
| Whole machine overloaded           | Many unrelated processes wait AND no single group dominates the CPU                                                                                  | A neighbor is one nameable group; overload is everybody              |
| The victim is just doing more work | Victim `run` goes **up**, its waits stay low                                                                                                         | With a neighbor, the victim's `run` goes down                        |
| Slow disk                          | Disk-type sleep (`D`) goes up                                                                                                                        | With a neighbor, `D` stays near 0; the victim is ready, not sleeping |
| Lock waiting                       | Threads sleep (`S`) in a lock call; waits for the CPU stay low                                                                                       | Same: a neighbor's victim is ready, not sleeping                     |
| Slow network or dependency         | Threads sleep (`S`); waits for the CPU stay low                                                                                                      | Same: a neighbor's victim is ready, not sleeping                     |
| CPU pinning (cpuset)               | Victim runs only on some CPUs while others are idle                                                                                                  | A neighbor's victim still runs on all CPUs, just less                |

---

## Part 2. What you need

| Input                                                                                                         | Why                                               |
|---------------------------------------------------------------------------------------------------------------|---------------------------------------------------|
| The trace folder: the `metadata` file, the channel data files (one per CPU), and `index/`                     | Everything comes from here                        |
| `sched_switch` and `sched_waking` (or `sched_wakeup`) events in the trace                                     | To measure running, waiting, and who held the CPU |
| A normal period to compare with: a normal stretch in the same trace, or a fault-free trace of the same system | Numbers only mean something when you compare them |
| `babeltrace2`, `python3`, GNU `date`                                                                          | To read the trace and run the scripts             |
| The ten scripts below, all in one folder                                                                      | To read the index, cut slices, and measure        |

The scripts:

| Script             | What it does                                                                                                               |
|--------------------|----------------------------------------------------------------------------------------------------------------------------|
| `idx_summary.py`   | Trace date, start, end, length, CPUs, health checks, and data written over time. Reads only the index, so it takes seconds |
| `idx_dump.py`      | Every field of one index file, one row per packet                                                                          |
| `idx_slice.py`     | Copies only the packets that cover a time window into a small trace                                                        |
| `extract_slice.sh` | Cuts one time slice (using `idx_slice.py`) and keeps only the scheduling events                                            |
| `sched_budget.py`  | Time budget per process: running, waiting, sleeping, long waits                                                            |
| `cpu_hogs.py`      | Who used the CPU in the slice, and who held it WHILE the victim waited. The decisive check                                 |
| `rhythm.py`        | How often a process gets the CPU, in 10 ms buckets, and whether it repeats. Used here to rule a cap OUT                    |
| `cpu_ceiling.py`   | The victim's on-CPU time per period. Used here to rule a cap OUT                                                           |
| `victim_info.py`   | Who a process is: PID, names, threads, container. Works on the aggressor too                                               |
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
ls $TOOLS/{idx_summary.py,idx_dump.py,idx_slice.py,extract_slice.sh,sched_budget.py,cpu_hogs.py,rhythm.py,cpu_ceiling.py,victim_info.py,wake_graph.py} > /dev/null && echo "all ten scripts found"
```

Both lines must print OK.

- If `metadata` is missing, `TRACE` points to the wrong folder. Look one or two levels deeper. LTTng often stores the trace in a subfolder named after the domain, for example `kernel/`.
- If `index/` is missing, the method still works, but cutting slices is slow.

---

## Part 4. Procedure

### Step 1. Check the trace

**Goal:** know when the trace starts and ends, whether it is healthy, and which events it holds.


```bash
python3 $TOOLS/idx_summary.py $TRACE > $WORK/summary.txt
cat $WORK/summary.txt

DAY=$(awk '/^date \(UTC\)/ {print $4}' $WORK/summary.txt)
TRACE_START=$(awk '/^trace start/ {print substr($4,1,8)}' $WORK/summary.txt)
TRACE_END=$(awk '/^trace end/ {print substr($4,1,8)}' $WORK/summary.txt)
echo "DAY=$DAY TRACE_START=$TRACE_START TRACE_END=$TRACE_END"

grep -a -o '"type":"event-record-class"[^{]*"name":"[^"]*"' $TRACE/metadata \
  | sed 's/.*"name":"//; s/"$//' | sort -u > $WORK/event_names.txt
grep -x -E 'sched_(switch|waking|wakeup)' $WORK/event_names.txt
```

- Read the health checks (lost events, time gaps, seq gaps, file sizes). Avoid stretches with loss, or say so in your report.
- If `sched_switch` is missing, or both `sched_waking` and `sched_wakeup` are missing, **stop**. This blueprint cannot work on this trace.

### Step 2. Find when something changed

**Goal:** find the stretch of time where the machine behaved differently. This step decodes no events, so it takes seconds.

```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```

Read it:

- With a noisy neighbor, the rate usually **rises** when the aggressor arrives — more work means more events — and falls back when it leaves. (A cap makes the rate FALL. The direction is a hint, not proof.)
- The first and last rows are only partly covered. Ignore them.
- A change in the rate does not prove a fault. The workload can also start, stop, or change. Step 4 decides.

If there is no clear change, continue to Step 3 with slices spread evenly across the trace.

```bash
WINDOW_START=<HH:MM:SS>   # first row where the rate changed (or TRACE_START)
WINDOW_END=<HH:MM:SS>     # first row where it was back to normal (or TRACE_END)
```

### Step 3. Find the victim

**Goal:** find who suffers inside the window.

Take 10-second slices: one or two before the window, two or three inside, one after. **Six to eight slices are enough** — stop as soon as the picture is clear.

```bash
SLICE_TIMES="<t1> <t2> <t3> <t4> <t5> <t6>"     # HH:MM:SS each, from Step 2
rm -f $WORK/s_*.txt
for t in $SLICE_TIMES; do
  bash $TOOLS/extract_slice.sh $TRACE $DAY $t 10 $WORK/s_$t.txt
done

for f in $WORK/s_*.txt; do
  echo "== $f"
  python3 $TOOLS/sched_budget.py "$f" 10 | head -n 8
done
```

Read it:

- In a normal slice, nobody waits much and the longest wait is a few milliseconds.
- In a slice inside the window, look at `wait`, `>=1ms`, `>=10ms` and `max_ms`. A neighbor's victims have **many** waits — hundreds of `>=1ms` per 10 s — but the single waits stay short-to-medium (often 1–20 ms). Long 50 ms+ freezes point at a cap instead; keep that in mind for Step 7.
- **Several processes waiting at once is normal here.** A busy aggressor slows everyone. You do not have to pick the one true victim yet — pick the process you care about, or the one that waits most. Write down its `pid`.
- **If the biggest waiters are many processes under ONE name, stop and think.** A CPU-hungry group large enough to fill the machine also competes with itself, so its own members top the wait table. They are the AGGRESSOR, not your victim. Pick as victim a process OUTSIDE that group — any other waiter, or the service you care about — and carry the group's name forward as the aggressor candidate for Step 5.
- The aggressor itself often shows up in this same table: high `run`, and (if it over-fills the machine) its own waits too.

```bash
VICTIM=<pid>             # the process that suffers
BASE_START=<HH:MM:SS>    # a slice time before the window
FAULT_START=<HH:MM:SS>   # a slice time inside the window
```

### Step 4. Decide whether there is a fault

Answer three questions in order.

1. **Did something change?** In Step 2, the rate moved to a new level for a long stretch.
2. **Did process wait during that stretch?** In Step 3, waits for the CPU appear inside the window and are rare outside it.
3. **Does the waiting line up with the change?** It starts and stops with the window.

Decide:

- **All three are yes:** there is CPU competition. Go to Step 5.
- **The rate changed, but nothing waits:** the workload changed, nobody suffered. Report "no CPU competition found" and **stop**.
- **Nothing changed and nothing waits:** report "no CPU competition found" and **stop**. Do not write "no fault" — this blueprint does not look for other kinds of faults.

### Step 5. Find who is eating the CPU

**Goal:** name the processes that hold the CPU in the fault window, and compare with the baseline.

```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START  10 $WORK/baseline_slice.txt
bash $TOOLS/extract_slice.sh $TRACE $DAY $FAULT_START 10 $WORK/fault_slice.txt

python3 $TOOLS/cpu_hogs.py $WORK/fault_slice.txt    10
python3 $TOOLS/cpu_hogs.py $WORK/baseline_slice.txt 10
```

The first lines say how busy the CPUs were. Then comes the hog table: CPU time per process name, with the number of processes sharing that name.

Read it:

- **A neighbor looks like this:** a name that was small (or absent) in the baseline holds a large share in the fault slice. Many processes under one name count as one group — 16 workers called `worker` are one aggressor.
- Write down the aggressor candidate's name and share.
- **Check that your baseline really is a baseline.** If the aggressor's name is busy in the baseline slice too, your baseline sits inside the fault window — the shares will look "identical" and prove nothing. Move the baseline earlier, or use a healthy trace of the same system.
- If the busy share itself did not rise, and no name stands out, there is no aggressor to find — look at the Step 7 table for what else fits.

### Step 6. The decisive check: who runs while the victim waits

**Goal:** separate neighbor, cap, and overload with one measurement.

```bash
python3 $TOOLS/cpu_hogs.py $WORK/fault_slice.txt 10 $VICTIM
```

The second part of the output says where every CPU-second went **while the victim had a thread ready and waiting**.

Read it:

- **NEIGHBOR, heavy: one name (or one group) takes most of this time, and idle is small.** That group is the aggressor. Measured on a real contended machine: the worker group took 96% and idle was 1%.
- **NEIGHBOR, subtle: a NEW group is here at a modest share.** A neighbor does not have to dominate. If the group was absent from the baseline slice (Step 5), its arrival lines up with the start of the victim's waits, and idle is not the biggest share, it is the aggressor even at 15–25%. Measured on a real subtle case: a 4-process stress group arrived, took 17% of the CPU (18% during the victim's waits), and the victim's waits rose five-fold exactly then — that IS the neighbor. Demanding dominance there misses a real fault.
- **CAP: idle is a large share.** Nobody took the CPU from the victim; a quota held it back. Measured on a real capped run: idle was 96% while the victim waited. Hand the case to the CPU-cap blueprint and **stop**.
- **OVERLOAD: many unrelated names share the time**, idle is small, no single group dominates, **and nothing new arrived with the window** — the same names were busy in the baseline, just more so. That is the whole machine being full, not one neighbor. Report it and **stop**.

```bash
AGGRESSOR=<pid or name>   # from the output; a group can be a name, e.g. "worker x16"
```

### Step 7. Rule out the lookalikes

**Goal:** check the other causes in the table in 1.3, using what you already have.

| Check                                            | Where to look                                                                                                         | A neighbor looks like this                                                                                                                                                                                                                            |
|--------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Is it really not a cap?                          | `rhythm.py` and `cpu_ceiling.py` on the victim's fault slice (commands below), read together with Step 6's idle share | No repeating beat, and the CPUs were BUSY during the waits. Careful: N equal busy threads on C cores each settle at a FLAT ~C/N of a core — fair sharing mimics a quota ceiling. A real cap also leaves the CPUs idle (Step 6); fair sharing does not |
| Is the victim just doing more work?              | Step 5, the victim's `run` in `sched_budget.py`                                                                       | Lower in the fault slice than the baseline, or flat — not higher                                                                                                                                                                                      |
| Is it the disk?                                  | `sched_budget.py`, the victim's `D`                                                                                   | Near 0 in both slices                                                                                                                                                                                                                                 |
| Is it locks or the network?                      | `sched_budget.py`, the victim's `S` against `wait`                                                                    | The waits are for the CPU (`wait`), not sleeps (`S`)                                                                                                                                                                                                  |
| Did the aggressor really arrive with the window? | Step 5: the aggressor's share in baseline against fault slice                                                         | Small or absent before, large inside                                                                                                                                                                                                                  |

```bash
python3 $TOOLS/rhythm.py      $WORK/fault_slice.txt $VICTIM $FAULT_START 1.0
python3 $TOOLS/cpu_ceiling.py $WORK/fault_slice.txt $VICTIM 100
```

Measured on the contended machine: rhythm score 0.28 (weak, no beat) and the ceiling check found busy periods varying from 5 to 48 ms with 14% flatness — no quota. On a genuinely capped run the same checks read 82–90% flatness at a fixed ceiling.

If one check does not fit, say which one in your report, and treat the neighbor as unconfirmed.

### Step 8. Describe the aggressor

**Goal:** say who the aggressor is, as precisely as the trace allows.

```bash
python3 $TOOLS/victim_info.py $WORK/fault_slice.txt 10 <aggressor_pid>
python3 $TOOLS/wake_graph.py  $WORK/fault_slice.txt <aggressor_pid>
```

- `victim_info.py` works on any pid. It gives the aggressor's program name, threads, and its container namespaces — so you can say whether the aggressor lives in a different container than the victim. **Remember: a namespace number of 0 means "could not be read", not a real namespace.**
- If the aggressor is a group (many pids, one name), run `victim_info.py` on two or three of them and check they share a container or a parent.
- `wake_graph.py` hints at who feeds the aggressor work. A batch job woken by a timer looks different from a service woken by network traffic.
- Also, useful: the aggressor's own `run` total from Step 5 — "the group used 66% of all CPU on a 4-CPU machine" is a concrete, checkable claim.

**Next:** Step 9.

### Step 9. Identify the victim

```bash
python3 $TOOLS/victim_info.py $WORK/fault_slice.txt 10 $VICTIM
python3 $TOOLS/wake_graph.py  $WORK/fault_slice.txt $VICTIM
```

Name the victim with the most specific thing you have: process name and PID always; the suffering threads if one kind stands out; the container (`pid_ns=<n>`) if recorded. The kernel trace never holds a service or container NAME — say what you saw, do not invent one.

**Next:** Step 10.

### Step 10. Write the RCA statement

Template:

> From **[start]** to **[end]** (UTC), **[victim]** was slowed by CPU competition from **[aggressor: name, pids, container]**, which held **[share]** of the machine's CPU. We know because **[evidence 1: the victim's waits]**, **[evidence 2: where the CPU went while it waited]**, and **[evidence 3: the aggressor's arrival matches the window]**. We ruled out a CPU cap because **[no rhythm, no flat ceiling, CPUs busy not idle]**. We did not check **[what was not tested]**.

Rules:

- Name the victim, the aggressor, the time window, and the share.
- Give at least two independent pieces of evidence. For a neighbor: the victim's waits (Step 3), the while-waiting attribution (Step 6), and the aggressor's arrival (Step 5).
- Mark each claim **Measured** (seen in the trace) or **Inferred** (reasoned from what you saw).
- Say what you did not test.

You are done.

---

## Part 5. Limits of this blueprint

- It confirms or rejects one cause: CPU competition from a nameable co-tenant workload. If a step points elsewhere (cap, overload, disk, locks), it stops and tells you so.
- It cannot say which workload "deserves" the CPU. The scheduler shared the machine exactly as configured; whether the aggressor is legitimate is a question for the operator, not the trace.
- It cannot give service or container names — only process names (truncated to 15 characters by the kernel) and namespace numbers.
- It needs scheduling events. A trace without `sched_switch` cannot be used.
- It needs a normal stretch to compare with, in the same trace or a healthy one of the same system.
- The shares printed by `cpu_hogs.py` depend on the slice you chose. Quote the slice with the number.
- The heavy-case numbers (96% to the aggressor, idle 1%, waits of 1–14 ms) come from one machine at 4x CPU over-subscription; the subtle-case numbers (17–18% share, five-fold wait rise) come from one 12-CPU microservice host. Use them to get a feel for the sizes, not as thresholds.
- **Arrival beats share.** A subtle neighbor's share can be small. The decisive questions are: is the group NEW, did the waits rise when it arrived, and is idle NOT the biggest share. Share size alone neither confirms nor rejects.

---

## Part 6. References

Why CPU interference between co-tenants happens, and how it is handled at scale:

1. Zhang, Tune, Hagmann, Jnagal, Gokhale, Wilkes, *CPI2: CPU performance isolation for shared compute clusters*, EuroSys 2013. https://research.google/pubs/pub40737/
2. Verma, Pedrosa, Korupolu, Oppenheimer, Tune, Wilkes, *Large-scale cluster management at Google with Borg*, EuroSys 2015. https://research.google/pubs/pub43438/
3. Linux kernel documentation, *CFS Scheduler* and *Control Group v2* (`cpu.weight` — how the scheduler splits a contended CPU). https://docs.kernel.org/admin-guide/cgroup-v2.html

The method, finding waits in kernel traces:

4. F. Giraldeau and M. Dagenais, *Wait analysis of distributed systems using kernel tracing*, IEEE TPDS 27(8), 2016. https://publications.polymtl.ca/3078/
5. B. Gregg, *Off-CPU Analysis*. https://brendangregg.com/offcpuanalysis.html

The tools and the trace format:

6. LTTng documentation. https://lttng.org/docs/
7. Babeltrace 2, `source.ctf.fs` component. https://man7.org/linux/man-pages/man7/babeltrace2-source.ctf.fs.7.html

---

## Appendix A. What the index files hold

The same as the CPU-cap blueprint's Appendix A: each channel file has an `index/*.idx` table of contents saying where each packet sits and what time it covers. `idx_summary.py` reads only this, which is why Steps 1 and 2 take seconds. The index cannot say which process is inside a packet — for that the packet must be decoded.

## Appendix B. One solved case

This is how the numbers looked in one investigation, on a 4-CPU machine where a 16-worker CPU-hungry group was started next to an interactive service. Use it to get a feel for the sizes. Do not reuse the numbers as thresholds.

- **Trace:** 4 CPUs, about 40 seconds, no lost events. The worker phase lasted 3.8 s.
- **Step 3:** inside the window, 16 processes named `ttworker` each sat at `run` 0.17–0.18 and `wait` 0.49 — waiting half their time — with 320+ waits of 1 ms or more each, and single waits up to 14 ms. No 50 ms freezes anywhere.
- **Step 5:** the hog table: `ttworker` (16 procs) held **66% of all CPU**; every other name was at 1% or less. CPU busy 68% against an idle baseline.
- **Step 6:** while the victim (`claude`, the interactive service) waited, **96% of CPU time went to `ttworker` and 1% was idle**. Clear neighbor, not a cap.
- **Step 7:** rhythm score 0.28 (no beat). Ceiling check: busy periods 5–48 ms, 14% flatness — no quota. The same checks on a genuinely capped run read 82–90% flatness, confirming the discrimination.
- **Verdict:** CPU competition from the `ttworker` group (16 pids, same parent), holding two thirds of the machine; the victim was slowed, not capped.
