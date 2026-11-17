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
