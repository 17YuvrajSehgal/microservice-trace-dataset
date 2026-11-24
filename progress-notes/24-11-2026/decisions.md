# 24-11-2026 - decisions

## v3 collection: first VM

**Process (decided by the user).** One fault family at a time, one run at a time. After each
run the data goes to Trillium and is verified there before the next run starts. One VM first;
several in parallel only when the single-VM loop is trusted.

**Account.** `gcp200106@gmail.com`. It cannot see the old `teleeporter` project. It owns
`project-ba99825a-df02-4405-af4` ("My First Project"), billing account open, Compute API on.
Three stopped VMs of other work are in it (`kt-measure-1/2/3`, 200 GB disks each); not touched.

**Quota (measured).** CPUS_ALL_REGIONS 24, us-east1 SSD_TOTAL_GB 400, N2_CPUS 200. So one
Sock Shop VM (12) or one Train Ticket VM (16) fits, two Sock Shop VMs fit exactly, and Sock
Shop + Train Ticket together (28) do not. Parallel collection needs a quota increase, which the
user must request.

**VM `stratatrace-ss-v3`.** us-east1-d, n2-custom-12-40960, 200 GB pd-balanced boot, Ubuntu
24.04.5 - the v2 Sock Shop shape. Differences from v2, both deliberate or unavoidable:
- kernel 7.0.0-1017-gcp (v2: 1011 and 1014). A fresh image gets the current kernel.
- no 1 TB archive disk. Runs are shipped one at a time, so nothing accumulates; the trace was
  always written to the boot disk, so the runs are not affected.
- SSH: the WSL key `~/.ssh/google_compute_engine`, user `17yuv`, put in instance metadata.
  From Git Bash the key path must be protected with `MSYS_NO_PATHCONV=1`.

**Bootstrap and gate.** `vm_bootstrap.sh`: 233 kernel tracepoints, stack up, BOOTSTRAP OK. The
workload image step failed on the known docker-group issue and was rerun in a fresh login
shell. `run_gate.sh gate01`: six OK (trace 41 spans, logs 4,079 lines, load 454 requests,
metrics 524 series, kernel 1,710,390 events, clock drift 0.000 ms).

**Not done yet.** The restricted pull key for Trillium, one end-to-end dry run of the
collect -> pull -> verify -> delete loop, the Train Ticket VM, and recipes for the new families
(none of the 70 candidates has one).

## v3 family 1: `code_lock_contended` (5 runs collected, all accepted)

**Process change (user).** Runs stay on the VM while a family is collected and go to Trillium
at the end. Every run is monitored and quality-checked as it lands; run 1 of a family is a
check run, and the other four start only if it passes.

**What it is.** The same defect as `code_lock_across_io` (catalogue holds a mutex across its
list query), collected so that the lock is contended. New family name so it cannot be mixed
with the 5 v2 runs, which show nothing.

**Three setups were tried; two were rejected by the per-run checks.**

| setup | result | decision |
|---|---|---|
| 20 clients on the catalogue, as fast as possible | first attempt: the probe never started (it built a list of 1e9 items); catalogue rate stayed at 245/s, verification unconfirmed | bug fixed; run deleted |
| same, probe fixed | fault present (catalogue median 3.4 -> 16.6 -> 4.7 ms) but host 81% busy in the baseline and 70% in the fault: the lock throttled the load, so p95 FELL (150 -> 37 ms) and the front-end got faster | rejected: the baseline is a stressed machine; run deleted |
| constant 5 ms delay on catalogue-db + 4 clients every 100 ms (40 list requests/s) | host 49-56% busy in all windows; catalogue p95 38-44 -> 101-135 -> 42-52 ms | chosen |

Why the delay is needed: our local database answers in 0.4 ms, so the lock is held about 1 ms
and never queues at any calm load. With 5 ms it is held about 12 ms. Measured without extra
clients the delay alone is too weak (p95 34 -> 40 ms at 5 ms, 48 -> 112 ms at 10 ms), because
normal users call the list endpoint rarely.

