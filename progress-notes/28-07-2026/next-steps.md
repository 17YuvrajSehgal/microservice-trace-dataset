# Next steps — as of 28-07-2026 (end of day)

## Status: Phase 0 AND Phase 1 DONE.
- Phase 0: six-modality alignment gate PASSED.
- Phase 1: all 7 fault recipes calibrated on the VM; verification_targets.json
  corrected against reality; verify_injection built + settle-fix + regression
  tested; full run_scenario pipeline validated end-to-end on a real slow_db
  run (verify CONFIRMED, all 6 audit modalities aligned).
  See calibration-summary.md.
VM is STOPPED (disk persists, 171G free).

## Next: Phase 2 — the collection campaign
The rig is fully validated. The campaign runs run_scenario.sh over the
fault × intensity × workload × repeats matrix.

1. **Decide the campaign matrix** (fault_catalog + msr-research §5):
   ~12 faults × 2 intensities × 5 repeats (steady) + normals + a low/burst
   subset ≈ 150–200 runs. Each ~4–5 min (180–300s) + ~10GB kernel.
   Storage: ~2–4 TB raw -> resize disk or stream bundles to GCS (decide first).
2. **Use INJECTION_S >= 120** (verify_injection settle needs a settled segment;
   calibration used 40s which was marginal).
3. **Write a campaign driver** that loops run_scenario over the matrix with
   nightly QC (verification-confirmed rate per recipe; fix recipes >20%
   unconfirmed before continuing) — mirrors the loop in msr-research §10.
4. Host-stressor faults (F1–F4) need one empirical VM re-check of their
   verification_targets (only the service/app faults were calibrated live).
5. F12 per-container netem recipe still to implement (VM-only, sch_netem).

## Resume on the VM (fast path)
```
gcloud compute instances start stratatrace-collector --zone=us-east1-b
gcloud compute ssh stratatrace-collector --zone=us-east1-b
cd microservice-trace-dataset && git pull
# if stack down after stop/start: sudo docker start prometheus cadvisor
#   (or re-run the last stage of vm_bootstrap.sh)
# sanity: run_gate.sh gatecheck   (expect six OK)
```
Known gotchas + fixes: microservice-lttng-data-collection-scripts/TROUBLESHOOTING.md
Driving the VM over SSH: `pgrep -f <script>` gives FALSE POSITIVES (matches
your own SSH command string) - check bundle/log files by path instead.

## Deferred (not blocking Phase 2)
- Tier-2 instrumentation (user, payment).
- Kernel L1–L3 derivers (representation ladder) - gate runs produce fixtures.
- matplotlib on the VM for verify_injection impact PNGs (pip install).

## Mentor items (decisions only)
- Venue split (MSR technical track vs FSE/EMSE for the study paper).
- Approve dataset name StrataTrace.
- Review fault_catalog.md pre-registrations BEFORE the Phase-2 freeze
  (predictions are calibrated but not yet frozen).

## Pacing
Jul 28; MSR abstract Nov 5 (~14 wks). Phases 0+1 done ~on plan. Phase 2
campaign is ~1 week (setup + collection + QC).
