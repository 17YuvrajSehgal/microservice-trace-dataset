<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: someone else's compute on our machine (resource abuse)

| | |
|---|---|
| Problem class | Security / capacity (an unauthorised workload uses the machine) |
| Root cause this blueprint confirms or rejects | One process burns CPU and contacts something at a fixed interval (a heartbeat), the shape of a miner or a bot. |
| Evidence | An LTTng kernel trace only, with `syscall_entry_connect` and the scheduling events |
| Not used | Logs, metrics, packet contents |

**When to use this.** CPU use went up and nothing explains it; or blueprint 2 (noisy neighbour) found a CPU user and you need to know whether it is a heavy job of ours or something that reports to someone.

**Status.** Calibrated on 10 labelled `resource_abuse` runs (5 Sock Shop, 5 Train Ticket; a container hashing on one core and connecting to a local listener every 5 s) and checked on the other 292 runs of both applications. The labelled workload is a harmless simulation: only the shape is real. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, confirmed.

## Part 1. Background

A CPU-hungry intruder looks like any CPU-hungry job. Measured on the labelled runs:

- Blueprint 2's tools see the extra CPU (machine busy 64% -> 77% on one application,
  10% -> 20% on the other), but the hog is named `python3`, the same name as an existing
  process, so `cpu_hogs.py` shows an old group growing, not a new arrival.
- Nobody suffers much: the worst waiter goes from 0.70 to 1.32 s of waiting per 10 s, and
  on the 80%-idle host nothing waits at all. Blueprint 2 stops there with "no CPU
  competition".

What a batch job does not have is the **heartbeat**: a `connect()` to the same destination
every few seconds, with almost no jitter. Monitoring and connection pools are periodic too
(measured: `prometheus` every 5 s, a database pool every 10 s), but they use almost no CPU.
So the verdict needs **both in one process**:

| | resource abuse | noisy neighbour | scraper / pool keep-alive |
|---|---|---|---|
| uses half a core or more | **yes** (0.93-1.01) | yes | no (at most 0.15) |
| periodic `connect()` to one destination | **yes** (every 5.2-5.5 s, jitter 1-5%) | no | yes |

Problems that look similar:

- Noisy neighbour (blueprint 2): uses half a core or more, but has no periodic `connect()` to one destination.
- A scraper or a pool keep-alive: periodic `connect()` to one destination, but it uses almost no CPU (at most 0.15 cores).
- A legitimate worker that polls a queue every 5 s and computes in between: the same shape. The trace cannot say the workload is unauthorised.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `beacon.py` | Periodic connectors, their CPU use, the verdict | `beacon.py <connect_slice> <secs> --sched <sched_slice>` |
| `victim_info.py` | Who a pid is (blueprint 2's tool) | `victim_info.py <sched_slice> <secs> <pid>` |
| `cpu_hogs.py` | The CPU view (blueprint 2's tool) | `cpu_hogs.py <slice> <secs> [victim_pid]` |
| `sched_budget.py` | The CPU view (blueprint 2's tool) | `sched_budget.py <slice> <secs>` |

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a time inside the suspect window for the two slices. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. Pick a time inside the suspect
window. If you were given a suspect time, use it. If nothing stands out, use the
middle of the trace. The connect slice is 60 s and must lie inside the trace.

Write down: `slice_time` (start of both slices (60 s of connects, 10 s of scheduling) inside the suspect window, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `time_chosen` | a slice time is chosen |  | go to `beacon` |

### Step 3. Find one process that is both CPU-heavy and a periodic connector. (`beacon`)

```
extract_slice.sh $TRACE <day> <slice_time> 60 $WORK/conn.txt syscall_entry_connect
extract_slice.sh $TRACE <day> <slice_time> 10 $WORK/sched.txt
beacon.py $WORK/conn.txt 60 --sched $WORK/sched.txt
```

Cut the two slices at the same time. The connect slice is long (60 s) because a
heartbeat needs at least 5 beats to be called periodic. It is small: only `connect()`
calls are kept. The scheduling slice is cut with no event list (the default).
beacon.py prints a table of the periodic connectors (scrapers, pools) and one VERDICT
line. If it prints `NOTE: no --sched slice given`, run it again with `--sched`;
periodic alone is not a verdict. If the heartbeat could be slower than 12 s, cut 120 s
or more: 60 s holds fewer than 5 beats.

Write down: `abuse_pid` (the pid on the RESOURCE ABUSE SHAPE verdict line), `abuse_process` (the process on the verdict line (comm, pid, pid_ns)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `abuse_shape` | the tool reads RESOURCE ABUSE SHAPE (one process is both CPU-heavy and a periodic connector) | `VERDICT: RESOURCE ABUSE SHAPE ...` | go to `who` Root cause **confirmed**. |
| `no_beacon` | the tool reads NO BEACON FROM A CPU-HEAVY PROCESS (none of the periodic connectors uses 0.5 cores or more) | `VERDICT: NO BEACON FROM A CPU-HEAVY PROCESS ...` | **Stop.** Not this fault. The table above the verdict lists the periodic connectors (scrapers, pools). Root cause **rejected**. |

### Step 4. Say who the process is and which container it runs in. (`who`)

```
victim_info.py $WORK/sched.txt 10 <abuse_pid>
```

victim_info.py has no verdict line. Its container (`pid_ns`) is the unit to remove.
A pid_ns that no other process of the system shares is a container of its own.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `identified` | the process and its pid_ns are known |  | go to `report` |

### Report

fault_type: `resource_abuse`. Root cause: the process and container from the verdict line
(`comm`, `pid_ns`). Culprit: `comm (pid P)`. Victims: none, unless blueprint 2 showed
waiters. Incident window: from the first beat you can find (cut earlier slices to find
it) to the end of your slice. Evidence: the verdict line word for word. Fix: identify and
remove the workload; find out how it was started. The trace cannot say the workload is
unauthorised: the verdict names the shape; a person decides.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file. 10 of 10 labelled runs, 0 false alarms in 292 other runs. Largest CPU use of any periodic connector outside the labelled runs: 0.15 cores, against 0.93 for the smallest hog.
- **The trace cannot say the workload is unauthorised.** A legitimate worker that polls a queue every 5 s and computes in between has the same shape. The verdict names the shape; a person decides.
- A heartbeat over an already-open connection (no new `connect()`) is invisible to this tool.
- A hog that hides its heartbeat in another process (a helper that connects, a worker that computes) passes: the two halves must be in one pid.
- Only the aggressive setting was collected (one core, 5 s). A slower, lighter variant (15 s heartbeat, less CPU) is untested.
