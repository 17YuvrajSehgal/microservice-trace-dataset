<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: every packet of one sender waits one fixed time

| | |
|---|---|
| Problem class | Network (path) |
| Root cause this blueprint confirms or rejects | Every packet a service sends waits the same fixed time at its own interface: a longer path, with no loss and no jitter. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** One service and its callers got slower by a steady amount, with no resends and no errors.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

`dev_delay.py` (from blueprint 32) measures how long a packet waits between its sender's interface and the next hop.

| | this fault | normal |
|---|---|---|
| wait at the sender's interface | **20 ms median and 20 ms p95** | 0.01 ms |
| packets measured in 20 s | 32,170-33,571 | |
| the tool's KIND | A FIXED DELAY | |

The service's own answer time rises too (span p50 1.5 to 43 ms): the delay also sits on its calls to its database.

Problems that look similar:

- A rate limit (blueprint 32): the same verdict with KIND 'a rate limit or a full queue'; the wait varies.
- Reordering (blueprint 46): only part of the packets wait, and the tool stays quiet.
- Delay with loss (blueprint 5): packets are also sent again.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `dev_delay.py` | Wait at the sender's interface per sending address; the verdict and its KIND | `dev_delay.py <fault_slice> <secs> [baseline_slice]` |

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
dev_delay.py $WORK/f.txt 20 $WORK/b.txt
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads PACKETS WAIT AT THE SENDER'S INTERFACE | `VERDICT: PACKETS WAIT AT THE SENDER'S INTERFACE ...` | go to `report` Root cause **confirmed** (`net_latency`). |
| `no` | the tool reads NO PACKETS WAITING AT A SENDER'S INTERFACE | `VERDICT: NO PACKETS WAITING AT A SENDER'S INTERFACE ...` | **Stop.** No sender's packets wait at its interface. Not this fault. Root cause **rejected**. |

### Report

fault_type: net_latency. Copy the VERDICT line. Fix: remove the delay on the path (here: `tc qdisc del` in the sender's network namespace). Confirm the KIND reads A FIXED DELAY.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**, each with KIND: A FIXED DELAY; reversed quiet.
- **Quiet on the other 45 runs**, including the 5 `net_reorder` runs.
- **The tool is unchanged from blueprint 32.** Nothing was fitted to this family.
- **Not yet run on the earlier runs.**
