# Decisions — 04-08-2026 (branch `agentic-tracing`)

## Batch L1+L3 re-derivation across all runs — COMPLETE + clean

Ran the full clean re-derivation (after the shell-wrapper TGID fix + system-collapse) with a
proper pre-flight and an auto-stop watcher. Outcome:

- **46/46 runs OK, 0 failures.** Batch ran ~10.5 h (01:55→12:18 UTC), concurrency 2. Every
  real run now has fresh `kernel_l1.parquet` + `kernel_l3.jsonl` with the corrected mapping.
- **Quality sweep across all 46 parquets:** service count 16 (×32) / 17 (×14) — tight, no
  outliers; **java split present in 46/46** (carts + orders as distinct services);
  `kernel` + `system` buckets in 46/46; **0 runs** with >25 services or leftover
  `system:<comm>` noise. The fix + collapse held across every fault family.
- **Auto-stop worked:** guest-shutdown watcher fired on the `BATCH DONE` marker
  (`DONE_marker=1 ok=46 fail=0`) → VM TERMINATED at 12:19, no idle billing. Outputs persisted
  on the boot disk; started briefly only to read the tally + run the sweep, then stopped again.

### How we got here (this session)
1. Spotted that the first batch left `n_services`≈100–150 (raw `system:<comm>` proliferation)
   and was re-deriving 4 superseded calibration runs. User chose to redo it clean rather than
   post-process the dataset.
2. **`--collapse-system`** (default on): fold non-container host processes → one `system`
   bucket; real services + `kernel` (kswapd/F3 actor) + known comms preserved. Offline-tested.
3. **Excluded** the 4 anomaly_mem calibration runs (bigheap/fix/swap/vmhang) in the batch glob;
   empty `normal/gate01` auto-excluded (no ground_truth).
4. **Full pre-flight** before relaunch: code version, deps, 46-run inventory, disk headroom,
   and an **end-to-end smoke test** on the smallest run (svc_cpu_cap → 16 clean services)
   — only then launched the 46-run batch.
5. Wiped stale pre-fix outputs first (derived artifacts, not the dataset), seeded the manifest
   with the smoke run, launched detached (`setsid`), recorded the PGID for clean shutdown.

### Notes carried forward
- **Ops:** killing/heavy SSH commands intermittently 128'd under derive load; used the process
  **group** (PGID) to kill the batch cleanly, and ran launches as minimal standalone commands.
- **Cosmetic:** the progress manifest writes event counts with thousands-commas, breaking that
  one CSV column's field alignment (the *log* is the source of truth). Tidy next script touch.
- **Deriving is expensive:** every trace is 100–370 M events (~18–38 min/run). Full 46-run
  batch ≈ 10.5 h at concurrency 2. Unavoidable at full fidelity; run unattended.

## State
Kernel representation ladder is **fully derived for the whole dataset**: L0 (raw CTF, gz) +
**L1 (46 KPI parquets)** + **L3 (46 NL-digest jsonl)** + L2 engine validated (per-run L2 is
on-demand, scoped). Loader validated. VM STOPPED.

---

## StrataTrace v1 — FROZEN (2026-08-04)
User asked whether we can save the first dataset and branch to new subjects (a 2nd app +
agentic). Decided to **audit + freeze v1 first** (protect it before branching). Done:
- **Completeness audit:** 46/46 runs have all 4 modalities + L1/L3 + gt/verif/load/meta —
  **zero gaps.** cAdvisor per-container metrics present (a gap I'd feared is closed; 432
  series/run). Verification 43 confirmed / 3 borderline / 0 unconfirmed.
- **Two documented limitations** (in the datasheet, not silent): (1) traces cover **6/14
  services** — Tier-2 `user`+`payment` are deliberate blind spots (design variable for the
  "can kernel compensate" RQ); (2) the **3 `dependency_outage` runs are borderline** — fault
  is real but its verify target likely mis-catches on a trace-blind service; review the check.
