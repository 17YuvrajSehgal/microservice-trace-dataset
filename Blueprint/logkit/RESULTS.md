# Results: the log tools on labelled runs

Two sweeps, tools only, no model, Trillium login node. The full sweep (26-11) is below the first set (25-11).

## First set (25-11-2026)

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

## Full sweep: all 363 labelled runs (26-11-2026)

LOGS-PLAN.md step 4b. The tools exactly as committed after the first set; the only change
before this run was in the profile (Train Ticket's file names) and the safety check (below).
Scorer output on Trillium: `work/logs_plan/sweep_full.jsonl`, `sweep_full.md` (one row per
family, the 8 first-set families marked "set on").

| Runs | fault runs (families) | onset within 30 s | onset later | onset before the injection | no onset | the culprit itself changes |
|---|---|---|---|---|---|---|
| Sock Shop, set on | 52 (8) | 39 | 5 | 0 | 8 | 18 |
| **Sock Shop, held out** | 167 (30) | 67 | 4 | **0** | 96 | 26 |
| **Train Ticket, held out** | 124 (20) | 21 | 9 | **1** | 93 | 5 |

| Normal runs | `log_onset` alarms | `log_window` alarms |
|---|---|---|
| Sock Shop (10) | 0 | 0 |
| Train Ticket (10) | **1** | 0 |

### What it says

- **On held-out Sock Shop runs the false-alarm count stays 0** (167 fault runs, 10 normal runs).
  The on-time onsets are in 13 of the 30 held-out families: `slow_db`, `fd_exhaustion`,
  `pid_limit`, `port_exhaustion`, `conn_pool_exhaustion`, `code_lock_contended`, `dns_delay`,
  `slow_client`, `anomaly_net`, `anomaly_cpu`, `svc_net`, `svc_cpu_cap` (3 of 8),
  `code_serial_awaits` (1 of 5). Silent in 17, as the probe said.
- **Train Ticket's logs say much less.** An on-time onset in 6 of 20 families (`tt_svc_mem_cap`
  8 of 8, `tt_fd_exhaustion` 5 of 5, `tt_error_storm` 5 of 8, and single runs of three others).
  `tt_dependency_outage` is found only 120 s after the injection, `tt_slow_db` at a median of 44 s.
  Its services are Java behind a registry and a gateway, and their logs carry no request duration.
- **Two false alarms on Train Ticket, both read:**
  - `tt_normal_none_burst_r5`: `ts-order-other-service` warnings 0.1/s -> 1.2/s, 115 s into a
    healthy run (the "known warnings" share rule). A real false alarm.
  - `tt_anomaly_mem_aggressive_steady_r1`: `ts-travel-service` SQL errors 8.3 s BEFORE the
    labelled injection. Counted as a false alarm. Two Sock Shop families also change slightly
    before their label (`conn_pool_exhaustion` median -1.3 s), so the label may lag the start of
    the fault by a few seconds; this is not checked.

### Problems found on held-out data (not fixed: fixing them here would tune on the test runs)

1. **`log_window`'s baseline is too short for a periodic warning.** In every Train Ticket fault
   run, `ts-travel-service` writes 13 to 20 SQL warnings every 30 s, starting before the injection.
   A 20 s baseline can fall between two bursts, and `log_window` then reports "known warnings
   0.0/s -> 4/s" in families that have nothing to do with it (`tt_noisy_neighbor` 8 of 8,
   `tt_svc_cpu_cap` 8 of 8, `tt_anomaly_mem` 7 of 8). `log_onset` is not fooled: its baseline is
   the first 40 s of the run, which holds a burst. Candidate fix: a "known" template only counts
   as risen when its rate in the window is above its highest rate in any equal window earlier in
   the run.
2. **The safety check refused all 134 Train Ticket runs** on the first try: it searched for
   "verification" anywhere in a file name, and Train Ticket has `ts-verification-code-service`.
   It now matches the dataset's label files at the start of a name only (fixed before the counted
   run; a test covers both cases).

### Line-rate drops (LOGS-PLAN.md section 12, item 3): stays a NOTE

On all 10 healthy Train Ticket runs a busy service (`ts-basic-service`, once `ts-travel-service`)
drops at the same moment, 245 s into the run: a load phase ends. On Sock Shop the drop was early
and clean (`code_event_loop_block`, `anomaly_net`, `fd_exhaustion`, `slow_client`, `dns_delay`,
5 of 5 or 8 of 8 each). It is a useful hint where the load is steady and a false alarm where it is
not, so it stays a NOTE and never decides an onset.

## Narrowing with the call graph from spans (26-11-2026)

LOGS-PLAN.md section 6.5. The shortlist is the entities `log_onset` finds changing while the fault
is on, plus the services they call in the run's OWN call graph (`Blueprint/spankit`, built from
`otlp/spans.jsonl`; 363 of 363 graphs, largest 52 s on the login node). Runs whose fault has one
target service. Output on Trillium: `work/logs_plan/sweep_graph.jsonl`, `sweep_graph.md`.

| application | runs | logs flag something | target among the flagged | **target in the shortlist** | median shortlist / entities |
|---|---|---|---|---|---|
| Sock Shop | 150 | 102 | 44 | **67** | 5 / 15 |
| Train Ticket | 55 | 26 | 5 | **21** | 6 / 46 |

- **Sock Shop: all 35 misses are blind spots of the spans, none a wrong edge.** catalogue writes no
  span for its database calls (24 misses: `slow_db`, `db_table_lock`, `conn_pool_exhaustion`, target
  catalogue-db), and edge-router writes no spans at all (11 misses: it is the only service that
  complains when front-end blocks). With Sock Shop's wiring filled in by hand the count was 98 of
  102 (section 6.5); the 31-run gap is exactly these two services.
- **Train Ticket: 5 -> 21 of 26**, from 6 of 46 entities, through span links (its services call
  each other by IP) and the database behind toxiproxy. The 5 misses: `tt_svc_mem_cap` (4), where
  the target ts-order-service is not a callee of any flagged service in the graph, and one
  `tt_svc_cpu_cap`.
- So the shortlist needs edges the spans do not have. Candidates, in order of cost: (1) the kernel's
  own TCP connections (which container connects to which; also the only source on partner hosts),
  (2) peers named in log lines (edge-router writes "Error forwarding to http://front-end:8079").
