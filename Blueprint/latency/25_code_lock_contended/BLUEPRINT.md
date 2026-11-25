<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: requests wait inside one service, and nothing else explains it (a lock held too long)

| | |
|---|---|
| Problem class | Concurrency (a lock or a pool) |
| Root cause this blueprint confirms or rejects | Requests queue inside one service for a lock (or a pool) that is held while it does slow work, so they finish one after another. |
| Evidence | An LTTng kernel trace only, with `net_dev_queue` and the scheduling events |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service is slow, uses little CPU, its own dependencies answer quickly, and nothing is lost on the network.

**Status.** Calibrated on the 5 v3 `code_lock_contended` runs (catalogue). Checked on all 347 runs. The first step is not specific (see Measured); the second step is. Not run by an agent yet.

## Part 1. Background

Every request a service receives is, at each moment, in one of four states: on a CPU, waiting for a
core, waiting for a call it made to another service, or waiting inside the service for something the
trace cannot name (a lock, a pool, an internal queue). `inside_wait.py` counts the last one from the
transmit events (a call is timed at the server) and the scheduling events.

That count says WHERE requests wait, not WHY. On the sweep it named a service in 13 other fault
families: a CPU cap, a network delay, a blocked event loop, a slow dependency all leave requests waiting
somewhere. So `wait_cause.py` rules out the causes the other tools can see, on the same two slices.

| | this fault | `db_table_lock` | a CPU cap | a fixed network delay |
|---|---|---|---|---|
| requests waiting inside | **4.5-5.4** (catalogue) | 67.4-69.1 (`mysqld`) | named | named |
| threads waiting for a core | 0.17-0.25 | 0.01 | 7.1-15.6 | low |
| interface queue | none | none | none | yes |

Problems that look similar:

- A delay injected inside a proxy (`slow_db`): the proxy holds every query the same time. Same picture; not separated.
- A CPU limit or a busy host: the threads wait for a core (`wait_cause.py` explains it).
- A network delay or a rate limit: packets wait at an interface (`dev_delay.py`, blueprint 32).
- A blocked or overloaded single-threaded service: it uses about one whole core.
- A service that stopped answering: `unanswered.py`, blueprint 31.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `inside_wait.py` | Where requests wait, per service; the first verdict | `inside_wait.py <fault_slice> <secs> <baseline_slice>` |
| `dev_delay.py` | Packets waiting at the sender's interface | `dev_delay.py <fault_slice> <secs> <baseline_slice>` |
| `unanswered.py` | Connections with a request and no answer | `unanswered.py <fault_slice> <secs> <baseline_slice>` |
| `wait_cause.py` | Rules out the other causes; the final verdict | `wait_cause.py <inside_wait.out> <dev_delay.out> <unanswered.out>` |

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

### Step 3. Find where requests wait, then rule out the other causes. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/f.txt $EV
inside_wait.py $WORK/f.txt 20 $WORK/b.txt > $WORK/iw.out
dev_delay.py $WORK/f.txt 20 $WORK/b.txt > $WORK/dd.out
unanswered.py $WORK/f.txt 20 $WORK/b.txt > $WORK/un.out
wait_cause.py $WORK/iw.out $WORK/dd.out $WORK/un.out
```

inside_wait.py must get a baseline slice with about the same traffic: a single-threaded service always has a
standing queue, and a service with much less traffic in the baseline is NOT JUDGED. Read the last line of
wait_cause.py. If it says EXPLAINED, follow the cause it names, not this blueprint.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `inside` | wait_cause.py reads REQUESTS WAIT INSIDE THE SERVICE AND NOTHING ELSE EXPLAINS IT | `VERDICT: REQUESTS WAIT INSIDE THE SERVICE AND NOTHING ELSE EXPLAINS IT ...` | go to `report` Root cause **confirmed** (`code_lock_contended`). |
| `explained` | wait_cause.py reads THE WAIT IS EXPLAINED BY ANOTHER CAUSE | `VERDICT: THE WAIT IS EXPLAINED BY ANOTHER CAUSE ...` | **Stop.** Requests wait, but for a reason another blueprint covers (see the EXPLAINED line). Root cause **rejected**. |
| `nothing` | inside_wait.py names no service (NO REQUESTS WAITING INSIDE A SERVICE) | `VERDICT: NO REQUESTS WAITING INSIDE A SERVICE ...` | **Stop.** No service holds requests inside. Not this fault. Root cause **rejected**. |

### Report

fault_type: code_lock_contended. The service on the verdict line holds the requests. Evidence: the verdict line of
wait_cause.py and the inside_wait.py row of that service. The trace cannot name the lock; read the service's code for a
lock held across a call. Fix: release the lock before the slow call.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**, reversed comparison quiet in 5.
- **The first step is a locator.** `inside_wait.py` alone gave a positive verdict in 68 runs of 13 other families.
- **With the second step: 10 of 10 lock runs, 12 lookalike runs, 0 of 20 normal.** The 12 are `slow_db` (11, a delay injected inside the database proxy) and `anomaly_mem` (1).
- **A delay inside a proxy reads the same as a lock in it.** The tool cannot tell them apart; the program it names (a proxy) is the hint.
- **A request that never gets an answer is not counted** (see blueprint 31).
- **Bars were fitted after seeing data**: the first step's bars once after the 5 runs, the second step's after the sweep.
- **One defect in one service** (Go catalogue).
