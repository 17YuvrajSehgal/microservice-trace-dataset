# 2026-10-29 — svc_mem_cap re-collection (ICSE plan P3.1)

## The real bug (root cause of "svc_mem_cap not evaluable on microservice")
`collect_trace.sh` KERNEL_MEM=1 enabled `vmscan_* compaction_* migrate_*`, but the kernel
tracepoints are named `mm_vmscan_* mm_compaction_* mm_migrate_*` (verified in the agentic traces:
mm_vmscan_memcg_reclaim_begin/end). LTTng wildcards match from the START of the event name, so
`vmscan_*` matched NOTHING. `collect_wave2.sh` DOES set KERNEL_MEM=1 for svc_mem_cap/anomaly_mem,
so v2 *intended* to capture reclaim but silently recorded ZERO memory events. That is why the
memory blueprint had no signal and svc_mem_cap was "not evaluable."

**Fix (committed 2b22bb0, pushed):** KERNEL_MEM=1 -> `mm_vmscan_* writeback_* mm_compaction_*
mm_migrate_* oom_* mark_victim`; KERNEL_MEM=full -> `mm_* kmem_* ...`. Added a loud post-enable
GUARD that fails visibly if no mm_vmscan/oom events enabled, so this can never silently recur.

## Re-collection VM
- `stratatrace-ss-mem`, project **teleeporter** (account **aylabsltd@gmail.com**), zone us-east1-d,
  **n2-custom-12-40960** (12 vCPU / 40 GB), 200 GB pd-balanced boot, Ubuntu 24.04.5,
  kernel 7.0.0-1014-gcp, LTTng 2.15.3. Same shape as the Sock Shop collector.
- Plan: clone --recursive (has the fix) -> vm_bootstrap.sh -> run_gate.sh gate01 ->
  collect_wave2.sh (svc_mem_cap, KERNEL_MEM=1, now captures mm_vmscan) -> VERIFY memcg events in
  the trace -> pull to Trillium -> build index -> re-run svc_mem_cap eval -> DELETE the VM.
- Only svc_mem_cap needed (8 aggressive + subtle). 200 GB boot is enough; no 1 TB archive (avoids
  orphan-disk billing).

## Must-verify before trusting the runs
The GUARD prints "KERNEL_MEM verified: N memory/reclaim events enabled". Also decode a sample and
confirm mm_vmscan_memcg_reclaim_* actually appear with non-zero counts in the injection window —
the whole point is that the memory blueprint now has its signal.
