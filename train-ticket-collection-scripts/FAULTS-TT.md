# Train Ticket fault plan — targets, blast radius, invocation

Pre-registered fault→target→**blast-radius**→modality predictions for the Train Ticket subject
(the TT analogue of `fault_catalog.md`). Blast radii are grounded in the **observed call graph**
(from the OTLP spans + the booking-flow debugging on 2026-08-04), not guessed. To be validated
against the collected data; treat as pre-registration once the TT campaign starts.

The shared fault recipes in `../microservice-lttng-data-collection-scripts/faults/` are
app-agnostic: set `CONTAINER_PREFIX=trainticket` and drive the target + ground-truth annotations
via env (all recipes now read `${EXPECTED_BLAST_RADIUS:-…}` / `${EXPECTED_WINNING_MODALITY:-…}` /
`${TARGET_TRACE_VISIBILITY:-…}`, Sock Shop defaults preserved). Validated: `CONTAINER_PREFIX=
trainticket TARGET_SVC=ts-travel-service svc_cpu_cap.sh inject subtle` caps
`trainticket_ts-travel-service_1` (cgroup `cpu.max=50000 100000`) and cleans up.

## Observed call graph (the booking flow)
```
ts-ui-dashboard (nginx :8080) ── /api/v1/* ──▶ ts-gateway-service (Spring Cloud GW, :18888)
                                                  └─ lb:// via nacos discovery ─▶ each ts-*-service
login  : ts-auth-service ─▶ ts-user-service ─▶ MySQL(ts-auth,ts-user)
search : ts-travel-service ─▶ ts-basic-service ─▶ {ts-route, ts-train, ts-price, ts-station}
                            └─▶ ts-seat-service ─▶ ts-order-service ─▶ MySQL
book   : ts-preserve-service ─▶ {ts-travel, ts-seat, ts-contacts, ts-order,
                                  ts-security, ts-station, ts-assurance, ts-food, ts-consign} ─▶ MySQL
pay    : ts-inside-payment-service ─▶ {ts-order, ts-payment} ─▶ MySQL
```
**Front door for every user path = ts-ui-dashboard + ts-gateway-service** (TT's analogue of Sock
Shop's `front-end`). **All 20 DB services share ONE `mysql`** (our coherent deployment) — so a DB
fault's blast radius is far larger here than Sock Shop's per-service DBs. This architectural
contrast (shared vs per-service DB; nacos gateway vs DNS; synchronous REST vs a message queue) is
exactly the "diverse types of systems" the multi-app dataset is for.

## Fault families → TT targets, blast radius, modality

| Family | Recipe | TT target | Expected blast radius | Winning modality | Trace vis |
|---|---|---|---|---|---|
| A_host CPU | anomaly_cpu | host | host, all services | kernel | n/a |
| A_host mem | anomaly_mem | host | host, all services | kernel | n/a |
| A_host disk | anomaly_disk | host | host, all services | kernel | n/a |
| A_host net | anomaly_net | host | host, all services | traces | n/a |
| A_host noisy | noisy_neighbor | host | host, all services (mild) | kernel | blind_spot |
| B_svc CPU | svc_cpu_cap | ts-travel-service | ts-travel-service, ts-preserve-service, ts-gateway-service, ts-ui-dashboard | kernel | covered |
| B_svc mem | svc_mem_cap | ts-order-service | ts-order-service, ts-preserve-service, ts-inside-payment-service, ts-gateway-service | logs | covered |
| B_svc net | svc_net | ts-basic-service | ts-basic-service, ts-travel-service, ts-gateway-service, ts-ui-dashboard | traces | covered |
| C_dep DB-slow | slow_db | **mysql (shared)** | **mysql + all 20 DB services + ts-gateway-service + ts-ui-dashboard** | kernel | blind_spot |
| C_dep outage | dependency_outage | ts-seat-service | ts-seat-service, ts-travel-service, ts-preserve-service, ts-order-service | traces | covered |
| E_app errors | error_storm | ts-order-service | ts-order-service, ts-preserve-service, ts-inside-payment-service | logs | covered |

### Notes / TT-specific decisions
- **`slow_db` on the shared MySQL is the headline TT fault** — one target, ~22-container blast
  radius. Inject via **Toxiproxy on the service→mysql path** (latency/bandwidth toxics) so it is
  restart-free, mirroring Sock Shop's catalogue→catalogue-db toxiproxy. TODO: insert a toxiproxy
  in front of `mysql` in the dbenv overlay and repoint the 20 services' `*_MYSQL_HOST` at it.
- **`queue_backlog` does not port directly** — TT's booking path is synchronous REST with **no
  message broker** (Sock Shop had rabbitmq + queue-master). Re-model the D_saturation family as
  **MySQL connection-pool exhaustion** (drop `--max_connections`, or a toxiproxy connection-cap on
  the shared DB) — the closest TT analogue of a saturating shared resource. Do NOT reuse the
  rabbitmq recipe.
- **Trace-visibility blind spots** (the "can kernel compensate?" RQ): TT injects the OTel agent
  into all 39 Java services, so nearly everything is trace-covered — EXCEPT `mysql`, `nacos`, and
  the 2 non-Java services (voucher=Python, ticket-office=Node). MySQL faults are therefore a clean
  trace blind spot where the **kernel** modality must carry the signal.
- **Blast-radius direction** = the SOURCE service + its UPSTREAM callers (who wait on it), not its
  downstream dependencies. A slow ts-travel-service inflates its own span and its callers'
  (preserve, gateway, ui); its callees (route/train/price) are unaffected.

## Invocation (per fault, during a `run_gate_tt.sh`-style traced run)
```bash
cd microservice-lttng-data-collection-scripts/faults
CONTAINER_PREFIX=trainticket \
TARGET_SVC=ts-travel-service \
EXPECTED_BLAST_RADIUS='["ts-travel-service","ts-preserve-service","ts-gateway-service","ts-ui-dashboard"]' \
  ./svc_cpu_cap.sh inject subtle          # ... run window ... then:
CONTAINER_PREFIX=trainticket TARGET_SVC=ts-travel-service ./svc_cpu_cap.sh cleanup
```
Ground truth (target, blast radius, winning modality, trace visibility, remediation, injection
window) lands in `$FAULT_STATE_DIR/<fault>.ground_truth.json`, same schema as Sock Shop.

## Remaining before the TT fault campaign
1. Toxiproxy in front of the shared `mysql` (for `slow_db` + connection-cap `queue_backlog` remodel).
2. `verification_targets(TT)` — per-fault automated confirmation checks (the TT analogue of
   `faults/verification_targets.json`), keyed on the TT service ports / metrics.
3. A TT campaign driver (fault × intensity × repeats) that wraps `run_gate_tt.sh` with the env above.
4. Intensity calibration on the VM (esp. noisy_neighbor "KPIs barely move", slow_db latency).
