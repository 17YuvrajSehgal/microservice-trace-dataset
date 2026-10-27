# Train Ticket — by-hand judgment (see ../../JUDGING.md)

**TT is not a clean testbed.** Judged from the TRACE + recipe (not the metric `verification_status`,
which is unreliable for TT — the documented `no_metric_signature` issue). Most TT injections did
not produce clear kernel-visible harm, for reasons in the dataset, not the agent. The agent's
conservative "normal / not proven" verdicts on non-biting injections are correct, not misses.

| blueprint | by-hand | what actually happened |
|---|---|---|
| **slow_db** | **4/8 DETECTED** | the one TT family that bit kernel-visibly. All 4 aggressive-500 ms caught (db_latency via toxiproxy / the MySQL endpoint, windows match). Misses: 2 subtle-60 ms (below TT's natural variance), 1 "other", 1 "normal". |
| svc_cpu_cap | — not evaluable | caps did not bite. `ts-travel-service` idle under load (CPU 0.003→0.005 cores vs a 0.2-core cap); all 8 `verification_status=unconfirmed`, sigma ~2. Agent correctly says normal / "suspected not proven". |
| noisy_neighbor | — not evaluable | 2–4 stress-ng workers on a **16-CPU host → host stayed 63–84 % idle**, so no victim contention existed. Agent correctly identified the stress-ng workload (named in 6/8) but correctly declined to call it harmful. r4: agent even found the noisy container's own 2.0-core cap. Injection too weak to be "noisy". |
| svc_net | — inconclusive | ts-basic-service traffic **collapsed** in the injection window (consistent with netem delay) but with no retransmissions (`net_loss` found no TCP segments — traffic dropped to ~0) and amid 60 services' natural load swings. Agent read the collapse as reduced workload. Ambiguous; verification unconfirmed. Not a clean miss or detect. |
| svc_mem_cap | — not evaluable | no memcg tracepoints in the profile (same as Sock Shop). |

## Honest conclusion

On Train Ticket, only **slow_db (aggressive)** produced a clear kernel-visible fault, and the
agent **detected it 4/4** (plus 0/2 on the subtle-60 ms variant). Every other TT family either
did not bite (cpu idle service; noisy-neighbor too weak on a 16-core host), is ambiguous (net
collapse without retransmission), or is not collectable (mem). This is a **dataset-intensity /
collection limitation of Train Ticket v2**, consistent with the known `no_metric_signature` and
re-collection notes — **not** an agent or blueprint weakness: where TT's fault was actually
visible (aggressive slow_db), the agent performed as it does on Sock Shop.

**Do not cite TT detection rates as agent performance.** The citable TT fact is narrow and honest:
of the TT injections that produced a clear kernel signature (aggressive slow_db), the agent
detected 4/4.
