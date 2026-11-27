<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one process opens files and does not close them

| | |
|---|---|
| Problem class | Resource leak (file descriptors) |
| Root cause this blueprint confirms or rejects | A process opens files faster than it closes them, so its descriptor count only grows. Nothing fails until the limit is reached. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service's open descriptors climb for minutes with no change in traffic; or you look for the cause before a later 'too many open files'.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

`fd_growth.py` follows each descriptor opened in the slice to its close. It counts files and sockets apart and gives a verdict for files.

| | this fault | the same process before |
|---|---|---|
| files opened in 20 s | 110-121 | |
| of those, still open at the end | **74-85 (3.7-4.2 per second)** | 0 |

No service slows down. The leak is far from the limit in one run.

Problems that look similar:

- Sockets that pile up: when a service falls behind, its connections stay open longer. In `code_chatty_calls` the catalogue had 344 more sockets open at the end of a slice. The tool lists this as OTHER GROWTH with no verdict.
- A program that opens thousands of files and closes them (cadvisor: about 8,006 opened, 68 open at the end): the share bar keeps it out.
- Descriptor exhaustion (blueprint 12): calls already fail with EMFILE; that is the end state of this fault.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `fd_growth.py` | Files and sockets opened and closed again, per process; the verdict (files only) | `fd_growth.py <baseline_slice> <fault_slice> <secs>` |

`EV='syscall_exit_openat|syscall_exit_open|syscall_exit_socket|syscall_exit_accept|syscall_exit_dup|syscall_exit_epoll_create|syscall_exit_eventfd|syscall_exit_pipe|syscall_entry_close'`

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

The last table is the trace data written per 10 s. If you were given a suspect time, take a slice that starts 40 s after it.
The baseline slice is the same length, just before the suspect time, with the same traffic. Both must lie inside the trace.

Write down: `fault_time` (start of the suspect slice, HH:MM:SS), `base_time` (start of the baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Run the tool on the two slices. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/f.txt $EV
fd_growth.py $WORK/b.txt $WORK/f.txt 20
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads FILES ARE OPENED AND NOT CLOSED | `VERDICT: FILES ARE OPENED AND NOT CLOSED ...` | go to `report` Root cause **confirmed** (`code_fd_leak`). |
| `no` | the tool reads NO FILE DESCRIPTOR GROWTH | `VERDICT: NO FILE DESCRIPTOR GROWTH ...` | **Stop.** No process keeps the files it opens. Not this fault (a socket leak is not judged by this tool). Root cause **rejected**. |

### Report

fault_type: code_fd_leak. Copy the VERDICT line. Fix: close every file you open; do not keep handles in a list that only grows.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 45 runs.**
- **The rule was changed after run 1, in four ways**; see RESULTS. Runs 2-5 were tested with the final rule.
- **A socket leak is not confirmed by this tool.** Socket growth is listed without a verdict.
- **Not yet run on the earlier runs.**
