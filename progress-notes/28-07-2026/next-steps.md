# Next steps — as of 28-07-2026 (end of day)

## Status: Phase 0 DONE. Phase 1 (fault calibration) is next.
The VM gate that blocked the collection campaign is cleared — all six
modalities time-aligned (see decisions.md). The collection rig is fully
verified AND now scripted end-to-end, so re-running on any VM is fast.
VM is stopped (disk persists).

## Fast resume on the VM (should now take minutes, not hours)
```
gcloud compute instances start stratatrace-collector --zone=us-east1-b
gcloud compute ssh stratatrace-collector --zone=us-east1-b
# on the VM:
cd microservice-trace-dataset && git pull
# if the stack isn't up after a stop/start, re-run the last stage of:
microservice-lttng-data-collection-scripts/vm_bootstrap.sh
# sanity re-check any time:
microservice-lttng-data-collection-scripts/run_gate.sh gatecheck
```
If anything misbehaves, `microservice-lttng-data-collection-scripts/TROUBLESHOOTING.md`
has every gotcha from the first bring-up with its fix.

## 1. Phase 1 — fault calibration (VM; the real next work)
For each fault recipe in `faults/`, run it under tracing+load and confirm the
pre-registered signature actually appears; tune subtle/aggressive intensities:
- **noisy_neighbor** is the critical one — its whole premise is "service KPIs
  barely move while kernel contention is blatant." Tune the cpu cap so the
  service p95 stays within normal variance (needs real KPI observation).
- slow_db / error_storm / svc_cpu_cap / svc_mem_cap / dependency_outage /
  queue_backlog: verify each expected-winning-modality signature (fault_catalog.md §5).
- Drive each with a fault-aware version of run_gate.sh (baseline → inject →
  recover windows). TODO: generalize run_gate.sh to run_scenario.sh that
  takes a fault recipe + injects mid-run and records the window.

## 2. Phase 1 — verify_injection.py (can start locally)
Automated per-run QC: read a run's Prometheus export + the recipe's
ground_truth.json, compute baseline/injection/recovery deltas vs the fault's
declared target metrics, write confirmed|borderline|unconfirmed + an impact
PNG. Buildable locally against a stress container; thresholds calibrate on VM.

## 3. Deferred rig hardening (nice-to-have, not blocking)
- Tier-2 instrumentation (user, payment) — same Go/otelhttp pattern as
  catalogue; needed before the full campaign, not before Phase 1.
- Kernel L1–L3 derivers (representation ladder) — needs real CTF; the gate
  runs now produce fixtures to develop against.

## 4. Mentor items (unchanged; only decisions outstanding)
- Venue split: study paper to MSR technical track vs FSE/EMSE.
- Approve dataset name **StrataTrace**.
- Review fault_catalog.md pre-registrations BEFORE the Phase-2 freeze.

## Pacing
Jul 28; MSR abstract Nov 5 (~14 wks). Phase 0 done ~on plan. Phase 1
calibration + verify_injection is ~1 week, then the Phase-2 campaign
(~1–2 days of runtime for ~200 runs).
