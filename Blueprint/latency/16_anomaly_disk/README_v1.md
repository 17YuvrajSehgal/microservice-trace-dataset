# Blueprint: one workload saturating the disk (anomaly_disk)

| | |
|---|---|
| Problem class | Resource saturation (block I/O, host-wide) |
| Root cause this blueprint confirms or rejects | One process issues most of the host's disk requests. The device queue fills, every other process's I/O waits behind it, and processes that write (databases, logging, the tracer itself) spend time in **D state** (uninterruptible sleep, waiting for the disk) |
| Evidence | An LTTng kernel trace with `block_rq_issue` / `block_rq_complete` and `sched_switch` |
| Not used | Metrics (node disk io_time would show it), logs |

**When to use this.** Services slow down but CPU is not saturated; threads show D-state time;
the database or the logger stalls.

> **Honest status.** Calibrated on the 5 labelled Sock Shop v2 `anomaly_disk` runs (`stress-ng
> --hdd` with fsync in a co-located container, 120 s) and checked against 15 runs of other faults
> and 3 normal runs. The first version missed all 5 because the tracer's own writes were counted
> in the share; see Part 1.

---

## Part 1. Background

`block_rq_issue` names the process that queued a request; `block_rq_complete` fires when the
disk is done (matched on device + sector, so each request has a latency). A `sched_switch` with
`prev_state = 2` puts a thread in **D state**; the time until it is switched back in is time
spent waiting for I/O.

Two traps, both measured:
- **The tracer writes too.** `lttng-consumerd` issued ~1,500 requests/s in every slice, fault or
  not. Counted in the total, it pulled the culprit's share down to 47%. The tool now takes the
  share among **user-space issuers only** (kernel writeback threads and the tracer are left out).
- **Kernel writeback looks slow at baseline.** `kworker` writeback requests had a p50 latency
  of ~90 ms with nothing wrong (they are merged, batched writes). They are shown but never blamed.

Measured on run r1: `stress-ng-hdd` (a new container) issued **22,389** requests in 10 s,
**none** at baseline, spent 11.8 s/s in D state (many threads), and other writers' latency rose
from p50 **1.0 ms to 4.7 ms**.

| Lookalike | What the trace shows | How it differs |
|---|---|---|
| **disk hog (this)** | one user-space process >= 50% of user-space block requests, >= 10x baseline; others' latency and D state rise | — |
| noisy neighbour (`2`) | runnable wait (CPU), little block I/O | CPU, not disk |
| memory cap (`4`) | reclaim events; re-reads of the same pages | reclaim, not one writer |
| slow database (`3`) | the DB answers late, little extra block I/O | no request flood |

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span; where the event rate changes | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `blk_pressure.py` | Block requests and latency per issuer, D-state time per comm, baseline comparison; the verdict | `blk_pressure.py <slice> <secs> --baseline <base> <secs>` |
| `thread_top.py` | Per-thread run / wait / D, to name the victims | `thread_top.py <slice> <secs>` |

```bash
BEV='block_rq_issue|block_rq_complete|sched_switch|sched_waking|sched_wakeup'
```

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```

### Step 2. A fault slice and a quiet baseline
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $WINDOW_START 10 $WORK/df.txt "$BEV"
bash $TOOLS/extract_slice.sh $TRACE $DAY $BASE_START   10 $WORK/db.txt "$BEV"
```

### Step 3. The decisive check
```bash
python3 $TOOLS/blk_pressure.py $WORK/df.txt 10 --baseline $WORK/db.txt 10
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: DISK HOG: <comm> (ns N) issued P% of user-space block requests (R req/s, B MB/s; baseline r req/s); its D-state D s/s; other issuers' latency p50 a ms -> b ms; newly in D state: ...` | **This fault.** That process is the culprit; the latency change and the D-state list are the victims |
| `NO DISK PRESSURE (top user-space issuer ...)` | Not this fault |

### Step 4. Submit
- `fault_type`: `anomaly_disk`.
- `root_cause_service`: the container of the top issuer.
- `culprit_kind`: `container`; `victim_thread`: the processes from "newly in D state".
- `evidence`: the verdict line word for word.
- Fix: throttle that workload's I/O (cgroup `io.max`), move it to another device, or stop it.

---

## Part 4. Measured, and limits

- Per-run lines on the labelled runs and the controls: `RESULTS.md` next to this file.
- One device in our data. On a host with several disks, run the tool per `dev` (not split yet).
- A database that legitimately writes a lot (a bulk load) will also be named: the baseline
  ratio is what makes it an anomaly.
