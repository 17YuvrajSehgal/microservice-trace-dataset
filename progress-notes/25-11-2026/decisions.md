
## RCA Studio: demo data restored, simpler tree, data sources

- **The WSL data folder was deleted on 18-11** (disk cleanup in another session), so the
  partner traces, links and runs were gone from the UI. Restored from: the original archives
  (extracted, not read), the link map found in the 04-11 session log, and the final-pass
  verdicts in the local, git-ignored results folder. The copy on Trillium is the first pass
  only (before the blueprint fixes), so it must not be used for demos.
- **Tree**: runs are listed only under their trace; a run row starts with its blueprint.
  Why: every run was shown twice and rows under one trace looked the same.
- **Run panel** opens as a tab in the active editor group, not a new column per run.
- **Data sources** (logs, metrics, distributed traces) can be connected to a trace. One
  record shape (time, source, text, fields) and a registry of types, so a new backend is one
  class and the extension does not change (it builds its form from the server's field list).
  Why this shape: we do not know the partner's log / metric systems yet. Built-in types only
  read our dataset's files. Not done: the agent does not use these sources yet; they are for
  viewing. Queries read files from the start (logs 2-4 s, 768 MB of spans up to 10 s).

## v3 collection, group 1 (25-11, from 16:10 UTC) - written by the collection session

VM restarted (new address each start; warm-up 150 s before the first measurement). The
Trillium login had expired, so finished families stay on the VM disk until the next login.

### B3 kill-and-restart loop: calibrated, NOT collected (looks like a duplicate of v2)

Recipe `faults/oom_restart_loop.sh` (carts, `docker update -m`). Measured under 150 users:
- 64 MB: 11 restarts and 24 kills in 120 s; carts never serves. The front-end's rate falls to
  about 0, because users hang on connects to a container that has no address while it restarts.
- 160 MB: ALSO a restart loop: 9 restarts and 20 kills in 120 s, each life 15-20 s, carts
  serves nothing. The front-end keeps answering, with 50-98 errors/s.

160 MB is the limit v2 used for `svc_mem_cap` aggressive on carts. So v2 very likely already
holds this fault. Rule 1 of the candidate list: two recipes that leave the same trace are one
problem. **Not checked on the v2 runs themselves** (Trillium not reachable); to confirm there:
count the JVM starts in the fault window of the `svc_mem_cap` aggressive runs. If they show a
loop, B3 is removed; if they show one kill and a slow phase, B3 is collected at 64 MB.

A side finding for the recipe if it is used: after the limit is restored the service stays down
until Docker's back-off timer fires (up to 60 s here); `docker start` does not shorten it.

### C2 inode exhaustion: NOT collected (nothing creates files)

Counted `openat` calls with O_CREAT and `mkdirat` calls on the whole host for 20 s under the
150-user load with bpftrace: none, from any program. A volume with no free inodes then changes
nothing for a service that only writes to files it already has open. Same kind of result as
`io_cap`. One check only, 20 s; `creat` and `openat2` were not counted.

### B3 settled: it is a duplicate of v2 `svc_mem_cap` (checked on the v2 logs, 18:00 UTC)

Carts log of the 8 v2 Sock Shop `svc_mem_cap` runs: the 3 subtle runs (300 MB) have 8-9 JVM
start banners each; the 5 aggressive runs (160 MB) have 1 (the JVM is killed before it prints
one, and one prints after the limit is lifted). With the calibration (9 restarts in 2 minutes
at 160 MB) this says `svc_mem_cap` is a restart loop at both settings. B3 removed from the
candidate list. Consequence for blueprint 4: its text should say "killed and restarted in a
loop", not "killed once" - to check against its README.

### `net_bandwidth` (D4): collected, on Trillium (17:50 UTC)

- Calibration on the catalogue (it sends a little over 4 Mbit/s): cap 4 Mbit/s p95 4.8 -> 415 ms;
  2 Mbit/s p50 240 ms, p95 2.0 s, rate 260 -> 140/s; 1 Mbit/s p50 1.2 s. No errors anywhere,
  recovery within 20 s. Aggressive = 2 Mbit/s, subtle = 4 Mbit/s.
- 5 of 5 runs accepted: verification confirmed (catalogue p95 4.8 ms -> 1.83-1.88 s), no kernel
  events lost, 2,544-2,645 catalogue server spans over 1 s in the fault and 0 in the baseline,
  0 errors, the rate limit gone after every run.
- On Trillium: `v3/sockshop/net_bandwidth.tar.gz` (14.97 GB), 0 checksum errors. Run 1 has
  1,373 files against 1,385 (12 periodic snapshot files fewer; not looked into). Deleted on the VM.
- The local monitor was stopped by Claude Code for low laptop memory during run 4. The driver
  on the VM finished runs 4 and 5 alone; I checked both by hand afterwards.

### Blueprint 32 (`net_bandwidth`): `inside_wait.py` gives a WRONG answer, new tool `dev_delay.py`

**`inside_wait.py` names the wrong service, 5 of 5.** It says requests wait inside toxiproxy
(34-36 "inside") and, second, inside the catalogue (16). Cause: the cap is on everything the
catalogue sends, also its own queries to the database. The tool times a call from the moment
the client's packet is queued on the client's interface. With a cap, the packet then waits
there, and that wait is counted as time inside the server it is going to. So a queue on the
SENDER's interface is read as slowness of the RECEIVER. This is a real limit of that tool, not
only of this family: it must be stated in blueprints 25 and 30, or the tool must time a call
at the receiver's interface.

**`dev_delay.py` (new).** A packet is queued on the sender's interface and then on the next
interface. The tool measures the time between the two sightings, per sender. Bars set before
the first run and not changed: 500 packets, median 5 ms, p95 20 ms, 10 times the baseline.

**Result, 5 of 5 on the first try, one verdict line per run:** the catalogue's packets wait
62-76 ms (median) and 328-347 ms (p95) at its interface; 0.01 ms in every baseline and for
every other sender (11 others in the table). It also reads the cap: the catalogue sent
2,053-2,093 kbit/s in the fault slice (limit 2,000). Reversed comparison quiet in 5 of 5.
No check on other families yet.

### `cpu_weight` (A2): calibration

Lowest CPU weight on carts while a neighbour keeps the host busy. The neighbour runs for the
whole run, so only the weight changes at injection.
- Neighbour alone, 12 busy processes: host 50% -> 100% busy; the BASELINE already suffers (cart
  rate 120 -> 91/s, p95 23 -> 88 ms; front-end p95 50 -> 240 ms). 6 and 8 processes slow the
  baseline about as much (host 90% and 96% busy).
- 12 processes + weight 1: carts completes nothing. Not used (an outage).
- 12 processes + weight 10: p50 22 -> 590 ms, p95 -> 3.0-4.2 s, rate 91 -> 66/s, no errors,
  back to normal within 40 s. **Chosen for aggressive.**
- 8 processes + weight 10: p95 72 -> 240 ms. 6 processes + weight 10: no change.
Consequence to state in the dataset: this family's baseline is a busy host and is not
comparable with the baselines of the other families. Check run started 18:35 UTC.

## Review pass: weaknesses and bugs fixed before going on (25-11, 18:40-19:40 UTC)

The user asked for all known weaknesses and bugs to be fixed before the next blueprint or
collection. `cpu_weight`, already running, finished (5 of 5, on Trillium, 9.31 GB).

**Tools**
- `inside_wait.py`: (1) a call is now timed AT THE SERVER (client segments where they arrive,
  server segments where they leave). Before, a queue on the sender's interface was counted as
  time in the receiver. (2) A service is not judged when the comparison slice has under 25% of
  its request rate. (3) The header says what it cannot see. Re-test, 20 runs, both directions:
  `code_lock_contended` 5/5 (5.0-5.4 inside the catalogue, 0.50-0.59 baseline; the numbers
  changed because calls from the host are now counted - before, a connection seen on one
  interface per direction produced no calls at all), `db_table_lock` 5/5 unchanged,
  `net_bandwidth` 5/5 now names the catalogue and nothing else, `slow_client` reversed says
  "not judged" in 5/5. Reversed quiet everywhere.
- `unanswered.py`: a connection is answered if ANY interface shows server data. The 30-51
  silent connections at the edge router in every baseline were this bug (0 of 151 with all
  interfaces). Fault runs unchanged, 5/5.
- Not changed, stated as limits: `new_errors.py` needs a slice that contains a crash for
  `disk_full`; `inside_wait.py` bars were lowered once after seeing 5 runs.

**Collection**
- `run_family.sh` stops a family when a run loses kernel events.
- `check_run_quality.py`: `baseline_quiet` runs from the bundle; new gate `ust_has_events`.
- `otel-to-lttng.py` tails the log file (CAMPAIGN-ISSUES issue 26).
- `pid_limit.sh` takes the lowest of 10 task-count readings.
- `slow_client.sh` carries the measured notes next to its prediction.

**Process**: v3 families entered in the `fault_catalog.md` amendment log, said to be late.

**The two "not collected" decisions, re-checked properly**
- `io_cap`: the limit DOES hold the writes back. carts-db: 68.6 KB/s -> 16.0 KB/s, and its
  tasks wait for I/O 500-650 ms per second (2 ms before). No service notices. So it is a fault
  the kernel sees and users do not, like the subtle noisy neighbour. Still not collected; it
  could be collected as a kernel-only family if the user wants one.
- Inode exhaustion: every call that can create a file, 30 s under load, whole host: 3 calls
  (a database diagnostic thread, runc, sshd). No service creates files. Decision stands.

**Open, for the user**: re-collect the 37 v3 runs without a user-space trace or accept the gap
(issue 26); Train Ticket relay; whether `cpu_weight` with its busy baseline stays in the dataset.

## User decisions on the review (25-11, about 19:50 UTC)

- **User-space trace gap: no re-collection.** Fix it for future runs and report the gap in the
  paper. The relay fix is in; the relay now also follows Train Ticket containers (it knew only
  four Sock Shop names; the Train Ticket path is not tested on a Train Ticket VM yet).
- **`cpu_weight` stays** for now; **`io_cap` stays as it is** (recipe, no runs). Both to be
  looked at again later.

## False-alarm sweep of the five new tools (job 2931081, 25-11, 20:00 UTC)

Approved by the user. One Trillium node, 34 minutes (about 110 core-hours). `LevelFS` before:
`def-naser2` 27.3. Script `Blueprint/latency/sweeps/v3_tools_sweep.sbatch`; outputs
`work/dx_check/sweep_v3tools/` on Trillium. All 349 runs: v2 Sock Shop 170, v2 Train Ticket
134, v3 45 (8 families plus `cpu_weight`). One baseline slice (20 s ending 20 s before the
injection) and one fault slice (20 s from +30 s) per run feed all five tools. 347 judged; 2
slices failed (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`: babeltrace
could not read the trace - not looked into). **All 20 normal runs: no positive verdict from any
tool** (after the `new_errors.py` change below).

| tool | own families | positive elsewhere | reading |
|---|---|---|---|
| `cpu_confine.py` | `svc_cpuset` 5/5 | 1 of 342 (`code_event_loop_block`, one run: the blocked Node process) | specific |
| `unanswered.py`, with its slow-clients clause | `slow_client` 5/5 | 0 of 342 | specific |
| `unanswered.py`, "service does not answer" alone | `slow_client` 5/5 | 17: `dependency_outage` 5/5, `code_event_loop_block` 5/5, `fd_exhaustion` 5/5, `dns_delay` 2/5 | true in all of them: these services do stop answering. A symptom, not a cause |
| `dev_delay.py` | `net_bandwidth` 5/5 | 21: `svc_net` 5/5 on both applications, `anomaly_net` 8/8 Sock Shop and 3/8 Train Ticket | true: those faults are a delay queue (netem) on an interface. The tool cannot tell a rate limit from a delay yet. Quiet in the 316 runs without an interface queue |
| `new_errors.py`, limit errors only | `port_exhaustion` 5/5, `pid_limit` 5/5 (`disk_full` 0/5 in this slice, as known: it needs the crash slice) | 16: Train Ticket `fd_exhaustion` 5/5 (EMFILE, the real fault), and the edge router out of file descriptors in `slow_client` 5/5, `anomaly_net` 3/8, `dns_delay` 3/5 | all real limits. The edge router ones are a second effect: connections pile up there when requests hang |
| `inside_wait.py` | `code_lock_contended` 5/5, `db_table_lock` 5/5 | 68 runs in 13 other family groups: `slow_db` 11/11 (names the proxy that holds the delay), `anomaly_net` 8/8, `svc_cpu_cap` 6/8 (names the capped service), `anomaly_cpu` 5/5, `code_event_loop_block` 5/5, `code_serial_awaits` 5/5, `dependency_outage` 5/5, `fd_exhaustion` 5/5, `svc_net` 5/5, `cpu_weight` 5/5, `net_bandwidth` 5/5, `error_storm` 3/8, `dns_delay` 2/5, `anomaly_mem` 1/7, Train Ticket `slow_db` 2/11 | NOT specific to a lock. It answers "in which service do requests wait", and that is true for many faults. Quiet in 239 runs |

**What this means.**
- `cpu_confine.py`, the slow-clients clause and (with one more rule) `dev_delay.py` identify
  their fault.
- `inside_wait.py` and the plain "does not answer" verdict are LOCATORS: they name the service
  where requests wait, for any cause. Blueprints 25 and 30 cannot rest on `inside_wait.py`
  alone. They need a second step that rules out the other causes (CPU cap, network delay,
  blocked event loop, a slow dependency) with the tools that already exist for those.
  Whether its named service is the right one in each of the 68 other runs has been checked only
  where the table says so.
- `new_errors.py` was CHANGED because of this sweep: before, every new error gave a verdict and
  it fired in 4 of 10 normal Train Ticket runs (`openat` returning "no such file" in node and
  python, and `docker exec` helpers) and in 22 other groups. Now only errors that mean a limit
  was reached give a verdict (no space, no port, too many files or tasks, no memory, quota, no
  buffers); other new errors are listed without one. The numbers in the table apply that rule
  to the sweep's own output lines (same result as re-running; the tool's self-test covers it).
  Consequence: a port scan (refused connects) will NOT get a verdict from this tool.

**Next for the tools:** a rule in `dev_delay.py` to separate a rate limit from a fixed delay; a
second step for blueprints 25 and 30; a tool for the port scan and one for `cpu_weight`.

## Logs component: plan written (`Blueprint/latency/LOGS-PLAN.md`), nothing built

Read the INQUEST paper, its workflow code and its stored results again, in full, and designed
the logs component for the graph blueprints from them.

- **Logs are a witness, the kernel check is the judge.** A log step proposes a time, explains a
  confirmed verdict or points at code; it never confirms or rejects. Why: in INQUEST the
  printing file was a fixed file in 0-40% of matched cases, and our 16-11 pilot blamed the
  service that complained.
- **Fixed steps, not free tools.** Why: INQUEST's staged procedure ties the free loop on files
  and gains 14.1 points on functions; our free log tools were called 0 times on one run.
- **Source-neutral from the start.** Partner traces have no logs today but may get them. So:
  one record shape, a declared profile per log format, a clock offset and a join table in the
  index, and tools that say `LOG CLOCK NOT ALIGNED` / `NOT JOINED` instead of guessing. A
  synthetic syslog profile is in the build order to prove it without partner data.
- **First real work is a tool-only sweep on the 349 runs**, compared with the pre-registered
  `expected_winning_modality`. It doubles as the two tests the INQUEST paper lists as missing.

Open: the pass bars (section 8.3) and the 30 s onset window need the user's agreement.

## `port_scan` (G1): collected, on Trillium (25-11, 20:45 UTC)

- The scanner runs inside the front-end's network namespace (no new container): 200 connection
  attempts per second to ports 1-1024 of the 15 other containers.
- 5 of 5 runs: 23,781-23,840 attempts per run, no kernel events lost, no scanner process left.
  **First family collected with all the fixes:** user-space trace 212-216 MB in every run,
  `baseline_quiet` ran and passed in every run.
- Verification reads `no_metric_signature` in runs 1, 3, 4, 5 as calibrated. **Run 2 reads
  `confirmed`**: the front-end p95 used as the (expected flat) target moved by chance
  (0.099 -> 0.115 s; today's baseline wanders between 0.10 and 0.17 s). The run is fine - the
  scan ran - but its verification label is a false positive of the metric check. A reader must
  not take run 2 as "metrics see the scan".
- On Trillium: `v3/sockshop/port_scan.tar.gz` (17.34 GB), small files checksummed, 0 errors.

## `conntrack_full` (D7): calibrated, NOT collected - parked

Recipe `faults/conntrack_full.sh` (host `nf_conntrack_max` set to the current entry count).
- Steady load uses 380-470 entries. With the maximum at 472: 400 "table full, dropping packet"
  kernel lines in 80 s and a TOTAL outage - the front-end completes nothing, Prometheus cannot
  scrape or answer, even host name resolution fails.
- After the setting was restored the stack was healthy (checked: all containers up, pages
  answer, a fresh 150-user load gives normal numbers), but **the load generator of that test
  never recovered** (51% of its requests failed and it stopped sending). So a run would have an
  empty recovery window.
- The second setting (50 entries of headroom) was not measured properly: it ran on the dead
  load, and the safety timer restored the limit in the middle.
Why parked: as calibrated it is a host-wide outage of everything, including the metrics
pipeline, and the load generator does not survive it. To be useful it needs (1) a setting
that drops some new connections and not all, if one exists, and (2) a look at why the load
generator stops. Not worth more VM time before the user decides.

## State at 20:55 UTC, 25-11

- v3 on Trillium: 10 families, 50 runs: the first 7, `net_bandwidth`, `cpu_weight`, `port_scan`.
- Group 1 is finished: 3 collected (D4, A2, G1), 2 removed with evidence (B3, C2), 1 parked (D7).
- VM stopped.

## Logs: evaluation and a small start (decisions with the user)

- **A log tool is a watchdog, not a judge.** Quiet means unknown, never healthy. Why: a probe on
  one run per family (37 fault runs, Sock Shop v2+v3) found 14 families with nothing in the logs.
- **Four numbers, never one accuracy**: false alarms (normal runs + the time before every
  injection), coverage per family, timing and role when it barks, added value with the agent.
- **Start with 8 families where the probe showed logs help**, not all 349 runs: dependency_outage
  / queue_backlog / svc_mem_cap, disk_full, db_table_lock / net_bandwidth, error_storm,
  code_event_loop_block. Probe: Trillium `work/logs_plan/`.
- **Probe findings worth keeping**: 13 families clear within 12 s, 10 victims-only or late;
  latency-only faults exist (db_table_lock 1.2 -> 965 ms); log text misleads (pid_limit reads
  OutOfMemoryError); the load generator's warm-up end looks like a change in every run.
- **Checked: the graph blueprints do not use our count index** (tsv.gz), only LTTng's
  `index/*.idx`. The count index is left with agent_v2, nsmap/score and the selector scripts.
  The log-to-kernel join in LOGS-PLAN was corrected to work from a slice.

## logkit built (LOGS-PLAN build steps 1 and 3)

`Blueprint/logkit/`: record, source profiles (YAML per log format), index builder, and two
blueprint tools. Organisation decisions and why:

- **Tools are standard-library only** (`logkit/tools/`), with the index format defined once in
  `logidx.py` and "what is a change" defined once in `logsig.py`. Why: the harness runs a
  blueprint's tools with a bare `python3`; the builder needs PyYAML and runs in the venv.
- **The tools read an index, never a log file.** One build per run (3.3 s for the 250 MB sample;
  73 KB index), then each tool call is ~0.1 s.
- **Warning SHARE, not warning rate.** A healthy front-end logs ~1 error per second ("payment
  declined"); under a load burst the count rises with the load, the share does not.
- **Latency as a histogram, 20 bins per decade** (~12%): a p50 over any window, exact to one bin,
  without storing 30,000 samples per method.
- **A test found a template flaw:** go-kit `result=` is a row count in catalogue (result=7) but an
  outcome in payment (result=false). Numbers in kept keys are now masked.

First real check (sample svc_cpu_cap r1, label read afterwards): onset 15:19:47 in edge-router,
injection 15:19:46; the culprit (carts) is silent, the victims complain. One run; the first-set
sweep is next.

## Steps 1-3 asked by the user (25-11, evening): second step, new tools, write-ups

**1. Second step for blueprints 25 and 30: `wait_cause.py`.** Reads the outputs of
`inside_wait.py`, `dev_delay.py` and `unanswered.py` on the same two slices and rules out what
those tools can see: a silent service, an interface queue, threads waiting for a core (0.5
thread-seconds per second), one busy thread (0.9-1.2 cores). Run on the saved outputs of all
347 sweep runs: 10 of 10 lock runs, 0 of 20 normal, 12 lookalikes left (`slow_db` 11, a delay
injected inside the database proxy; `anomaly_mem` 1). Bars set after seeing the sweep numbers.

**1b. `dev_delay.py` tells a rate limit from a fixed delay** by p95/median of the wait: 4.5-5.3
for the 5 rate-limit runs, 1.4-1.6 for all 21 netem runs. Bars 3.0 and 2.0, set after seeing.

**2. New tools.** `33_cpu_weight/tools/cpu_starved.py` (wait for a core per second of work, per
container): 5 of 5 `cpu_weight` (10.6-19.8, 4.5-8.9 times; others 0.7-0.8 times), reversed quiet,
quiet on 15 other v3 slices. Bars from the sweep's `cpu_confine` tables; a CPU quota would fire
too (stated). `34_port_scan/tools/scan_fanout.py` (different targets per source address): 5 of 5
(3,904-3,910 pairs on 262 ports, 100% refused, 4 before), reversed quiet, quiet on 15 other v3
slices; bars set before the first run. Neither new tool has been run on the 347 sweep runs (the
sweep kept no slices) - that needs a SLURM job.

**3. Write-ups.** `blueprint.yaml`, `BLUEPRINT.md` (rendered) and `RESULTS.md` for blueprints
25-34; all ten pass `bp_check.py`. Every number comes from these notes. Blueprints 27-29 share
`new_errors.py`; 25 and 30 share `inside_wait.py` + `wait_cause.py`.
