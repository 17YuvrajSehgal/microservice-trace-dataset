<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: packets of one sender leave out of order

| | |
|---|---|
| Problem class | Network (path) |
| Root cause this blueprint confirms or rejects | The path after one sender delivers its packets in another order, so TCP sees the signs of loss with nothing lost. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** One service's answers got slower and it resends data, but no packet is dropped anywhere.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

A packet from a container is seen on its own interface and again on the next hop. `pkt_order.py` counts data segments that
reach an interface for the first time after a later segment of the same connection.

| | this fault | normal |
|---|---|---|
| late data segments in 20 s | **165-199 of 15,677-16,430 (1.0-1.2%)** | 0-2 |
| segments sent more than once | 56-69 | |

The share is small because most answers are one segment long, and one segment cannot be out of order.

Problems that look similar:

- Packet loss (blueprints 5 and 7): segments are sent twice and none arrives late; resends are not counted as late.
- A constant delay (blueprint 51) or a rate limit (blueprint 32): the order is kept.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `pkt_order.py` | Late data segments per sender and interface; the verdict | `pkt_order.py <fault_slice> <secs> [baseline_slice]` |

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
pkt_order.py $WORK/f.txt 20 $WORK/b.txt
```

One table and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads PACKETS LEAVE OUT OF ORDER | `VERDICT: PACKETS LEAVE OUT OF ORDER ...` | go to `report` Root cause **confirmed** (`net_reorder`). |
| `no` | the tool reads NO REORDERING | `VERDICT: NO REORDERING ...` | **Stop.** No sender's packets arrive out of order. Not this fault. Root cause **rejected**. |

### Report

fault_type: net_reorder. Copy the VERDICT line. Fix: remove the reordering on the path (here: `tc qdisc del` in the sender's network namespace).

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet.
- **Quiet on the other 45 runs** (at most 2 late segments).
- **The share bar was lowered after run 1** (from 2% to 0.5%); see RESULTS.
- **Not yet run on the earlier runs.**
