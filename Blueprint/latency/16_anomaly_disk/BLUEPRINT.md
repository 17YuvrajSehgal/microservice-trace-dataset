<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one workload saturating the disk (anomaly_disk)

| | |
|---|---|
| Problem class | Resource saturation (block I/O, host-wide) |
| Root cause this blueprint confirms or rejects | One process issues most of the host's disk requests. The device queue fills, every other process's I/O waits behind it, and processes that write (databases, logging, the tracer itself) spend time in D state (uninterruptible sleep, waiting for the disk). |
| Evidence | An LTTng kernel trace with `block_rq_issue` / `block_rq_complete` and `sched_switch` |
| Not used | Metrics (node disk io_time would show it), logs |

**When to use this.** Services slow down but CPU is not saturated; threads show D-state time; the database or the logger stalls.

**Status.** Calibrated on the 5 labelled Sock Shop v2 `anomaly_disk` runs (`stress-ng --hdd` with fsync in a co-located container, 120 s) and checked against 15 runs of other faults and 3 normal runs. The first version missed all 5 because the tracer's own writes were counted in the share; see Background. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, confirmed on the second try; the first try cut its slice 20 s after the fault ended and rejected.

## Part 1. Background

`block_rq_issue` names the process that queued a request; `block_rq_complete` fires when
the disk is done (matched on device + sector, so each request has a latency). A
`sched_switch` with `prev_state = 2` puts a thread in **D state**; the time until it is
switched back in is time spent waiting for I/O.

Two traps, both measured:
- **The tracer writes too.** `lttng-consumerd` issued ~1,500 requests/s in every slice,
  fault or not. Counted in the total, it pulled the culprit's share down to 47%. The tool
  now takes the share among **user-space issuers only** (kernel writeback threads and the
  tracer are left out).
- **Kernel writeback looks slow at baseline.** `kworker` writeback requests had a p50
  latency of ~90 ms with nothing wrong (they are merged, batched writes). They are shown
  but never blamed.

Measured on run r1: `stress-ng-hdd` (a new container) issued **22,389** requests in 10 s,
**none** at baseline, spent 11.8 s/s in D state (many threads), and other writers'
latency rose from p50 **1.0 ms to 4.7 ms**.

This fault: one user-space process >= 50% of user-space block requests, >= 10x baseline;
others' latency and D state rise.

Problems that look similar:

- Noisy neighbour (blueprint 2): runnable wait (CPU), little block I/O. CPU, not disk.
- Memory cap (blueprint 4): reclaim events; re-reads of the same pages. Reclaim, not one writer. A memory-capped JVM that reads its own pages back issues most of the requests but hardly waits for the disk itself.
- Slow database (blueprint 3): the DB answers late, little extra block I/O. No request flood.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `blk_pressure.py` | Block requests and latency per issuer, D-state time per comm, baseline comparison; the verdict | `blk_pressure.py <slice> <secs> --baseline <base> <secs>` |
| `thread_top.py` | Per-thread run / wait / D, to name the victims | `thread_top.py <slice> <secs>` |

`BEV='block_rq_issue|block_rq_complete|sched_switch|sched_waking|sched_wakeup'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Choose a time for the fault slice and a time for a quiet baseline slice. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. It shows where the event rate
changes. window_start is the start of the fault slice. base_start is the start of a
quiet baseline slice. Both slices are 10 s and must lie inside the trace.

Write down: `window_start` (start of the 10 s fault slice, HH:MM:SS only (no date)), `base_start` (start of a 10 s quiet baseline slice, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | the two times are chosen |  | go to `pressure` |

### Step 3. Measure block requests per issuer and D-state time in the fault slice against the baseline, and read the verdict. (`pressure`)

```
extract_slice.sh $TRACE <day> <window_start> 10 $WORK/df.txt $BEV
extract_slice.sh $TRACE <day> <base_start> 10 $WORK/db.txt $BEV
blk_pressure.py $WORK/df.txt 10 --baseline $WORK/db.txt 10
```

blk_pressure.py prints one row per issuer, the time in D state per comm, and one
verdict line. On a DISK HOG line the named process is the culprit; the latency
change and the "newly in D state" list are the victims. Kernel writeback threads and
the tracer are shown but never blamed. The hog's own threads must wait on the disk
for 1 thread-second per second or more (true hogs: 11.8 to 15.9). A top issuer below
that bar gets NO DISK PRESSURE and a NOTE line. A database that legitimately writes
a lot (a bulk load) will also be named: the baseline ratio is what makes it an anomaly.

Write down: `hog_process` (the process on the verdict line (comm, ns), and the processes listed as newly in D state).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `hog` | the tool reads DISK HOG for one process | `VERDICT: DISK HOG ...` | go to `report` Root cause **confirmed**. |
| `none` | the tool reads NO DISK PRESSURE and prints no NOTE line | `NO DISK PRESSURE ...` | **Stop.** Not this fault. Root cause **rejected**. |
| `busy_no_wait` | the tool reads NO DISK PRESSURE (it issues most of the requests but hardly waits for the disk itself) and prints a NOTE line | `NOTE: a NEW busy reader that does not wait ...` | **Stop.** Not this fault. A new busy reader that does not wait is usually a process reading its own pages back under a memory limit: run blueprint 4 on that namespace. Root cause **rejected**. |

### Report

fault_type: anomaly_disk. Root cause: the container of the top issuer on the verdict
line. The victims are the processes from "newly in D state". Evidence: the verdict line
word for word. Fix: throttle that workload's I/O (cgroup `io.max`), move it to another
device, or stop it.

## Part 4. Measured, and limits

- Per-run lines on the labelled runs and the controls: `RESULTS.md` next to this file.
- **All 304 v2 runs of both applications (17-11-2026): 10 of 10, 0 false alarms in 294.**
- **The disk-wait bar was added after the Train Ticket check.** The hog's own threads must wait on the disk for 1 thread-second per second or more. True hogs: 11.8 to 15.9. Without the bar, 12 runs read DISK HOG: 11 memory-capped JVMs (0.07 to 0.14) and one host `grep` that read 97 MB/s (0.35). The first check on 25 Sock Shop runs did not include those families.
- One device in our data. On a host with several disks, run the tool per `dev` (not split yet).
- A database that legitimately writes a lot (a bulk load) will also be named: the baseline ratio is what makes it an anomaly.
