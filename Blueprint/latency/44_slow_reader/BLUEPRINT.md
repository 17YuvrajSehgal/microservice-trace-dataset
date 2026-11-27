<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a peer reads so slowly that the sender must stop

| | |
|---|---|
| Problem class | Network (flow control) |
| Root cause this blueprint confirms or rejects | A client takes a large answer very slowly: it advertises a receive window of zero, and the service cannot send the rest. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** Connections to one service stay open for minutes and its send buffers are full, while the service is fast for everyone else.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

Every TCP segment carries the sender's receive window: how much more data it can take. A reader that does not read
advertises zero. `zero_window.py` counts those segments per reader and per server port.

| | this fault | normal |
|---|---|---|
| zero-window segments in 20 s | **800, on 200 connections** | 0 |
| the service | no change in rate or answer time | |

No metric shows this fault (the family runs with `no_metric_signature`).

Problems that look similar:

- A slow client on the SENDING side (blueprint 31): the service waits to read a request; no zero window.
- A reset carries a window of zero too: resets and connection attempts are left out.
- A delayed ACK (blueprint 20): a fixed 40 ms stall, the window stays open.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `zero_window.py` | Zero-window segments per reader and server port; the verdict | `zero_window.py <fault_slice> <secs> [baseline_slice]` |

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
zero_window.py $WORK/f.txt 20 $WORK/b.txt
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads A PEER READS TOO SLOWLY | `VERDICT: A PEER READS TOO SLOWLY ...` | go to `report` Root cause **confirmed** (`slow_reader`). |
| `no` | the tool reads NO SLOW READER | `VERDICT: NO SLOW READER ...` | **Stop.** No peer advertises a zero window. Not this fault. Root cause **rejected**. |

### Report

fault_type: slow_reader. Copy the VERDICT line. Fix: close the slow connections; set a write timeout on the service.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 45 runs**: not one zero-window segment in the 95 other slices.
- **The reader is named by address and interface, not by program.** Its address (the host's bridge) is shared by several programs. The tool adds which program was running when the stopped side sent its next data (`python3`, the slow readers); between containers on one host that is the reader, because its read opens the window.
- **Not yet run on the earlier runs.**
