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

## Execution (same day, on the VM)
- **Tracepoint reality on kernel 7.0.0-1014-gcp:** `mm_vmscan_*` (14 events incl.
  `mm_vmscan_memcg_reclaim_begin/end`) and `writeback_*` EXIST. `oom_*`, `mark_victim`,
  `mm_compaction_*`, `mm_migrate_*` do NOT exist on this stock GCP kernel. This is fine: the enable
  loop in collect_trace.sh is `|| true` per group, so missing wildcards enable 0 and the missing
  NAMED event `mark_victim` fails harmlessly. The guard greps `mm_vmscan` which DOES match → count
  >0 → no false alarm. So the fix is sound here; only the `mm_vmscan_*`/`writeback_*` half of the
  KERNEL_MEM=1 set actually captures on this kernel, which is exactly the reclaim signal we need.
- **Bootstrap gotcha (worth a TROUBLESHOOTING line):** vm_bootstrap adds the user to the `docker`
  group but its own running shell doesn't get the group → docker calls loop on "permission denied".
  Fix: let it finish the non-docker steps, then relaunch bootstrap in a FRESH login shell (has the
  group). SSH from Windows plink is flaky; use WSL ssh to the external IP with the gcloud key.
- **gate01: six OK** on the fresh VM (trace 39 spans, logs 4081/11 w/ trace_id, load 484 req,
  metrics 541 series, kernel 1.6M events, clocks 0.000 ms drift). Pipeline validated.
- **Collection launched:** `collect_wave2.sh mem` = 3×anomaly_mem + 3×svc_mem_cap, all KERNEL_MEM=1
  (both families had the same wildcard bug in v2). ~24 min collect + metrics/verify/audit.

## Result — fix PROVEN
- All 6 runs collected. Verify: anomaly_mem 3/3 confirmed; svc_mem_cap r2+r3 confirmed, r1
  "unconfirmed" (explained below). (`collect_wave2.sh` summary "6/6 confirmed" is a grep bug —
  `grep -c confirmed` matches "unconfirmed" too.)
- **DECODE PROOF (the whole point):** svc_mem_cap r2 injection window (23:36:21..23:38:21) contains
  **78,418 mm_vmscan events**, incl. **1,238 mm_vmscan_memcg_reclaim_begin + 1,238 _end** pairs
  (sample `nr_reclaimed=3676`), 6,980 lru_shrink_inactive, 31,517 shrink_slab pairs. In v2 this was
  **ZERO**. The memory blueprint now has its signal.
  - Fast-decode lesson: babeltrace2 text sink is too slow to scan a whole ~20 GB trace; and bt2
    Python (object-per-message) is worse. The fast path is `--begin/--end` with the CTF **index/**
    dir present (seek). My gunzip-to-/tmp step must copy `index/` too, not just metadata+channels.
- **svc_mem_cap r1 "unconfirmed" is NOT a failed injection.** The `-m 160m` cap was applied for
  100% of the window (`fraction_above_threshold=1.0`, `injection_mean=167772160`=160 MiB). It failed
  only `direction_ok`: the canonical check wants the limit to *decrease*, but carts started with no
  limit → Prometheus reports `0`, so `0→160M` reads as an increase. r2/r3 confirm because their
  baseline is the restored host-total (42 GB→160M = real decrease). This is a pre-existing
  `verify_injection.py:116` bug (treats `0`=unlimited as a real number). Fix proposed, not yet
  applied — do NOT silently flip r1 to confirmed (no-falsification rule).

## Transfer + replacement (Trillium)
- Pulled via `pull_from_vm.sh` (Trillium dials the VM, restricted `ss_vm` forced-command key).
  Setup gotchas fixed: export_recipe `SRC` was `/mnt/archive/runs` (old VM's archive disk) → set to
  `/home/17yuv/traces`; metrics/load live in `$HOME` not `~/traces` → moved into the recipe dirs so
  the bundle is complete; `pull_from_vm.sh` uses strict BatchMode → had to `ssh-keyscan` the VM into
  Trillium `known_hosts` first.
- Staging: `v2/sockshop-mem-20261029/` (svc_mem_cap 9.46 GB, anomaly_mem 10.87 GB, normal 186 MB).
- Replacement: old `sockshop/{svc_mem_cap,anomaly_mem}` MOVED to
  `sockshop/_superseded_no_memcg_20261029/` (reversible, not deleted); new runs extracted in place.
  NOTE new set = 3 aggressive each (old had 5 aggressive + 3 subtle) — smaller but has the signal.
- Format note: old Trillium runs store kernel channels RAW; new runs arrive GZIPPED
  (channel0_*.gz). Must gunzip the new channels before the index rebuild (babeltrace can't read .gz).

## Index rebuild + verify fix (user decisions: collect parity + fix verify/re-verify r1)
- Index: gunzipped new channels, quarantined 16 old index files to
  `index-v2/_superseded_no_memcg_20261029/`, rebuilt index-v2 for the 6 new runs
  (`build_ctf_index.py <run> --out-root index-v2`, ctf_subdir defaults to kernel/kernel).
  CONFIRMED the index itself carries the signal: `svc_mem_cap_r2.tsv.gz` has 927 mm_vmscan rows
  incl. mm_vmscan_memcg_reclaim_begin/end counts. `.lines.gz` not built by default (`--with-lines`
  is opt-in) → rebuilding with it for dataset consistency with the old runs.
- **verify_injection.py fix (committed):** the decrease check read a limit metric's baseline 0 as
  a real number; a cap from unlimited (0→160M) looked like an INCREASE. Fixed: baseline 0 on a
  limit metric (promql has spec_memory_limit/cpu.max/..., or a `zero_is_unlimited` flag) is treated
  as +inf. Scoped so genuine zero-baseline decrease metrics are unaffected. 2 self-test cases added;
  all 8 pass. **r1 RE-VERIFIED → confirmed** (honest: 160 MiB held 100% of window); corrected
  verification.json/png copied to Trillium. Now all 3 aggressive svc_mem_cap runs confirm.
- **Parity collection (user chose this):** collecting 10 more on the VM to match old depth —
  svc_mem_cap {aggr r4,r5; subtle r1,r2,r3} + anomaly_mem {aggr r4,r5; subtle r1,r2,r3}, all
  KERNEL_MEM=1. (collect_wave2's matrix has no svc_mem_cap subtle, so driven via run_scenario.sh
  directly.) Then transfer + index, then DELETE the VM.
- Transfer-script gotcha fixed: `pull_from_vm.sh` uses strict BatchMode → `ssh-keyscan` the VM into
  Trillium known_hosts first (added to the lessons; the script could do this itself).
