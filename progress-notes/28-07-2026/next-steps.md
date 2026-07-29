# Next steps — as of 28-07-2026 (end of day)

## Status: Phases 0, 1, AND 2 COMPLETE. Dataset collected.
- Phase 0: six-modality alignment gate PASSED.
- Phase 1: all fault recipes calibrated; verify_injection built + fixed.
- **Phase 2: collection campaign COMPLETE — 40 runs / 164 GB, 34 fault runs
  (31 confirmed + 3 borderline), zero genuine failures.** Every fault
  verified as pre-registered. See `campaign-complete.md` +
  `campaign_manifest_final.csv`.
- VM is STOPPED (us-east1-d; 164 GB dataset persists on disk). Relocation
  snapshot deleted. Old us-east1-b disk deleted.

## The dataset lives on the VM disk
`~/traces/<fault>/<run_id>/` — 40 run bundles, each with:
kernel/ (curated CTF, channel0_*.gz) + otlp/ (native spans) + ust/ + logs/
+ meta/ (+ ground_truth.json + verification.json for fault runs).
Nothing is downloaded off the VM yet.

## Next: Phase 3 — packaging + derivers + study
1. **Package the release** (needs VM): gzip the OTLP files (~1.5 GB/run ->
   ~200 MB), build the **Lite tier** (L1–L3 kernel + app modalities,
   ~20–30 GB) and **Full tier** (~120 GB compressed). Publish to Zenodo
   (Lite, DOI) + HF Datasets (Full).
2. **Kernel L1–L3 derivers** (the representation ladder) — build against the
   40 real bundles now that they exist (L1 kernel KPIs, L2 wait attribution,
   L3 NL digests). Can develop locally once a few bundles are pulled down.
3. **The modality-ablation study** (Phase 3 core): T1–T4 × modality subsets
   × 40 runs, budget-matched LLM eval + classical baselines. This is the
   study paper's empirical content (RQ1–RQ6).
4. **Loader SDK** (`stratatrace`) + datasheet + repo hygiene (vendor already
   done).

## Resume on the VM (fast path)
```
gcloud compute instances start stratatrace-collector --zone=us-east1-d
gcloud compute ssh stratatrace-collector --zone=us-east1-d
# stack only needed for MORE collection; for packaging/derivers just read ~/traces
# if stack needed: sudo docker start prometheus cadvisor
```
Gotchas + fixes: microservice-lttng-data-collection-scripts/TROUBLESHOOTING.md

## Mentor items (decisions)
- Venue split (MSR technical track vs FSE/EMSE for the study paper).
- Approve dataset name StrataTrace.
- **fault_catalog.md predictions are now effectively FROZEN** — the campaign
  is collected, so changes go via the §7 Amendment log only.

## Deferred (not blocking Phase 3)
- F12 per-container netem recipe (optional catalog extra).
- Tier-2 instrumentation (user, payment) — a v1.1 addition.

## Pacing
Jul 28; MSR abstract Nov 5 (~14 wks). Phases 0+1+2 done in the first days —
well ahead. Phase 3 (derivers + study + paper) is the bulk of the remaining
runway.