**Driver changes** (`run_family.sh`, `run_scenario.sh`, `loadprobe.py`; all off by default
for v2 behaviour): load settles 30 s before tracing opens (steady baseline, the fix
CAMPAIGN-ISSUES 20 deferred to "a future collection"); optional second load; background
conditions recorded in `meta/load_setup.txt`; the family stops at the first run that the
quality gate calls not usable or whose extra load reports no requests.

**The 5 runs.** All: six audit lines OK, no kernel event loss, verification confirmed, quality
usable, `verification.png` present, 441 metric series, about 12,000 extra-load requests, 5.5-5.7 GB
packed.

| run | catalogue p95 ms (base / fault / recovery) | list-endpoint span median ms | host busy |
|---|---|---|---|
| r1 | 44 / 135 / 47 | 13.8 / 67.6 / 12.4 | 51-54% |
| r2 | 41 / 106 / 46 | 13.1 / 59.3 / 12.4 | 49-53% |
| r3 | 42 / 112 / 52 | 13.3 / 66.7 / 12.5 | 51-54% |
| r4 | 41 / 114 / 43 | 13.9 / 64.2 / 12.3 | 52-54% |
| r5 | 42 / 126 / 45 | 13.8 / 64.9 / 12.6 | 51-56% |

The other catalogue endpoints do not move (get-one 12.6-13.4 ms, tags 6.3-6.6 ms in every
window of every run). So the spans localise the fault to one endpoint.

**Kernel trace, r1, checked on the VM** (babeltrace 2.1.2 is installed there; `call_fanout.py`
on 20 s slices): the trace reads and slices. Front-end -> catalogue answers go 13.3 -> 19.1 ms;
real database calls (proxy -> MySQL) with 2 or more in flight go 99.2% -> 84.3%; catalogue ->
proxy stays at 98% because the delay sits in the proxy and the other endpoints are not locked.
So the kernel signal exists but this tool shows it weakly. The blueprint will need a sharper
measure; the data is not the limit.

**Known, not a defect:** `baseline_quiet` in `run_quality.json` reads "failed" in every run
because it needs per-interface counters that are only built later on Trillium. `logs: 0 contain
trace_id` in the audit (the gate run had 11): not looked into yet.

**State.** 5 bundles in `~/archive/runs/code_lock_contended/` on `stratatrace-ss-v3` (about 28 GB),
plus `gate01`. Not on Trillium yet. VM stopped.

## `code_lock_contended` moved to Trillium and verified

- Pull, not push: Trillium's existing key `~/.ssh/ss_vm` is in the VM's `~/.ssh/authorized_keys2`
  (not `authorized_keys`, which the GCP guest agent rewrites), bound to `~/bin/export_recipe.sh`,
  so it can only `list`, `sizes`, or stream one family. `/mnt/archive/runs` on the VM is a
  symlink to `~/archive/runs`, because the export command has that path fixed. Nothing has to
  be registered with the Alliance.
- Archive: `/scratch/yuvraj17/stratatrace/v3/sockshop/code_lock_contended.tar.gz`, 19.64 GB,
  683 s. `pull_from_vm.sh --verify`: 5 runs.
- Working copy: `/scratch/yuvraj17/stratatrace/data/stratatrace-v3/sockshop/code_lock_contended/`
  (28 GB, kernel channels still gzipped). Every file of every run checked against the bundle's
  own `SHA256SUMS` (1,386 files per run): 0 mismatches in all 5.
- v3 is kept apart from v2 (`v3/`, `data/stratatrace-v3/`): its baselines are collected at
  settled load and must not be mixed with v2 baselines.
- Only after that check were the 5 runs deleted from the VM. Kept on the VM for the provenance
  archive at the end: `gate01`, the driver logs, `campaign_manifest.csv`, `fault-state/`.
- Lesson for the next transfer: over `ssh ... 'bash -s'`, any inner `ssh` without `-n` eats the
  rest of the script, and `cat > f && nohup ... &` backgrounds the `cat` too (empty file). Upload
  the script in one command, start it in a second.
- The "0 log lines contain trace_id" audit line is not a regression: it counts lines with the id
  of the single trace the audit picked.
