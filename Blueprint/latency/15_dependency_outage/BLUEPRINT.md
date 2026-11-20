<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a service that stopped running (dependency_outage)

| | |
|---|---|
| Problem class | Availability (a dependency is down or frozen) |
| Root cause this blueprint confirms or rejects | One container's processes stop being scheduled at all: paused (`docker pause`, a cgroup freezer, `SIGSTOP`), or dead. Its callers then wait on connections that never answer, time out and retry, so they slow down too. |
| Evidence | An LTTng kernel trace with the container context (`pid_ns`) |
| Not used | Logs (they would show the timeouts), request traces (they would point at the callee) |

**When to use this.** Requests fail or time out; several services slow at once; nothing burns CPU, disk or network. The question is: who went quiet?

**Status.** Calibrated on the 5 labelled Sock Shop v2 `dependency_outage` runs (`payment` paused with `docker pause` for 120 s). It also covers `queue_backlog` (the queue consumer paused the same way). Checked on all 304 v2 runs of both applications: the two decisive steps together find 15 of 15 frozen containers with 0 false alarms. The silence check alone is not enough: it fires on 80 other runs, so the freeze-moment check is required. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run confirmed, one run of another fault rejected.

## Part 1. Background

Every running thread produces kernel events (it is scheduled in and out, it makes system
calls). A **paused** container's threads are never scheduled, so **no event at all
carries its namespace**. That silence is the signature: measured on run r1, the paused
`payment` service went from 3,441 events in 10 s to **exactly 0**, while its callers fell
to about half.

Silence is not proof. A service with no traffic is silent, and so is a helper that ended.
A freeze has a moment: the kernel makes every thread of the container run once so that it
can park itself, also the threads that had been asleep.

The tools also tell "paused" from "died": a dead container shows `sched_process_exit`
events first (and, if it restarts, new `exec`s).

Problems that look similar:

- A crash: the namespace's processes exit (`sched_process_exit`), maybe restart.
- fd_exhaustion (blueprint 12): EMFILE errors, then a restart loop; errors and restarts, not silence.
- deadlock (blueprint 14): the process still produces events; some threads stuck in futex.
- Slow dependency (blueprint 3): the callee is busy and answers late; active, not silent.
- A service with no traffic: low rate before and after; the bar needs 20 events/s before.
- A service whose rate only falls (for example one that is short of CPU): slower, not silent.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `ns_silence.py` | Events per second per namespace, baseline vs fault; exits, forks, execs; the verdict | `ns_silence.py <base> <secs> <fault> <secs>` |
| `freeze_moment.py` | Confirms a freeze: every thread of the namespace scheduled out at one moment | `freeze_moment.py <sched_slice> <secs> [--ns PID_NS]` |
| `sched_budget.py` | The callers' sleep and wait (who is affected) | `sched_budget.py <slice> <secs>` |

`SEV='sched_switch|sched_waking|sched_wakeup|sched_process_|syscall_'`

