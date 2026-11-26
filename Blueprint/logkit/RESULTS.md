# Results: the log tools on the first set (25-11-2026)

LOGS-PLAN.md build step 4a. Tools only, no model. Tools: `tools/log_onset.py` and
`tools/log_window.py` through their shared rules (`tools/logsig.py`). Scorer:
`Blueprint/eval/log_sweep.py` (it reads the labels; the tools do not). On Trillium:
`work/logs_plan/` (`first_set.txt`, `idx/`, `sweep3.jsonl`, `sweep3.md`).

**Data.** Sock Shop, every run of 8 families (52 fault runs: v2 `dependency_outage`,
`queue_backlog`, `svc_mem_cap`, `error_storm`, `code_event_loop_block`; v3 `disk_full`,
`db_table_lock`, `net_bandwidth`), plus the 10 v2 normal runs. v3 has no normal runs; its healthy
data is the time before each injection. Index build: 62 of 62, about 5.5 s per run.

**These rules were set on these runs** (rule history below). The full sweep on the other
families and on Train Ticket (step 4b) is the test on runs they were not set on.

## The four numbers

**1. False alarms: 0.** `log_onset` and `log_window` print no change on any of the 10 normal
runs, and `log_onset` finds no change before the injection in any of the 52 fault runs.

**2. Coverage** (`role`: which entities `log_onset` finds changing while the fault is on):

| family | runs | culprit logs it | only others | silent |
|---|---|---|---|---|
| `error_storm` | 8 | 8 | 0 | 0 |
| `disk_full` | 5 | 5 | 0 | 0 |
| `net_bandwidth` | 8 | 5 | 1 | 2 |
| `svc_mem_cap` | 8 | 0 | 8 | 0 |
| `dependency_outage` | 5 | 0 | 5 | 0 |
| `db_table_lock` | 8 | 0 | 7 | 1 |
| `code_event_loop_block` | 5 | 0 | 5 | 0 |
| `queue_backlog` | 5 | 0 | 0 | 5 |

**3. Timing** (`log_onset`, no label, baseline = the start of the run):

| family | onset found | within 30 s of the injection | median seconds after it |
|---|---|---|---|
| `error_storm` | 8 | 8 | 0.5 |
| `svc_mem_cap` | 8 | 8 | 0.6 |
| `disk_full` | 5 | 5 | 2.0 |
| `db_table_lock` | 7 | 6 | 5.0 |
| `net_bandwidth` | 6 | 6 | 5.0 |
| `dependency_outage` | 5 | 5 | 5.3 |
| `code_event_loop_block` | 5 | 1 | 53.9 |
| `queue_backlog` | 0 | 0 | - |

The misses in `db_table_lock` and `net_bandwidth` are the subtle setting (3 runs each).

**4. Added value with the agent:** not measured yet (step 7).

## What the numbers say

- **The first entity to change is the culprit in only 2 families** (`error_storm`, and
  `net_bandwidth`'s aggressive runs). In 5 families it is a caller or the entry proxy. The
  "witness, not judge" rule of LOGS-PLAN.md section 1 holds on our data, as it did in INQUEST.
- **The culprit can name its own cause:** in `disk_full` carts-db writes "Failed to write to
  interim file" and WiredTiger error 28 (out of space) 2 s after the injection, in 5 of 5 runs.
- **Some faults show as latency only:** `db_table_lock` catalogue `List` p50 1.2 -> 1,334 ms,
  `net_bandwidth` 0.5 -> 150 ms. No error line is written.
- **The gap blueprint 15 admits is filled here:** `dependency_outage` 5 of 5 found (orders logs
  timeouts at +5 s), `queue_backlog` 0 of 5. This is the case where logs can tell apart what the
  kernel trace cannot.
- **A slice at a fixed time can miss a short burst.** `log_window` at injection +30 s saw nothing
  in `disk_full` 0 of 5, because carts-db crashed at +9 s and then wrote nothing. A blueprint
  should cut its log slice where `log_onset` points, not at a fixed offset.

## Line-rate drops (LOGS-PLAN.md section 12, item 3)

Counted only for entities with at least 20 lines/s in the baseline (queue-master and shipping log
about 6/s, only at the start of a run, and "drop" in every run):

- `code_event_loop_block`: a drop 4 to 5 s after the injection in 5 of 5 runs, when the first
  new error comes 22 to 63 s after it.
- No drop before any injection, and none on the 10 normal runs.
- `svc_mem_cap` subtle: drops at +185 s in 3 runs, after the fault.

So a drop in a busy entity looks like a usable early signal on this set. It is still a NOTE in
the tools until the full sweep shows its false-alarm count.

## Rule history

| # | Change | Run that showed it | Effect on the first set |
|---|---|---|---|
| 1 | Bug: a window must include the whole second its start falls in (`logidx.window_sum`) | `disk_full_aggressive_steady_r2`: every new template counted 0 lines in its first 10 s | needed for 2 and 3 |
| 2 | New warning lines are counted over all new templates of an entity together, not per template | `disk_full_aggressive_steady_r2`: a crash wrote 15 different error lines, 1 to 5 each | `disk_full` 2 -> 5 of 5 |
| 3 | New warning lines must fall in at least 2 different seconds | `normal_none_burst_r1`: edge-router wrote 7 lines in one second, never again | false alarms 1 -> 0 |

Change 1 also hid change 3's false alarm before it was fixed: with the bug, the 7 lines in
one second were never counted.

A template rule found by a unit test: go-kit's `result=` is a row count in catalogue
(`result=7`) and an outcome in payment (`result=false`); numbers in kept keys are now masked.
