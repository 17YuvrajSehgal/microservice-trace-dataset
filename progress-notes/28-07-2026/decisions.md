# Progress notes — 28-07-2026

## HEADLINE: Phase-0 gate PASSED — all six modalities time-aligned on the VM

Ran the cross-modality audit on a real Sock Shop run (`gate06`, GCP VM
`stratatrace-collector`, us-east1-b). Final verdict — all green:

```
trace    OK (24 spans)
logs     OK (4340 lines in window)
load     OK (468 client requests in window)
metrics  OK (207 series with samples near window)
kernel   OK (2,319,085 events in window, 6345 (container,event) groups)
clocks   OK (drift 0.001 ms over run)
```

An earlier run (`gate05`) produced the money shot: a single `POST /orders`
distributed trace spanning **front-end → orders → carts → shipping →
queue-master** (47 spans incl. the async RabbitMQ publish→consume), aligned
with 7948 in-window log lines (25 carrying the trace_id), 984 load rows, and
0.001 ms clock drift. The kernel section attributes 2.3M events to processes
by pid/tid (node/java/traefik/dockerd...). **This empirically demonstrates
the plan's core claim: one time base across kernel + traces + logs + metrics.**

Phase 0 is the gate that unblocks the Phase-2 collection campaign
(msr-research.md §10). It is now cleared.

## I drove the VM directly from the local session (gcloud compute ssh)

Non-interactive `gcloud compute ssh --command` let this session run the whole
gate remotely (no separate VM Claude session needed). Robust pattern that
emerged: for long jobs, write a script + `nohup ... & disown`, then poll a
result file with short commands — SSH sessions drop on long inline commands.

## Bugs the gate surfaced (exactly what a gate is for) — all fixed

Environment / infra:
- **cAdvisor vs edge-router port 8080 collision** → cAdvisor host port
  remapped to 8081 (scrape unaffected; it's over the compose network).
- **LTTng consumer-daemon wedge = the big one.** An interrupted run (SSH
  drop mid-collection) leaks an LTTng session; the wedged consumerd then
  makes every subsequent `lttng destroy` BLOCK FOREVER. All my "SSH exit
  128" errors were actually plink timing out on these hangs — not network
  flakiness. Soft reboot couldn't clear it; `gcloud compute instances reset`
  (hypervisor hard reset) did, and the Docker stack auto-restarted.
  ROOT-CAUSE FIX: `collect_trace.sh` now runs a bounded pre-flight
  (`timeout 10 lttng destroy`; force-kill daemons if it wedges) so this
  self-heals and can never hang the campaign.
- **Prometheus has no restart policy** → stayed down after the reboot
  (metrics empty for gate05). Restarted manually. TODO: add
  `restart: unless-stopped` to the monitoring stack (VM-todo) or a
  pre-run health check.

Audit tool (`audit_alignment.py`) — none catchable on synthetic data:
- anchor was picking `/metrics`,`/health` scrape spans → now skips
  observability self-traffic.
- kernel used the invalid v1 `--clock-gmt` flag (silent bt2 abort) →
  removed; correct bt2 trimmer `--begin/--end YYYY-MM-DD HH:MM:SS.ffffff`.
- kernel CTF was root-owned → `collect_trace.sh` now chowns the run bundle
  back to the user.
- **kernel regex could not skip the hostname token.** bt2 lines are
  `[ts] (+delta) <hostname> <event>: { cpu_id.. }`; the old pattern
  anchored after `]` and couldn't cross `host.zone.project.internal`,
  silently matching 0 of 2.3M events. Re-anchored on the event name before
  `: { cpu_id`. This was the last red.
- metrics matched by filename (curated naming) → now also matches series by
  label content, so the full raw-metric-name export is read.

## Reporting notes (for the datasheet / methods)
- Every collection-rig component is now VM-verified end to end, not just
  locally: OTLP native spans from all 6 instrumented services (2 Tier-1 +
  4 Java), cAdvisor per-container metrics, full Prometheus export (411
  metrics), lossless kernel capture, per-container logs, clock anchors.
- Measured cross-modality clock drift over a run: **~0.001 ms** — quote this
  as the alignment bound.
- The `otlp-out/spans.jsonl` collector file grows unbounded across runs
  (collect_trace slices per-run by byte offset but never truncates). Needs
  rotation for a multi-hundred-run campaign (VM-todo).

## Phase-1 tooling built (local, no faults run on the dev PC)
User constraint: do NOT run fault injection on the dev PC. So these were
built with offline unit tests only; real fault-through-Prometheus validation
is deferred to the VM (Phase 1).
- **`faults/verification_targets.json`** — the pre-registered per-fault
  target-metric panel (fault_catalog.md §6a): canonical + corroborating
  Prometheus signals per fault, with direction / σ-threshold / abs-threshold
  / min-fraction gates. 11 faults covered.
- **`verify_injection.py`** — reads a recipe's ground_truth.json window +
  the targets, queries Prometheus over baseline/injection/recovery, writes
  `confirmed | borderline | unconfirmed` + impact PNG. Handles flat baselines
  (σ undefined → abs-threshold fallback) and noisy baselines (σ computed).
  Verdict math is **regression-tested offline** (`--self-test`, 5 cases
  across all tiers + both directions, all pass). The live-Prometheus query
  path mirrors download_metrics.sh (proven) and runs on the VM.
- **`run_scenario.sh`** — the Phase-2 workhorse: continuous trace+load across
  baseline→inject→hold→cleanup→recovery, then verify + audit, emitting a run
  bundle with ground_truth.json + verification.json. Syntax-checked; VM-only
  to run (LTTng + injects faults).

## State
VM gate cleared; Phase-1 QC tooling built and offline-tested. Next on the VM:
fault intensity calibration (run_scenario.sh per recipe; tune thresholds in
verification_targets.json against real KPIs; noisy_neighbor is the critical
one), then the Phase-2 campaign. Mentor items unchanged (venue split;
StrataTrace name approval; pre-registration review before the freeze).
