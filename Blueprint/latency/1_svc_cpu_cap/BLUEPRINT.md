<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a CPU cap on one service (svc_cpu_cap)

| | |
|---|---|
| Problem class | Latency |
| Root cause this blueprint confirms or rejects | One service (container) has a CPU limit that is too small for its work. |
| Evidence | An LTTng kernel trace only: the `metadata` file, the channel data files, and the `index/` folder. It needs `sched_switch` and `sched_waking` (or `sched_wakeup`) events |
| Not used | Logs, request traces (spans), metrics, container settings |

**When to use this.** One service is slow because its threads wait for the CPU: waits of 10 ms and 50 ms or more appear, many times per second, while its CPU use stays low and flat. Other processes are fine. The trace writes less data per second while the fault lasts.

**Status.** No sweep on all labelled runs and no `RESULTS.md`, so this blueprint has no found and no false-alarm counts. Its tools print tables and no `VERDICT:` line. The rhythm rules of thumb come from one solved case. The ceiling check was validated on runs with known limits and read each one correctly; the README does not list those runs. The evidence in this folder is `EVALUATION-on-agentic-runs.md`: one capped agentic run (0.25 core) against one uncapped baseline. As written, `sched_budget.py` showed no victim there, because it counted a thread as waiting only when `prev_state` was 0 and that kernel reports a preempted thread as 256. After the one-line fix the victim (`python3`) showed 126 waits of 50 ms or more, the longest 89 ms, and the baseline showed none. `tools/sched_budget.py` now counts 256 as waiting. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run confirmed (java pid 52884, cap inferred about 0.285 cores against 0.2 set).

## Part 1. Background

Linux enforces a CPU limit with a quota and a period (cgroup v2 `cpu.max`, for example
20000 100000 = 20 ms of CPU in every 100 ms = 0.2 cores). The container's threads use up
the quota, the kernel stops them (throttling), and they stay stopped until the next
period. A throttled thread is ready to run but not allowed to: in a kernel trace it
counts as WAITING FOR THE CPU. The trace does not record the quota. You find it from its
effects on the victim: long waits for the CPU, low and flat CPU use, a burst-and-freeze
rhythm once per period, no disk wait, while other processes are fine and the CPUs are
idle during the victim's waits.

Problems that look similar:

