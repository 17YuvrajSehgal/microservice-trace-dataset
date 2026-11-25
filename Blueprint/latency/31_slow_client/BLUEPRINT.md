<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: slow clients hold a service's worker threads (thread pool exhaustion)

| | |
|---|---|
| Problem class | Concurrency (a pool) |
| Root cause this blueprint confirms or rejects | Many connections send a request body very slowly; each holds one worker thread, so the service has no thread left for normal requests. |
| Evidence | An LTTng kernel trace only, with `net_dev_queue` |
| Not used | Logs, metrics, spans, source code |

**When to use this.** A service stops answering while its process is alive, logs nothing and its dependencies are fine.

**Status.** Calibrated on the 5 v3 `slow_client` runs (carts, 220 slow connections, 200 worker threads). Checked on all 347 runs. Not run by an agent yet.

## Part 1. Background

`unanswered.py` counts, per server address and port, connections on which the client sent data and the
server sent nothing for 5 s or more. A service that stopped answering has many. When most of them keep
sending segments of 16 bytes or less at a slow, steady pace, the clients are what holds the threads.

`inside_wait.py` cannot see this fault: a request that never gets an answer has no end (0 of 5).

Problems that look similar:

- A service whose dependency is frozen: it does not answer either, but no client trickles (`dependency_outage`).
- A blocked event loop: it does not answer, and it uses one whole core (`code_event_loop_block`).
- A service waiting for a full upstream: the edge router and the load generator also show as callers.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `unanswered.py` | Connections with a request and no answer, per server; the verdict | `unanswered.py <fault_slice> <secs> <baseline_slice>` |

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

### Step 3. Find a service with many unanswered connections, and whether the clients trickle. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/b.txt $EV
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/f.txt $EV
unanswered.py $WORK/f.txt 20 $WORK/b.txt
```

A table per server, ALSO NOT ANSWERING lines for callers that wait on others, and VERDICT lines. Only a verdict
that contains SLOW CLIENTS is this fault; without it the service stopped answering for another reason.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `slow` | the tool reads SERVICE DOES NOT ANSWER with a SLOW CLIENTS clause | `SLOW CLIENTS: ...` | go to `report` Root cause **confirmed** (`slow_client`). |
| `silent_other` | the tool reads SERVICE DOES NOT ANSWER without a SLOW CLIENTS clause | `VERDICT: SERVICE DOES NOT ANSWER: ...` | **Stop.** The service stopped answering, but not because of slow clients. Find what it waits for. Root cause **rejected**. |
| `answers` | the tool reads NO SERVICE THAT DOES NOT ANSWER | `VERDICT: NO SERVICE THAT DOES NOT ANSWER ...` | **Stop.** Every service answers. Not this fault. Root cause **rejected**. |

### Report

fault_type: slow_client. The service on the verdict line, and the client address that trickles. Fix: a read
timeout for request bodies on that service, or a limit per client address.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**, one verdict each; reversed quiet.
- **The SLOW CLIENTS clause: 0 of 342 other runs.** The plain 'does not answer' verdict: 17 other runs, all real outages.
- **One change after the first pass**: callers that wait on the silent service are reported separately.
- **A second fix after the sweep check**: a connection is answered if ANY interface shows server data.
