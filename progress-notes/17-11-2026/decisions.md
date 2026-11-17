# 17-11-2026

## Blueprints 2, 4, 5 on the Train Ticket anomaly runs, and a real bug in `net_loss.py`

Tool only, Trillium, no API. Outputs: `work/anom_check/` (Sock Shop), `work/anom_check_tt/`.

**Train Ticket, 83 slices.** `anomaly_cpu` 5/5 (`stress-ng-cpu` x32 = 59-61% of all CPU, absent
before and in 5 normal runs). `anomaly_mem` 8/8 consumer named (one `stress-ng-vm` request of
22,503 MB = ground truth; none in 29 other slices). The network runs were wrong: `svc_net` read
0 retransmits on 5/5 runs with 4% loss injected.

**The bug.** `net_loss.py` bucketed a flow by (device, net_ns of the context). The first copy of
a segment leaves in the sender's context, the retransmit leaves from a timer in another one, so
the two copies were never matched. It hid most retransmits on Sock Shop and all of them on Train
Ticket. Fixed: bucket by device name only.

**What the fix exposed.** Healthy Sock Shop slices then show 50-110 retransmits per 10 s, all
toward the front-end: a 5-byte last segment re-sent 3-15 ms later, both copies delivered. These
are tail-loss probes (the receiver is slow to ACK), not loss. So "retransmits" cannot be the
signal. The signal is now **DROPPED**: a segment seen more often at the sender's own interface
than at the next device, i.e. thrown away by the sender's queue. It also names who loses.

| slices (10 s unless said) | dropped | tool says |
|---|---|---|
| healthy, both apps, 36 slices | 0 in every one | no queue drops |
| SS `svc_net` 5 | 236-283, one sender | ONE-PATH, carts, 100% |
| SS `anomaly_net` 8 | 124-239, 8-10 senders | HOST-WIDE, largest 21-28% |
| TT `svc_net` 5 | 5-19, one sender | ONE-PATH, ts-basic-service (port 15680), 100% |
| TT `anomaly_net` 8 | 5-24 (10 s), 13-33 (30 s) | HOST-WIDE 8/8 at both lengths; 7-13 senders at 30 s |

Rules tried and dropped on the way, each wrong on real slices: "largest sender >= 60% of
retransmits" (2 of 13), "<= 3 senders with 3+ retransmits" (fails when traffic collapses on TT),
"top address is an end of >= 90% of retransmits" (healthy runs read as one path).

Consequences:
- The old numbers in blueprint 5 (4 retransmits in 90,107; 1.4-3.2% per flow) and every earlier
  `svc_net` / `anomaly_net` result made with this tool undercount. README says so.
- RUNS-TRACKER has TT `svc_net` as "inconclusive, no retransmission signal". That was the bug:
  the fault is visible (5/5). Not yet re-scored with the agent.
- Under 20 drops the tool asks for a 30 s slice (TT traffic falls to ~1,000 segments per 10 s).
- Limits: a flow seen at one device only (traffic leaving the host) cannot be placed; pure delay
  with no loss gives no drops.

TT memory caveats: no `mm_vmscan_*` events at all, so reclaim is invisible and only the large
request is seen; "kswapd active" also fires on normal TT runs (92-483 events), so it proves nothing.

## `resource_abuse` with blueprint 2's tools (tool only, 5 Sock Shop + 5 Train Ticket runs)

The recipe: a Python container, 4 hashing threads capped at 2 CPUs, plus a TCP connect to a
local listener (port 18098) every 5 s. Outputs: Trillium `work/ra_check/`.

| | before | inside the fault |
|---|---|---|
| SS CPU busy | 64-66% | 77-79% |
| SS `python3` group (`cpu_hogs.py`) | 2 procs, 5% of all CPU | 4 procs, 12-13% |
| TT CPU busy | 9-11% | 19-20% |
| TT `python3` group | 2% | 12-13% |
| the hog in `sched_budget.py` | absent | one new pid in a new pid_ns, run 0.95-1.01 (about one core: the 4 threads share the GIL) |
| `connect()` to port 18098 from the hog's pid, 60 s | not cut | 11-12, every 5.1-5.5 s, 10/10 runs |

Reading:
- Blueprint 2's tools see the CPU user in 10/10, but `cpu_hogs.py` groups by NAME and the hog is
  called `python3` like the load generator, so it shows as a bigger old group, not a new one. The
  blueprint's "is it NEW" test then needs the per-pid table. Grouping by container (pid_ns) would
  fix it. Not done.
