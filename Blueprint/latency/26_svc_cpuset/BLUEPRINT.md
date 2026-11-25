<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one container runs on far fewer CPUs than before (cpuset too small)

| | |
|---|---|
| Problem class | CPU (a placement limit) |
| Root cause this blueprint confirms or rejects | The CPUs one container may use were cut down, so its threads queue for the few cores left while the other cores are idle. |
| Evidence | An LTTng kernel trace only, with the scheduling events |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service is slower and its CPU use is flat or lower, while the host has idle cores.

**Status.** Calibrated on the 5 v3 `svc_cpuset` runs (carts confined to one core). Checked on all 347 runs: one false alarm. Not run by an agent yet.

## Part 1. Background

`cpu_confine.py` finds, per container, the fewest CPUs that carry 99% of its CPU time, in a baseline
slice and in the suspect slice. A confined container ran on many CPUs before and on few now, and its
threads wait for a core while other cores are idle.

| | this fault | a CPU quota (`svc_cpu_cap`) | a low CPU weight (`cpu_weight`) |
|---|---|---|---|
| CPUs it runs on | **12 before, 1 now** | all | all |
| other cores | idle | idle | busy |

Problems that look similar:

- A CPU quota: the container runs on all CPUs, in bursts of a 100 ms period.
- A low CPU weight on a busy host: all CPUs, and no core is idle (the `cpu_weight` blueprint).
- A single-threaded program: one CPU by nature; it needs 8+ threads and 4+ CPUs before to be judged.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `cpu_confine.py` | CPUs used per container, before and now; the verdict | `cpu_confine.py <baseline_slice> <fault_slice> <secs>` |

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

### Step 3. Count the CPUs each container runs on, before and now. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/f.txt $EV
cpu_confine.py $WORK/b.txt $WORK/f.txt 20
```

One row per container with 8+ threads and 0.2+ cores in both slices, and one VERDICT line.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `confined` | the tool reads CONTAINER CONFINED TO FEW CPUS | `VERDICT: CONTAINER CONFINED TO FEW CPUS ...` | go to `report` Root cause **confirmed** (`svc_cpuset`). |
| `free` | the tool reads NO CONTAINER CONFINED TO FEW CPUS | `VERDICT: NO CONTAINER CONFINED TO FEW CPUS ...` | **Stop.** No container lost CPUs. Not this fault. Root cause **rejected**. |

### Report

fault_type: svc_cpuset. The container on the verdict line. Evidence: the verdict line (CPUs before and now, CPU
wait, idle share of the other CPUs). Fix: widen its cpuset (docker update --cpuset-cpus).

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5** on the first try; reversed quiet in 5.
- **1 false alarm in 342 other runs**: one `code_event_loop_block` run, where the blocked Node process ran on few CPUs.
- **A container that uses little CPU is not judged** (0.2 cores, 8 threads).
