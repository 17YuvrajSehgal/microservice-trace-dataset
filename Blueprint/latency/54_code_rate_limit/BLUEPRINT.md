<!-- Generated from blueprint.yaml by Blueprint/agent/bp_render.py. Edit the yaml, not this file. -->
# Blueprint: a service's own rate limit trips its circuit breaker

| | |
|---|---|
| Problem class | Dependency protection (rate limit, circuit breaker) |
| Root cause this blueprint confirms or rejects | A service rejects requests above a rate; its own circuit breaker counts the rejections as failures, opens, and then fails every request on that path at once. |
| Evidence | The per-container log files of the run (Docker's timestamped lines) |
| Not used | Kernel trace, metrics, spans |

**When to use this.** A service suddenly answers part of its requests with fast errors (500 or 429), and nothing it depends on is slow.

**Status.** Calibrated on its 5 v3 runs; tested on all 70 runs of groups 5-8 and the 20 of group 4. The second tool's bars were set after seeing 10 of those runs. Not run by an agent yet.

## Part 1. Background

Two tools on the logs. `log_errors.py` (from blueprint 41) finds a NEW STREAM of one error message. Here it is the
catalogue's `circuit breaker is open`. That message only says that the breaker opened; `breaker_cause.py` says why,
from the catalogue's other server-side errors in the same window:

| 60 s window | `code_rate_limit` | `mtu_blackhole` (a failing database path) |
|---|---|---|
| `circuit breaker is open` | **1,960-2,095** | 10,667-11,401 |
| `too many requests` | 13-20 | 0-4 |
| `database connection error` | **0** | 21 in each run |

`too many requests` is also what the breaker library (gobreaker) answers while it is half-open, so it is not proof
on its own; the verdict rests on the ABSENCE of dependency errors.

Problems that look similar:

- A failing dependency behind the breaker (`mtu_blackhole`, `error_storm`): the dependency's error is logged; `breaker_cause.py` names it.
- Any other new error stream (in `dns_delay_jvm` the orders service logs connection errors): `log_errors.py` fires, the message differs.
- A real rate limiter in front of the service (a proxy): the service itself logs nothing; not covered by these tools.

## Part 2. What you need

| Script | What it does | Usage |
|---|---|---|
| `idx_summary.py` | Date, span, health | `idx_summary.py <trace_dir> [--rate SECONDS]` |
| `extract_slice.sh` | Cuts one slice with the events you name | `extract_slice.sh <trace_dir> <date> <time> <secs> <out> '<regex>'` |
| `log_errors.py` | Error-like log lines per container and message, before and now; the verdict | `log_errors.py <logs_dir> <suspect_start_utc> <window_seconds>` |
| `breaker_cause.py` | Why a go-kit service's circuit breaker opened: a dependency, or its own rejections | `breaker_cause.py <logs_dir> <suspect_start_utc> <window_seconds>` |

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
before the suspect time must be inside them, or the tools say NOT JUDGED.

Write down: `fault_utc` (the suspect time as YYYY-MM-DDTHH:MM:SSZ).

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `times_chosen` | the time is chosen |  | go to `measure` |

### Step 3. Find a new error stream, then say why the breaker opened. (`measure`)

```
log_errors.py $LOGS <fault_utc> 60
breaker_cause.py $LOGS <fault_utc> 60
```

`log_errors.py`: up to 3 VERDICT lines with a sample message. `breaker_cause.py`: one VERDICT line. This fault is a
`circuit breaker is open` stream AND THE BREAKER OPENED ON THE SERVICE'S OWN REJECTIONS.

| The step ends with | When | Verdict line | Then |
|---|---|---|---|
| `own` | breaker_cause.py reads THE BREAKER OPENED ON THE SERVICE'S OWN REJECTIONS | `VERDICT: THE BREAKER OPENED ON THE SERVICE'S OWN REJECTIONS ...` | go to `report` Root cause **confirmed** (`code_rate_limit`). |
| `dep` | breaker_cause.py reads THE BREAKER OPENED BECAUSE A DEPENDENCY FAILS | `VERDICT: THE BREAKER OPENED BECAUSE A DEPENDENCY FAILS ...` | **Stop.** The breaker opened on a failing dependency. Follow the dependency (for example blueprints 22 and 40). Root cause **rejected**. |
| `none` | breaker_cause.py reads NO NEW OPEN BREAKER | `VERDICT: NO NEW OPEN BREAKER ...` | **Stop.** No breaker opened. Not this fault. Root cause **rejected**. |

### Report

fault_type: code_rate_limit. The service on the verdict line. Fix: raise the limit or make callers back off; do not count rejections as breaker failures.

## Part 4. Measured, and limits

- Per-run lines: `RESULTS.md` next to this file.
- **Own runs: 5 of 5** with both tools; reversed quiet.
- **`log_errors.py` also fires on all 5 `dns_delay_jvm` runs** (a different message); `breaker_cause.py` is quiet there.
- **`breaker_cause.py` separates this family from `mtu_blackhole` (5 of 5 each way)**, but its bars were set after seeing those 10 runs.
- **It reads go-kit's server error lines only** (the catalogue and the user service here).
- **Not yet run on the earlier runs.**
