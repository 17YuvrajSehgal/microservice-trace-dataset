<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one service's answers became much larger with the same number of calls

| | |
|---|---|
| Problem class | Data volume (a code defect) |
| Root cause this blueprint confirms or rejects | A service returns far more data per answer than its callers need, so bytes on the network grow while calls stay the same. |
| Evidence | An LTTng kernel trace only, with `net_dev_queue` |
| Not used | Logs, metrics, spans, source code |

**When to use this.** Network traffic or a caller's memory grows with no change in request rate.

**Status.** Calibrated on its 5 v3 runs; tested on all 20 group-2 runs. One rule added after run 1. Not yet checked on the earlier 349 runs. Not run by an agent yet.

## Part 1. Background

`bytes_per_call.py` counts, per server address and port, the answers per second and the bytes per answer,
each packet once. A larger answer travels through every service in front of the source, so those rise
too, but less; the verdict names the largest rise.

| | the source (catalogue) | the front-end, edge router, port forward |
|---|---|---|
| bytes per answer | **0.4-0.5 -> 7.5-9.0 kB (17-21 times)** | about 1.5 -> 6.2 kB (about 4 times) |
| answers per second | 238-251 before, 242-247 now | unchanged |

Problems that look similar:

- Data exfiltration: many bytes to an address that is not a normal caller.
- More traffic: more calls, the same bytes per answer.
- The services in front of the source: smaller rise, listed as 'also larger'.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `bytes_per_call.py` | Answers per second and bytes per answer, per server; the verdict | `bytes_per_call.py <fault_slice> <secs> <baseline_slice>` |

`EV='net_dev_queue'`

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

### Step 3. Compare bytes per answer and answers per second, per server. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 10 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 10 $WORK/f.txt $EV
bytes_per_call.py $WORK/f.txt 10 $WORK/b.txt
```

One row per server, one VERDICT line for the largest rise, and ALSO LARGER lines.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `larger` | the tool reads ANSWERS GOT LARGER | `VERDICT: ANSWERS GOT LARGER ...` | go to `report` Root cause **confirmed** (`code_large_payload`). |
| `none` | the tool reads NO LARGER ANSWERS | `VERDICT: NO LARGER ANSWERS ...` | **Stop.** No server's answers grew. Not this fault. Root cause **rejected**. |

### Report

fault_type: code_large_payload. The server on the verdict line. Fix: return only the fields the caller needs, and
page large results. The trace cannot see which fields.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5** (17-21 times larger answers); reversed quiet.
- **Quiet on the other 15 group-2 runs.**
- **One rule added after run 1**: only the largest rise gets a verdict; the 3 services in front of the source rose about 4 times and are listed apart.
- **Not yet run on the earlier 349 runs.**
