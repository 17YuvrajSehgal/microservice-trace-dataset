<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a stream of connection attempts that are never completed (SYN flood)

| | |
|---|---|
| Problem class | Security (denial of service) |
| Root cause this blueprint confirms or rejects | Someone sends connection attempts (SYN) to one port from an address that never completes them; the server keeps answering and waiting. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service's port gets very many new connection attempts, or its listen queue is full, with few real clients more.

**Status.** Calibrated on its 5 v3 runs; tested on all 70 runs of groups 5-8. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

`half_open.py` counts, per source and server port, the connection attempts and how many the source later confirmed.
Real clients confirm almost all of theirs. The server's answers to a false address may not be sent at all (the address
cannot be resolved), so they are not needed.

| | this fault | normal |
|---|---|---|
| attempts from one source to one port in 20 s | **201,280-205,360 (about 10,100 per second)** | at most 7,796 |
| completed | 0% | 100% |

SYN cookies stay on, so real users are hardly hurt; under tracing the front-end's p95 still rose 30-75 ms.

Problems that look similar:

- A port scan (blueprint 34): many ports, refused; here one port, never answered.
- Connection churn (blueprint 45): many attempts, all completed.
- A busy client pool: all completed.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `half_open.py` | Connection attempts per source and server port, and how many completed; the verdict | `half_open.py <fault_slice> <secs> [baseline_slice]` |

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
half_open.py $WORK/f.txt 20 $WORK/b.txt
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads CONNECTION ATTEMPTS ARE NEVER COMPLETED | `VERDICT: CONNECTION ATTEMPTS ARE NEVER COMPLETED ...` | go to `report` Root cause **confirmed** (`syn_flood`). |
| `no` | the tool reads NO HALF-OPEN FLOOD | `VERDICT: NO HALF-OPEN FLOOD ...` | **Stop.** No stream of uncompleted attempts. Not this fault. Root cause **rejected**. |

### Report

fault_type: syn_flood. Copy the VERDICT line. Fix: block the source and keep SYN cookies on.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 65 runs.**
- **The bars were set before the test and not changed**; run 1 was only looked at to see that the attempts are in the trace.
- **Not yet run on the earlier runs.**
