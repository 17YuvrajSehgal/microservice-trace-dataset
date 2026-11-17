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
