# Next steps — as of 27-07-2026 (end of day)

The local work queue is EMPTY. Everything below either needs the GCP VM or
the mentor. Full record of what was completed today: `decisions.md` §1–§12.

## Done today (summary, details in decisions.md)
- Phase-0 rig committed + independently re-verified; full-stack compose
  conformance verified; pushed (§1–§2, commit 9a44380).
- Tier-1 instrumentation: front-end (Node 20 + OTel, §6) and catalogue
  (Go modules + otelhttp, §7), both verified end-to-end locally, overlays
  merged-render-checked, branches on the forks.
- `models/` + `dataset/` vendored from adaptive_tracer @405e49e (§8).
- `audit_alignment.py` cross-modality audit tool, verified on a synthetic
  bundle (§9).
- Fault recipes: fault_lib + 7 recipes, all mechanically verified locally,
  incl. three docker-update API gotchas fixed in restore paths (§10).
- `fault_catalog.md` pre-registration: 12×4 informativeness matrix,
  per-task winners, signature cards, H1–H4, frozen scoring rules (§11).
- Name decided: **StrataTrace** (§12).

## 1. VM session (the only engineering blocker) — runbook: vm-todo.md
Phase-0 gate: bring up the extended stack (now 7 compose files incl.
toxiproxy), build the two Tier-1 images from the fork branches, run a 30 s
sample, and run `audit_alignment.py` on it. Six OK verdict lines ⇒ Phase 0
complete ⇒ Phase 2 collection can start (recipes + ground truth +
pre-registration are already in place).
Also on the VM (Phase 1 wrap-up): fault-intensity calibration (critical for
noisy_neighbor's "KPIs barely move" property), per-container netem recipe
(F12), `verify_injection.py` automation over the recipes' ground-truth
records, overhead-matrix runs for RQ4.

## 2. Mentor conversation (the only decision blocker)
- Venue split: study paper to MSR 2027 technical track vs FSE/EMSE
  (data paper target is fixed: MSR Data & Tool Showcase, abstract Nov 5).
- Sanity pass on msr-research.md + fault_catalog.md pre-registrations
  (predictions freeze at Phase-2 campaign start — mentor review before the
  freeze is the moment to amend cheaply).
- FYI: name decided (StrataTrace) — flag for approval.

## Pacing check
Jul 27 today; MSR abstract Nov 5 (14.5 weeks). Plan budgets Phase 0 through
week 2. Local prep finished ahead of schedule; the VM session is the
critical path — doing it this week keeps everything green.
