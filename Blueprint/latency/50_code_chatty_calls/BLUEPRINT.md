<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a caller makes several calls where one would do, and slows the callee

| | |
|---|---|
| Problem class | Code defect (call pattern) |
| Root cause this blueprint confirms or rejects | A service makes extra identical calls to another service for each request it receives; the callee gets several times the load and its answers slow down. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** One service's request rate multiplied with no more users, and its answers got slower at the same time.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

`call_fanout.py` divides the calls a client makes to each server by the requests the client itself received. With `--slower-ok`
it also gives a verdict when that number at least doubles AND the answers get slower.

| | this fault | the same pair before |
|---|---|---|
| calls to the catalogue per request received | **2.1-2.3** | 0.6 |
| calls per second to the catalogue | 551-606 | 219-234 |
| time per answer | 14.76-17.02 ms | 1.81-1.93 ms |

Problems that look similar:

- N+1 queries (blueprint 23): calls per request rise and the answers are NOT slower; that is the tool's rule without the flag.
- A retry storm: a slow server that is called again would give the same line. We have no such runs, so the tool says 'either the extra calls slow the server, or a slow server is being called again'. Check which came first.
- More users: calls per second rise, calls per request do not.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `call_fanout.py` | Calls per received request to each dependency, and the answer time; the verdict | `call_fanout.py <fault_slice> <secs> [baseline_slice] [--slower-ok]` |

`EV='net_dev_queue'`

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
call_fanout.py $WORK/f.txt 20 $WORK/b.txt --slower-ok
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads MORE CALLS PER REQUEST AND SLOWER ANSWERS | `VERDICT: MORE CALLS PER REQUEST AND SLOWER ANSWERS ...` | go to `report` Root cause **confirmed** (`code_chatty_calls`). |
| `no` | the tool reads NO CALL AMPLIFICATION | `VERDICT: NO CALL AMPLIFICATION ...` | **Stop.** Calls per received request did not double. Not this fault. Root cause **rejected**. |

### Report

fault_type: code_chatty_calls. Copy the VERDICT line. Fix: make one call per request and reuse its answer.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 45 runs** (largest rise 1.21 times).
- **The `--slower-ok` rule was added after run 1**; see RESULTS. Without the flag the tool is unchanged, so blueprint 23's results hold.
- **Not tested against a retry storm** (no such runs).
- **Not yet run on the earlier runs.**
