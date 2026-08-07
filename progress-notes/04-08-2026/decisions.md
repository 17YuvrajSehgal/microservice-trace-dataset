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

## Phase-2 workhorse VALIDATED — a real labeled TT fault bundle
Ran one full scenario on the VM (`svc_cpu_cap subtle ts-travel-service`, 20/30/20 s):
- **All six modalities OK** + `ground_truth.json` in the bundle with `target_service:
  ts-travel-service`, the TT `expected_blast_radius`, and the **injection window** (19:37:47→
  19:38:17, matching INJECTION_S=30). The CPU cap visibly throttled the search path (fewer kernel
  events under fault than the no-fault run — the fault working).
- **Footgun found:** `run_scenario_tt.sh` standalone doesn't set `TARGET_SVC`, so a service-fault
  falls back to the recipe's Sock Shop default (`carts`) → caps a non-existent `trainticket_carts_1`
  → inject silently fails (`|| WARN`), bundle collects with NO fault. **The campaign driver sets
  TARGET_SVC per fault, so `run_campaign_tt.sh` is correct**; only ad-hoc `run_scenario_tt` calls
  must pass `TARGET_SVC`.
- **Scale/disk:** ~7.8 G uncompressed kernel / 70 s @ 15 u → a 240 s campaign run @ 20 u ≈ 27-30 G
  uncompressed → ~7-8 G gzipped. 38 runs ≈ **285 G**; VM has **457 G free** → fits (campaign gzips
  between runs, peak ~1 run uncompressed). No disk expansion needed.

## Toxiproxy + verification_targets(TT) DONE — full OB fault parity (46-run matrix)
- **Toxiproxy permanently in front of the shared `mysql`** (`docker-compose.toxiproxy.yml` +
  `agents/toxiproxy-config-tt.json`, proxy `mysql`:3306→mysql:3306, admin :8474): repoints all 20
  DB services' `*_MYSQL_HOST`→toxiproxy (loads after dbenv so it wins), in-path for every run.
  `slow_db.sh`/`error_storm.sh` made PROXY/TARGET_SERVICE/FAULT_NAME env-overridable. Commit `5ed85ee`.
- **slow_db VALIDATED live (dramatic):** 500 ms latency toxic on mysql → search **0.14 s → 16 s**
  (100×+; the search fans out to ~30 DB round-trips, each +500 ms), cleanup → 0.14 s. Since mysql
  is uninstrumented this is a **trace blind spot across TT's ~22-container shared DB** — the
  textbook kernel-wins fault. Toxiproxy transparent when idle (0.15 s).
- **`run_campaign_tt.sh` now 46 runs** (matches OB): slow_db + error_storm added with PROXY=mysql
  + shared-DB blast radius; INTENSITY/WORKLOAD variants include them.
- **`verification_targets_tt.json`** (11 faults) — cAdvisor + node metrics ONLY (TT has no
  app-latency Prometheus metric, so slow_db/svc_net/anomaly_net are metrics-WEAK by design →
  throughput-drop proxies, kernel/traces/load-CSV carry them; thresholds CALIBRATE). Wired via
  `VERIFY_TARGETS` (run_scenario `--targets`). **verify path proven:** on the 33 s slow_db test →
  BORDERLINE with `mysql_cpu` moving correctly (0.0114→0.0056, -51%), just under 3σ due to the
  short window; 120 s campaign runs + calibration will settle it.

## Calibration pass DONE + campaign LAUNCHED (46 runs, running)
- **Calibration** (`calibrate_tt.sh`, 13 faults under load; details above): safety bound for
  anomaly_mem (FRAC=35), threshold tuning (anomaly_disk/noisy 0.5->0.15), and the headline finding
  — TT latency faults are metrics-blind (slow_db search 60ms->28.8s, dep_outage ->30s hang) while
  cAdvisor signals flip/weak: the kernel-wins thesis, quantified. Committed `d173fcf`.
- **CAMPAIGN RUNNING** (launched 2026-08-04 21:18 UTC): 46-run matrix via `systemd-run --unit=
  tt-campaign` (baseline 60 / injection 120 / recovery 60). `tt-campaign-watch` unit shuts the VM
  down 5 min after completion (data persists on the boot disk). Monitor: `systemctl status
  tt-campaign`, `tail ~/tt_campaign.out`, `~/tt_campaign_manifest.csv`.
