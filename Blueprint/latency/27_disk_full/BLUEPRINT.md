<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a container's disk is full (writes fail with no space)

| | |
|---|---|
| Problem class | Resource limit (an error return) |
| Root cause this blueprint confirms or rejects | The volume of one container is full, so its writes or file growth fail with -28 and the program crashes or stops writing. |
| Evidence | An LTTng kernel trace only, with the exits of about twenty system calls |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A database or service crashes or restarts and no metric explains it.

**Status.** Calibrated on the 5 v3 `disk_full` runs (carts database on a full 1 GB volume). Checked on all 347 runs. Not run by an agent yet.

## Part 1. Background

When a limit is reached the kernel says so in the return value of one system call, in one container:
-28 no space, -99 no local port, -11 on clone the task limit, -24 too many open files. Programs get
errors all the time when nothing is wrong, so `new_errors.py` looks for an error that is NEW: 10+
failing calls in the suspect slice, at most 10% of that in the baseline. Only errors that mean a
LIMIT give a verdict; other new errors are listed without one.

Own runs: `mongod` gets -28 on 30 `fallocate` calls, 94% of its calls, 0 in the baseline - but ONLY in the slice that holds a crash.

Problems that look similar:

- A peer that is down: connects fail with -111 (refused). Listed, no verdict: the fault is at the peer.
- A program that looks for a missing file (-2). Listed, no verdict.
- A limit reached as a CONSEQUENCE of another fault: the edge router runs out of descriptors when requests hang.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `new_errors.py` | New error returns per container; the verdict | `new_errors.py <baseline_slice> <fault_slice> <secs>` |

`EV='syscall_exit_(connect|write|pwrite64|writev|pwritev|fallocate|fsync|fdatasync|ftruncate|openat|socket|accept4|accept|clone|clone3|fork|vfork|mmap|bind|sendto|sendmsg)'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a suspect time and a baseline time, 20 s each. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. If you were given a suspect time, take a slice that
starts 30 s after it, and a baseline slice that ends 20 s before it. If not, take the stretch where the rate
changes and a stretch before it with the same traffic. Both slices are 20 s and must lie inside the trace.

Write down: `fault_time` (start of the 20 s suspect slice, HH:MM:SS), `base_time` (start of the 20 s baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Find error returns that are new and mean a limit was reached. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/f.txt $EV
new_errors.py $WORK/b.txt $WORK/f.txt 20
```

A table of failing calls per container, OTHER NEW ERROR lines for new errors that are not a limit, and one
VERDICT line per limit error. If several containers hit a limit, the one with the most failing calls and
the earliest is usually the cause; check whether the others wait on it.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `limit` | the tool reads NEW ERROR RETURNS | `VERDICT: NEW ERROR RETURNS: ...` | go to `report` Root cause **confirmed** (`disk_full`). |
| `none` | the tool reads NO NEW ERROR RETURNS | `VERDICT: NO NEW ERROR RETURNS ...` | **Stop.** No container hit a limit in this slice. Not this fault, or the slice missed it (see the limits). Root cause **rejected**. |

### Report

fault_type: disk_full. The container on the verdict line, and the call and path that failed. Fix: free or grow the volume.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **5 of 5 in a slice that holds a crash; 0 of 5 between crashes.** A blueprint must scan the window, or read the logs, which name the cause at once.
- **No metric sees this fault** (verification target `expected_to_fail`).
- **0 of 20 normal runs** with the limit-only rule.