- Whole machine overloaded: processes in DIFFERENT containers wait at once, no idle CPUs.
- Noisy neighbor: the victim waits while one busy process holds the CPU; waits irregular.
- Too much work or garbage collection: the victim's `run` goes UP, its waits stay low.
- Slow disk: disk-type sleep (`D`) goes up. In a cap `D` stays near 0.
- Lock, network or slow dependency: threads sleep (`S`), waits for the CPU stay low.
- CPU pinning: the victim runs only on some CPUs while other CPUs are idle.
- A cgroup limit covers a whole process tree: several waiting processes in ONE container
- are one cap, not host overload.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Trace date, start, end, length, CPUs, health checks, and data written over time. Reads only the index, so it takes seconds | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one time slice (using `idx_slice.py`) and keeps only the scheduling events | `extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> <seconds> <out_file>` |
| `sched_budget.py` | Time budget per process: running, waiting, sleeping, long waits | `sched_budget.py <sched_events.txt> <slice_seconds> [pid_to_always_show]` |
| `rhythm.py` | How often a process gets the CPU, in 10 ms buckets, and whether it repeats | `rhythm.py <sched_events.txt> <pid> <slice_start HH:MM:SS> [seconds]` |
| `cpu_ceiling.py` | The victim's on-CPU time per period: a flat ceiling below the period is the direct signature of a quota | `cpu_ceiling.py <slice.txt> <victim_pid> [period_ms] [baseline_slice.txt]` |
| `cpu_hogs.py` | Who used the CPU, and who held it WHILE the victim waited. A cap leaves the CPUs idle during the waits; this proves it | `cpu_hogs.py <slice.txt> <slice_seconds> [victim_pid]` |
| `victim_info.py` | Who the victim is: PID, names, threads, container | `victim_info.py <sched_events.txt> <slice_seconds> <pid> [rows]` |
| `wake_graph.py` | Which processes wake the victim, and which ones it wakes | `wake_graph.py <sched_events.txt> <pid> [rows]` |

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`, `seq_gaps`, `file_sizes`. Next: `find_window`.

### Step 2. Find the stretch of time where the system behaved differently (the candidate window). (`find_window`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data all CPUs wrote per 10 s. More work means more events.
Look for a long stretch where the rate moves to a clearly different level, and often
comes back. The first and last rows are only partly covered: ignore them. Edges look
a few seconds wide. A change in the rate does not prove a fault: the workload can also
start, stop or change. If there is no clear change, the fault may cover the whole
trace or be too small to show here.

Write down: `window_start` (where the data rate changed, HH:MM:SS (trace_start if no clear change)), `window_end` (where it was back to normal, HH:MM:SS (trace_end if it never came back)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `window_found` | the rate moved to a different level for a long stretch |  | go to `find_victim` |
| `no_clear_change` | no clear change. Set window_start = trace_start and window_end = trace_end |  | go to `find_victim` |

### Step 3. Find the process that suffers inside the window, and decide whether there is a fault. (`find_victim`)

```
extract_slice.sh $TRACE <day> <HH:MM:SS> 10 $WORK/s_<HHMMSS>.txt
sched_budget.py $WORK/s_<HHMMSS>.txt 10
```

Cut 10 s slices: one or two before the window, three inside, one or two after. With no
clear window, spread them over the trace. You may cut several in one turn. Six to
eight slices are enough: stop slicing when one slice shows a clear victim.
sched_budget.py is sorted by waiting time. Columns: `run` = cores in use, `wait` =
threads ready with no CPU, `S` = asleep, `D` = disk-type sleep, `>=10ms` `>=50ms` =
how many single waits lasted that long, `max_ms` = the longest wait.
Normal slice: no process has waits of 50 ms or more; the longest is a few ms.
Victim: one process that jumps to the top inside the window with many waits of 10 ms
and 50 ms or more, and few or none outside it. Rule of thumb, not a fixed bar: waits
of 50 ms or more that are absent in normal slices and appear hundreds of times per
10 s are a clear sign.
Several processes suffer at once: do NOT conclude host overload yet. Run
victim_info.py on each and compare their namespaces. Same container: treat them as
one victim group and take the busiest member as the victim.

Write down: `victim_pid` (pid of the process that suffers), `base_start` (start time of a 10 s slice where everything was normal, HH:MM:SS only (no date)), `fault_start` (start time of a 10 s slice inside the window, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `one_victim` | one process has many long waits inside the window and few or none outside |  | go to `compare_budget` |
| `victim_group` | several processes suffer and they are in the same container |  | go to `compare_budget` |
| `weak_candidate` | the waits look small but one process is a candidate. A mild cap throttles only a few dozen times, so the ceiling check must decide. Give the candidate as victim_pid |  | go to `ceiling` |
| `no_starvation_rate_changed` | the rate changed but no process has long waits |  | **Stop.** No CPU starvation found. The rate change is probably a change in the workload. Root cause **rejected**. |
| `no_starvation` | nothing changed and no slice shows long waits |  | **Stop.** No CPU starvation found. This blueprint does not look for other kinds of faults. Root cause **rejected**. |
| `machine_overloaded` | processes in different containers wait at once and there are no idle CPUs |  | **Stop.** The whole machine is short of CPU. That is not a cap on one service. Root cause **rejected**. |

### Step 4. Show what the victim's threads were doing before and during the fault, and rule out the common other causes. (`compare_budget`)

```
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/baseline_slice.txt
extract_slice.sh $TRACE <day> <fault_start> 10 $WORK/fault_slice.txt
sched_budget.py $WORK/baseline_slice.txt 10 <victim_pid>
sched_budget.py $WORK/fault_slice.txt 10 <victim_pid>
```

Compare the victim's row in the two slices. If slices for these two times already
exist in $WORK from an earlier step you may use them.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `starved` | `wait` and the long-wait counts jump, while `run` stays low or falls |  | go to `ceiling` |
| `small_waits` | the waits look small but the candidate remains; only the ceiling check can decide |  | go to `ceiling` |
| `busier` | `run` goes up a lot and `wait` stays small |  | **Stop.** The victim is busy, not starved. This is not a cap. Root cause **rejected**. |
| `disk` | `D` goes up a lot |  | **Stop.** The victim waits on the disk. This is not a cap. Root cause **rejected**. |
| `sleeping` | `S` goes up a lot while `wait` stays low |  | **Stop.** The victim waits on locks, the network or another service. This is not a cap. Root cause **rejected**. |
| `competition` | the waits are many but short (a few ms, no 50 ms freezes) while the machine is busy |  | **Stop.** Slowed by CPU competition, not a quota. Hand the case to the noisy-neighbor blueprint. Root cause **rejected**. |

### Step 5. Tell a CPU cap apart from other CPU starvation. A cap makes the victim run in short bursts at a fixed period, under a per-period ceiling. (`ceiling`)

```
rhythm.py $WORK/fault_slice.txt <victim_pid> <fault_start> 1.0
rhythm.py $WORK/baseline_slice.txt <victim_pid> <base_start> 1.0
cpu_ceiling.py $WORK/fault_slice.txt <victim_pid> <period_ms> $WORK/baseline_slice.txt
```

rhythm.py: `quiet buckets` and the `repeat` period with a score from -1 to 1. Cap, as
a rule of thumb: quiet buckets above 50% and a repeat score above 0.5 in the fault
slice, low in the baseline. The repeat period is the quota period; do not assume
100 ms. No beat does not reject a cap: a victim that idles between spells of work
shows little beat. Use 100 for the period then.
cpu_ceiling.py is the decisive check: the victim's on-CPU ms per period, the
busy-period ceiling, how far it sits below the period, and how far it collapsed from
the baseline. Do not require a flat line: a multi-threaded or bursty victim shows a
low but variable ceiling. cap_cores = ceiling / period, an estimate.

Write down: `period_ms` (the quota period (from the rhythm, or 100 if none was found)), `ceiling_ms` (the victim's busy-period on-CPU time per period in the fault slice), `cap_cores` (ceiling_ms / period_ms. Always an estimate (Inferred)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `ceiling_below_period` | the busy-period ceiling sits well below the period and collapsed against the baseline, and the victim was waiting |  | go to `rule_out` |
| `full_period` | the ceiling is at the full period |  | **Stop.** The victim saturates one core. A cap of one full core cannot be told apart from this. Root cause **inconclusive**. |
| `not_waiting` | per-period use is low but the victim is not waiting runnable |  | **Stop.** The victim simply had little work. Not a cap. Root cause **rejected**. |
| `no_signature` | starved, but no sub-period ceiling and no beat |  | **Stop.** Starved of CPU, but no quota signature. See the look-alikes for a likely cause. Root cause **inconclusive**. |

### Step 6. Check the look-alike causes. The check that settles it is who held the CPUs while the victim waited. (`rule_out`)

```
cpu_hogs.py $WORK/fault_slice.txt 10 <victim_pid>
```

cpu_hogs.py says where every CPU-second went while the victim had a thread ready and
waiting. Cap: idle is a large share; nobody took the CPU, the kernel refused the
victim. One name or one group takes most of it and idle is small: a noisy neighbor.
Also check, from what you already have: other processes have no long waits; the
victim's `D` is near 0; its `run` is lower or flat in the fault slice; its `run` is
about the same in every slice inside the window.

Write down: `idle_share` (share of the CPU time that was idle while the victim waited).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `cpus_idle` | idle is a large share while the victim waits and the other checks look like a cap |  | go to `identify` Root cause **confirmed**. |
| `lookalike_open` | idle is large but one of the other checks does not look like a cap. Say which one; the cap is unconfirmed |  | go to `identify` Root cause **unconfirmed**. |
| `neighbor` | one name or one group takes most of the CPU and idle is small |  | **Stop.** A noisy neighbor, not a cap. Hand the case to the noisy-neighbor blueprint. Root cause **rejected**. |

### Step 7. Describe the victim as precisely as the trace allows. (`identify`)

```
victim_info.py $WORK/fault_slice.txt 10 <victim_pid>
wake_graph.py $WORK/fault_slice.txt <victim_pid>
```

victim_info.py: pid, program name, thread names, namespace numbers (a container when
they differ from the host's), and the threads that waited longest. wake_graph.py: who
wakes the victim and whom it wakes; a hint about who talks to whom, not proof. The
kernel trace never holds service or container names.

Write down: `victim_name` (program name of the victim).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `identified` | the victim is named |  | go to `report` |

### Report

Name the victim, the time window and the mechanism. Give at least two independent pieces
of evidence. Mark each claim Measured (seen in the trace) or Inferred (reasoned from what
was seen). The size of the cap is always Inferred. Say what was not tested.
The kernel trace never holds the configured quota, so the cap is always found from its
effects; that alone is not a reason to doubt the verdict. A tool call that failed because
of wrong arguments is not evidence for or against anything.

## Part 4. Measured, and limits

- It confirms or rejects one cause: a CPU cap on one service. If a step points to another cause, it stops and tells you so. It does not diagnose that other cause.
- It cannot read the quota or the period settings. It infers them from their effects.
- It cannot give the service name. That needs a list from the platform that ran the system.
- It needs scheduling events. A trace without `sched_switch` cannot be used.
- It needs a normal stretch to compare with: in the same trace, or a healthy trace of the same system.
- It samples 10-second slices, so a fault shorter than a few seconds can be missed.
- If tracing was limited to some processes, you cannot rule out a busy machine.
- The rhythm rules of thumb (quiet buckets above 50%, repeat score above 0.5) come from one solved case and are weak for bursty victims that idle between spells of work - that is why Step 6b exists. The ceiling check was validated on runs with known limits and read each one correctly.
- A cgroup cap covers a process tree, so several suffering processes in one container are one victim group (Step 4), not host overload.
- On agentic runs (`EVALUATION-on-agentic-runs.md`): the agent is idle about 84% of the run (blocked on the model), so the whole-run average of `run` (0.09) is diluted and does not read near the quota. Slice to the active burst, where `run` approaches the cap.
- On the same run `cpu.stat` (not used by this blueprint) gave `nr_throttled = 208` and `throttled_usec = 20.1 s`. The preempt-coded waits recover about half of the 20 s as visible per-thread wait: enough to diagnose, but `cpu.stat` is the only exact total.