- **Freeze artifacts** (`release/`): `DATASET_MANIFEST.csv` (46-run index), `COVERAGE_MATRIX.md`,
  `FREEZE-v1.md`. **Disk snapshot `strata-v1-freeze-20260804`** (READY, supersedes the stale
  `...20260729`). **Git tag `strata-v1-freeze`.**
- **Not the freeze, but the path to *citable*** (release packaging, plan §8): datasheet,
  canonical splits (exclude 3 borderline), Lite/Full tiers, Zenodo DOI, GHCR images,
  `pip install stratatrace` finalize.

**Recommendation to user on branching:** v1 is now safe to build on. Prioritize the **agentic
M5 track** (planned paper-2, rig-ready, reuses this testbed + ground truth) over a 2nd app
(Train Ticket = full rig re-standup, future-work per plan §10). Keep the ablation study on the
critical path — it's what proves v1's value.

---

## Train Ticket = 2nd app — offline authoring done (user chose to proceed)
Read supervisor+meeting notes + mapped Sock Shop deployment/pipeline (2 explore agents). TT =
FudanSELab/train-ticket (forked `17YuvrajSehgal/train-ticket`), **~67 containers** (41 uniform
Java Spring Boot `ts-*-service` + 24 mongo + mysql/redis + JS ui-dashboard:8080), compose v3,
build-from-source (`${IMG_REPO}/${IMG_TAG}`), **no built-in observability**.
- **Key win:** uniform Java → OTel agent injects into all 41 via `JAVA_TOOL_OPTIONS` (no source
  forks; Spring Boot has no explicit compose `command` so it's honored). Deploy compose on one
  big VM (not TT's k8s) for single-host LTTng consistency.
- **Authored (offline, committed):** `service_map`+L2 refactored to **profile-based**
  (`STRATATRACE_APP`, default sockshop=v1 unchanged; trainticket profile = 68 containers);
  generated `docker-compose.otel.yml` (agent injection + collector); `docker-compose.metrics.yml`
  + `prometheus-tt.yml` (TT ships none); reused generic agent configs; `load_generator.py` (TT
  booking flow, identical CLI/CSV, `--probe` for live API check); `vm_bootstrap_tt.sh` + README +
  `PORT-PLAN.md`. All in `train-ticket-collection-scripts/`.
- **9 Sock Shop lessons baked into PORT-PLAN** (map-ALL-PIDs, CLI reader, per-netns netem, gzip,
  uncapped `--vm-hang`, warmup, SSH-by-PGID, collapse-system, KERNEL_MEM/mm_vmscan).
- **Remaining (Phase 0b/1, needs live stack):** `load_generator --probe` API validation;
  `collect_trace` container-regex + `fault_lib` prefix → TT (parameterize); otel-to-lttng(TT);
  toxiproxy on a TT DB path; fault recipes repoint (re-model queue_backlog — no rabbitmq);
  `verification_targets`(TT) re-calibrate; alignment gate; tracing-scope/campaign-size decision.
- **VM:** new `n2-standard-16`/64 GB/~1 TB, created at deploy time (not during authoring). v1 VM
  untouched. See [[project_trainticket_track]].

## TT Phase-0b: VM + standup — stack UP, 3/4 modalities live
- **VM `strata-tt-collector`** (us-east4-c — us-east1 SSD quota was full; fresh region keeps v1
  untouched), n2-standard-16/64GB/500GB.
- **Fork was NOT stock** — prior Feb-2026 LTTng-UST effort + inconsistencies. User chose the
  Sock Shop-consistent OTel-spans approach. On a clean **`stratatrace` branch**: reverted
  ts-common LTTng-UST source tracing; removed 3 fork-deleted-but-compose-referenced services
  (avatar/food-map/ticketinfo); **added missing ts-gateway-service** (ui-dashboard nginx routes
  through it); gateway internal-only (host-port 18888 collided w/ assurance); fixed non-UTF-8
  byte in generated overlay. Built OUR images (mvn jars -> docker compose build).
- **Deployed base+metrics+otel: 70 containers, entry ts-ui-dashboard:8080=200, Prometheus=200,
  cAdvisor healthy, OTel spans FLOWING (agent injection works).** 2 non-critical services
  restart (ts-voucher=Python/mysql-pw, ts-ticket-office=Node) — off the booking path.
- **TT is mostly-Java + a few Python/Node** (voucher, ticket-office) — move those out of
  _TT_JAVA later (agent injection is a no-op on them anyway).
- **TODO:** push the `stratatrace` branch to the fork (secure token pipe); `load_generator
  --probe` API validation; parameterize collect_trace for TT names + run the alignment gate;
  fix/accept the 2 stragglers.

## TT deployment — the compose is fundamentally broken across ALL FudanSELab versions
Chasing the standup surfaced a hard truth: TT's `docker-compose.yml` is stale/incoherent in
EVERY release (v1.0.0/v0.2.0/v0.1.0 + master):
- **Source** (all versions) uses **nacos discovery** + **MySQL** (`jdbc:mysql://ts-*-mysql`) +
  routes the ui-dashboard through **ts-gateway-service**.
- **Compose** (all versions) has **MongoDB** (`ts-*-mongo`, 48 refs), **no nacos**, **no gateway**.
So the compose was never kept in sync with the source's migration to nacos+MySQL+gateway. The
MAINTAINED deployment is k8s (`deployment/` manifests have nacos+MySQL+gateway); compose is a
dead artifact. Fixing revealed the chain: missing nacos (added) -> missing gateway (added) ->
services want ts-*-MYSQL but compose gives ts-*-MONGO (UnknownHostException ts-auth-mysql).
- **What works:** VM up, OUR images built from the pinned fork, infra healthy (nacos,
  Prometheus, cAdvisor, node-exporter, otel-collector; **OTel spans flowing**). Rig is proven;
  TT's app-deployment is the blocker.
- **Realistic paths (next session):** (a) BUILD a coherent MySQL compose ourselves — deploy
  ts-*-mysql DBs (env-overridable `${*_MYSQL_HOST}`; likely one MySQL + per-service databases +
  hibernate ddl-auto) keeping the added nacos+gateway; (b) TT on single-node **kind** (the
  maintained k8s path, host-level LTTng still works on one node); (c) a vetted community TT
  compose. **User chose "known-good release" — but none exists in FudanSELab; re-decide among
  (a)/(b)/(c).**
- **VM stopped** to halt spend; stratatrace-branch fixes (nacos/gateway/orphan-removal) + all
  overlays committed. `stratatrace` branch NOT yet pushed to fork (Windows scp/token friction).

## Resolved: stratatrace branch pushed + train-ticket submodule added
Pushed the clean `stratatrace` branch to `17YuvrajSehgal/train-ticket` (@ 4abb427, from a local
clone since the VM scp/token failed) and added **train-ticket as a pinned submodule** of the
research repo (branch stratatrace), mirroring `microservices-demo @ 9dff06f`. Both now visible
in the repo. (Deployment still blocked on the mongo-vs-mysql compose issue — separate.)

## RESOLVED: coherent shared-MySQL compose (the mongo-vs-mysql blocker)
Built the coherent MySQL deployment. **Root cause confirmed by reading every service's source:**
TT migrated to nacos+MySQL but its docker-compose was never updated — it still shipped 24
`ts-*-mongo` that NO service connects to.
- **DB inventory (source of truth = each service's `application.yml`/`.yaml`):** **20 services use
  MySQL** (`jdbc:mysql://ts-*-mysql`). A `.yml`-only scan first found 18 — **auth + user live in
  `application.YAML`** (auth even defaults pw `Abcd1234#`), caught by widening to all extensions.
  The 2 nominal "mongo" services (preserve, preserve-other) have their **mongo config commented
  out** → **nothing needs Mongo.**
- **Fix (3 parts):**
  1. **Base compose (submodule → `d6d37a5a`):** removed all 24 dead `ts-*-mongo` (121 lines; no
     `depends_on` referenced them, so clean). Base now = 40 app svcs + redis + `ts-voucher-mysql`.
  2. **`docker-compose.dbenv.yml` + `tt-init.sql` (NEW):** ONE shared `mysql:8`
     (`--default-authentication-plugin=mysql_native_password`, `--max_connections=2000`) + **20
     per-service databases**; override every MySQL service's `<PREFIX>_MYSQL_{HOST,PORT,DATABASE,
     USER,PASSWORD}` → `mysql:3306 / ts-<x>-mysql / root / root`. Normalizes the bad source
     defaults (10.176.122.1, localhost, an `s-train-mysql` typo, auth's `Abcd1234#`).
     `ddl-auto=update` auto-creates each service's tables in its empty DB.
  3. **`service_map.py` trainticket profile:** dropped `_TT_MONGO`; added shared `mysql`+`nacos`
     (explicit `container_name`, no project prefix); added `ts-gateway-service` to the Java set.
     **sockshop profile byte-identical** (v1 untouched). Regenerated `docker-compose.otel.yml` →
     39 Java services incl. the gateway (Spring Cloud Gateway is on every request path).
- **Deploy order (compose merges by name, later wins):** base → nacos → dbenv → metrics → otel.
  Updated `vm_bootstrap_tt.sh` + README. Committed parent `bb55798`, pushed both repos.
- **Why one shared MySQL, not 20:** matches k8s intent (one mysql StatefulSet), saves ~19 DB
  containers of RAM, and `ddl-auto` means empty DBs are enough.

## VALIDATED ON VM: TT deploys coherently, full request path works end-to-end
Redeployed on `strata-tt-collector` (us-east4-c) with base(no-mongo)+nacos+dbenv+metrics+otel:
- **The MySQL blocker is gone.** `ts-auth-service` (previously died on `UnknownHostException
  ts-auth-mysql`) now connects to the shared `mysql` and **builds its schema via `ddl-auto`** —
  OTel JDBC spans show `CREATE/ALTER table` on `db.name=ts-auth-mysql`. **20 databases created.**
- **End-to-end 200s:** `load_generator --probe` → **LOGIN 200** (real JWT for `fdse_microservice`,
  i.e. nginx→gateway→auth→MySQL) + **SEARCH 200** (`[]` — travel→MySQL responds; empty only
  because DBs aren't seeded). Path proven: **nginx → Spring Cloud Gateway → nacos-discovered
  service → shared MySQL.**
- **Stack health:** 48 running / 2 restarting (voucher=Python, ticket-office=Node — off the
  booking path, agent-injection no-ops on them, non-blocking); **nacos 36 services registered**;
  **OTel spans flowing** (2.3 MB / 416 batches incl. JDBC spans); **Prometheus 200, cAdvisor 200,
  3 targets up**. 3/4 modalities live (logs always; kernel rig already proven).
- **New lesson — nginx stale DNS (baked into `vm_bootstrap_tt.sh`):** the ui-dashboard nginx
  resolves `ts-gateway-service` ONCE at load; the gateway boots ~70 s later (JVM+nacos) → nginx
  caches an absent IP → **every `/api/v1` 502s**. Fix: after "Started GatewayApplication", restart
  the ui-dashboard so nginx re-resolves, and gate on a **real login POST=200** (the static page is
  200 even when the gateway path is dead). Any redeploy that recreates the gateway needs this.
## TT booking SEARCH path validated end-to-end — 4 bugs found by driving the live API
Turned out TT auto-seeds (every service has an `InitData.java` CommandLineRunner) — data was
never the problem. Drove the booking flow and fixed a chain of 4 real bugs:
1. **Wrong request field** — load_generator sent `startingPlace`; the entity is `TripInfo.
   startPlace`. Wrong name → null → trips/left silently `[]` (`[Travel Query Fail][Something
   null]`, a pure request-validation guard). Fixed to `startPlace`.
2. **Station-name format** — seeded stations are lowercase/no-space (`shanghai`,`suzhou`,
   `taiyuan`), NOT the canonical "Shang Hai". Routes updated to the seeded names that have trips
   (InitData seeds shanghai→suzhou→taiyuan).
3. **MySQL 8 utf8mb4 × MyISAM × varchar(255) PK** — TT's DDL (`create table config ... primary
   key(name) engine=MyISAM`) is MySQL-5.x-era. utf8mb4 = 4 B → 255-char PK = 1020 B > MyISAM's
   1000 B limit → "Specified key was too long" → **config (and other) tables never created** →
   config empty → **ts-seat-service 500** → trips/left 500. Fix: `mysql --character-set-server=
   utf8` (3 B → 765 B). After a clean `down -v` redeploy the `config` table creates + seeds.
4. **afterToday date guard** — `trips/left` returns `[]` unless `departureTime` is strictly after
   today (`TravelServiceImpl.afterToday`). load_generator sent today → empty. Now queries
   `DEPART_DAYS_AHEAD=3` out.
- **RESULT (live):** `load_generator --probe` → LOGIN 200 (JWT) + SEARCH 200 returning trip
  **D1345** (DongCheOne, shanghai→suzhou, ¥22.5, seats avail). Full path works: nginx → Spring
  Cloud Gateway → travel → basic(route+train+price) → seat → shared MySQL. All seed data verified
  consistent (5 trips, 10 routes w/ matching route_ids, 6 train types, 10 prices, 13 stations,
  config). Commits `eec65a3` (charset+API), `9307424` (future date).

## FULL booking flow (login→search→book→pay) VALIDATED at load — load_generator complete
User chose "continue Phase 1 now". Drove the WRITE path and cleared its last blocker:
- **JDK 11 removed `javax.xml.bind`** — TT (jjwt 0.9.x) calls `DatatypeConverter` →
  `NoClassDefFoundError` 403 on preserve/pay (read path login/search never hits it). Fix, no
  rebuild: append `-Xbootclasspath/a:/otel/jaxb-api.jar` to every service's `JAVA_TOOL_OPTIONS`
  (agents dir already mounted at /otel); `vm_bootstrap_tt` downloads jaxb-api-2.3.1. Commit `16cb797`.
- **load_generator book_pay completed** (`a5eccae`): capture accountId at login; fetch+cache a
  seeded `contactsId` (fdse_microservice has 2 contacts, `GET contacts/account/{acc}`); tripId in
  search is `{type,number}` → needs the `D1345` string; preserve returns "Success" (not an
  orderId) so fetch newest order via `order/refresh` (POST `{loginId}`) then `inside_payment`.
- **Live load test (5 users, 25 s, steady): 276 requests, 276 ok, 0 fail.** All 200 across
  users/travel/travel2/contacts/**preserve ×12**/order/**inside_pay ×12**. The generator exercises
  the full realistic booking workflow (auth→travel→basic→route→train→price→seat→contacts→order→
  preserve→inside_payment→payment→MySQL) with zero errors. TT load generator is production-ready.

## TT PHASE-0 GATE PASSED — six modalities time-aligned on a real run (OB parity)
The Sock Shop analogue milestone, now for Train Ticket. Parameterized the shared tooling +
ran a real traced gate:
- **`collect_trace.sh` parameterized** (`51793fc`): env `TRACE_APP` / `CONTAINER_REGEX` /
  `LOG_CONTAINER_REGEX` (Sock Shop defaults keep v1 byte-identical). TT uses
  `trainticket_.*_1|^mysql$|^nacos$` — matches all 44 service_map containers, excludes pure infra.
- **`run_gate_tt.sh`** (`eaaac19`): one-command TT gate; reuses collect_trace + download_metrics_full
  + audit_alignment, supplies TT wiring (regex, `OTLP_SRC`=TT spans, TT load_generator, :8080).
- **`run_gate_tt.sh tt_gate01 60 15` VERDICT — all six OK:** trace 141 spans · logs 16233 lines
  (238 w/ trace_id) · load 222 requests · metrics 885 series · **kernel 8,192,101 events / 5041
  (container,event) groups** · **clocks drift 0.001 ms**. Four modalities time-aligned on a real
  TT booking-load run — the OB-parity the user required ("everything in OB is also there").

## TT fault recipes ready + blast-radius plan (mentor's ask) — validated
- **All 13 shared fault recipes made TT-ready:** `EXPECTED_BLAST_RADIUS` /
  `EXPECTED_WINNING_MODALITY` / `TARGET_TRACE_VISIBILITY` now env-overridable (`${VAR:-default}`,
  Sock Shop defaults byte-identical). Recipes already resolve TT containers via
  `CONTAINER_PREFIX=trainticket`. Commit `3c81d1e`.
- **Validated on VM:** `CONTAINER_PREFIX=trainticket TARGET_SVC=ts-travel-service svc_cpu_cap.sh
  inject subtle` → caps `trainticket_ts-travel-service_1` (cgroup `cpu.max=50000 100000`); with the
  blast-radius env → ground truth records the **TT blast radius**
  `[ts-travel-service, ts-preserve-service, ts-gateway-service, ts-ui-dashboard]`; cleanup restores;
  stack stays healthy (login 200).
- **`FAULTS-TT.md`** = pre-registered TT fault→target→blast-radius→modality plan, blast radii
  grounded in the **observed call graph** (login/search/book/pay). Headline TT finding: **slow_db
  on the SHARED mysql = ~22-container blast** (vs Sock Shop per-service DBs) AND a clean trace
  blind spot (mysql/nacos uninstrumented) → the **kernel** modality must carry it. `queue_backlog`
  re-modeled as MySQL connection-pool exhaustion (TT has no message broker).

## Tracing scope: "same as OB" — TT Phase-2 campaign driver built
User: **"do the same what we did in online boutique"** → identical methodology, full tracing
(collect_trace enables `-k --all '*'` + `--syscall --all`, already applied to TT in the gate). No
scoping-down. Built the campaign infrastructure to match the Sock Shop rig:
- **`run_scenario.sh`** gained a `LOAD_GEN` env (default = Sock Shop generator) so another app
  reuses the baseline→inject→recovery→metrics→verify→audit workhorse verbatim (SS unchanged).
- **`run_scenario_tt.sh`** — exports the TT app profile (TRACE_APP/CONTAINER_PREFIX/CONTAINER_REGEX/
  OTLP_SRC/LOAD_GEN/:8080) + delegates to `run_scenario.sh`.
- **`run_campaign_tt.sh`** — **38-run TT matrix** (normals steady+burst ×3 + 8 core faults
  aggressive/steady ×3 + intensity + workload variants), per-fault TT TARGET_SVC + blast radius
  from FAULTS-TT.md. Covers faults runnable without extra infra (docker update / netem /
  **docker pause** for dependency_outage / stress-ng). Commit `74909e4`.
- **Fault mechanism audit:** slow_db + error_storm use **toxiproxy** (excluded pending TT
  mysql-toxiproxy); dependency_outage=docker pause, svc_net/anomaly_net=netem, svc_cpu/mem=docker
  update, anomalies=stress-ng — all work standalone on TT.

## Remaining before the full TT campaign run
1. Toxiproxy in front of the shared `mysql` → adds slow_db + error_storm + connection-cap
   queue_backlog remodel (2-3 more fault types).
2. `verification_targets(TT).json` (per-fault Prometheus panel for verify_injection.py).
3. Intensity calibration (noisy_neighbor "KPIs barely move", svc_cpu_cap subtle) on the VM.
4. **Launch `run_campaign_tt.sh`** unattended (~38 runs × ~4 min + gzip ≈ several hours), then
   batch L1/L3 derive — same as the Sock Shop 46-run batch.
- **VM `strata-tt-collector` (us-east4-c) RUNNING.** Whole TT pipeline production-ready:
  deploy + booking flow + PHASE-0 gate + fault injection + Phase-2 scenario/campaign drivers.
