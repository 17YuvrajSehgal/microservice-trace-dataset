<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a noisy neighbor (noisy_neighbor), or one workload that takes every core (anomaly_cpu)

| | |
|---|---|
| Problem class | Latency |
| Root cause this blueprint confirms or rejects | Another workload on the same machine is eating the CPU, and the victim waits for it |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder |
| Not used | Logs, request traces (spans), metrics, container settings |

**When to use this.** A service is slow because it waits for the CPU: many waits, mostly short and irregular. The CPUs are busy, not idle. The trace often writes MORE data per second when the aggressor arrives.

**Status.** `cpu_newcomer.py` was measured on all 304 v2 runs of both applications (17-11-2026, tool only). FILLS THE MACHINE: 10 of 10 `anomaly_cpu` runs and 0 of the other 294. MACHINE NOT FULL: 16 of 16 `noisy_neighbor` runs, and also 66 runs of other families, so that verdict names a newcomer; it does not name the family. The worked cases behind the other steps are one machine under heavy CPU over-subscription and one larger host with a subtle co-tenant. The decisive tool of those steps, `cpu_hogs.py`, prints tables and no verdict line. Only the aggressive setting of `anomaly_cpu` was collected. Agent (20-11-2026, graph harness, gpt-6-luna): one `anomaly_cpu` run confirmed; one `noisy_neighbor` run inconclusive (baseline and fault slice were both cut at the end of the fault).

## Part 1. Background

A machine is shared. Another workload on it (a co-tenant container, a batch job, a
backup, a runaway script) starts using a lot of CPU. Your service now has to compete for
cores it used to get at once. The other workload is the **aggressor** (the noisy
neighbor). Your service is the **victim**. Nobody set a limit, and nothing is broken in
the victim itself.

Two things make this different from a CPU cap:

1. **There is an aggressor.** Someone else is on the CPU during the victim's waits. Under
   a cap, nobody is: the kernel just refuses the victim, and the CPU often sits idle.
2. **There is no rhythm.** A cap throttles on a fixed period. A neighbor takes the CPU
   whenever it runs, so the victim's waits are irregular.

The kernel trace does not record who "should" get the CPU. You find the aggressor from
who actually got it.

For the victim: many waits for the CPU, mostly short and irregular. Each wait is a few
milliseconds, but there are hundreds of them per second. Under a cap, single waits run
to 50 ms and more. `run` drops but does not go to a flat ceiling.

For the machine: the CPUs are busy, not idle. One process, or one group of processes
with the same name, takes a clearly visible share of CPU time, and it is NEW. In a heavy
case it dominates the machine. In a subtle case its share is modest, and what gives it
away is that it was absent before the waits began and arrived exactly when they did.

Host CPU saturation (`anomaly_cpu`) is the case where an uncapped workload takes every
core: the new CPU user fills the machine and the machine is 0% idle. A capped neighbor
(`noisy_neighbor`) uses CPU but cores are still free: the cores used sit exactly on the
cap, 1.0 or 2.0.

Problems that look similar:

- CPU cap on the victim: single waits are long (50 ms+), repeat at a fixed period, and the CPU is largely IDLE during them; on-CPU per period sits at a flat ceiling. A neighbor needs a busy aggressor; a cap needs nobody.
- Whole machine overloaded: many unrelated processes wait AND no single group dominates the CPU. A neighbor is one nameable group; overload is everybody.
- The victim is just doing more work: victim `run` goes up, its waits stay low. With a neighbor, the victim's `run` goes down.
- Slow disk: disk-type sleep (`D`) goes up. With a neighbor, `D` stays near 0; the victim is ready, not sleeping.
- Lock waiting, slow network or dependency: threads sleep (`S`); waits for the CPU stay low.
- CPU pinning (cpuset): the victim runs only on some CPUs while others are idle. A neighbor's victim still runs on all CPUs, just less.
- Other faults that start a container using about one core (`anomaly_mem`, `lock_contention`, `priority_inversion`, `nagle_delayed_ack`, `resource_abuse`, a restarted JVM in `svc_mem_cap`): they also read NEW CPU USER, MACHINE NOT FULL.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks, and data written over time | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time slice and keeps only the scheduling events | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file> [events_regex]` |
| `sched_budget.py` | Time budget per process: running, waiting, sleeping, long waits | `sched_budget.py <sched_events.txt> <slice_seconds> [pid_to_always_show]` |
| `cpu_hogs.py` | Who used the CPU in the slice, and who held it WHILE the victim waited. The decisive check | `cpu_hogs.py <slice.txt> <slice_seconds> [victim_pid]` |
| `cpu_newcomer.py` | Baseline slice against fault slice: the container that used no CPU before and uses a lot now, and whether the machine is full. One verdict line | `cpu_newcomer.py <baseline_slice.txt> <fault_slice.txt> <slice_seconds>` |
| `rhythm.py` | How often a process gets the CPU, in 10 ms buckets, and whether it repeats. Used here to rule a cap OUT | `rhythm.py <sched_events.txt> <pid> <slice_start HH:MM:SS> [seconds]` |
| `cpu_ceiling.py` | The victim's on-CPU time per period. Used here to rule a cap OUT | `cpu_ceiling.py <slice.txt> <victim_pid> [period_ms] [baseline_slice.txt]` |
| `victim_info.py` | Who a process is: PID, names, threads, container. Works on the aggressor too | `victim_info.py <sched_events.txt> <slice_seconds> <pid> [rows]` |
| `wake_graph.py` | Which processes wake the victim, and which ones it wakes | `wake_graph.py <sched_events.txt> <pid> [rows]` |

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find the stretch of time where the machine behaved differently. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. With a noisy neighbor, the rate
usually rises when the aggressor arrives (more work means more events) and falls back
when it leaves. A cap makes the rate FALL. The direction is a hint, not proof.
The first and last rows are only partly covered. Ignore them.
A change in the rate does not prove a fault. The workload can also start, stop, or
change. window_start is the first row where the rate changed, window_end the first
row where it was back to normal.

Write down: `window_start` (first row where the rate changed (or trace_start), HH:MM:SS only (no date)), `window_end` (first row where it was back to normal (or trace_end), HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `window_found` | the rate changed for a stretch of time |  | go to `find_victim` |
| `no_clear_change` | no clear change. Set window_start = trace_start and window_end = trace_end, and spread the slices of the next step evenly across the trace |  | go to `find_victim` |

### Step 3. Find who suffers inside the window, and decide whether there is CPU competition. (`find_victim`)

```
extract_slice.sh $TRACE <day> <HH:MM:SS> 10 $WORK/s_<HHMMSS>.txt
sched_budget.py $WORK/s_<HHMMSS>.txt 10
```

Take 10-second slices: one or two before the window, two or three inside, one after.
Six to eight slices are enough. Stop as soon as the picture is clear.
In a normal slice, nobody waits much and the longest wait is a few milliseconds.
In a slice inside the window, look at `wait`, `>=1ms`, `>=10ms` and `max_ms`. A
neighbor's victims have many waits (hundreds of `>=1ms` per 10 s) but the single
waits stay short-to-medium (often 1-20 ms). Long 50 ms+ freezes point at a cap.
Several processes waiting at once is normal here: a busy aggressor slows everyone.
Pick the process you care about, or the one that waits most. Write down its pid.
If the biggest waiters are many processes under ONE name, they are the AGGRESSOR,
not your victim: a CPU-hungry group large enough to fill the machine also competes
with itself. Pick as victim a process OUTSIDE that group and carry the group's name
forward as the aggressor candidate.
Then answer three questions. Did something change (the rate moved to a new level
for a long stretch)? Did a process wait during that stretch (waits appear inside the
window and are rare outside it)? Does the waiting line up with the change?
Do not conclude from the census alone. These steps only locate the window and show
that something waited. They cannot tell a neighbor from a cap. `cpu_hogs.py` is the
decisive check: go to it as soon as you have one slice inside the window. A real
neighbor that drove the machine busy looks quiet until you ask where the CPU went.

Write down: `victim_pid` (pid of the process that suffers), `base_start` (a slice time before the window, HH:MM:SS only (no date)), `fault_start` (a slice time inside the window, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `competition` | all three answers are yes. There is CPU competition |  | go to `newcomer` |
| `unclear` | the waits are small or the picture is not clear, but there is one slice inside the window. Never give a verdict before cpu_hogs.py has run on a window slice |  | go to `newcomer` |
| `rate_changed_nothing_waits` | the rate changed, but nothing waits |  | **Stop.** The workload changed, nobody suffered. Report "no CPU competition found". Root cause **rejected**. |
| `nothing_changed` | nothing changed and nothing waits |  | **Stop.** Report "no CPU competition found". Do not write "no fault". This blueprint does not look for other kinds of faults. Root cause **rejected**. |

### Step 4. Name the processes that hold the CPU in the fault window, compare with the baseline, and read the one verdict line (who is new, and is the machine full). (`newcomer`)

```
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/baseline_slice.txt
extract_slice.sh $TRACE <day> <fault_start> 10 $WORK/fault_slice.txt
cpu_hogs.py $WORK/fault_slice.txt 10
cpu_hogs.py $WORK/baseline_slice.txt 10
cpu_newcomer.py $WORK/baseline_slice.txt $WORK/fault_slice.txt 10
```

cpu_hogs.py: the first lines say how busy the CPUs were. Then comes the hog table:
CPU time per process name, with the number of processes sharing that name. A
neighbor is a name that was small (or absent) in the baseline and holds a large
share in the fault slice. Many processes under one name count as one group.
Check that your baseline really is a baseline. If the aggressor's name is busy in
the baseline slice too, your baseline sits inside the fault window. Move the
baseline earlier.
cpu_newcomer.py groups CPU time by container (pid namespace; host programs by name),
compares the two slices and prints one VERDICT line. A newcomer has under 0.05
cores before and 0.5 or more now.
FILLS THE MACHINE is host CPU saturation (`anomaly_cpu`): an uncapped workload takes
every core. Report it with this line; the next step then shows what the victim lost.
MACHINE NOT FULL is what a capped neighbor looks like (`noisy_neighbor`: the cores
used sit exactly on the cap, 1.0 or 2.0). It is not proof by itself: other faults
also start a container that uses about one core. The verdict names a newcomer; it
does not name the family.

Write down: `aggressor_candidate` (name and share of the aggressor candidate from the hog table or the cpu_newcomer.py verdict line; `none` if no name stands out).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `fills_machine` | the tool reads NEW CPU USER FILLS THE MACHINE (an uncapped workload takes every core; the machine is 0% idle) | `VERDICT: NEW CPU USER FILLS THE MACHINE ...` | go to `who_runs` Root cause **confirmed** (`anomaly_cpu`). |
| `not_full` | the tool reads NEW CPU USER, MACHINE NOT FULL (a new container uses CPU but cores are still free). Not proof by itself: 16 of 16 `noisy_neighbor` runs read this, and also 66 runs of other families whose injected workload uses about one core. The next step decides | `VERDICT: NEW CPU USER, MACHINE NOT FULL ...` | go to `who_runs` Root cause **unconfirmed**. |
| `no_newcomer` | the tool reads NO NEW CPU USER. Nothing new took CPU. Check that the baseline slice is before the window. If it is, go on; the next step separates a cap and overload | `VERDICT: NO NEW CPU USER ...` | go to `who_runs` |

### Step 5. The decisive check: who runs while the victim waits. Separate neighbor, cap, and overload, and rule out the lookalikes. (`who_runs`)

```
cpu_hogs.py $WORK/fault_slice.txt 10 <victim_pid>
rhythm.py $WORK/fault_slice.txt <victim_pid> <fault_start> 1.0
cpu_ceiling.py $WORK/fault_slice.txt <victim_pid> 100
sched_budget.py $WORK/fault_slice.txt 10 <victim_pid>
sched_budget.py $WORK/baseline_slice.txt 10 <victim_pid>
```

cpu_hogs.py prints no verdict line. The second part of its output says where every
CPU-second went while the victim had a thread ready and waiting. Read that table
with the rules in the outcomes below.
Share size alone neither confirms nor rejects. A subtle neighbor's share can be
small. The decisive questions are: is the group NEW, did the waits rise when it
arrived, and is idle NOT the biggest share.
Then check the lookalikes with what you have:
- Not a cap: rhythm.py shows no repeating beat, and the CPUs were BUSY during the
  waits. Careful: N equal busy threads on C cores each settle at a FLAT ~C/N of a
  core, so fair sharing mimics a quota ceiling. A real cap also leaves the CPUs
  idle; fair sharing does not.
- Not more work: the victim's `run` in sched_budget.py is lower in the fault slice
  than the baseline, or flat, not higher.
- Not the disk: the victim's `D` is near 0 in both slices.
- Not locks or the network: the waits are for the CPU (`wait`), not sleeps (`S`).
- The aggressor arrived with the window: small or absent before, large inside.
If one check does not fit, say which one, and treat the neighbor as unconfirmed.
The shares printed by cpu_hogs.py depend on the slice you chose. Quote the slice
with the number.

Write down: `aggressor` (the aggressor, a pid or a name (a group can be a name, for example "worker x16"), with one to three of its pids).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `host_saturation` | the step before read NEW CPU USER FILLS THE MACHINE, and here that new group holds the CPU while the victim waits. This shows what the victim lost |  | go to `identify` Root cause **confirmed** (`anomaly_cpu`). |
| `neighbor_heavy` | one name (or one group) takes most of the time while the victim waits, and idle is small. That group is the aggressor. The step before did not read FILLS THE MACHINE, and the lookalike checks fit |  | go to `identify` Root cause **confirmed**. |
| `neighbor_subtle` | a NEW group is here at a modest share. It was absent from the baseline slice, its arrival lines up with the start of the victim's waits, and idle is not the biggest share. The lookalike checks fit |  | go to `identify` Root cause **confirmed**. |
| `check_does_not_fit` | the table looks like a neighbor, but one of the lookalike checks does not fit. Say which one |  | go to `identify` Root cause **unconfirmed**. |
| `cap` | idle is a large share while the victim waits. Nobody took the CPU from the victim; a quota held it back |  | **Stop.** A CPU cap, not a neighbor. Hand the case to blueprint `1_svc_cpu_cap`. Root cause **rejected**. |
| `overload` | many unrelated names share the time, idle is small, no single group dominates, and nothing new arrived with the window (the same names were busy in the baseline, just more so) |  | **Stop.** The whole machine is full, not one neighbor. Report it. Root cause **rejected**. |

### Step 6. Say who the aggressor is and who the victim is, as precisely as the trace allows. (`identify`)

```
victim_info.py $WORK/fault_slice.txt 10 <a pid of the aggressor>
wake_graph.py $WORK/fault_slice.txt <a pid of the aggressor>
victim_info.py $WORK/fault_slice.txt 10 <victim_pid>
wake_graph.py $WORK/fault_slice.txt <victim_pid>
```

victim_info.py works on any pid. It gives the program name, threads, and the
container namespaces, so you can say whether the aggressor lives in a different
container than the victim. A namespace number of 0 means "could not be read", not a
real namespace.
If the aggressor is a group (many pids, one name), run victim_info.py on two or
three of them and check they share a container or a parent.
wake_graph.py hints at who feeds the aggressor work. A batch job woken by a timer
looks different from a service woken by network traffic.
Name the victim with the most specific thing you have: process name and PID always;
the suffering threads if one kind stands out; the container (`pid_ns=<n>`) if
recorded. The kernel trace never holds a service or container NAME.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `identified` | the aggressor and the victim are described |  | go to `report` |

### Report

fault_type: `anomaly_cpu` if cpu_newcomer.py read NEW CPU USER FILLS THE MACHINE (report
it with that line). Otherwise `noisy_neighbor`.
Template: From [start] to [end] (UTC), [victim] was slowed by CPU competition from
[aggressor: name, pids, container], which held [share] of the machine's CPU. We know
because [evidence 1: the victim's waits], [evidence 2: where the CPU went while it
waited], and [evidence 3: the aggressor's arrival matches the window]. We ruled out a
CPU cap because [no rhythm, no flat ceiling, CPUs busy not idle]. We did not check
[what was not tested].
Name the victim, the aggressor, the time window, and the share. Give at least two
independent pieces of evidence. Mark each claim Measured (seen in the trace) or Inferred
(reasoned from what you saw). Say what you did not test. The trace cannot say which
workload "deserves" the CPU, and it cannot give service or container names.

## Part 4. Measured, and limits

- It confirms or rejects one cause: CPU competition from a nameable co-tenant workload. If a step points elsewhere (cap, overload, disk, locks), it stops and tells you so.
- It cannot say which workload "deserves" the CPU. The scheduler shared the machine exactly as configured; whether the aggressor is legitimate is a question for the operator, not the trace.
- It cannot give service or container names — only process names (truncated to 15 characters by the kernel) and namespace numbers.
- It needs scheduling events. A trace without `sched_switch` cannot be used.
- It needs a normal stretch to compare with, in the same trace or a healthy one of the same system.
- The shares printed by `cpu_hogs.py` depend on the slice you chose. Quote the slice with the number.
- The worked cases behind this blueprint are one machine under heavy CPU over-subscription and one larger host with a subtle co-tenant. Their exact numbers are deliberately NOT printed as thresholds: judge each slice by comparison with its own baseline, not against memorized values.
- **`cpu_newcomer.py`, measured on all 304 v2 runs of both applications** (17-11-2026, per-run lines in `RESULTS.md`). FILLS THE MACHINE: 10 of 10 `anomaly_cpu` runs (24 or 32 `stress-ng-cpu` processes, 54-61% of all cores, 0% idle) and 0 of the other 294. MACHINE NOT FULL: 16 of 16 `noisy_neighbor` runs (2 or 4 processes at exactly 1.0 or 2.0 cores), and also 66 runs of other families whose injected workload uses about one core (`anomaly_mem`, `lock_contention`, `priority_inversion`, `nagle_delayed_ack`, `resource_abuse`, a restarted JVM in `svc_mem_cap`). So the second verdict names a newcomer; it does not name the family.
- **Only the aggressive setting of `anomaly_cpu` was collected.** The recipe's subtle setting (half the cores at 50% load) would leave idle cores and read as MACHINE NOT FULL.
- **Arrival beats share.** A subtle neighbor's share can be small. The decisive questions are: is the group NEW, did the waits rise when it arrived, and is idle NOT the biggest share. Share size alone neither confirms nor rejects.
- FILLS THE MACHINE: 10 of 10, 0 false alarms in 294. The margin: the fault runs are at 0% idle with 54-61% of all cores; the closest other run has 29% of the cores and 42% idle, and the fullest other machine with a newcomer is 11% idle.
