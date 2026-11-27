<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a Java service's name lookups time out

| | |
|---|---|
| Problem class | Network (name resolution) |
| Root cause this blueprint confirms or rejects | A Java service's DNS queries are lost: each lookup waits 5 s and is sent again, and requests that need the name fail or wait. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A caller of one Java service returns errors in bursts while that service's own metrics look normal.

**Status.** Calibrated on its 5 v3 runs; tested on all 50 runs of groups 5-7. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

`dns_retry.py` (from blueprint 21) finds lookups whose wait for the answer timed out and that were sent again by the same thread.

| | this fault | normal |
|---|---|---|
| lookups by the JVM in 60 s | 6-8 | |
| of those, timed out and sent again | **5-8 (83-100%)** | 0 |
| wait per timed-out lookup | 5.0 s | |

The JVM looks names up rarely (it keeps answers), so the numbers are small. The front-end returned 968 to 1,547 errors per run.

Problems that look similar:

- The same fault on a Node service (blueprint 21): many more lookups, the same verdict.
- A dependency that is down (blueprint 15): lookups work, connections fail.
- A wrong DNS answer: the lookup is fast; not covered here.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `dns_retry.py` | Lookups that timed out and were sent again, per program; the verdict | `dns_retry.py <slice> <secs>` |

`EV='syscall_entry_sendto|syscall_entry_sendmmsg|syscall_entry_poll|syscall_exit_poll|syscall_entry_close|sched_process_exec'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a suspect time and a baseline time, 60 s each. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. If you were given a suspect time, take a 60 s slice that starts at it (lookups are rare).
The baseline slice is the same length, just before the suspect time, with the same traffic. Both must lie inside the trace.

Write down: `fault_time` (start of the suspect slice, HH:MM:SS), `base_time` (start of the baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Run the tool on the suspect slice. (`measure`)

```
extract_slice.sh $TRACE <day> <fault_time> 60 $WORK/d.txt $EV
dns_retry.py $WORK/d.txt 60
```

One table and one VERDICT line naming the program.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `yes` | the tool reads NAME LOOKUPS TIME OUT | `VERDICT: NAME LOOKUPS TIME OUT ...` | go to `report` Root cause **confirmed** (`dns_delay_jvm`). |
| `no` | the tool reads NO LOOKUP TIMEOUTS | `VERDICT: NO LOOKUP TIMEOUTS ...` | **Stop.** No program's lookups time out. Not this fault. Root cause **rejected**. |

### Report

fault_type: dns_delay_jvm. Copy the VERDICT line. Fix: repair the resolver; cache answers; note that errors can go on for a while after the fix.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet (the tool takes one slice; the baseline slices are the reversed test).
- **Quiet on the other 45 runs** (at most 1 timed-out lookup of 95).
- **The tool is unchanged from blueprint 21.** Nothing was fitted to this family.
- **Errors continue into the recovery window in 4 of 5 runs**; do not read that window as healthy.
- **Not yet run on the earlier runs.**