- The victims barely suffer (SS dockerd wait 0.70 -> 1.32 s per 10 s; TT nothing waits, the host
  is 80% idle). On TT blueprint 2 would stop at Step 4 with "no CPU competition".
- The beacon, which is the recipe's whole point, is plainly in the trace (10/10) but no tool
  looks for it. On SS r1 only two other (process, port) pairs connect 6-20 times a minute.
- On TT the group row (+16.5 s on-CPU per 10 s) and the per-pid row (run 1.01) disagree. Not chased.

## Blueprint 18 `resource_abuse` built (`beacon.py`)

Rule: one pid that is BOTH CPU-heavy (>= 0.5 cores in a 10 s scheduling slice) and a periodic
connector (>= 5 `connect()` to one destination, gaps >= 1 s, jitter <= 10%, no gap more than
35% off the median). Periodic alone is not enough: `prometheus` (5 s) and the Train Ticket
database pool (10 s) are periodic. CPU alone is blueprint 2.

Swept on all 304 v2 runs as a SLURM job (2875043, one Trillium node, 28 min; sweeps no longer
go on the login node): 10/10 labelled runs, 0 false alarms in 292, 2 runs with a failed slice
cut. Margin: smallest hog 0.93 cores, largest other periodic connector 0.15. The first-guess
bars held, so none was tuned after seeing the sweep.

Limits written in the README: the trace cannot tell "unauthorised" from a legitimate poller
with the same shape; a heartbeat on an open connection is invisible; only the aggressive
setting exists (the 15 s / lighter variant was never collected).
Not done: agent run; index for this family; `cpu_hogs.py` still groups by name.

## Blueprints 19 `data_exfiltration` (`egress.py`) and 20 `nagle_delayed_ack` (`ack_stall.py`)

Both read one 10 s `net_dev_queue` slice. Swept on all 304 v2 runs as SLURM jobs (2877411,
then 2877421 with the final rule; one Trillium node, 4.5 min each).

**19.** Rule: one stream (source address -> destination address:port) with >= 5 MB/s TCP
payload, <= 1% payload coming back, flowing in >= 90% of the seconds. No baseline needed,
unlike the old-tree blueprint (gain per process against a baseline window). 10/10, 0 false
alarms in 293. Fault 41.9-42.0 MB/s; largest steady one-way stream elsewhere 2.96 MB/s
(`toxiproxy` relaying database results on Train Ticket). Why all three conditions: telemetry
export and database results are also one-way and steady, so direction alone does not separate.
Limit: the recipe's 5 MB/s setting was never collected and would sit on the bar.

**20.** Rule: per connection, count the pattern data / >= 20 ms silence / bare ACK / data
from the same side within 2 ms. Verdict needs >= 10 of them, >= 80% within 10% of the median,
and >= 20% of the slice spent waiting. 10/10, 0 false alarms in 293.
- The third bar was added AFTER the first sweep: one healthy run (`svc_mem_cap` r3) had a
  `node` telemetry connection with exactly 10 stalls of 40.6 ms (0.41 s of 10 s). It is the
  real interaction, only too small to matter. Fault connections wait 46-82% of the time.
- Lossy/delayed paths (`svc_net`, `anomaly_net`) make 10-22 such patterns per connection, but
  at spread-out lengths (0-60% at one length). The one-length test is what separates them.
- **Ground truth mismatch:** `expected_stall_ms` is 100 (from a smoke run). All 10 runs show
  40.6-40.9 ms, the usual Linux delayed-ACK minimum. Not corrected in the dataset; noted here
  and in the README.

Bug caught by the self-test: `name = "..."` also matches `procname = "..."`, so the device
was read as the process name. Fixed with a leading space.

Not done: agent run on 18, 19, 20; `anomaly_mem_subtle_steady_r3` still cannot be sliced.

## `dns_delay` (blueprint 21, `dns_retry.py`) and `queue_backlog` (covered by blueprint 15)

Jobs: 2877661 (both tools on all 304 runs, 52 min), 2878136 (dns final rule, 3 min),
2878132 and 2878303 (`freeze_moment.py` on 95 runs, 25 min each). One Trillium node each.

**dns_delay.** The direct signal is the resolver's own retry: `sendto` with an address,
`poll` returns 0 after 2.5 s, the same thread sends again on the same socket. Chosen over the
old-tree signal (share of EMFILE among failing syscalls), which is a side effect.
- r2, r4, r5: 76-88% of the front-end's lookups are resent. r4 is NOT a failed injection (the
  campaign notes say it is, because no metric moved).