- **HARD-WON LAUNCH LESSONS (do NOT rediscover):**
  1. **Never `pkill -f`/`pgrep -f` a pattern that also appears in your own gcloud-ssh command** —
     it self-matches, so `pkill` kills the SSH session (truncated output) and `pgrep -fc` counts
     itself (phantom "proc: 1"). Use `ps aux | grep '[b]racket'` or kill by PID.
  2. **Detached launch over `gcloud ssh --command` needs `systemd-run`, not `setsid &`** — non-PTY
     SSH close kills backgrounded processes. `sudo systemd-run --unit=... --uid=$(id -u) --gid=
     $(id -g) --property=SupplementaryGroups=docker --setenv=HOME=... --setenv=PATH=... bash -c
     '...'` runs fully independently (docker + sudo work; needs HOME+PATH+docker group).
  3. **Write-created scripts have NO +x bit and `git reset --hard` on Linux won't add it** (Windows
     filemode). `env script`/`./script`/`exec script` -> "Permission denied" -> every run failed
     instantly and the campaign blazed through 46 empty runs. Fix: `git update-index --chmod=+x`
     AND invoke via `bash <script>`. (`9a53eb5`)
## SCALE PROBLEM hit + SOLVED (disk) — campaign re-running clean
Once real runs started, two scale issues surfaced (the flagged "48 containers = big traces" risk,
now concrete):
- **Per-run bundle ~11 GB** (kernel 4.7 GB gz + ~6 GB docker logs — the OTel LOGGING span-exporter
  dumps every span to stdout; redundant with OTLP but complete). 46 runs = ~506 GB.
- **~30 min/run** (the per-run `audit_alignment` reading the multi-GB kernel trace dominates) →
  46 runs ≈ ~20-23 h.
- **DISK: the 500 GB root is pd-balanced = SSD quota, and us-east4 SSD_TOTAL_GB is 500/500 FULL**
  → can't resize (overflow ~run 40). BUT **DISKS_TOTAL_GB (pd-standard) had 4096 GB free.**
- **FIX (no fidelity loss):** created a **3 TB pd-standard data disk** `strata-tt-data`, attached,
  ext4, mounted `/mnt/data` (fstab `nofail` so it re-mounts across the auto-stop/restart),
  symlinked `~/traces -> /mnt/data/traces`. Sustained write **363 MB/s > the ~285 MB/s LTTng peak**
  + 4 GB ring buffers → verified **Discarded events: 0** on the first new run. Full 46-run "same
  as OB" now fits (2.7 TB free).
  - Gotcha: cross-device `mv ~/traces` = copy+delete, and `sudo lttng` leaves root-owned kernel
    files on an interrupted run -> needed `sudo rm` + drop incomplete runs before the symlink.
- **Campaign RE-RUNNING** (systemd-run, resumable): skipped the 5 complete normals, resumed at
  run 6, auto-stop watcher armed. ~40 runs left × ~30 min ≈ ~20 h.
