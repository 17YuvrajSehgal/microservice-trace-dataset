<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: packets wait at one container's interface (a rate limit, or a fixed delay)

| | |
|---|---|
| Problem class | Network (a queue on one interface) |
| Root cause this blueprint confirms or rejects | One container's interface holds its outgoing packets: a rate limit when it sends more than the limit, or a fixed delay on every packet. |
| Evidence | An LTTng kernel trace only, with `net_dev_queue` |
| Not used | Logs, metrics, spans, source code |

**When to use this.** One service is slower for its callers while its CPU, its threads and its dependencies look normal.

**Status.** Calibrated on the 5 v3 `net_bandwidth` runs (catalogue limited to 2 Mbit/s). Checked on all 347 runs. The rate-or-delay rule was set after the sweep. Not run by an agent yet.

## Part 1. Background

A packet is queued on the sender's interface and then on the next interface. `dev_delay.py` measures the
time between the two sightings, per sender. Normally it is about 0.01 ms.

How the wait is spread tells the kind:

| | rate limit (this fault) | fixed delay (`svc_net`, `anomaly_net`) |
|---|---|---|
| median wait | 62-76 ms | 78-81 ms or 149-153 ms |
| p95 / median | **4.5-5.3** | **1.4-1.6** |

Problems that look similar:

- A fixed delay with jitter (netem): every packet waits about the same time.
- A slow receiver: the sender's packets leave at once; the wait is elsewhere.
- A busy service: packets leave as soon as they are written.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `dev_delay.py` | Wait at the sender's interface, per sender; verdict and kind | `dev_delay.py <fault_slice> <secs> <baseline_slice>` |

`EV='net_dev_queue|sched_switch|sched_waking|sched_wakeup'`

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

### Step 3. Measure how long each sender's packets wait at its own interface. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/f.txt $EV
dev_delay.py $WORK/f.txt 20 $WORK/b.txt
```

One row per sender and one VERDICT line per sender that waits; its KIND part says rate limit or fixed delay.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `limit` | the verdict's KIND is A RATE LIMIT OR A FULL QUEUE | `KIND: A RATE LIMIT OR A FULL QUEUE ...` | go to `report` Root cause **confirmed** (`net_bandwidth`). |
| `delay` | the verdict's KIND is A FIXED DELAY | `KIND: A FIXED DELAY ...` | **Stop.** A fixed delay on that interface, not a rate limit (network impairment, see the netem blueprints). Root cause **rejected**. |
| `none` | the tool reads NO PACKETS WAITING AT A SENDER'S INTERFACE | `VERDICT: NO PACKETS WAITING AT A SENDER'S INTERFACE ...` | **Stop.** No interface holds packets. Not this fault. Root cause **rejected**. |

### Report

fault_type: net_bandwidth. The sender on the verdict line; the limit is about what it sent. Fix: raise or remove
the rate limit on that interface.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5** on the first try; reversed quiet.
- **Other runs with a wait at an interface: 21**, all faults that put a delay queue on an interface (`svc_net` 10, `anomaly_net` 11). The KIND rule separates them: p95/median 1.4-1.6 there, 4.5-5.3 here.
- **The KIND bars were chosen after seeing those numbers**, from the sweep's verdict lines.
- **0 of 20 normal runs.**
