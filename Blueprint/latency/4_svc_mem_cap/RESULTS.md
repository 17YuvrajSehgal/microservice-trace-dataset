# Blueprint 4: the large-request verdict of `mem_pressure.py` on all v2 runs (tool only, 17-11-2026)

Every v2 run of both applications (304): one 30 s slice (`sched_switch|syscall_entry_mmap`)
that starts 2 s before the injection (normal runs: 98 s after the trace start). SLURM job
2879026 on Trillium (one node, 16 min). Outputs: `work/dx_check/sweep_am/*.mem.out`.

| runs | verdict | the request |
|---|---|---|
| `anomaly_mem` Sock Shop, 8 | ONE LARGE MEMORY REQUEST | `stress-ng-vm`, 34.5 GB (aggressive) or 28.2 GB (subtle), then 13.3-26.5 s of CPU |
| `anomaly_mem` Train Ticket, 8 | ONE LARGE MEMORY REQUEST | `stress-ng-vm`, 22.0 GB, then 17.8-27.6 s of CPU; 2 to 4 processes made the request (restarted) |
| all other runs, 288 | NO LARGE MEMORY REQUEST | no request of 256 MB or more |

16 of 16, 0 false alarms in 288. The bar is 4 GB.

Not shown by this check: that the host was short of memory. On Sock Shop the reclaim events
show it (README Step 3). The Train Ticket traces have no reclaim events.
