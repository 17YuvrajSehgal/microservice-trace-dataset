# VM-only TODO (running list — things that need the GCP Linux VM)

**The VM (created 27-07-2026, record for the datasheet):**
`stratatrace-collector`, project `yuvraj-msc`, zone **`us-east1-b`**
(us-central1-a/b/c/f were capacity-exhausted), `n2-custom-12-40960`
(12 vCPU / 40 GB — matches the prior collection's shape for LTTng
channel-count and overhead-number comparability), 200 GB pd-ssd,
`ubuntu-2404-lts-amd64`. Keep this exact configuration fixed for the whole
campaign; all RQ4 overhead numbers come from it. Stop when idle:
`gcloud compute instances stop stratatrace-collector --zone=us-east1-b`.

Decision context: WSL2 rehearsal was considered and declined (would need an
lttng-modules build against the Microsoft kernel plus native docker-ce for
clean pid namespaces — not worth the effort). Everything LTTng-adjacent
happens on the VM only. This list is what the next VM session(s) must cover.

## Phase-0 gate (next VM session)
1. `git pull` + `git submodule update --init` (or fresh
   `git clone --recursive`).
2. Bring up the extended stack — now SEVEN `-f` files; the full ordered
   command is in the header of `docker-compose.toxiproxy.yml`. Deploy from
   the SUBMODULE's compose dir
   (`<repo>/microservices-demo/deploy/docker-compose`), not the VM's old
   standalone `~/microservices-demo` clone, so the pinned fork is what
   runs. `export TRACE_SCRIPTS_DIR=<abs path to
   microservice-lttng-data-collection-scripts>` first. Note: toxiproxy is
   part of the stack for NORMAL runs too (methodological note in that
   overlay's header).
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
   Optional in the same session: build the two instrumented Tier-1 services
   and add their overlays (front-end = root spans for every journey;
   catalogue = the most-hit service becomes trace-visible):
   `git clone -b otel-instrumentation https://github.com/17YuvrajSehgal/front-end.git && docker build -t frontend-otel:phase0 front-end/`
   `git clone -b otel-instrumentation https://github.com/17YuvrajSehgal/catalogue.git && docker build -f catalogue/docker/catalogue/Dockerfile -t catalogue-otel:phase0 catalogue/`
   then append `-f "$TRACE_SCRIPTS_DIR/docker-compose.frontend-otel.yml"`
   and `-f "$TRACE_SCRIPTS_DIR/docker-compose.catalogue-otel.yml"`.
6. THE AUDIT — run the audit tool on the sample run:
   `python3 "$TRACE_SCRIPTS_DIR/audit_alignment.py" ~/traces/<scenario>/<run> \
      --load-csv <load_results.csv> --metrics-dir <metrics_full_dir>`
   It picks the slowest request (or pass --trace-id), prints the aligned
   span tree / log lines / load rows / metric samples / kernel events
   (babeltrace2 window trim + container tid join) and a per-modality
   verdict + clock drift. All six verdict lines OK = Phase 0 complete;
   record the trace_id and the verdict block in that day's progress notes.
   (Kernel section is the one part unverified locally — first VM run
   checks it.)

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
