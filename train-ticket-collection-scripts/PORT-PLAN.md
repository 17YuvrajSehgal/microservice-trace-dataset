# StrataTrace → Train Ticket port plan

Second distributed system for the multi-app dataset (serves the "diverse types of systems"
goal + the "second benchmark beyond Sock Shop" the plan anticipates). Mirrors the Sock Shop
rig; reuses the app-agnostic pipeline; re-authors the app-specific pieces. Working doc for the
TT track. Started 2026-08-04.

## Target profile (FudanSELab/train-ticket → fork `17YuvrajSehgal/train-ticket`)
- **~41 `ts-*-service`** microservices, nearly all **Java Spring Boot** (uniform) + `ts-ui-dashboard`
  (JS) + a gateway; **~24 per-service MongoDB** + `ts-voucher-mysql` + `redis` = **~67 containers**.
- **Docker Compose** (`docker-compose.yml`, compose **v3**, **build-from-source**, images tagged
  `${IMG_REPO}/${IMG_TAG}` — the "deploy our images" hook). Upstream is k8s-first; we use compose
  on a single large VM to keep StrataTrace's single-host LTTng model.
- **No active observability** (only a commented zipkin) → we add all 4 modalities.
- **Uniform-Java win:** the OTel Java agent injects into all ~41 JVMs via `JAVA_TOOL_OPTIONS`
  (Spring Boot honors it) + a bind-mounted agent — **no per-service source forks** (Sock Shop
  needed Go/Node forks). Only `ts-ui-dashboard` (JS) + any non-Java bit need special handling.
- Container naming: run with **`COMPOSE_COMPATIBILITY=true`** → legacy `<project>_<svc>_1` scheme
  (what all downstream tooling + the UST relay expect). Project name = compose dir.

## Repo structure (faithful to the Sock Shop pattern)
- **TT fork = pinned submodule** of this repo (base app + `docker-compose.yml`); never edited in
  place. Push a fork branch ONLY if a source/Dockerfile change is truly needed (unlikely —
  agent injection is compose-env only). "Deploy our version" = build from the fork + our overlays.
- **`train-ticket-collection-scripts/`** (this dir) = our TT artifacts: compose overlays,
  agent/prometheus/toxiproxy configs, TT `service_map`, TT `load_generator`, TT fault recipes,
  TT `verification_targets.json`, `vm_bootstrap_tt.sh`, deploy command. Reuses the generic
  scripts from `microservice-lttng-data-collection-scripts/` where they're app-agnostic.
- The frozen Sock Shop v1 rig (`microservice-lttng-data-collection-scripts/`, tag
  `strata-v1-freeze`) stays untouched.

## Reuse vs re-author (from the deployment + pipeline audits)
**Reuse as-is (app-agnostic):** `download_metrics_full.sh`, `audit_alignment.py`,
`verify_injection.py` engine, `derive_kernel_l3.py`, `loader.py`, host-stressor recipes
(`anomaly_cpu/disk/mem`, `noisy_neighbor`), `derive_kernel_l1.py` (once service_map set), the
OTel collector config + Java agent + dual-export `otel.properties`, the metrics overlay
(cAdvisor/node-exporter + Prometheus restart fix), the `collect_trace.sh` kernel/UST/clock-
anchor/OTLP-slice/gzip machinery, and the `vm_bootstrap`/`run_gate` skeletons.

**Re-author for TT (the work):**
| Artifact | What changes |
|---|---|
| TT submodule + fork | pin fork; build our images (`IMG_REPO`/`IMG_TAG`) |
| `service_map.py` (TT) | `SERVICE_CONTAINER` for ~67 `ts-*` containers; `COMM_SERVICE` (drop traefik) — **highest leverage** (drives L1/L2) |
| `derive_kernel_l2.py` SERVICE_COMM | TT runtimes: `ts-*→java`, `*-mongo→mongod`, `*-mysql→mysqld`, dashboard→node; default service set |
| `load_generator.py` (TT) | **full rewrite** — booking flow (login→query trips→book→pay); keep CSV schema + CLI so downstream is unchanged |
| `verification_targets.json` (TT) | new fault keys, PromQL/job labels, cAdvisor `name=~` regexes, **re-calibrated** magnitudes |
| fault recipes | repoint svc-targeted (slow_db/error_storm/dependency_outage/svc_*); **re-model `queue_backlog`** (TT has no rabbitmq queue-master); host stressors port free |
| stack glue | OTel overlay (inject agent into all `ts-*` JVMs), `prometheus-tt.yml` scrape jobs, `toxiproxy` on a TT DB path, `otel-to-lttng.py` service list, `collect_trace.sh` container greps |
| `collect_wave2.sh` MATRIX | repoint `carts` rows to TT target services |
| `fault_lib.sh` CONTAINER_PREFIX | match TT compose project `_1` naming |

