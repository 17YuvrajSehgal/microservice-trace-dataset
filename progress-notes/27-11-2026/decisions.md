# 27-11-2026 decisions

## Group 5 collection

- **First start failed on my bug.** The recipe generator wrote doubled backslashes into `EXPECTED_BLAST_RADIUS`, so `ground_truth.json` was invalid and the verify step skipped the run. Fixed in 08f7005. The bad run was deleted on the VM and never shipped.
  - Lesson: `bash -n` does not catch this. Check that a new recipe's ground truth parses as JSON before the chain starts.
- **Collected:** `code_fd_leak` 5/5 confirmed, `code_zombie_procs` 5/5 (no metric signature, as registered), `code_blocking_wait` 4/5 confirmed.
- **`code_blocking_wait` run 5 was borderline and is replaced by a new run.**
  - Why borderline: its baseline was slow (front-end span p95 184 ms; the normal range over all v3 runs is 113 to 148 ms). The fault window was like the other runs (201 ms).
  - The discarded run's numbers: metric p95 baseline 0.2255, injection 0.2376; spans p50 82.4 to 88.8 ms.
  - This is a re-collection after a failed check, as the collection rules say. It must be reported with the dataset: one run replaced, reason a noisy baseline.
- **The front-end p95 metric tops out near 0.235 to 0.245 s in the fault window** (histogram buckets), while baselines range from 0.17 to 0.23 s. So the metric target for this family has little room. The spans are the better evidence for it.
- **Databases keep growing over the campaign** (25,853 customers, 38,039 orders on 27-11). Baselines are not slower than on 26-11, but this should be watched, or the databases reset between groups.

## Group 5 finished, group 6 started (the user is away; decisions taken alone)

- **Group 5 is on Trillium:** 20 runs, 0 checksum errors, deleted on the VM after the check. `code_chatty_calls` 5/5 confirmed.
- **Group 6 picks: A3, D6, D9, D3.** Chosen because none needs a front-end restart under load or a new trace event. Predictions registered before calibration (commit 6714e91).
- **Calibration, all four usable:**
  - `code_ctxswitch_storm` 400 threads, 5 ms: context switches 126k to 328k/s, catalogue p95 4.8 to 32 ms. CPU went up by 1.2 cores, so the registered "CPU up a little" was wrong.
  - `code_conn_churn`: 248 new connections per second, front-end p50 31 to 52 ms. The target uses p50, because the front-end p95 has too little room (seen in group 5).
  - `net_reorder` 10 ms, 25%: catalogue p95 4.8 to 89 ms. Far more than the delay, so the registered "up by about the delay" was wrong. Worth explaining in the blueprint.
  - `slow_reader`: 40 zero-window messages per second, no service slows. Runs with `expected_to_fail`.
- **Chain rule changed for unattended running:** a family whose check run fails is skipped and the chain continues. Before, the chain stopped at the first failure.
- **Trace buffers raised to 96 sub-buffers for `code_ctxswitch_storm`**, before its first run, because it adds about 200,000 scheduler events per second.
- **VM start race:** starting the VM within about a minute of the chain's own shutdown makes it go down again. Wait until the status is TERMINATED before starting.

## Group 6 done, group 7 started (still unattended)

- **Group 6 is on Trillium:** 20 runs, all checks passed, 0 checksum errors, deleted on the VM.
  - `code_ctxswitch_storm` slowed the catalogue more in the traced runs (p95 about 87 ms) than in calibration (32 ms). A likely cause is the tracing cost per context switch. Not checked yet; look at it when the blueprint is built, and report it as a caveat if it holds.
- **Group 7 picks: D8 `net_latency` and D11 `dns_delay_jvm`.** Small on purpose: the other ready candidates need a design decision from the user. G5 (SYN flood) is left out of the unattended plan.
- **Calibration:**
  - `net_latency` 20 ms: catalogue p50 2.6 to 45 ms, p95 4.9 to 226 ms, no errors. The registered "service's own time unchanged" was wrong, because the delay is also on the catalogue's calls to its database.
  - `dns_delay_jvm`: at a 60% drop the front-end errors come and go; at 90% they are steady at 13 to 15 per second. The family uses 90%. The orders service's own metrics do not move; the errors show at the front-end.
- **Lesson:** `dns_delay.sh` is not executable in git, so a wrapper must call it through `bash`. New recipes written on Windows have the same problem; the driver already calls recipes through `bash`.
