# Train Ticket collection scripts (StrataTrace 2nd app)

Our TT-specific deployment + collection artifacts. Reuses the app-agnostic pipeline from
`../microservice-lttng-data-collection-scripts/` (collect_trace, download_metrics_full, audit,
verify engine) and `../stratatrace/` (derivers + loader, now profile-driven via `STRATATRACE_APP`).
Full spec: `PORT-PLAN.md`. The frozen Sock Shop v1 rig is untouched.

## Fork & images
- App = **`17YuvrajSehgal/train-ticket`** fork (pinned), cloned to `~/train-ticket` on the VM =
  the compose project dir. Never edited in place; our instrumentation is compose overlays here.
- **We build OUR images from the fork** (`IMG_REPO=stratatrace-tt IMG_TAG=v1`) — reproducible,
  not dependent on upstream `codewisdom/ts-*:0.2.0`.

## Stand up (on a fresh Ubuntu 24.04 VM)
```bash
git clone --recursive <this repo> ~/microservice-trace-dataset
bash ~/microservice-trace-dataset/train-ticket-collection-scripts/vm_bootstrap_tt.sh
```
Installs LTTng/Babeltrace/Docker(+overlay2), clones the fork, **builds 41 Java services (~1–2 h
first time)**, brings up base + metrics + otel, health-checks ts-ui-dashboard:8080 + prometheus:9090.

## Deploy command (reference)
```bash
export TT_SCRIPTS_DIR=~/microservice-trace-dataset/train-ticket-collection-scripts
cd ~/train-ticket
COMPOSE_PROJECT_NAME=trainticket COMPOSE_COMPATIBILITY=true IMG_REPO=stratatrace-tt IMG_TAG=v1 \
docker compose -f docker-compose.yml \
  -f "$TT_SCRIPTS_DIR/docker-compose.nacos.yml" \
  -f "$TT_SCRIPTS_DIR/docker-compose.dbenv.yml" \
  -f "$TT_SCRIPTS_DIR/docker-compose.metrics.yml" \
  -f "$TT_SCRIPTS_DIR/docker-compose.otel.yml" \
  up -d
```
The stock TT compose can't boot on its own: its source expects **nacos** discovery, **MySQL**
(`jdbc:mysql://ts-*-mysql`), and a **gateway** the compose never had. Two overlays supply them —
`docker-compose.nacos.yml` (nacos-server + `NACOS_ADDRS`) and `docker-compose.dbenv.yml` (one
shared `mysql:8` + `tt-init.sql` per-service databases + normalized `<PREFIX>_MYSQL_*` env). The
24 dead `ts-*-mongo` are removed from the base compose (all services migrated to MySQL).
`COMPOSE_PROJECT_NAME=trainticket` + `COMPOSE_COMPATIBILITY=true` → containers
`trainticket_<svc>_1` (what `service_map` and the collection tooling expect). Toxiproxy overlay
(added in Phase 1) loads last, for the slow_db/error_storm faults.

## What's here (Phase 0a — authored offline)
- `docker-compose.otel.yml` — GENERATED: OTel Java agent into all 39 Java `ts-*-service` (incl.
  the Spring Cloud gateway) via `JAVA_TOOL_OPTIONS` (no rebuild) + otel-collector → `otlp-out/spans.jsonl`.
- `docker-compose.nacos.yml` — nacos-server + `NACOS_ADDRS` (TT source needs nacos discovery).
- `docker-compose.dbenv.yml` + `tt-init.sql` — one shared `mysql:8` + per-service databases +
  normalized `<PREFIX>_MYSQL_*` env (TT source uses MySQL; the 24 dead mongos were removed).
- `docker-compose.metrics.yml` + `prometheus-tt.yml` — Prometheus + node-exporter + cAdvisor.
- `agents/otel.properties`, `agents/otel-collector-config.yaml` — reused generic dual-export.
- `load_generator.py` — TT booking flow (login→search→book→pay), identical CLI/CSV; `--probe`
  prints a live login+search to validate/fix the API before a real run.
- `vm_bootstrap_tt.sh`, `PORT-PLAN.md`.

## Analysis (profile-driven, no per-app copies)
```bash
STRATATRACE_APP=trainticket python3 ../stratatrace/derive_kernel_l1.py <run_dir> --reader cli
STRATATRACE_APP=trainticket python3 ../stratatrace/derive_kernel_l2.py <run_dir>
```
`service_map`/L2 pick the trainticket profile (68 containers → `trainticket_<svc>`).

## TODO (Phase 0b/1 — needs the live stack)
- [ ] `load_generator.py --probe` on the VM → confirm/fix the exact TT API paths + payloads
      (login body, trips/left body, preserve/pay bodies) against the running services.
- [ ] `collect_trace.sh` container allow-list + LTTng session names → TT (parameterize via env,
      keep sockshop default). `fault_lib.sh` CONTAINER_PREFIX → `trainticket`.
- [ ] `agents/otel-to-lttng.py` (TT) — relay a representative subset to UST (clock bridge), or
      rely on clock anchors.
- [ ] Toxiproxy overlay + config on a TT DB path (for slow_db/error_storm).
- [ ] Fault recipes: repoint svc-targeted (slow_db/error_storm/dependency_outage/svc_*) to TT
      services; re-model `queue_backlog` (TT has no rabbitmq queue-master); host stressors port free.
- [ ] `verification_targets.json` (TT) — new fault keys, PromQL (cAdvisor + span-derived, since
      TT lacks actuator/prometheus), re-calibrated magnitudes.
- [ ] Alignment gate: one run with six-modality audit OK → go/no-go.
- [ ] Decide tracing-scope + campaign size (67 containers → large traces; see PORT-PLAN §scale).
