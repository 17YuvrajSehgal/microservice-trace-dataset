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

## Blueprint 25 (`code_lock_contended`): `inside_wait.py`, first results on the 5 runs

Login node only, low priority; one 20 s baseline slice (injection - 40 s) and one 20 s fault
slice (injection + 30 s) per run, kept in `work/v3bp/` so tool changes need no new cut.

**Measure.** Per service: requests in flight (received, not answered), minus its own calls
waiting on a dependency, minus the cores its container uses, minus its threads waiting for a
core. What is left is requests waiting inside the service for something the trace cannot name.
Chosen over call overlap (blueprint 23's column), which moved only 99% -> 84% on this fault.

**Result (final tool).** The catalogue: 0.00 in every baseline, 2.07-2.65 in every fault slice
(in flight 4.0-4.2 -> 6.2-6.7, calls waiting on the database 3.8-3.9 -> 3.56-3.61, CPU flat at
0.3 cores). One verdict line per run, naming the catalogue; the reversed comparison (baseline
judged against fault) gives none in 5 of 5.

**Two artifacts found and fixed on the way.**
1. A command that gets no answer (a MySQL statement close) looked like a call in flight until
   the next query. A call is now timed from the client's LAST data segment.
2. A reused client port joined two connections: a "quit" with no answer, then 12 s later the
   greeting of a new connection on the same port, read as one 12 s call (50 such calls in one
   slice, 27 requests "inside" the database). SYN, FIN and RST now end a pending call.
After (2) the database reads 0.00, and the proxy reads 2.8-3.0 in baseline AND fault: that is
the constant 5 ms background delay, seen as requests held in the proxy. The Node front-end
reads 6-12 in both windows (one thread, requests queue behind it).

**Bars.** Guessed at 2.0 requests and 50% of those in flight; lowered to 1.0 and 25% after the
5 runs (the catalogue is at 34-39%). Fitted to one defect in one service. A baseline is
required: without it the proxy and the front-end are named.

**Not done.** No check on other families yet (v2 `slow_db`, `svc_cpu_cap`, `normal`, and the
new `svc_cpuset` runs). That needs a SLURM job. No README or RESULTS file until then.

## v3 family 2: `svc_cpuset` (5 runs collected, all accepted, on Trillium)

**What it is.** `docker update --cpuset-cpus` restricts carts to one core (aggressive; subtle =
two cores, not collected). The look-alike of `svc_cpu_cap` on the same victim: no quota, no
period, the service just only runs on the cores it was given. Recipe `faults/svc_cpuset.sh`;
cleanup writes the full range and reads back `cpuset.cpus.effective` (an empty cpuset string is
"no change" to docker). No background conditions needed.

**Calibration (150 users, warm VM).** carts p95 23.8 ms on 12 cores, 153.7 ms on one, 23.8 ms
restored; two cores 39.8 ms; front-end on one core barely moves (Node is one thread).
A freshly started VM is not usable for the first minute (host 81% busy, carts 3.4 cores while
the JVMs compile): `run_family.sh` got `WARMUP_S`, used after every VM start.

**The 5 runs.** All: six audit lines OK, no kernel loss, verification confirmed, quality usable,
`verification.png` present, cores back to 0-11 after the run.

| run | carts p95 ms (base / fault / recovery) | carts span median ms | host busy |
|---|---|---|---|
| r1 | 34 / 70 / 46 | 7.6 / 15.3 / 7.8 | 54-60% |
| r2 | 33 / 71 / 45 | 7.5 / 14.4 / 7.4 | 50-54% |
| r3 | 34 / 64 / 46 | 7.5 / 13.0 / 7.6 | 54-60% |
| r4 | 34 / 71 / 47 | 8.2 / 13.7 / 8.0 | 55-60% |
| r5 | 38 / 71 / 48 | 8.6 / 15.1 / 8.7 | 56-59% |

- The effect in the runs (about 2x) is smaller than in the calibration (6x): carts used about
  0.65 of its one core, so the core was not full. Accepted because all 5 pass and agree.
- Kernel, r1, on the VM: the carts container (114 threads) runs on 12 CPUs in the baseline and
  on 1 CPU in the fault; every other container stays on 12. `cpu_newcomer.py` (blueprint 2)
  correctly says NO NEW CPU USER, so this family needs its own check.
- 439 metric series per run against 441 in family 1; which two differ is not checked.

**On Trillium.** `v3/sockshop/svc_cpuset.tar.gz` (15.04 GB, 263 s), 5 runs counted; working copy
`data/stratatrace-v3/sockshop/svc_cpuset/` (22 GB); every file checked against `SHA256SUMS`
(1,313-1,325 per run), 0 mismatches. Then deleted from the VM; VM stopped.

**User decision:** the false-alarm check for blueprint 25 (and a cpuset tool) waits; no SLURM
job until asked.

## v3 family 3: `disk_full` (5 runs collected, all accepted; still on the VM)

**What it is.** carts-db (MongoDB 3.4) is moved onto its own 1 GB loop-mounted ext4 volume
before tracing (`arm`), a filler file takes every free byte at injection, and is removed at
cleanup. Its own volume because every container shares the boot disk that LTTng writes to.
`run_scenario.sh` now arms any recipe marked `STRATA_NEEDS_ARM`.

**What a full disk really does (measured).** The database keeps serving; it aborts about once a
minute ("Invariant failure ... No space left on device", signal 6) and docker restarts it in
about 2 s. In all 5 runs the aborts are at 8-9 s and 70-71 s after the injection. Carts shows
3-10 failed requests and one 2.8-3.0 s request per run in the fault window, 0 errors and a
27-41 ms maximum in baseline and recovery; its median does not move (3.8-4.4 ms).

**Two recipe bugs found by the calibration, before any run.**
1. Mounting the volume root: the mongo entrypoint cannot enter the root-owned `lost+found`
   (the container drops DAC_OVERRIDE) and exits 1, so after its first crash the database never
   came back. The first calibration therefore showed a total outage that was NOT the fault.
   Fix: the database gets a subdirectory owned by uid 999.
2. `disarm` used force-recreate, but compose carries the old container's mount for an
   image-declared volume over to the new container, so the database kept the bind to a volume
   that was then unmounted, and was left "Exited (1)". Fix: `compose rm -sf` then `up`, and a
   check that it is running without the small volume.

**No metric signature (measured).** carts p95 over 1 m stays at 22-24 ms (17 ms in the
baseline); no 5xx series; the database's memory, threads, write rate and CPU do not move;
`container_start_time_seconds` does not change on a restart; node-exporter does not see the
loop mount. Target marked `expected_to_fail` -> `no_metric_signature`. The proof per run is in
`run_family.sh`: the database log in the bundle must hold "No space left on device" and an
abort, else the family stops.

**The 5 runs.** Six audit lines OK, no kernel loss, quality usable, `verification.png` present,
442 metric series, database back on its normal volume after each run.

**Open.** Kernel check of run 1 (ENOSPC returns, mongod exits) was started on the VM; its
result is in `~/kc_df.log` there. The family is NOT on Trillium: the connection dropped. The
local monitor was also stopped once by Claude Code for low laptop memory; the runs on the VM
were not affected.

## Blueprint 26 (`svc_cpuset`): `cpu_confine.py`, first results on the 5 runs

Login node only; one 10 s baseline slice (injection - 40 s) and one 10 s fault slice
(injection + 30 s) per run, scheduling events, kept in `work/v3bp26/`.

**Measure.** Per container, in both slices: the fewest CPUs that carry 99% of its CPU time, the
cores it used, and the thread-seconds per second its threads were ready and waiting for a core.
Verdict: it ran on 4 or more CPUs before and runs on at most half of them now (judged only if
it has 8+ threads and uses 0.2+ cores in both slices).

**Result.** 5 of 5, one verdict line per run, naming the carts container only: 12 (once 11)
CPUs -> 1 CPU (cpu 11, the one the recipe sets); cores used 0.59-0.65 -> 0.63-0.67; CPU wait
0.10-0.15 -> 1.23-1.50 thread-seconds per second; the other CPUs 47-54% idle. The reversed
comparison is quiet in 5 of 5. Every other container stays on 11-12 CPUs.

**Bars.** Set before the first run on data and not changed. This is the first v3 tool that
passed on the first try.

**What the numbers say about the fault.** The service uses the same CPU as before; what changes
is where it runs and that its threads now queue: about 1.3 threads are always waiting for the
one core. That is why metrics and spans see only a 2x slowdown while the kernel view is exact.

**Not done.** No check on other families (deferred by the user); the subtle setting (two
cores) was not collected, so "at most half" is untested near its edge; a service with fewer
than 8 threads is not judged.

## v3 family 4: `port_exhaustion` (5 runs collected, all accepted)

**What it is.** The catalogue's `net.ipv4.ip_local_port_range` is shrunk from 28,232 ports to
200, written into its network namespace with `nsenter` (no restart), and written back at
cleanup. Normal use is about 1,700 sockets in TIME_WAIT, so new connections to the database
fail with EADDRNOTAVAIL.

**Calibration.** 200 ports: catalogue 5xx 0.0 -> 7-12/s, 1,835 "cannot assign requested
address" lines in 80 s, 0.0 again within 20 s of the restore. 1,500 ports: nothing for a
minute, then a burst of 125/s (late and uneven; not collected). The front-end shows no 5xx
and no latency change in either.

**The 5 runs.** Six audit lines OK, no kernel loss, verification confirmed, quality usable,
`verification.png` present, 442 metric series, port range back to 32768-60999 after each run.

| run | catalogue 5xx/s (base / fault / recovery) | "cannot assign" log lines (base / fault / recovery) | failed catalogue spans (fault) |
|---|---|---|---|
| r1 | 0.00 / 74.9 / 22.8 | 0 / 2,575 / 0 | 8,639 of 29,686 |
| r2 | 0.00 / 14.6 / 56.8 | 0 / 2,276 / 0 | 4,156 of 31,111 |
| r3 | 0.00 / 14.7 / 61.9 | 0 / 3,308 / 0 | 3,309 of 30,564 |
| r4 | 0.00 / 44.2 / 11.6 | 0 / 2,711 / 0 | 4,932 of 30,264 |
| r5 | 0.00 / 13.4 / 58.0 | 0 / 4,122 / 0 | 1,726 of 30,250 |

- Kernel, r1, on the VM: in a 20 s fault slice 1,353 of the catalogue's 2,065 `connect()` calls
  return -99; 0 of 2,002 in the baseline slice. No other program has a -99.
- **The 5xx rate is uneven between runs, and in r2, r3, r5 it is higher in the recovery window
  than in the injection.** Cause, read from the catalogue log in 20 s buckets: the catalogue has
  a circuit breaker. Besides the dial error it logs "circuit breaker is open" (3,785-7,396 lines
  per run), in bursts of 20-40 s. In r2 and r5 a burst starts at the end of the injection and
  runs 20-40 s into the recovery window, after the ports are back (the dial error stops at
  cleanup in every run). So the tail is the application's own protection, not a failed cleanup.
  Blueprints must not read the recovery window of this family as healthy.
- The calibration under-read the effect (4% of requests failing, against 6-29% in the runs).

## Next family changed: `pid_limit` (H2) before thread pool exhaustion (E3)

E3 needs a small worker pool in one service. For the Java services here that is a start-up
option, so the "fault" would already be on in the baseline; a runtime switch (JMX) would have
to be built first. `pid_limit` is restart-free (`docker update --pids-limit`) and adds a third
"limit reached" error next to EMFILE and EADDRNOTAVAIL (clone returning EAGAIN). After it:
a table lock held on the catalogue's database (E6).

## Blueprints 27 (`disk_full`) and 28 (`port_exhaustion`): one tool, `new_errors.py`

Login node only; per run a 20 s baseline slice (injection - 40 s), a fault slice of the first
20 s and one from 30 to 50 s, system-call exits of about 20 calls. Kept in `work/v3bp27/`.

**Why one tool.** Both faults are a limit reached, and the kernel says so in the return value of
one system call in one container. Chosen over two special tools: the same check should cover
`pid_limit` (clone -11) and overlaps blueprint 12 (EMFILE). The tool does not look for errors
(programs get them all the time); it looks for an error that is NEW: 10 or more failing calls
of one kind in one container, with at most 10% of that count in the baseline.

**Result (final tool), 10 runs.**
- `port_exhaustion`: 5 of 5 in both fault slices, one verdict line each, naming the catalogue:
  927-1,902 `connect` calls returned -99 (EADDRNOTAVAIL) in the first 20 s (46-56% of its
  connects), 1,353-2,154 in the later slice (65-67%); 0 in every baseline.
- `disk_full`: 5 of 5 in the first 20 s, one verdict line each, naming the database: 30
  `fallocate` calls returned -28 (ENOSPC), 94% of its fallocate calls, 0 in the baseline.
  NO verdict in the 30-50 s slice of any run, as expected: the database only hits the error
  when it tries to grow a file, at start-up after each crash (aborts at 8 s and 70 s).
- The reversed comparison is quiet in 10 of 10.

**One change after the first pass.** In all 5 disk-full runs a second verdict named the carts
service: 111-124 `connect` calls returning -115 (EINPROGRESS), 0 in the baseline. That is its
driver reconnecting after the database crashed - a consequence, and -115 is not a failure.
Returns that are not failures are now left out: connect -115 and "would block" (-11) on
accept, write and send. clone -11 is kept: there it is a limit.

**Limits.** For `disk_full` the slice must contain a crash; a blueprint has to scan the window
(or use the logs, which name the cause at once). Bars (10 calls, 10%) were set before the
first pass and not changed. No check on other families (deferred by the user).

## `pid_limit` (family 5): collected, on Trillium, and blueprint 29 tested (25-11, 03:30 UTC)

- 5 of 5 runs accepted: verification confirmed, front-end 5xx 0.00 -> 13.1-14.5/s, 5,178-5,694
  "unable to create new native thread" lines in the orders log during the fault and 0 before,
  no kernel events lost, limit removed and orders running after every run.
- Recovery is not clean in the metric: front-end 5xx averages about 7/s in the recovery window
  of every run. The log lines stop at the cleanup and orders server spans show only 5-18 errors
  there, so this looks like the 1-minute rate window carrying the fault forward plus a short
  tail. Not checked further. A reader who needs a clean recovery should skip its first minute.
- On Trillium: `v3/sockshop/pid_limit.tar.gz` (18.45 GB), extracted, 1,385 files per run,
  0 checksum errors. Deleted from the VM after that.
- **A second session repeated the pull and the test by mistake** (its own report): it pulled
  the same family at the same time and started the tool test in the same work directory, which
  damaged the temporary kernel copy. I stopped the test, deleted `work/v3bp29`, checksummed the
  five runs again (0 errors) and re-ran the test from the start. The numbers below are from the
  clean re-run.

**Blueprint 29, `new_errors.py` unchanged (same file as 27 and 28).** 5 of 5 in both fault
slices, one verdict line each, naming the orders JVM: 269-471 `clone` calls returned -11
(EAGAIN) in the first 20 s (27-56% of its clone calls) and 267-610 in the 30-50 s slice
(34-51%); 0 in every baseline. Reversed comparison quiet in 5 of 5. Runs 4 and 5 have about
half the refused calls of runs 1-3; the log line counts are the same in all five, so the
service retried less, not failed less. Cause not looked into.

So one tool now covers three "limit reached" families (15 runs, 15 found, no change to the
bars). Still open, deferred by the user: the check on other families.

## `db_table_lock` (family 6, E6): recipe and calibration

**What it is.** One database session takes a WRITE lock on the catalogue's three tables for
2 s, lets go for 1 s, and repeats. Queries wait inside the database and finish together.

**Why a table lock and not a row lock** (the candidate list says "row lock wait"): the
catalogue only reads, and InnoDB reads do not wait for row locks. A row lock would do nothing
here. A table lock blocks reads too.

**Why one long session.** While the lock is held the waiting queries pile up connections; the
database reached its limit of 151. A lock client that reconnects each cycle could be refused.

**Calibration (150 users):** catalogue p95 4.8 ms -> 2,290 ms, request rate 262 -> 122/s,
no 5xx on catalogue or front-end, 0 refused connections, back to 4.8 ms within 20 s. Subtle
(0.3 s of every 3 s): p95 about 165 ms, rate unchanged. Verification target: catalogue p95.

## `db_table_lock` (family 6): collected and on Trillium (25-11, 04:10 UTC)

- 5 of 5 runs accepted: verification confirmed, catalogue p95 4.8 ms -> 2.2 s, no kernel
  events lost, no table locked and no lock client left after any run.
- Spans agree in every run: about 14,400 catalogue server spans in the fault window, 5,130-5,170
  of them over 1 s (0 in baseline and recovery), 0 errors, p95 1.95 s.
- The verification metric reads 1.4-1.6 s in "recovery". The spans show recovery is clean
  (p95 4 ms), so that is the 1-minute rate window carrying the fault forward, as in `pid_limit`.
- On Trillium: `v3/sockshop/db_table_lock.tar.gz` (14.64 GB), 1,385 files per run, 0 checksum
  errors. Deleted from the VM after that.

**Blueprint 30: `inside_wait.py` unchanged (the tool of blueprint 25).** One 20 s baseline slice
and one fault slice (30-50 s) per run. It names the database in every run tested: mysqld has
67.5-69.2 requests in flight and 67.4-69.1 of them wait inside it, 0.00 in the baseline, using
0.09 cores. The table shows the chain: catalogue 69.6 in flight with 69.3 downstream, toxiproxy
69.3 with 69.2 downstream, mysqld 69.2 with 0 downstream. So the tool puts the wait in the
database and not in the catalogue, which is what separates this from `code_lock_contended`
(there the catalogue itself holds the requests). Reversed comparison quiet. Bars not changed.

One thing the table shows that needs care: the front-end has 6.5 "inside" in the fault slice
and 9.8 in the BASELINE. It never reaches the bars (share below 25%), but a Node service
answering over keep-alive connections seems to carry a constant offset in this measure.

## `io_cap` (C4): recipe written, NOT collected - it does nothing to this application

cgroup `io.max` on a database container, written on the host. Measured first what each
database writes at the 150-user load: carts-db 60 KB/s and 19 operations/s; orders-db and
user-db 2 KB/s; catalogue-db nothing. Then limited carts-db to 64 KB/s and 20 ops/s, then
carts-db, orders-db and user-db to 16 KB/s and 5 ops/s, 80 s each: no change in any service's
rate, errors or answer time (cart p95 23.0-23.3 ms throughout).

Why (my reading, not measured): these databases acknowledge a write before it reaches the
disk, so no request waits for the disk. A limit on disk writes then delays only background
flushing. I did not check whether the kernel actually held the writes back.

Decision: no runs. Collecting it would add a second family with no signal, like
`code_lock_across_io` in v2. It needs a service that waits for its disk writes (a database set
to sync every commit). Recipe kept in `faults/io_cap.sh` for that.

## Next family: `slow_client` (thread pool exhaustion without a restart)

E3 was postponed because the pool size is a start-up option. A different way to the same
fault needs no restart: clients that send a POST body one byte per second each hold one worker
thread of the service. Enough of them hold the whole pool. Recipe `faults/slow_client.sh`,
client `faults/workloads/slow_client.py`. Whether it works on the carts service is being
calibrated; if it does not, the next candidates all need an image or start-up change and wait
for the user.