`FRZ='sched_switch|sched_process_exit'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find where the event rate drops and stays down, and choose a quiet baseline time and a time inside the drop. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. Look for the row where the rate
drops and stays down. base_start is a time before the drop where the rate is normal.
fault_start is a few seconds AFTER the drop, so the slice lies fully inside the
outage. If base_start or fault_start already came with the case, check them against
the table and keep them if they fit. If there is no drop, choose an early and a late
time anyway: the silence check decides.

Write down: `base_start` (start of a 10 s slice where everything was normal, HH:MM:SS only (no date)), `fault_start` (start of a 10 s slice a few seconds AFTER the rate dropped, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `drop_found` | the rate drops and stays down |  | go to `silence` |
| `no_drop` | no clear drop; two times were chosen anyway |  | go to `silence` |

### Step 3. Find the container (pid namespace) that went from active to silent between the two slices. (`silence`)

```
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/b.txt $SEV
extract_slice.sh $TRACE <day> <fault_start> 10 $WORK/f.txt $SEV
ns_silence.py $WORK/b.txt 10 $WORK/f.txt 10
```

ns_silence.py prints events per second per namespace in both slices and one verdict
line. The verdict names the silent namespace and the namespaces whose rate fell by
half or more (its callers). A namespace whose rate only falls is slower, not silent.

Write down: `silent_ns` (the pid namespace number on the ns_silence.py verdict line).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `frozen` | the tool reads SERVICE FROZEN (a namespace went to 0 events with no process exit) | `VERDICT: SERVICE FROZEN ...` | go to `freeze_moment` |
| `gone` | the tool reads SERVICE GONE (the namespace went silent and its processes exited) | `VERDICT: SERVICE GONE ...` | **Stop.** The dependency's processes exited (crashed or killed). An outage, but not a freeze. This outcome was not calibrated on labelled runs. Root cause **unconfirmed**. |
| `none` | the tool reads NO SILENT SERVICE | `NO SILENT SERVICE ...` | **Stop.** No container went silent. Not this fault. Root cause **rejected**. |

### Step 4. Confirm the freeze. Silence alone fired on 80 runs of other faults; a real freeze has one moment where every thread of the container is scheduled out. (`freeze_moment`)

```
extract_slice.sh $TRACE <day> <base_start> <seconds from base_start to the end of the fault slice> $WORK/s.txt $FRZ
freeze_moment.py $WORK/s.txt <the same seconds> --ns <silent_ns>
```

The scheduling slice must start at the baseline slice and end after the fault slice,
so that it contains the moment. Give the namespace from the silence step with --ns:
run on every namespace, the tool called an idle helper frozen in 3 runs.

Write down: `frozen_at` (the time on the freeze_moment.py verdict line).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `frozen_at` | the tool reads FROZEN AT (the threads were scheduled out within milliseconds and none ran again) | `VERDICT: FROZEN AT ...` | go to `report` Root cause **confirmed**. |
| `exited` | the tool reads EXITED AT (thread exits in its last second) | `VERDICT: EXITED AT ...` | **Stop.** It ended or was killed (for example by the memory limit). Not a freeze; say "crashed". Root cause **rejected**. |
| `no_moment` | the tool reads NO FREEZE MOMENT | `VERDICT: NO FREEZE MOMENT ...` | **Stop.** The namespace only went idle. Not this fault; the silence verdict is dropped. Root cause **rejected**. |

### Report

fault_type: `dependency_outage` if other services call the frozen container;
`queue_backlog` if it is a queue consumer (nobody waits for it, work piles up in the
broker). The trace names the container; which of the two it is depends on what that
container does, and the trace cannot tell them apart. Root cause: the silent container
(comm + pid_ns). List the affected callers from the silence verdict line. The incident
window starts at the freeze time. Fix: unpause or restart it; then find out who paused it
or why it stopped.

## Part 4. Measured, and limits

- Per-run lines on the labelled runs and the controls: `RESULTS.md` next to this file.
- **Full check, 17-11-2026 (all 304 runs).** `ns_silence.py` finds the frozen container in 15 of 15 runs (`dependency_outage` on both applications, `queue_backlog`). It also reports a frozen service on 80 other runs: 12 on Sock Shop and 68 on Train Ticket (idle `openresty` and `toxiproxy`, helper processes that ended between the two slices, traffic that collapsed). `freeze_moment.py` on the named namespace keeps the 15 (19-143 threads within 0.1-1.7 ms, 13-133 of them woken from sleep), calls 5 "exited" and rejects 75.
- **`freeze_moment.py` must be given the namespace from the silence step.** Run on every namespace it still calls an idle `toxiproxy` frozen in 3 Train Ticket runs (7 threads, 3-4 woken from sleep): a small Go program wakes all its threads now and then by itself.
- **The trace cannot tell `queue_backlog` from `dependency_outage`.** Accepted connections do not help (0-1 in 10 s for both; connections are kept open).
- Needs the container context (`pid_ns`). On a bare-metal box, run it per process name instead (not built yet).
- A service that idles legitimately (no traffic at all) can look silent; the bar (>= 20 events/s before) keeps quiet services out.
