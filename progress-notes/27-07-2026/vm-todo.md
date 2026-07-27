# VM-only TODO (running list — things that need the GCP Linux VM)

Decision context: WSL2 rehearsal was considered and declined (would need an
lttng-modules build against the Microsoft kernel plus native docker-ce for
clean pid namespaces — not worth the effort). Everything LTTng-adjacent
happens on the VM only. This list is what the next VM session(s) must cover.

## Phase-0 gate (next VM session)
1. `git pull` + `git submodule update --init` (rig at commit 9a44380+).
2. Bring up extended stack: `export TRACE_SCRIPTS_DIR=...` + the four `-f`
   compose files (usage headers in docker-compose.metrics.yml / .otel.yml).
3. Sanity checks before tracing:
   - spans arriving in `otlp-out/spans.jsonl` while browsing the front-end
     (also confirms the `user: "0:0"` collector can write the bind mount);
   - `container_*` series in Prometheus (cAdvisor privileged mounts work on
     a real Linux host — unverifiable under WSL/Windows);
   - otel-collector healthy in `docker ps`; UST relay still parses the
     agents' logging output (dual export unchanged format — spot-check).
4. `chronyc tracking` available for the clock anchors (GCP images ship
   chrony; snapshot falls back to timedatectl, but confirm which fires).
5. Run one 30 s sample (`sample_normal.sh` pattern).
6. THE AUDIT: one request traced across all four modalities — load CSV row →
   OTLP span tree → log lines → metrics window → kernel syscalls via
   pid↔container join. Passing = Phase 0 complete; record the audit in that
   day's progress notes with the trace_id used.

## Later VM sessions (Phase 1+)
- tc/netem + tbf fault recipes (need sch_netem etc. — kernel-module
  dependent, untestable locally) and per-container netem (nsenter/pumba).
- stress-ng recipes under live tracing (lossless-buffer confirmation at the
  new run lengths 180–300 s; disk headroom check at ~8 GB/100 s kernel).
- Subtle-intensity calibration for every fault recipe (needs real
  service-KPI response, not emulatable locally).
- verify_injection.py end-to-end against real injected faults.
- Overhead matrix for RQ4 ({baseline, +metrics, +logs, +otel, +lttng, all})
  — ALL performance numbers come from the VM, never from local machines.
- Full Phase-2 collection campaign.

## Standing rule
Local PC = pipeline mechanics, image builds, userspace fault recipes,
analysis code. VM = anything touching LTTng, kernel modules, performance
numbers, or the published dataset.
