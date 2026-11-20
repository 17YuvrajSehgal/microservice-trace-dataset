<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: name lookups time out and are sent again (unreliable resolver)

| | |
|---|---|
| Problem class | Configuration / dependency (the resolver loses queries) |
| Root cause this blueprint confirms or rejects | One service's DNS queries or answers are lost; each lookup waits for a timeout and is sent again. |
| Evidence | An LTTng kernel trace only, with the `sendto`, `poll` and `close` system calls |
| Not used | Logs, metrics, packet contents |

**When to use this.** A few requests take seconds while the median and the 95th percentile look healthy; CPU, disk and network are idle; nothing reports an error.

**Status.** Calibrated on the 5 labelled Sock Shop `dns_delay` runs (60% of the front-end's queries to the resolver dropped) and checked on the other 297 runs of both applications. **Only 3 of the 5 labelled runs are a clean case** (see Measured). Train Ticket has no runs of this fault. Agent (20-11-2026, graph harness, gpt-6-luna): one labelled run, confirmed.

## Part 1. Background

A lookup by the C library resolver is a short sequence of system calls in one thread:

```
socket, bind            a fresh UDP socket
sendto (with address)   the query (two of them: A and AAAA)
poll(timeout 2500 ms)   wait for the answer
close
```

A healthy lookup takes 0.1-0.4 ms. When a query is lost, `poll` returns 0 after 2.5 s and
the **same thread sends again on the same socket**. The slowest lookups take 5.0 s. The tool
counts lookups with that timeout-then-resend.

| | this fault | a program that keeps restarting | healthy |
|---|---|---|---|
| lookups that time out and are sent again | **76-88%** | 9-13% | 0-1% |
| the program's pids in 60 s | 1 | 4-6 | 1 |

A program that restarts loses lookups while it starts, with a healthy resolver (measured on
the 5 `fd_exhaustion` runs, where the front-end crash-loops). So the tool looks at restarts
before it blames the resolver.

Problems that look similar:

- A program that keeps restarting (for example fd_exhaustion, blueprint 12): it loses 9-13% of its lookups while it starts, with a healthy resolver; it has 4-6 pids in 60 s, not 1.
- Any UDP protocol with the same send, poll, resend pattern: the destination of a `sendto` is not in the trace, so it would be counted as a lookup.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `dns_retry.py` | Lookups per program, timeouts, resends, the verdict | `dns_retry.py <slice> <secs>` |
| `victim_info.py` | Who a pid is | `victim_info.py <sched_slice> <secs> <pid>` |

`DNSEV='syscall_entry_sendto|syscall_entry_poll|syscall_exit_poll|syscall_entry_close|sched_process_exec'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick a time inside the suspect window for one 60 s slice. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

The last table is the trace data written per 10 s. Pick a time inside the suspect
window. If you were given a suspect time, use it. With this fault CPU, disk and
network are idle, so the rate may show little. The slice is 60 s and must lie inside
the trace.

Write down: `slice_time` (start of the 60 s slice inside the suspect window, HH:MM:SS only (no date)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `time_chosen` | a slice time is chosen |  | go to `lookups` |

### Step 3. Count, per program, the name lookups that time out and are sent again, and read the verdict. (`lookups`)

```
extract_slice.sh $TRACE <day> <slice_time> 60 $WORK/dns.txt $DNSEV
dns_retry.py $WORK/dns.txt 60
```

The slice must be long: lookups are rare (about one every 2 s here, because
connections are pooled). dns_retry.py prints one row per program (`lookups`,
`resent`, `gave up`, `slowest s`, `lost s`, and `pids`) and one VERDICT line. `pids`
more than one means the program restarted in the slice. A program that restarts loses
lookups while it starts, with a healthy resolver, so the tool does not blame the
resolver for it.
Only resolvers that use `sendto` with an address and wait in `poll` are seen: musl
(the Node front-end here), and glibc when it does not connect first. Go and Java
resolve differently and are not counted.
To find the incident window, cut earlier slices to find the first one with the verdict.

Write down: `victim_program` (the program on the verdict line (comm, pid_ns)).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `lookups_time_out` | the tool reads NAME LOOKUPS TIME OUT for one program (it ran as one process) | `VERDICT: NAME LOOKUPS TIME OUT ...` | go to `report` Root cause **confirmed**. |
| `restarting_program` | the tool reads LOOKUPS TIME OUT IN A RESTARTING PROGRAM (the program ran as several processes in the slice) | `VERDICT: LOOKUPS TIME OUT IN A RESTARTING PROGRAM ...` | **Stop.** Not proven. The program restarts; find out why first (blueprint 12 for a descriptor limit). Lookups fail while a program starts. Two of the 5 labelled `dns_delay` runs read this way; whether the DNS fault caused the first crash in those two runs is not shown. Hand the case to blueprint `12_fd_exhaustion`. Root cause **unconfirmed**. |
| `no_timeouts` | the tool reads NO LOOKUP TIMEOUTS | `VERDICT: NO LOOKUP TIMEOUTS ...` | **Stop.** No program has lookups that time out and are sent again. Not this fault. Root cause **rejected**. |

### Report

fault_type: dns_delay. Root cause service: the program and container from the verdict
line (comm, pid_ns). It is the victim of the resolver, and the place where the fix goes.
Evidence: the verdict line word for word. Fix: repair or replace the resolver; cache
lookups; use addresses for internal calls.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **3 of 5 labelled runs are clean** (r2, r4, r5: 76-88% of lookups resent, one pid). In r1 and r3 the front-end crash-loops (4 and 6 pids in 60 s) and only 10-11% of lookups time out, the same as in the `fd_exhaustion` runs. The tool says "restarting program" for them. Whether the DNS fault caused the first crash in those two runs is not shown.
- **r4 is a real injection.** The campaign notes call it failed (no metric moved). The kernel shows 28 of 32 lookups timing out.
- **The restart verdict was added after the sweep.** The first rule (3 resent lookups, 5% of the program's lookups) fired on all 5 `fd_exhaustion` runs.
- **Only resolvers that use `sendto` with an address and wait in `poll` are seen**: musl (the Node front-end here), and glibc when it does not connect first. Go and Java resolve differently and are not counted. So this was measured on one program of one application.
- The destination of a `sendto` is not in the trace, so any UDP protocol with the same send, poll, resend pattern would be counted as a lookup.
