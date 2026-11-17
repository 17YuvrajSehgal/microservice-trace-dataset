# Blueprint: someone else's compute on our machine (resource abuse)

| | |
|---|---|
| Problem class | Security / capacity (an unauthorised workload uses the machine) |
| Root cause this blueprint confirms or rejects | One process burns CPU **and** contacts something at a fixed interval (a heartbeat), the shape of a miner or a bot |
| Evidence | An LTTng kernel trace only, with `syscall_entry_connect` and the scheduling events |
| Not used | Logs, metrics, packet contents |

**When to use this.** CPU use went up and nothing explains it; or blueprint 2 (noisy neighbour)
found a CPU user and you need to know whether it is a heavy job of ours or something that
reports to someone.

> **Honest status.** Calibrated on 10 labelled `resource_abuse` runs (5 Sock Shop, 5 Train
> Ticket; a container hashing on one core and connecting to a local listener every 5 s) and
> checked on the other 292 runs of both applications. The labelled workload is a harmless
> simulation: only the shape is real.

---

## Part 1. Background

A CPU-hungry intruder looks like any CPU-hungry job. Measured on the labelled runs:

- Blueprint 2's tools see the extra CPU (machine busy 64% -> 77% on one application, 10% -> 20%
  on the other), but the hog is named `python3`, the same name as an existing process, so
  `cpu_hogs.py` shows an old group growing, not a new arrival.
- Nobody suffers much: the worst waiter goes from 0.70 to 1.32 s of waiting per 10 s, and on
  the 80%-idle host nothing waits at all. Blueprint 2 stops there with "no CPU competition".

What a batch job does not have is the **heartbeat**: a `connect()` to the same destination
every few seconds, with almost no jitter. Monitoring and connection pools are periodic too
(measured: `prometheus` every 5 s, a database pool every 10 s), but they use almost no CPU.
So the verdict needs **both in one process**:

| | resource abuse | noisy neighbour | scraper / pool keep-alive |
|---|---|---|---|
| uses half a core or more | **yes** (0.93-1.01) | yes | no (at most 0.15) |
| periodic `connect()` to one destination | **yes** (every 5.2-5.5 s, jitter 1-5%) | no | yes |

---

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `beacon.py` | Periodic connectors, their CPU use, the verdict | `beacon.py <connect_slice> <secs> --sched <sched_slice>` |
| `cpu_hogs.py`, `sched_budget.py`, `victim_info.py` | The CPU view and who a pid is (blueprint 2's tools) | see blueprint 2 |

---

## Part 3. Procedure

### Step 1. Orient
```bash
python3 $TOOLS/idx_summary.py $TRACE --rate 10 | sed -n '/^data written per/,$p'
```
Pick a time inside the suspect window (`T`). If nothing stands out, use the middle of the trace.

### Step 2. Two slices at the same time
```bash
bash $TOOLS/extract_slice.sh $TRACE $DAY $T 60 $WORK/conn.txt 'syscall_entry_connect'
bash $TOOLS/extract_slice.sh $TRACE $DAY $T 10 $WORK/sched.txt
```
The connect slice is long (60 s) because a heartbeat needs at least 5 beats to be called
periodic. It is small: only `connect()` calls are kept.

### Step 3. The decisive check
```bash
python3 $TOOLS/beacon.py $WORK/conn.txt 60 --sched $WORK/sched.txt
```

| Verdict line | Meaning |
|---|---|
| `VERDICT: RESOURCE ABUSE SHAPE: <comm> (pid P, pid_ns N) uses X cores and connects to A:port every T s (n connects, jitter J%)` | **This fault.** That process is both CPU-heavy and a periodic connector |
| `VERDICT: NO BEACON FROM A CPU-HEAVY PROCESS (K periodic connectors, none uses 0.5 cores or more)` | Not this fault. The table above the verdict lists the periodic connectors (scrapers, pools) |
| `NOTE: no --sched slice given ...` | Run it again with `--sched`; periodic alone is not a verdict |

If the heartbeat could be slower than 12 s, cut 120 s or more: 60 s holds fewer than 5 beats.

### Step 4. Who is it
```bash
python3 $TOOLS/victim_info.py $WORK/sched.txt 10 <pid from the verdict>
```
Its container (`pid_ns`) is the unit to remove. A pid_ns that no other process of the system
shares is a container of its own.

### Step 5. Submit
- `fault_type`: `resource_abuse`.
- `root_cause_service`: the process and container from the verdict line (`comm`, `pid_ns`).
- `culprit_thread`: `comm (pid P)`; `victim_thread`: `none` unless Step 3 of blueprint 2 showed waiters.
- `incident_window`: from the first beat you can find (cut earlier slices to find it) to the end of your slice.
- `evidence`: the verdict line word for word.
- Fix: identify and remove the workload; find out how it was started.

---

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file. 10 of 10 labelled runs, 0 false alarms in 292
  other runs. Largest CPU use of any periodic connector outside the labelled runs: 0.15 cores,
  against 0.93 for the smallest hog.
- **The trace cannot say the workload is unauthorised.** A legitimate worker that polls a queue
  every 5 s and computes in between has the same shape. The verdict names the shape; a person
  decides.
- A heartbeat over an already-open connection (no new `connect()`) is invisible to this tool.
- A hog that hides its heartbeat in another process (a helper that connects, a worker that
  computes) passes: the two halves must be in one pid.
- Only the aggressive setting was collected (one core, 5 s). A slower, lighter variant
  (15 s heartbeat, less CPU) is untested.
