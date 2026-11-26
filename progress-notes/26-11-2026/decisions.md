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

## Blueprints 35-38 for group 2 (26-11, 16:10-17:15 UTC, login node only)

Three new tools, written after looking at real lines of the run-1 slices, bars set before the
first run unless said:
- `35_code_thread_leak/tools/thread_growth.py`: threads started and ended per process. The
  baseline already has about 1,600 thread starts per 10 s (the orders JVM starts and ends
  749-854), so the tool looks at threads that stay, not at starts.
- `36_code_spin_loop/tools/cpu_runs.py` (also blueprint 38): on-CPU stretches of 5 ms or more
  with no system call, per container, with a KIND: many threads and short, or one thread and long.
- `37_code_large_payload/tools/bytes_per_call.py`: bytes per answer and answers per second per server.

Result on the 20 group-2 runs (10 s slices, each tool on every run, both directions): each tool
5 of 5 on its own family, quiet on the other families, 0 of 60 reversed comparisons fired, KIND
right in all 10 CPU runs.

Two rules changed after run 1, said in the blueprints: `cpu_runs.py` got a second rule (3 stalls
of 100 ms with none before; run 1 of regex had 0.09 cores, under the 0.1 bar; 2 of 5 regex runs
sit exactly at 3 stalls); `bytes_per_call.py` gives a verdict only to the largest rise (the 3
services in front of the source rose about 4 times and got verdicts too).

Not done yet: the four tools on the earlier 349 runs (needs a SLURM job, as for 25-32).

## Group 4: four families, registered first, calibrated, collecting (26-11, 18:30-19:25 UTC)

Picked from the 29 "ready" candidates for needing no image rebuild and each adding a mechanism
nothing covers: `rt_hog` (A8), `mtu_blackhole` (D5), `login_bruteforce` (G2), `unexpected_exec` (G3).
**Predictions were entered in `fault_catalog.md` section 7 BEFORE calibration** (the first v3
families were entered after collection).

Calibration (150 users), also entered in the catalog log as a later entry:
- `rt_hog`: last CPU 57% -> 100% busy, no service moves. As predicted.
- `mtu_blackhole` (576): EVERY catalogue request fails with 5xx (100-255/s), not only large
  answers - the database's answers to the catalogue are dropped too. Errors last 60-90 s after
  the restore. Not as predicted.
- `login_bruteforce` (50/s requested, about 18/s achieved, sequential): all refused; the user
  service answers 500 (0 -> 20-24/s) and logs `err=Unauthorized`; the front-end has no 401
  series in its metrics.
- `unexpected_exec`: 4 shell rounds in 90 s, nothing outside the kernel. Run check counts rounds.

Chain on the VM (`~/chain_g4.sh`): rt_hog, login_bruteforce, unexpected_exec, mtu_blackhole
(last: slow recovery). It ends with `sudo shutdown -h now`, also after a failure, so the VM
cannot sit idle again. Started 19:22 UTC.
