# 11-11-2026 - decisions

## 1. Four new blueprints from families we had data for but no blueprint
Built evidence-first on Sock Shop v2 (Trillium login node only; the queues were drained):
13 fork_storm (`proc_spawn.py`), 14 deadlock (`futex_hang.py`), 15 dependency_outage
(`ns_silence.py`), 16 anomaly_disk (`blk_pressure.py`). Chosen because their recipes promise a
kernel-only signal and a probe on r1 showed it (fault vs a quiet slice 45 s before injection).
Validation: all 4 tools on 20 fault runs (5 per family) + 5 normal runs. Each tool: 5/5 on its
own family, 0 false alarms on the other 15 fault runs and on the 5 normal runs. Per-run lines in
each folder's RESULTS.md.

Why each bar is where it is (all measured):
- fork_storm: processes (child_pid == child_tid) counted apart from threads. A JVM makes 70-90
  threads/s in every run; the storm is ~100 processes/s from nothing.
- deadlock: version 1 fired on every run - every JVM/Go service keeps 7-31 idle pool threads in
  untimed futex waits. The verdict now needs >= 2 threads CREATED in the slice that hung within 1 s
  (the deadlock pairs hang ~50 ms after birth). futex_wait.py (blueprint 11) cannot see a
  deadlock at all: it measures waits that end.
- dependency_outage: the paused service goes to exactly 0 events; callers keep 37-87%. Wide margin.
- anomaly_disk: v1 missed 5/5 (tracer writes diluted the share to 47%) -> share among user-space
  issuers; v2 fired on a Prometheus compaction (25 req/s) -> floor of 200 req/s (hog: 1,800-2,200).

A process bug caught before reporting: the first normal-run tally showed "clean", but every tool
had crashed (normal runs have no ground_truth.json, so the slice anchor was empty). Fixed and
re-run; the normal-run numbers are real now.

## Open
- Agent runs with blueprints 13-16 (needs a model server; none up).
- Add the four checks to select_d's container ladder (fork/disk/silence before the CPU checks).
- Train Ticket has the same families (deadlock, dependency_outage, fork_storm, anomaly_disk):
  run validate_one.sh on them as a second-application check.
