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
The rig is fully validated AND the campaign infrastructure is BUILT (see
below). Scale + kernel profile finalized: **~40 runs, curated kernel, ~100GB,
fits the disk** (scale-and-kernel-profile.md). No GCS streaming needed.

**Campaign infrastructure (built + committed, syntax-checked, VM-untested):**
- `run_campaign.sh` — the ~40-run matrix driver. Resumable (skips runs with a
  runinfo_end.txt), per-run QC verdict -> campaign_manifest.csv, end summary
  flags non-confirmed fault runs. `--dry-run` and `--only <recipe>` for
  smoke-testing. Dry-run confirms exactly 40 runs.
- `run_scenario.sh` — now supports PROFILE (steady|burst) + RECIPE=normal
  (fault-free reference run).
- `load_generator.py` — `--profile burst` ramps base->peak (verified locally).
- `faults/anomaly_cpu.sh` — host CPU stressor recipe (the matrix's host fault).

**To launch the campaign on the VM (INJECTION_S>=120 is the default):**
```
gcloud compute instances start stratatrace-collector --zone=us-east1-d
# ensure stack up (prometheus/cadvisor started); then:
nohup microservice-lttng-data-collection-scripts/run_campaign.sh > ~/campaign.out 2>&1 &
```
Smoke-test first: `run_campaign.sh --only normal` (or `--only slow_db`) for a
couple runs, confirm bundles + manifest, then let the full matrix run (~1-2 days).

**Pre-campaign VM checks (small):**
1. Validate the CURATED kernel profile on the first real run (which wildcards
   match this kernel; actual per-run GB) — see scale-and-kernel-profile.md.
2. Empirically check the `anomaly_cpu` verification target live (only the
   service/app faults were calibrated; host CPU saturation may also stress the
   collector/load-gen — watch the first aggressive run).
3. `pip install matplotlib` on the VM for verify_injection impact PNGs.

**Deferred (NOT in the ~40-run matrix, not blocking):**
- F12 per-container netem recipe (VM-only, sch_netem) — optional catalog extra.

## Resume on the VM (fast path)
```
gcloud compute instances start stratatrace-collector --zone=us-east1-d
gcloud compute ssh stratatrace-collector --zone=us-east1-d
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