## Hard-won lessons to bake in from day 1 (do NOT re-learn)
1. Map **ALL** container PIDs, not PID 1 — TT's Spring Boot likely uses a shell-wrapper entrypoint (java child TGID); the fix is essential.
2. Use the **babeltrace2 CLI reader** (`--reader cli`), never bt2-python (~15× slower, RAM-pressures VM).
3. **Per-container-netns netem** (`nsenter`), not on the bridge (L2-forwarded frames bypass a bridge qdisc).
4. **gzip kernel channels** post-audit (idle priority) — mandatory; raw is ~6× and overruns disk.
5. **anomaly_mem:** uncapped single-worker `--vm-hang` (a cgroup cap contains reclaim → no `mm_vmscan_`).
6. **Warm up** before overhead measurement (cold first run destroys the P95).
7. Drive SSH defensively: `setsid` detached, kill by **PGID**, minimal standalone commands, poll a result file.
8. **`--collapse-system`** on (fold host processes → one `system` bucket) for clean service tables.
9. `KERNEL_MEM=1` for memory faults; **no `kmem_*`** on this kernel — use `mm_vmscan_*` + `writeback_*`.
Plus: Toxiproxy always in-path; `docker update` gotchas (`--cpus=0` no-op, mem limit uncap via `--cpu-quota=-1`/host MemTotal); cAdvisor needs `overlay2` + Prometheus `restart: unless-stopped`.

## Scale consideration (TT-specific risk)
67 containers under full-syscall tracing → traces likely **much larger** than Sock Shop's
100–370M events/run (possibly ~1B). Mitigations to decide in Phase 1: keep the curated profile
+ gzip; consider a shorter injection window or tracing a **representative subset** of services;
budget derive time (CLI reader ~15× helps but 1B events ≈ ~80 min/run). Flag before the campaign.

## VM decision — NEW VM (keep v1 pristine)
- **`strata-tt-collector`**, `n2-standard-16` (16 vCPU / 64 GB — 41 JVMs + 24 mongos + tracing),
  Ubuntu 24.04, **~1 TB** pd-balanced (bigger app → bigger traces + 67 images), us-east1.
- Created only when ready to DEPLOY (author overlays/configs offline first — no idle billing).
- Frozen Sock Shop VM (`stratatrace-collector`, stopped) untouched as the v1 reference.

## Phased plan
- **Phase 0a — offline authoring (now):** fork ✓; TT service list ✓; author service_map(TT),
  the OTel agent-injection overlay + collector, metrics overlay (prometheus-tt scrape),
  toxiproxy on a TT DB path, `otel-to-lttng`(TT), container greps; rewrite `load_generator`(TT);
  draft fault recipes + `verification_targets`(TT); `vm_bootstrap_tt.sh` + deploy command.
- **Phase 0b — VM + gate:** create VM, bootstrap, `git clone --recursive` fork, build images,
  bring up the stack, one perfectly-aligned run (six-modality audit OK) — the go/no-go gate.
- **Phase 1 — fault calibration + verification:** calibrate each recipe on the live TT stack,
  fill `verification_targets`, confirm-rate QC; decide the tracing-scope mitigation.
- **Phase 2 — campaign:** the run matrix (mirror the ~40–46-run scale), then derive L1/L3 +
  freeze TT v1 (snapshot + tag + manifest + coverage matrix), same discipline as Sock Shop.

## Immediate next steps
1. Add the TT fork as a submodule (`train-ticket/`) + pin.
2. Author `train-ticket-collection-scripts/service_map.py` (SERVICE_CONTAINER for the 67 containers).
3. Author the OTel agent-injection overlay + collector for all `ts-*` JVMs.
4. Rewrite `load_generator.py` for the TT booking flow (needs the gateway host + endpoints).
