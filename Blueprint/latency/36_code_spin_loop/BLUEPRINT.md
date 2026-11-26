<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: threads of one service stay on the CPU without system calls (a busy-wait)

| | |
|---|---|
| Problem class | CPU (a code defect) |
| Root cause this blueprint confirms or rejects | A busy-wait or hot loop in a multi-threaded service: many threads spin on the CPU for a few milliseconds each, requests are slower but still served. |
| Evidence | An LTTng kernel trace only, with `sched_switch` and the system-call entries |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service uses more CPU and answers slower, with nothing failing and its dependencies fine.

**Status.** Calibrated on its 5 v3 runs; tested on all 20 group-2 runs. Not yet checked on the earlier 349 runs. Not run by an agent yet.

## Part 1. Background

A normal service thread runs a little and then asks the kernel for something (read a socket, write an answer,
wait). `cpu_runs.py` cuts each thread's time on a CPU at every system call and keeps the pieces of 5 ms or more
("stretches"). A busy-wait, a heavy computation or a backtracking regular expression shows as stretches.

| | `code_spin_loop` | `code_regex_backtrack` |
|---|---|---|
| container | catalogue (Go, many threads) | front-end (Node, one thread) |
| cores in stretches | 0.38-0.43 (0.00 before) | 0.09-0.13 (0.00 before) |
| threads with stretches | 12-13 | one (91-100% of the long ones) |
| median stretch | 10-11 ms | stalls of 100 ms or more: 3-4 per 10 s, longest 289-431 ms |

Problems that look similar:

- A blocked event loop (`code_event_loop_block`): the same thread, but EVERY request blocks it, not a few.
- A CPU-heavy service under normal load: stretches in the baseline too (the MongoDB carts-db spends 0.85-1.47 cores in stretches in every slice).
- A CPU cap: threads wait for a core instead (blueprint 33's tool).

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `cpu_runs.py` | On-CPU stretches with no system call, per container; verdict and kind | `cpu_runs.py <baseline_slice> <fault_slice> <secs>` |

`EV='sched_switch|syscall_entry_'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a suspect time and a baseline time, 10 s each. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. If you were given a suspect time, take a slice that
starts 40 s after it, and a baseline slice that starts 30 s before it. If not, take the stretch where the
rate changes and a stretch before it with the same traffic. Both slices are 10 s.

Write down: `fault_time` (start of the 10 s suspect slice, HH:MM:SS), `base_time` (start of the 10 s baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Find a container whose threads stay on the CPU without a system call, and how. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 10 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 10 $WORK/f.txt $EV
cpu_runs.py $WORK/b.txt $WORK/f.txt 10
```

One row per container and one VERDICT line with a KIND part. The KIND part decides between this blueprint and its pair.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `this` | the verdict's KIND is MANY THREADS, SHORT STRETCHES | `KIND: MANY THREADS, SHORT STRETCHES ...` | go to `report` Root cause **confirmed** (`code_spin_loop`). |
| `other` | the verdict's KIND is ONE THREAD, LONG STALLS | `KIND: ONE THREAD, LONG STALLS ...` | **Stop.** Stretches on the CPU, but of the other kind. See the other CPU blueprint (spin loop or regular expression). Root cause **rejected**. |
| `none` | the tool reads NO LONG CPU STRETCHES | `VERDICT: NO LONG CPU STRETCHES ...` | **Stop.** No container stays on the CPU without system calls. Not this fault. Root cause **rejected**. |

### Report

fault_type: code_spin_loop. The container on the verdict line. Evidence: the verdict line. Fix: wait on an event or a
timer instead of spinning. The trace cannot name the function; a CPU profile of that service can.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**, KIND right in 5; reversed quiet.
- **Quiet on the other 10 group-2 runs** (it fires on the 5 regex runs with the other KIND, by design).
- **Not yet run on the earlier 349 runs.** A busy service that is CPU-heavy in normal operation would need its own baseline to be judged.
- **It sees the absence of system calls, not user code**: a page fault or an interrupt inside a stretch is not seen.
