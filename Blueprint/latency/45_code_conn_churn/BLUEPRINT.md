<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a client opens a new connection for every call

| | |
|---|---|
| Problem class | Network (connection handling) |
| Root cause this blueprint confirms or rejects | A client has keep-alive switched off: every call to a service opens a connection and closes it after one answer. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** One caller got a little slower with the same number of calls, and the callee accepts far more connections than before.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

`conn_rate.py` counts, per client and server port, the connections opened, the data segments each one carried, and how they ended.

| | this fault | the same pair before |
|---|---|---|
| connections opened per second | **151-169** | 0.1-0.3 |
| data segments from the client per connection | 1 | |
| closed normally / reset | 100% / 0% | |

Problems that look similar:

- A service that opens a database connection for most requests: here the healthy catalogue opens 50-95 per second to its database, but each carries 5 or 6 calls, so the calls bar keeps it out. It rose to 384 per second when the catalogue got four times the calls.
- A reset storm (blueprint 22): the connections end with a reset, not a normal close.
- A port scan (blueprint 34): many different ports, almost all refused.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `conn_rate.py` | Connections opened, calls per connection and how they ended, per client and server port; the verdict | `conn_rate.py <fault_slice> <secs> [baseline_slice]` |

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
conn_rate.py $WORK/f.txt 20 $WORK/b.txt
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads A NEW CONNECTION FOR EVERY CALL | `VERDICT: A NEW CONNECTION FOR EVERY CALL ...` | go to `report` Root cause **confirmed** (`code_conn_churn`). |
| `no` | the tool reads NO CONNECTION CHURN | `VERDICT: NO CONNECTION CHURN ...` | **Stop.** No client opens one connection per call. Not this fault. Root cause **rejected**. |

### Report

fault_type: code_conn_churn. Copy the VERDICT line. Fix: keep connections alive and reuse them; do not send `Connection: close`.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 45 runs.**
- **Not yet run on the earlier runs.**
