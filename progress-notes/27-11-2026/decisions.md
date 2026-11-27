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

## Group 7 collected; transfer waits for a Trillium login

- **Group 7: 10 of 10 runs passed, no lost events.** `net_latency` 5/5 (catalogue span p50 1.5 to 43 ms, p95 7.5 to 110 ms, 0 errors). `dns_delay_jvm` 5/5 (front-end 5xx 0 to 7-12 per second, about 1,000 to 1,500 failed requests per run).
  - In `dns_delay_jvm` the errors go on into the recovery window in 4 of 5 runs (5xx 5 to 8 per second in the metric). The JVM keeps failed lookups for a while. A blueprint must not read the recovery window as healthy.
- **NOT on Trillium yet.** The Trillium session went stale at about 16:10 UTC (master process alive, no answer). A new login needs the user's Duo approval. The two families (48 GB) are on the VM's disk and the VM is stopped.
- **To finish:** log in to Trillium, start the VM, run the pull with `DEST=.../v3/sockshop` for `net_latency` and `dns_delay_jvm`, check the checksums, then delete on the VM. The script is `tr122.sh` in the session scratchpad; only `VM_HOST` needs the new address.
- **Collection stops here for now.** The 14 ready candidates left need a design choice by the user.

## Group 7 on Trillium

- After the user logged in again: 10 runs pulled, extracted, 0 checksum errors. Deleted on the VM. The VM is stopped.
- Day total: 50 runs, 10 new families (groups 5, 6, 7), all verified on Trillium. v3 Sock Shop now has 28 families.
- Open after today: tools and blueprints for the 10 new families; the false-alarm sweep for tools 33 to 42 on the earlier runs (needs a SLURM job, not requested yet).

## Blueprints 43 to 52 (the 10 families of groups 5, 6, 7)

- **Result: every tool finds its own family in 5 of 5 runs, 0 hits on the other 45 runs, 0 reversed.** Tested on the Trillium login node on all 50 runs. All ten blueprints pass `bp_check.py`.
- **7 new tools:** `switch_rate`, `zero_window`, `conn_rate`, `pkt_order`, `fd_growth`, `unreaped`, `busy_sleep`. **3 existing tools reused:** `dev_delay` and `dns_retry` unchanged; `call_fanout` got an optional `--slower-ok` rule (default behaviour unchanged, so blueprint 23 holds).
- **Rules changed after seeing data, all written in the tool headers and RESULTS:**
  - `fd_growth`: four changes after run 1 (it first missed its own family, then fired on two others). The verdict is now for files only. A socket leak is not confirmed by it.
  - `pkt_order`: share bar 2% to 0.5% after run 1.
  - `busy_sleep`: bars set on run 1; narrowed to fixed-length sleeps after the 50-run test found two false alarms on healthy baselines (a MongoDB connection thread). A blocking call of varying length is not confirmed by it.
  - `zero_window`: wrong field name (`window` for `window_size`), and wrong reader naming. The self-test had the same wrong name, so it passed. Lesson: build self-test lines from a real trace line, not from memory.
  - `call_fanout --slower-ok`: added after run 1. Not tested against a retry storm, because we have no such runs.
- **Unchanged from first setting:** `switch_rate`, `conn_rate`, `unreaped`, and the two reused tools. These five are the cleanest results.
- **Side findings:**
  - The healthy catalogue opens a new database connection for most requests (50 to 95 per second).
  - A MongoDB connection thread is on the CPU about half the time in some healthy baselines. This may be the growing databases (noted this morning); not checked.
  - `dns_retry.py` works on the JVM's resolver without a change, although its header says it reads the C library resolver.
- **Trillium login node:** processes there are killed when the laptop goes off, also with `nohup`. Long work needs the laptop on, or a SLURM job.
- **Open:** these ten tools and tools 33 to 42 are not yet run on the earlier v2 and v3 runs. That needs a SLURM job, which the user has not asked for.