- **NEXT (after collection):** batch L1/L3 derive across the 46 TT runs (`STRATATRACE_APP=
  trainticket`), same as the Sock Shop 46-run batch (~15-20 h for TT's bigger traces). VM
  auto-stops after collection; restart for the derive (`/mnt/data` re-mounts via fstab).
- **TT pipeline is FEATURE-COMPLETE with full OB parity**, every stage validated on real data.

## Mid-campaign bug caught by monitoring: 4 non-executable recipes -> unlabeled runs
A progress check at run 42/46 found `anomaly_mem`/`anomaly_net`/`svc_net` verifying **n/a** = NO
ground_truth written. Root cause: those 3 (+ `anomaly_disk`) were committed **100644** (Windows-
authored, no +x); `run_scenario.sh` gated recipes on `[[ -x ]]` and invoked them directly, so they
hit "no such recipe" -> exited with no trace, no label (9 unlabeled runs). `anomaly_disk` was also
MISSING from the TT matrix. `calibrate_tt` didn't catch it (it invokes recipes via `bash`).
- **QC that DID work (reassuring):** reliable faults verified right — `noisy_neighbor` confirmed
  x5, `svc_mem_cap` confirmed; metrics-blind faults (slow_db, error_storm, svc_cpu_cap) borderline/
  unconfirmed exactly per the calibration thesis (kernel/client-latency carry them).
- **Fix `b6d4cd4`:** `git update-index --chmod=+x` the 4 recipes; `run_scenario.sh` gates on `-f`
  and invokes recipes via `bash "$RECIPE_SH"` (missing +x can never silently drop a fault again);
  added `anomaly_disk` to CORE_FAULTS -> **49-run matrix**.
- **Resumed** (stop -> sudo-clean incomplete dirs -> pull -> relaunch): skipped the **34 good
  bundles**, now collecting the 15 missing (svc_net/anomaly_disk/anomaly_mem/anomaly_net x3 +
  slow_db/error_storm burst x2). **Verified svc_net now traces + writes ground_truth.** ~8h left,
  auto-stop re-armed. LESSON: after any Write-authored `.sh`, `git update-index --chmod=+x` it.

## TT DATASET COLLECTION COMPLETE (2026-08-06 ~01:29 UTC) — 49/49 labeled bundles
Campaign finished all 49 runs, auto-stopped the VM (no idle billing). Restarted to verify +
finalize:
- **49/49 complete + LABELED bundles** on `/mnt/data` (fstab remounts on restart). One run
  (`slow_db_aggressive_burst_r1`) had its trace but the ground-truth-COPY step never ran (it was
  in-flight when I stopped for the disk migration; kept because it had runinfo_end.txt) -> copied
  the GT from fault-state into the bundle + verified. Clean index -> `~/tt_dataset_manifest.csv`.
- **Verdict distribution TELLS THE THESIS:** reliable resource/host faults CONFIRM (anomaly_mem x3,
  anomaly_disk x3, noisy_neighbor x5, svc_mem_cap x2) - cAdvisor/node metrics see caps + host
  stress; the latency/frozen/contention faults go borderline/unconfirmed (slow_db, error_storm,
  svc_cpu_cap, svc_net, anomaly_net, dependency_outage, anomaly_cpu) - resource metrics MISS them,
  the kernel + traces + client-latency carry them. ~half the fault families are metrics-blind =
  the kernel-wins argument, emergent from the QC verdicts themselves.
- **anomaly_mem CONFIRMED + no OOM** validates the FRAC=35 safety calibration.
- Full-fidelity "same as OB": full-syscall kernel, all 44 containers, 60/120/60 windows, on the
  3 TB pd-standard data disk (0 event drops). Bundle sizes ~5-11 GB (kernel 4.7 GB gz + logs).
- **NEXT:** batch L1/L3 derive across the 49 runs (`STRATATRACE_APP=trainticket`), then release
  packaging. VM currently RUNNING (restarted to verify).

## TT L1/L3 DERIVE COMPLETE (2026-08-06) — 47/49, auto-stopped
`batch_derive_tt.sh` (systemd-run, concurrency 3 -> raised to **6** after stopping the idle docker
stack that was eating 4+ cores @ `426% java`; per-derive RAM is tiny so 6 is safe). Ran ~13 h then
auto-stopped. **BATCH DONE: ok=47 skip=0 fail=2.** 47/49 `kernel_l1.parquet` + `kernel_l3.jsonl`.
- **Parquet validated:** 43 services, **38 ts-services (java split works)**, kernel+system buckets
  present -> the TT `service_map` profile derives correctly.
- **SCALE reality:** TT under CPU/disk stress + full-syscall tracing = **500-700 M events/run** (the
  anomaly_cpu/disk runs), ~90 min/derive each. A genuinely large-trace dataset characteristic.
- **2 FAILS = lost kernel traces, NOT a derive bug:** `normal_none_burst_r2` +
  `slow_db_aggressive_burst_r1` -> "No CTF metadata found" (their kernel CTF files are missing).
  These 2 are the first-attempt runs interrupted by the disk migration; the botched cross-device
  `mv` (root-owned `sudo lttng` files -> "permission denied") lost their kernel trace when I
  `sudo rm`'d the root copy. Other 3 modalities survive. LESSON: after a cross-device `mv` of
  sudo-owned trace data, VERIFY the kernel CTF copied before deleting the source.
- Dataset is 47/49 kernel-derived, ALL fault families/intensities/repeats intact (the 2 lost are
  single burst-workload repeats). Re-collect the 2 for a clean 49/49, or accept 47.

## TT DATASET 49/49 COMPLETE (2026-08-06) — user chose to re-collect the 2
Restarted the VM, restarted the docker stack (`docker start` all + restart ui-dashboard for the
gateway DNS; healthy in ~3 min), re-ran the 2 lost scenarios via `run_scenario_tt.sh` (burst/40u;
slow_db with PROXY=mysql) - both collected FULL kernel traces this time (20-21 GB) + labels
(slow_db verified borderline, normal n/a). Gzipped + derived them (~55 min each).
- **FINAL: 49/49 COMPLETE bundles** (4-modality kernel/traces/logs/metrics + L0/L1/L3 ladder +
  labels), **ZERO gaps**. Verdicts: 13 confirmed / 15 borderline / 15 unconfirmed / 6 n/a(normal).
  Clean index `~/tt_dataset_manifest.csv`. VM STOPPED (data on both disks; `/mnt/data` fstab-mounts).
- **Train Ticket = full Sock Shop (OB) parity achieved.** Same methodology (full-syscall kernel,
  all containers, 60/120/60 windows, toxiproxy DB path, 4 modalities + kernel ladder), 2nd diverse
  app (shared-MySQL vs per-service-DB; nacos gateway; 500-700 M events/run under stress).
- **NEXT:** release packaging (datasheet, splits, Zenodo/GHCR) + the modality-ablation study across
  BOTH apps (the plan's critical path). Optional: prune the redundant OTel span-logs (~6 GB/run) for
  leaner bundles; move voucher/ticket-office out of _TT_JAVA (non-Java, agent-injection no-op).
