<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: one kind of query got expensive in a database

| | |
|---|---|
| Problem class | Dependency (database work) |
| Root cause this blueprint confirms or rejects | A database answers one kind of query far more slowly than before (a missing index), while its other answers stay fast and its CPU rises. |
| Evidence | An LTTng kernel trace only |
| Not used | Logs, metrics, spans, source code |

**When to use this.** One service is slower on some requests only, its database looks healthy on average, or the database's CPU went up with no more traffic.

**Status.** Calibrated on its 5 v3 runs; tested on all 70 runs of groups 5-8. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

`slow_answers.py` times each call from a client to a server (from the client's request to the server's first answer
segment) and counts the long answers (10 ms or more). The median does not move when only one kind of query is slow,
so the tool looks at the group of long answers. With scheduler slices it adds the server's CPU: a server that WORKS
longer (an expensive query) uses more CPU; a server that WAITS (a lock, a delay) does not.

| | this fault (user-db) | the same pair before |
|---|---|---|
| answers of 10 ms or more in 20 s | **218-260 of 4,919-5,326** | 0 |
| their median | 22.8-23.9 ms | |
| median of all answers | 0.19-0.21 ms | 0.19-0.21 ms |
| user-db CPU | 0.26-0.32 cores | 0.05 cores |

In 3 of 5 runs a second verdict names the user service (KIND: THE SERVER WAITS): it waits on user-db. The root is the
verdict with KIND: THE SERVER WORKS LONGER.

Problems that look similar:

- A slow network path or a slow proxy (blueprints 3, 5, 51): EVERY answer is slower; the share and median bars keep them out.
- A load change: every answer shifts with the load; the median bar keeps it out.
- A lock in the database (blueprint 30): long answers with the server WAITING; the KIND says which.
- Full scans that were there before (issue 28: orders and carts read whole collections): long answers in the baseline too; the rise bar keeps them out.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `slow_answers.py` | Long answers per client and server, with the server's CPU; the verdict and its KIND | `slow_answers.py <fault_net> <baseline_net> <secs> [fault_sched baseline_sched sched_secs]` |

`NET='net_dev_queue'`

`SCHED='sched_switch'`

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

The last table is the trace data written per 10 s. If you were given a suspect time, take a slice that starts 40 s after it.
The baseline slice is the same length, just before the suspect time, with the same traffic. Both must lie inside the trace.

Write down: `fault_time` (start of the suspect slice, HH:MM:SS), `base_time` (start of the baseline slice, HH:MM:SS).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | both times are chosen |  | go to `measure` |

### Step 3. Time the answers of every client and server pair, with the servers' CPU. (`measure`)

```
extract_slice.sh $TRACE <day> <base_time> 20 $WORK/nb.txt $NET
extract_slice.sh $TRACE <day> <fault_time> 20 $WORK/nf.txt $NET
extract_slice.sh $TRACE <day> <base_time> 10 $WORK/sb.txt $SCHED
extract_slice.sh $TRACE <day> <fault_time> 10 $WORK/sf.txt $SCHED
slow_answers.py $WORK/nf.txt $WORK/nb.txt 20 $WORK/sf.txt $WORK/sb.txt 10
```

One table and one VERDICT line per pair that passes. If there are several, the root is the one with KIND: THE SERVER WORKS LONGER.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `works` | a line reads SOME ANSWERS ARE SLOW with KIND: THE SERVER WORKS LONGER | `VERDICT: SOME ANSWERS ARE SLOW ...` | go to `report` Root cause **confirmed** (`slow_query`). |
| `waits` | every SOME ANSWERS ARE SLOW line has KIND: THE SERVER WAITS | `VERDICT: SOME ANSWERS ARE SLOW ...` | **Stop.** Some answers are slow but the server is waiting, not working: a lock or a delay. See blueprints 25 and 30. Root cause **rejected**. |
| `none` | the tool reads NO NEW SLOW ANSWERS | `VERDICT: NO NEW SLOW ANSWERS ...` | **Stop.** No group of new slow answers. Not this fault. Root cause **rejected**. |

### Report

fault_type: slow_query. The server and client on the verdict line. Fix: find the slow statement in the database's own log or profiler and add the missing index.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**, each with KIND: THE SERVER WORKS LONGER; reversed quiet.
- **Quiet on the other 65 runs.**
- **Changed after the first 70-run test**: the server of a connection is now the side with a port below 32768 (the first version sometimes took the server for the client). Also added then: the median may rise by at most 25% (a load change had passed the first version, reversed).
- **It names the database, not the query.** The kernel trace does not carry the query text.
- **Not yet run on the earlier runs.**
