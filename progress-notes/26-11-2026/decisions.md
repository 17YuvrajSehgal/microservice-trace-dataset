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

### Transfer of group 2 (26-11, 15:20-15:45 UTC): half done, Trillium dropped again

- Pull finished: 4 archives on Trillium, 16.0-17.6 GB. The pull log printed OK for 3 of them;
  `code_regex_backtrack.tar.gz` is there (16.0 GB) with no OK line - to be checked.
- Then Trillium stopped answering during verification and extraction, so the checksum result
  is unknown. Runs NOT deleted from the VM. VM stopped at about 15:45.
- To resume after login: read `work/tr95.log`; if `code_regex_backtrack` or any run fails,
  start the VM and re-pull that family; only then delete on the VM.

### Group 2 transfer completed (26-11, 16:05 UTC)

The check had finished before Trillium dropped: all 20 runs extracted, 1,373 files each, 0
checksum errors; `code_regex_backtrack` included (its archive extracted completely; only the
pull's OK line was missing). Runs deleted on the VM, VM stopped. v3 now: 14 families, 70
aggressive runs + 9 subtle, all on Trillium.
