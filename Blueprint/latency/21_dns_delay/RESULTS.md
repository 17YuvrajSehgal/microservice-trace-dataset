# Blueprint 21 results (tool only, 17-11-2026)

`dns_retry.py` on every v2 run of both applications: one 60 s slice, 30 s after the injection
(normal runs: 100 s after the trace start). SLURM job 2877661 on Trillium (one node, 52 min,
shared with the blueprint 15 check), first rule. The final rule (with the restart verdict)
was rerun on `dns_delay`, `fd_exhaustion` and `svc_mem_cap` in job 2878136 (3 min). Outputs:
`work/dx_check/sweep_dq/*.dns.out`, `work/dx_check/sweep_dns2/`.

| runs | verdict (final rule) | lookups resent |
|---|---|---|
| `dns_delay` r2, r4, r5 | NAME LOOKUPS TIME OUT | 25 of 33, 28 of 32, 27 of 31 (76-88%), slowest 5.0 s |
| `dns_delay` r1, r3 | LOOKUPS TIME OUT IN A RESTARTING PROGRAM | 4 of 41, 6 of 57 (10-11%); `node` ran as 4 and 6 processes |
| `fd_exhaustion`, 5 | LOOKUPS TIME OUT IN A RESTARTING PROGRAM | 3-4 of 24-46 (9-13%); `node` ran as 4 processes |
| all other runs, 292 | NO LOOKUP TIMEOUTS | at most 1 of 75-146; `svc_mem_cap`: 8-10 of about 6,700 (0.15%) |
| 2 runs | no result: the slice cut failed (`anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5`) |

First rule (no restart verdict): the 5 `dns_delay` runs and the 5 `fd_exhaustion` runs all
read NAME LOOKUPS TIME OUT, so 5 false alarms.

Train Ticket: the rows there are host tools (`iptables`, `dockerd`, `sshd`: netlink and
other datagram sends, not DNS) and a few Java sends, none with a timeout. The Java services
do not resolve with `sendto` and `poll`, so the tool is untested there in the positive direction.
