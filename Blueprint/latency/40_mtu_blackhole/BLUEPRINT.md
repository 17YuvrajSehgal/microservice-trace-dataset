<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: large packets to one service are dropped and small ones pass (an MTU black hole)

| | |
|---|---|
| Problem class | Network (packet size) |
| Root cause this blueprint confirms or rejects | A link in front of one service has a smaller MTU than the service and drops larger packets silently, so only small exchanges get through. |
| Evidence | An LTTng kernel trace only, with `net_dev_queue` |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service fails or hangs on some requests while others work, with no CPU or memory problem.

**Status.** Calibrated on its 5 v3 runs; tested on all 20 group-4 runs. The rule was changed twice after seeing the 5 runs. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

A lost packet is sent again with the same sequence number and size. `big_resends.py` counts, per path and per
interface, the segments that leave more than once, and the smallest size among them (the cut-off). An MTU black
hole resends only segments above a size; normal loss resends segments of every size, down to 5 bytes.

| | this fault, path into the catalogue | normal resends elsewhere |
|---|---|---|
| resends in 10 s | 146-149 | up to 356 |
| smallest resent segment | **596-625 bytes** | 5 bytes |
| smaller segments resent | **0%** | |

The drops show only in the FIRST seconds: after that the catalogue's circuit breaker stops it from querying its
database at all, and nothing large is sent. Take the suspect slice at the start of the fault.

Problems that look similar:

- Packet loss on a link (`svc_net`, `anomaly_net`): resends of every size.
- A service that stopped answering: no resends, silence (the slow-client blueprint).
- The service's own errors: they follow the drops (circuit breaker, 5xx), see the logs blueprint.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `big_resends.py` | Resent segments per path, the size cut-off; the verdict | `big_resends.py <fault_slice> <secs> <baseline_slice>` |

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

The last table is the trace data written per 10 s. If you were given a suspect time, take a slice that STARTS at it: the drops are in the first seconds.
The baseline slice is the same length, just before the suspect time, with the same traffic. Both must lie inside the trace.

Write down: `fault_time` (start of the suspect slice, HH:MM:SS), `base_time` (start of the baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Count resent segments per path and the size above which they are resent. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 10 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 10 $WORK/f.txt $EV
big_resends.py $WORK/f.txt 10 $WORK/b.txt
```

One row per path and one VERDICT line naming the receiving end.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `hole` | the tool reads LARGE PACKETS ARE DROPPED ON ONE PATH | `VERDICT: LARGE PACKETS ARE DROPPED ON ONE PATH ...` | go to `report` Root cause **confirmed** (`mtu_blackhole`). |
| `none` | the tool reads NO LARGE-PACKET DROPS | `VERDICT: NO LARGE-PACKET DROPS ...` | **Stop.** No path drops only large packets. Not this fault, or the slice is too late (see Background). Root cause **rejected**. |

### Report

fault_type: mtu_blackhole. The receiving address on the verdict line and the cut-off size. Fix: make the MTU the same on both sides of that link.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5** in a slice at the start of the fault; reversed quiet.
- **Quiet on the other 15 group-4 runs.**
- **0 of 5 in a slice 40 s into the fault**: the circuit breaker has stopped the traffic by then.
- **The rule was changed twice after seeing the 5 runs** (a fixed size cut-off, then a share of resent segments that swung from 37% to 78%); see RESULTS.
- **Not yet run on the earlier runs.**
