<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one container waits for CPU far more than the others (a low CPU weight on a busy host)

| | |
|---|---|
| Problem class | CPU (a share) |
| Root cause this blueprint confirms or rejects | One container has a very low CPU weight on a busy host, so its threads wait for a core much longer than before while other containers do not. |
| Evidence | An LTTng kernel trace only, with the scheduling events |
| Not used | Logs, metrics, spans, source code |

**When to use this.** One service is slow on a busy host, with no CPU quota and all CPUs available to it.

**Status.** Calibrated on the 5 v3 `cpu_weight` runs (carts at weight 10, a 12-process neighbour). Bars set from the sweep's numbers; the tool itself was run only on the v3 slices. Not run by an agent yet.

## Part 1. Background

For each container `cpu_starved.py` divides the time its threads wait for a core by the time they run
(wait per core). A starved container waits several seconds for every second of work, much more than
before, while the other containers' numbers do not change.

| | this fault | a CPU quota | a small cpuset | host-wide CPU stress |
|---|---|---|---|---|
| wait per core | **10.6-19.8** | 29-31 | 1.9-2.4 | 1.2-1.6 |
| others change | **0.7-0.8 times** | | | everybody waits |

Problems that look similar:

- A CPU quota (`svc_cpu_cap` aggressive): the same picture with a higher number. Check for a 100 ms ceiling first.
- A small cpuset: lower wait per core; `cpu_confine.py` names it (blueprint 26).
- Host-wide CPU stress: every container waits more.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `cpu_starved.py` | Wait per core, per container, before and now; the verdict | `cpu_starved.py <baseline_slice> <fault_slice> <secs>` |
| `cpu_confine.py` | The scheduler reader it uses; also blueprint 26 | `cpu_confine.py <baseline_slice> <fault_slice> <secs>` |

`EV='sched_switch|sched_waking|sched_wakeup'`

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

### Step 3. Compare each container's wait for a core per second of work, before and now. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/f.txt $EV
cpu_starved.py $WORK/b.txt $WORK/f.txt 20
```

One row per container and one VERDICT line. The verdict cannot tell a low weight from a CPU quota: if the
service's CPU use sits flat at a round number of cores in bursts, it is a quota.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `starved` | the tool reads ONE CONTAINER IS STARVED OF CPU | `VERDICT: ONE CONTAINER IS STARVED OF CPU ...` | go to `report` Root cause **confirmed** (`cpu_weight`). |
| `none` | the tool reads NO CONTAINER STARVED OF CPU | `VERDICT: NO CONTAINER STARVED OF CPU ...` | **Stop.** No single container waits for CPU much more than before. Not this fault. Root cause **rejected**. |

### Report

fault_type: cpu_weight. The container on the verdict line. Evidence: its wait per core before and now, and the
others' change. Fix: give it its normal CPU weight. Check for a CPU quota before reporting.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet in 5.
- **Quiet on the 15 other v3 slices tested** (`db_table_lock`, `slow_client`, `net_bandwidth`).
- **Not yet run on the 347 sweep runs.** From the same numbers in the sweep's tables: a CPU quota (`svc_cpu_cap`, 3 aggressive runs) would fire; normal runs stay at most 1.17.
- **Its baseline is a busy host**, not comparable with the other families.
