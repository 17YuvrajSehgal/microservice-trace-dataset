# 26-11-2026 decisions

## Group 2 collected: 20 of 20 runs pass (chain on the VM, 03:28-07:11 UTC)

| family | runs | per-run check | numbers |
|---|---|---|---|
| `code_spin_loop` | 5 | 5 pass | catalogue spans p95 3.2-3.7 -> 17.4-17.7 ms, 0 errors |
| `code_large_payload` | 5 | 5 pass | catalogue network transmit 0.29 -> 2.07-2.15 MB/s; spans p95 3.6 -> 4.0-4.2 ms |
| `code_regex_backtrack` | 5 | 5 pass | front-end p95 (metric) 0.088-0.095 -> 0.197-0.215 s; spans p95 150-174 ms, p50 31-34 ms |
| `code_thread_leak` | 5 | 5 pass | catalogue `go_threads` 16-17 -> 289-316 (fault mean), 498-529 (recovery mean, as designed) |

Every run: verification confirmed, no kernel events lost, `baseline_quiet` and `ust_has_events`
gates pass (user-space trace 231-236 MB), site healthy and stock images back after the run.
Running the chain on the VM itself worked: no laptop monitor was needed.

**Not moved yet.** The VM sat idle from 07:11 to 15:12 UTC (8 hours, about the cost of one
collection day) because nobody was watching and the Trillium login had expired. Stopped at
15:12. Runs are on the VM disk in `~/archive/runs/code_*`. Lesson: the on-VM chain should end
with a step that stops the VM itself, or move the runs out first.
