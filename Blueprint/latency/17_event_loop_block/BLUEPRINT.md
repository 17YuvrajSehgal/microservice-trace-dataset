<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a service thread that computes and stops serving (event_loop_block)

| | |
|---|---|
| Problem class | Code defect in one service (single-threaded runtime) |
| Root cause this blueprint confirms or rejects | A request-serving thread - a Node.js event loop is the usual case - does synchronous CPU work inside a request handler: a hash, a busy wait, a tight loop. While it computes it cannot accept, read or answer anything, so the whole service stalls, including requests that never touch that code. |
| Evidence | An LTTng kernel trace only: `metadata`, the channel files, `index/` |
| Not used | Logs, metrics, request traces. (Callers' logs show timeouts; the service itself usually logs nothing) |

**When to use this.** A service stopped answering but is not down: its process is alive and its CPU use looks the same as before. Callers time out or hit their own limits. The host's total event rate drops (less network, fewer system calls) with no resource saturated.

**Status.** Calibrated on the 10 labelled Sock Shop v2 runs of the two code defects that have a runtime effect (`code_event_loop_block`, `code_serial_awaits`, 5 each; both in the front-end Node service) and checked against 47 runs of other faults and normal load (see Measured). Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, confirmed.

## Part 1. Background

A healthy serving thread alternates: a little CPU, then a system call (`read`, `write`,
`epoll_wait`, `futex`), thousands of times per second. The CPU time between two system
calls is a **syscall-free run**. It is normally far below a millisecond.

A blocked loop stays on a CPU for tens or hundreds of milliseconds without entering the
kernel once. That is the whole signature, and **CPU tables cannot see it**:

| front-end Node main thread (measured, run r1) | before | during |
|---|---|---|
| CPU use | 95% | 98% |
| system calls per second | 6,755 | 243 |
| share of time in syscall-free runs of >= 20 ms | 0.0% | 95% |
| a typical such run | none | 107 ms |

The thread was busy before and is busy now. What changed is that it stopped talking to
the kernel. The blocked loop is the SAME thread (same tid) that existed before and served.

Problems that look similar:

- Noisy neighbour / CPU anomaly (blueprint 2): `stress-ng-cpu` threads compute without system calls. A NEW process; nothing that used to serve has stopped. The tool prints a NOTE, not a verdict.
- CPU cap (blueprint 1): the service is throttled. Its threads are OFF the CPU waiting for quota; no long runs (measured: 0-6%).
- Lock contention (blueprint 11, lock family): threads sleep in `futex`. Sleeping, not computing.
- Dependency outage (blueprint 15): a container goes silent. Its threads are asleep or gone; here the thread is at ~100% CPU.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `loop_block.py` | Per thread: CPU share, system calls per second, time in long syscall-free runs, against a baseline; the verdict | `loop_block.py <slice> <secs> --baseline <base> <secs>` |
| `sched_budget.py` | Who waited for CPU meanwhile (to rule out a starved host) | `sched_budget.py <slice> <secs>` |

`LEV='sched_switch|syscall_entry_'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Find where the event rate falls, and choose a time inside the fall and a baseline time before it. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. Look for where the event rate
falls. A blocked front door makes the whole host quieter: on run r1 the host's
scheduling and system-call events fell about 8x. fault_start is a time 30-60 s after
the change, so the slice is fully inside it. base_start is in a stretch before the
change. If the rate never changes, pick the middle of the recording for fault_start
and a slice near its start for base_start. Both slices are 5 s and must lie inside
the trace.

Write down: `base_start` (start of a 5 s slice in a stretch before the event rate fell, HH:MM:SS only (no date)), `fault_start` (start of a 5 s slice 30-60 s after the event rate fell, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `rate_falls` | the event rate falls; a time inside the fall and a time before it are chosen |  | go to `measure` |
| `no_change` | the rate never changes; the middle of the recording and a time near its start are chosen |  | go to `measure` |

### Step 3. Find a thread that used to make system calls and now computes in long runs with no system call. (`measure`)

```
extract_slice.sh $TRACE <day> <fault_start> 5 $WORK/lf.txt $LEV
extract_slice.sh $TRACE <day> <base_start> 5 $WORK/lb.txt $LEV
loop_block.py $WORK/lf.txt 5 --baseline $WORK/lb.txt 5
```

loop_block.py prints one row per thread, then its verdict lines. The baseline is
required: a thread that computes without system calls is only a fault if it used to
serve. If the tool prints `NOTE: no --baseline given`, run it again with the baseline.
Keep the slices at 5 s; the healthy one holds every system call on the host (about
1.6 million lines).
After a BLOCKED LOOP verdict the tool prints a SHAPE line. Median run of ~100 ms, few
per second: one long synchronous computation per request (`event_loop_block`). Median
of a few tens of ms, many per second: short equal busy stretches repeated per request
(`serial_work`). The 60 ms line between them comes from two injected defects; report
the numbers along with the label. Copy the VERDICT line and the SHAPE line word for
word.

Write down: `culprit_thread` (the thread on the BLOCKED LOOP verdict line (comm, tid, pid, ns)), `culprit_pid` (the pid on the BLOCKED LOOP verdict line).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `blocked` | the tool reads BLOCKED LOOP for one thread (it served system calls in the baseline and now only computes) | `VERDICT: BLOCKED LOOP ...` | go to `starved_host` Root cause **confirmed**. |
| `new_process` | the tool prints a NOTE that the computing thread did not exist in the baseline (a new CPU-bound process) | `in the baseline: a new CPU-bound process ...` | **Stop.** A CPU hog, not this fault. Go to blueprint 2 (noisy neighbour). Root cause **rejected**. |
| `same_in_baseline` | the tool prints a NOTE that the thread computed the same way in the baseline (a CPU-bound job, not a change) | `a CPU-bound job, not a ...` | **Stop.** The thread was the same in the baseline. A thread that legitimately computes for long stretches from the start (batch work, a compiler) gets this NOTE. A fault already active at the start of the recording has no baseline; the tool then says only NOTE. Root cause **inconclusive**. |
| `quiet` | the tool reads NO BLOCKED LOOP and no thread is over the bar | `NO BLOCKED LOOP: the thread with the most syscall-free CPU ...` | **Stop.** Not this fault. Report the NO BLOCKED LOOP line word for word. Root cause **rejected**. |

### Step 4. Rule out a starved host (one call). The blocked thread should have a CPU and keep it. (`starved_host`)

```
extract_slice.sh $TRACE <day> <fault_start> 5 $WORK/sched.txt
sched_budget.py $WORK/sched.txt 5 <culprit_pid>
```

sched_budget.py has no verdict line; read its table. The blocked thread should show
`run` near 1.0 and little `wait`: it has a CPU and keeps it. Large `wait` across many
services is CPU pressure, a different fault. The README calls this check optional.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `has_cpu` | the blocked thread's process shows `run` near 1.0 and little `wait` |  | go to `report` |
| `cpu_pressure` | large `wait` across many services |  | **Stop.** Large `wait` across many services is CPU pressure, a different fault. Root cause **unconfirmed**. |

### Report

fault_type: `event_loop_block` or `serial_work`, as the SHAPE line says. Root cause
service: the container of the verdict's namespace (name, or `comm` + pid_ns). The culprit
is a thread: `<comm> tid T`. Victims: none, or the callers that time out. Incident window:
from where the event rate fell to where it recovers (orient step). Evidence: the verdict
line, with the baseline numbers. If the source is connected: look in that service for
synchronous CPU work on a path every request takes - a `*Sync` call, a hashing or
compression call, a `while` loop on the clock. Fix: move the computation off the serving
thread (async API, worker thread), or remove the wait.

## Part 4. Measured, and limits

- 10 / 10 labelled runs fire; 47 / 47 other runs stay quiet. Per-run lines: `RESULTS.md`.
- Margins: the fault runs spend 70-96% of the slice in long runs; the highest quiet service thread is 6% (a MongoDB connection thread under a CPU cap). The bar is 40%.
- Three other code defects (`code_lock_across_io`, `code_n_plus_one`, `code_unbounded_cache`) stay quiet here, correctly: they change nothing measurable in those runs.
- Only Node.js is covered by data. The check is per thread, so a blocked worker in a multi-threaded service would be found on that thread, but the service would keep answering on its others and the host would not go quiet. That case is not tested.
- A thread that legitimately computes for long stretches from the start (batch work, a compiler) gets a NOTE: it was the same in the baseline.
- A fault already active at the start of the recording has no baseline; the tool then says only NOTE.