- r1, r3: the front-end crash-loops (4-6 pids in 60 s), 10-11% resent. Same numbers as the 5
  `fd_exhaustion` runs, where the resolver is healthy. So those two runs are not usable as
  clean positives. Whether the DNS fault caused the first crash is not shown.
- Rule change after the sweep: a program that ran as more than one pid in the slice gets
  "LOOKUPS TIME OUT IN A RESTARTING PROGRAM" and not the fault verdict. Before that, 5 false
  alarms (`fd_exhaustion`).
- Limit: musl-style resolvers only (sendto + poll). One program, one application.
- Also seen, not chased: during r1 `traefik` makes up to 8,000 lookups per 10 s through
  dockerd to systemd-resolved, and it goes on after the injection ends.

**queue_backlog.** Same mechanism as `dependency_outage` (`docker pause`), so no new
blueprint: blueprint 15 covers it. But the full sweep showed that blueprint 15's
`ns_silence.py` is not reliable alone: it finds 15/15 frozen containers and also fires on 80
of 288 other runs (68 on Train Ticket: idle `openresty`/`toxiproxy`, helpers that ended
between the slices, collapsed traffic). The earlier "0 false alarms" was on 18 runs.
- Fix: `freeze_moment.py`. A freeze makes every thread of the container run once to park
  itself, also the sleeping ones: 19-143 threads scheduled out within 0.1-1.7 ms, 13-133 of
  them woken from >= 1 s of sleep. Idle services go quiet one thread at a time.
- Rule change after the first pass: "3 threads woken from sleep" was added, because an idle
  `toxiproxy` (small Go program, all threads park together) read as frozen in 3 runs.
- Result of both steps: 15/15, 0 false alarms in 288 (75 rejected, 5 correctly "exited").
  Run on every namespace without the Step 3 name it still has 3 false alarms (toxiproxy, 7
  threads, 3-4 woken). Not tuned further: a count bar between 4 and 13 would be fitted.
- The trace cannot tell `queue_backlog` from `dependency_outage`: accepted connections in the
  baseline are 0-1 per 10 s for both. The label depends on what the container is.

Not done: agent runs on 15 (new Step 3b), 18-21; rca-studio vendored copies not synced.

## `anomaly_cpu` and `anomaly_mem` (covered by blueprints 2 and 4, no new folders)

Job 2879026 (both checks on all 304 runs, one Trillium node, 16 min).

Both faults are one `stress-ng` container, the mechanism blueprints 2 and 4 already describe,
and their tools had been tried on the Sock Shop runs on 16-11. Missing were a verdict line and
a full-dataset check. So no new blueprint, two tool changes.

**anomaly_cpu.** New `cpu_newcomer.py` in blueprint 2: CPU time per container (pid namespace;
host programs by name) in a baseline slice and a fault slice. Chosen over extending
`cpu_hogs.py`, which groups by process name only and has no baseline.
- "FILLS THE MACHINE" (newcomer >= 25% of cores, machine < 5% idle): 10/10 `anomaly_cpu`, 0 in
  294. Fault runs: 54-61% of cores, 0% idle. Closest other: 29% of cores, 42% idle.
- "MACHINE NOT FULL": all 16 `noisy_neighbor` (exactly 1.0 or 2.0 cores), but also 66 other
  runs (the injected workload of `anomaly_mem`, `lock_contention`, `priority_inversion`,
  `nagle_delayed_ack`, `resource_abuse` uses about one core; restarted JVMs in `svc_mem_cap`).
  So that verdict names a newcomer, not a family. The bars were set before the sweep and
  not changed.
- Limit: only the aggressive setting was collected. The subtle one (half the cores at 50%)
  would not fill the machine.

**anomaly_mem.** `mem_pressure.py` (blueprint 4) already listed large `mmap` requests; it now
ends with a verdict (one writable anonymous request >= 4 GB) and the CPU time the process
used after the request (it is touching the pages).
- 16/16 (22.0-34.5 GB, 13-28 s of CPU in the 30 s slice), 0 in 288; no other run has a
  request of 256 MB or more in the 30 s from the injection.
- Train Ticket: 2-4 `stress-ng-vm` processes make the same 22 GB request within 30 s, so the
  consumer is restarted there. Cause not shown (no reclaim or OOM events in those traces).
- The memory slice of `anomaly_mem_subtle_steady_r3` could be cut this time (30 s from the
  injection); its scheduling slices still fail.

Not done: agent runs; rca-studio vendored copies not synced.
