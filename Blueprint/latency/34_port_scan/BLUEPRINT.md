<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one address tries very many ports (a port scan from inside the stack)

| | |
|---|---|
| Problem class | Security (reconnaissance) |
| Root cause this blueprint confirms or rejects | One container's address tries to connect to hundreds of different ports on many hosts, almost all refused: a scan from a compromised service. |
| Evidence | An LTTng kernel trace only, with `net_dev_queue` |
| Not used | Logs, metrics, spans, source code |

**When to use this.** Nothing is slow and nothing fails, but someone asks whether a service is probing its neighbours.

**Status.** Calibrated on the 5 v3 `port_scan` runs. Tested on those and on 15 other v3 slices; not yet on the 347 sweep runs. Not run by an agent yet.

## Part 1. Background

A service talks to a few peers on a few ports, again and again. A scan is the opposite: one source,
hundreds of different destination ports, each tried once, almost all refused. `scan_fanout.py` counts,
per source address, the different (address, port) pairs it tried (SYN packets) and how many were reset.

No metric, log or span shows it (measured): it uses no CPU and moves no data.

Problems that look similar:

- A busy client opening many connections: many attempts, but to the same one or two ports.
- A service whose peer is down: refused connects, but to one port.
- Health checks: many hosts, one port each.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `scan_fanout.py` | Different targets tried per source address; the verdict | `scan_fanout.py <fault_slice> <secs> <baseline_slice>` |

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

### Step 3. Count the different targets each source address tries. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/f.txt $EV
scan_fanout.py $WORK/f.txt 20 $WORK/b.txt
```

One row per source and one VERDICT line. The scanner here runs in the front-end's network namespace from the
host, so the address is the front-end's while the program name is the scanner's: go by the address.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `scan` | the tool reads ONE SOURCE TRIES MANY PORTS | `VERDICT: ONE SOURCE TRIES MANY PORTS ...` | go to `report` Root cause **confirmed** (`port_scan`). |
| `none` | the tool reads NO SOURCE TRIES MANY PORTS | `VERDICT: NO SOURCE TRIES MANY PORTS ...` | **Stop.** No address fans out over many ports. Not this fault. Root cause **rejected**. |

### Report

fault_type: port_scan. The address on the verdict line and the program that sent the packets. Treat that
service as compromised.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**, 3,904-3,910 pairs on 262 ports; reversed quiet; quiet on 15 other v3 slices.
- **Not yet run on the 347 sweep runs** (needs a SLURM job).
- **`new_errors.py` gives no verdict for it** (refused connects are not a limit).
