# 9 September 2026 — decisions

## Context

Blueprints exist for 8 of the 27 problems. Today: start the remaining latency faults. The rule is
measure first, write second, so the work is extraction, not authoring.

---

## 1. Split the missing faults by what they cost, before starting any of them

Of the 19 problems with no blueprint, **3 should never get one**: `dependency_outage`,
`queue_backlog` and `error_storm` were already measured as invisible to kernel traces. They
belong on the out-of-scope list, not the backlog. The real gap is 16.

Of those 16, **11 need no new measurement code** — the signals are already in the packs:

| fault | signal already measured |
|---|---|
| `resource_abuse` | `thief_cores` |
| `lock_contention`, `deadlock` | futex wait shape |
| `anomaly_mem` | interrupt time, block I/O |
| `code_*` (5) | endpoint slowdown, socket blocking |

The other 5 needed one new script between them.

## 2. Checked the event format before writing a single regex

Sampled a real trace first, rather than writing patterns from memory:

    sched_switch        prev_prio = 20, prev_state = 0, next_comm = "dockerd", next_prio = 20
    syscall_exit_read   ret = 0
    net_dev_queue       len = 126 ... protocol = ( "tcp" ... source_port = N, dest_port = N
    sched_process_fork  parent_comm = "..." child_comm = "..." child_tid = N

All four present. `process_probe.py` measures five signals in one pass: fork rate, failing
syscalls by errno, bytes sent per process, DNS packet rate, and the spread of scheduling
priorities. None of this needs new collection - it was recorded all along and never extracted.

## 3. The recipe's own prediction was wrong, and the smoke test caught it

`fork_storm`'s header claims `sched_process_fork` "is unmistakable and nothing else in our
dataset produces it in volume". Measured on `fork_storm_aggressive_steady_r1`:

| | baseline | incident | |
|---|---|---|---|
| host forks/s | 134.31 | 237.07 | **1.77x** |
| forks by `python3` | 3.64 | 100.00 | **27x** |
| top forking process | `java` | `python3` | changed |

At the host level it is not unmistakable at all. The machine already forks 134 times a second,
from Java and **from our own collection script**. The fault adds 77% to a busy baseline.

What is unmistakable is the arrival: a process that forked 3.6 times a second now forks 100.

**Third fault, same lesson.** `thief_cores` for CPU and `io_newcomer` for disk both separate
cleanly where their host totals do not. Measure the arrival, not the level. The probe now reports
newcomers for forks, errors and bytes.

Worth noting the shape of the error: this was a claim written from mechanism, by us, and it was
wrong. It read as obviously true and took one measurement to disprove.

## 4. The error signal has the same problem, found before it cost anything

The baseline runs **16,349 failing syscalls per second**, almost all `EAGAIN` on non-blocking
reads. A total error rate is noise, so `fd_exhaustion`'s EMFILE would have drowned in it. The
newcomer treatment applies there too, and is in place before that fault is ever scored.

Two sanity checks passed: EMFILE is 0.0 on a fork-storm run, which is correct, and priorities
0..39 are present for the priority-inversion work.

## Still open

- The 156-run pack job is queued. Trillium is in maintenance - 1229 of 1230 compute nodes
  drained - so it has not started. It will run on its own. Neptune is not open to our account.
- Nothing has been written into a blueprint. The order is packs, then
  `derive_v2_thresholds.py` across all families, then author only what separates.
- A fault with no separating signal is a result to report, not a gap to hide.
