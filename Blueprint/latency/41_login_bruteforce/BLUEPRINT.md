<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a new stream of error messages in one service's log (here: failed logins)

| | |
|---|---|
| Problem class | Security (credential guessing) |
| Root cause this blueprint confirms or rejects | One client tries passwords for an account many times per second; every attempt fails and the user service logs each failure. |
| Evidence | The per-container log files of the run (Docker's timestamped lines) |
| Not used | Kernel trace, metrics, spans |

**When to use this.** Something may be attacking the shop, or a service suddenly logs one error over and over.

**Status.** Calibrated on its 5 v3 runs; tested on all 20 group-4 runs. One rule added after run 1. Not yet checked on the earlier runs. Not run by an agent yet.

## Part 1. Background

`log_errors.py` keeps the log lines that look like errors, turns each into a template (numbers and ids replaced)
and compares every template's rate in a suspect window and the window just before. The span-export lines the
Java agents print are left out: they carry status codes and are not messages.

The tool finds NEW ERROR STREAMS, whatever their cause: it also fires on `mtu_blackhole` (the catalogue's 'circuit
breaker is open'). The MESSAGE says which fault it is.

| | `login_bruteforce` | `mtu_blackhole` |
|---|---|---|
| user service | `err=Unauthorized`, 13-19 per second | - |
| front-end | `Error with log in`, the same count | circuit breaker errors, about 30 per second |

Problems that look similar:

- Any fault that makes a service fail: its error stream is found too; read the message.
- A real user who mistypes a password: a few lines, far under 1 per second.
- Lines that are not messages (span exports): left out by name.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `log_errors.py` | Error-like log lines per container and message, before and now; the verdict | `log_errors.py <logs_dir> <suspect_start_utc> <window_seconds>` |

`LOGS='the run's logs/ directory'`

## Part 3. Procedure

The commands are suggestions that worked on the labelled runs. Change them when the trace needs it.

### Step 1. Know the date, when the trace starts and ends, and whether it is healthy. (`check_trace`)

```
idx_summary.py $TRACE
```

Read from the output: `day`, `trace_start`, `trace_end`, `duration_s`, `lost_events`. Next: `orient`.

### Step 2. Pick the suspect time. (`orient`)

```
idx_summary.py $TRACE --rate 10
```

If you were given a suspect time, use it. The logs of a run start about 60 s before the injection; the window
before the suspect time must be inside them, or the tool says NOT JUDGED.

Write down: `fault_utc` (the suspect time as YYYY-MM-DDTHH:MM:SSZ).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | the time is chosen |  | go to `measure` |

### Step 3. Compare error messages per container before and after the suspect time. (`measure`)

```
log_errors.py $LOGS <fault_utc> 60
```

A table of error messages per container and up to 3 VERDICT lines with a sample of each message. Read the message: it names the fault.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `stream` | the tool reads A NEW STREAM OF ERRORS and the message is about failed logins (Unauthorized, log in) | `VERDICT: A NEW STREAM OF ERRORS ...` | go to `report` Root cause **confirmed** (`login_bruteforce`). |
| `other_stream` | the tool reads A NEW STREAM OF ERRORS about something else | `VERDICT: A NEW STREAM OF ERRORS ...` | **Stop.** A new error stream, but not failed logins. Follow the message (for example a circuit breaker: see the network blueprints). Root cause **rejected**. |
| `none` | the tool reads NO NEW STREAM OF ERRORS or NOT JUDGED | `VERDICT: NO NEW STREAM OF ERRORS ...` | **Stop.** No new error stream. Not this fault. Root cause **rejected**. |

### Report

fault_type: login_bruteforce. The containers and messages on the verdict lines. Fix: block the client, rate-limit or lock logins for the account.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5**; reversed quiet (every reversed window inside the logs).
- **Also fires on all 5 `mtu_blackhole` runs** (real error streams); quiet on `rt_hog` and `unexpected_exec`. It is a locator for error streams; the message decides.
- **One rule added after run 1**: the span-export lines are left out (they made every reversed check fire).
- **The logs cannot show the source address** of the attempts here; the user service does not log it.
- **Not yet run on the earlier runs.**
