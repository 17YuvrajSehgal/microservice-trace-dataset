# StrataTrace — Complete Dataset Guide (for new team members)

> **Read this first.** It explains, from scratch, what we collected, how, why, what it looks
> like, what faults we injected, how many runs there are, and how the data will be used. No prior
> knowledge of the project is assumed. Authoritative source files are cited throughout so you can
> dig deeper: `msr-research.md` (the research plan), `fault_catalog.md` (the pre-registered
> predictions), `release/FREEZE-v1.md` + `release/COVERAGE_MATRIX.md` + `release/DATASET_MANIFEST.csv`
> (Sock Shop v1), `train-ticket-collection-scripts/FAULTS-TT.md` (Train Ticket faults), and the
> daily decision log in `progress-notes/`.

---

## 1. The one-paragraph summary

**StrataTrace** is a four-modality observability dataset for microservice fault diagnosis. We take
two real microservice applications, run them under realistic user load on a single instrumented
Linux VM, **inject a controlled fault** ("anomaly"), and simultaneously record **four kinds of
telemetry**: **kernel traces, distributed traces, logs, and metrics**. Every run is **labeled**
with ground truth (which fault, where, when, expected impact). The distinctive ingredient is the
**kernel-trace modality** — no comparable public dataset has it. The research question:
**which observability modality is actually needed for which diagnosis task, and can the kernel
modality reveal faults that traces/logs/metrics are blind to?** Target venue: **MSR 2027**
(a dataset paper + a modality-ablation study paper).

---

## 2. Why this dataset exists (the research idea)

Existing incident datasets (RCAEval, OpenRCA, LEMMA-RCA, AIOpsLab, …) ship metrics + logs +
sometimes traces, but **none has a kernel layer** (`msr-research.md` §2). Yet many real faults are
**invisible** to metrics/logs/traces:
- A *slow database* makes requests take seconds, but the DB's CPU barely moves — a metrics blind spot.
- A *frozen dependency* (a paused service) makes callers **hang** rather than error — logs and
  metrics stay quiet; only the kernel sees threads blocked in `read()` on a socket.
- A *noisy neighbor* steals CPU while app KPIs stay within normal variance.

The kernel sees **every syscall, scheduler decision, and block/network event of every service
without instrumenting anything**. So StrataTrace lets us *measure*, rather than assert, when the
kernel modality carries information the others cannot. The four defensible novelty claims
(`msr-research.md` §2): first dataset that **time-aligns kernel traces with app traces/logs/metrics
under labeled faults**; first **per-task modality-ablation study including the kernel**; only
dataset shipping **measured per-modality collection cost**; first **LLM-consumable kernel-trace
representations**.

---

## 3. The two subject applications (and why two)

We collected the **same methodology on two architecturally different systems** so findings
generalize beyond one design (`progress-notes` "diverse types of systems"):

| | **Sock Shop** (app 1) | **Train Ticket** (app 2) |
|---|---|---|
| Upstream | Weaveworks `microservices-demo` | FudanSELab `train-ticket` |
| Domain | e-commerce cart/checkout | train-ticket booking (login→search→book→pay) |
| Services / containers | ~14 services | ~40 Java services (48 containers) |
| Languages | Go, Java, Node.js, MySQL/Mongo | Java Spring Boot (+ a Python & a Node service) |
| **Database design** | **per-service databases** | **one shared MySQL** for all 20 DB services |
| Service discovery / routing | DNS | **nacos** discovery + Spring Cloud **gateway** |
| Trace instrumentation | OTel Java agent + 2 forked services (front-end, catalogue) | OTel Java agent into all 39 Java services (incl. gateway) |
| Runs | **46 canonical** (60 bundles on disk) | **49** |
| Status | **v1 FROZEN** (git tag `strata-v1-freeze`, snapshot `strata-v1-freeze-20260804`) | **complete** |

**Why the second app matters:** Train Ticket's **shared MySQL** means one database fault ripples
across ~22 containers (a big, trace-blind blast radius), whereas Sock Shop's per-service DBs
contain it. Its full-syscall traces are also far larger — **500–700 million kernel events in a
single 4-minute run** under CPU/disk stress. Both apps are pinned as **git submodules of our
forks** so our deployment changes never touch (frozen) upstream.

---

## 4. The four modalities (what each is)

(`msr-research.md` §3.)

| Modality | Source | What it captures | Files in a run |
|---|---|---|---|
| **Kernel traces** | LTTng 2.13/2.15, full-syscall (`-k --all '*'` + `--syscall --all`) + sched/block/net/irq | every syscall, context switch, block-I/O, packet, page-fault of every service — no instrumentation | `kernel/kernel/channel0_*.gz` (raw CTF) |
| **Distributed traces** | OpenTelemetry Java agent (auto-injected via `JAVA_TOOL_OPTIONS`) → OTLP → collector | per-request spans across services (start/end, parent/child, attributes) | `otlp/spans.jsonl` |
| **Logs** | `docker logs --timestamps --since <run-start>` per container | application logs (exceptions, GC, connection errors); some carry `trace_id` for correlation | `logs/<container>.log` |
| **Metrics** | Prometheus 5 s scrape: **cAdvisor** (per-container CPU/mem/net/blkio) + **node-exporter** (host) + app histograms | resource + KPI time series | `<run_id>_metrics/` (sibling of the bundle) |

**Time alignment (novelty claim #1).** All four run on one host, one clock. Kernel + UST share the
LTTng monotonic clock; logs/OTLP/Prometheus use wall-clock. Each run records the
(realtime, monotonic, boottime) offsets at start/tick/end in `meta/runinfo_*.txt`, so any two
records across modalities align to a **measured, sub-millisecond** bound (a passing alignment audit
reports ~0.001 ms drift).

### The kernel "representation ladder" (`msr-research.md` §4)

Raw kernel traces are enormous, so we derive smaller, more usable views (profile-driven; run
`STRATATRACE_APP=trainticket|sockshop` + the shared `stratatrace/` package):

- **L0 — raw CTF (gzipped).** For systems researchers. The ground truth; huge.
- **L1 — `kernel_l1.parquet`.** Per `(service, 1 s window)`: syscall counts by family, syscall
  latency percentiles, sched_switch/wakeup rates, run-queue delay, block-I/O ops/latency, net
  throughput, page-fault/reclaim, cgroup throttle. **This is what analysis code reads.** Directly
  comparable to metrics.
- **L2 — per-request wait attribution.** Where a request's wall-time went: on-CPU vs
  runnable-but-waiting (contention) vs blocked-on-disk/net/futex. The kernel's unique semantic —
  *why* a request was slow. Computed on demand.
- **L3 — `kernel_l3.jsonl`.** A deterministic, templated natural-language digest per service, e.g.
  *"carts: p95 syscall latency 4.1× baseline; runnable-wait share rose 3%→41%; disk latency
  normal"*. The **LLM-consumable** form (templated so it can't hallucinate).

---

## 5. How each run was collected (the strategy)

A **run** is one deploy-and-load session with a **baseline → injection → recovery** structure, so
every bundle contains fault *onset* and *recovery* (needed for the explanation/repair tasks):

```
|---- baseline 60s ----|-------- fault active 120s --------|---- recovery 60s ----|
      no fault                  anomaly injected                fault removed
   <------------------- entire 240s window traced continuously ------------------>
```

Per run, the driver (`run_scenario.sh` / `run_scenario_tt.sh`, orchestrated by `run_campaign*.sh`)
does (`msr-research.md` §6, `fault_catalog.md` §6a):

1. Start **continuous LTTng kernel + UST tracing** and a **closed-loop load generator** (realistic
   journeys — for Train Ticket: login → search trips → book → pay; per-request CSV recorded).
2. **Inject** the fault at baseline+60 s; **remove** it after 120 s (the recipe's cleanup *is* the
   correct remediation — that gives the repair task an objective label).
3. Snapshot **metadata**: `docker top` per container (→ the **PID/TGID → service** map), `docker ps`,
   thread list, and the **clock anchors**.
4. **Slice** the OTLP span file to this run's window; **dump** per-container logs; **download**
   Prometheus metrics for the exact window.
5. **Verify** (`verify_injection.py`): did the fault move its declared target metric? → verdict
   `confirmed | borderline | unconfirmed` (+ an impact PNG). This is a QC gate, not the study's
   modality claim.
6. **Audit** (`audit_alignment.py`): are all modalities time-aligned? A passing run shows six OK
   lines (trace, logs, load, metrics, kernel, clocks) with ~0.001 ms drift.

**Key collection lessons baked into the tooling** (`progress-notes`): map **all** of a container's
PIDs to its service (Java shell-wrapper entrypoints split the JVM under a child TGID); use the
babeltrace2 **CLI** reader (~15× the Python bindings); per-netns `netem` (not the shared bridge);
gzip the kernel CTF (mandatory — it's the bulk); uncapped memory stressor (a cgroup cap contains
reclaim); warm-up before overhead runs; `--collapse-system` (fold host noise into one `system`
bucket so tables stay ~clean); a `WARMUP` before RQ4 overhead runs.

---

## 6. The anomalies we injected (the fault catalog)

Two axes (`fault_catalog.md`, `msr-research.md` §5): **scope** (host-wide vs service-targeted) ×
**layer** (resource vs application/dependency vs infrastructure). Each fault runs at two
**intensities** (`subtle`, `aggressive`) and under two **workloads** (`steady`, `burst`). Faults
are toggled cleanly (Toxiproxy toxics / cgroup / netem / pause — no restarts, which would pollute
the data). Every recipe (`microservice-lttng-data-collection-scripts/faults/*.sh`) writes a
ground-truth label with its **pre-registered expected winning modality**.

| # | Fault (recipe) | Family / scope | Mechanism | Models | Predicted winner (RCA) |
|---|---|---|---|---|---|
| F1 | `anomaly_cpu` | host resource | stress-ng CPU saturation | CPU exhaustion / noisy host | metrics detect, **kernel** attributes |
| F2 | `anomaly_disk` | host resource | stress-ng `--hdd` block I/O | disk saturation | metrics / **kernel** |
| F3 | `anomaly_mem` | host resource | stress-ng `--vm` memory pressure | memory exhaustion / reclaim | metrics / **kernel** |
| F4 | `anomaly_net` | host resource | host-bridge `netem` delay+loss | network degradation | traces / kernel |
| F5 | `slow_db` | application (blind spot) | **Toxiproxy latency toxic** on the DB path | slow query / saturated DB | **kernel** (DB is trace-blind) |
| F6 | `error_storm` | application | Toxiproxy reset/timeout toxic | 5xx / connection-error storm | **logs** |
| F7 | `svc_cpu_cap` | service resource | cgroup CPU quota (`docker update`) | one service throttled | **kernel** (rival: cAdvisor throttle counter) |
| F8 | `svc_mem_cap` | service resource | cgroup memory limit | GC pressure / OOM-kill | **logs** (terminal); kernel leads early |
| F9 | `dependency_outage` | dependency | `docker pause` a service | a **frozen** dependency (hangs, not errors) | **traces** (broken edge); kernel sees the silence |
| F10 | `queue_backlog` | dependency (silent) | pause the queue consumer | silent async backlog | **kernel** only (Sock Shop; TT has no broker) |
| F11 | `noisy_neighbor` | infrastructure (blind spot) | co-located cgroup-capped stress container | contention with app KPIs ~flat | **kernel** only |
| F12 | `svc_net` | service resource | per-netns `netem` on one service | one service's network slow | traces / kernel |

**Aggregate hypotheses (pre-registered, frozen — `fault_catalog.md` §4):**
- **H1** — kernel is the only modality with ≥medium informativeness across *every* fault (no blind
  spots), but never the cheapest detector.
- **H2** — for the blind-spot faults (F5/F10/F11), removing the kernel causes the largest ablation
  drop of any (fault, modality) pair.
- **H3** — metrics win detection on *aggressive* faults; their edge shrinks at *subtle* intensity.
- **H4** — no single modality is top-1 for RCA across all fault families (the task→modality table is
  non-trivial).

`fault_catalog.md` §5 has a **per-fault card** listing the exact evidence each modality is expected
to contain (these double as the fact-checklists for grading incident-explanation output). Train
Ticket's realized blast radii + targets are in `train-ticket-collection-scripts/FAULTS-TT.md`
(grounded in the observed call graph; the shared-MySQL `slow_db` is TT's flagship kernel-wins case).

---

## 7. How many runs (the matrices)

**Sock Shop v1 — 46 canonical runs** (`release/FREEZE-v1.md`; 60 bundles on disk incl.
calibration/overhead runs):

| Family | Faults | Runs |
|---|---|---|
| A — host resource | anomaly_cpu, anomaly_disk, anomaly_mem, anomaly_net | 12 |
| B — service resource | svc_cpu_cap, svc_mem_cap, svc_net (carts) | 11 |
| C — application | error_storm (catalogue), slow_db (catalogue-db) | 12 |
| D — dependency | dependency_outage (payment), queue_backlog (queue-master) | 6 |
| E — infrastructure | noisy_neighbor | 5 |
| **Total** | **12 fault types** | **46** |

**Train Ticket — 49 runs**, same campaign structure (6 normal references + core faults ×3 repeats +
intensity/workload variants). Per-recipe counts: `anomaly_cpu 3, anomaly_disk 3, anomaly_mem 3,
anomaly_net 3, dependency_outage 3, error_storm 5, noisy_neighbor 5, normal 6, slow_db 7,
svc_cpu_cap 5, svc_mem_cap 3, svc_net 3`.

**Run IDs encode everything:** `<app>_<recipe>_<intensity>_<workload>_r<repeat>`
(e.g. `tt_slow_db_aggressive_burst_r1`, `anomaly_cpu_aggressive_steady_r2`).

The matrix design (`msr-research.md` §5): more **fault diversity** beats more repeats. 6 normals are
the fault-free reference/negative class; core faults get 3 repeats for variance; a small intensity
study (subtle variants) and workload study (burst variants) support the condition-sensitivity RQ.

---

## 8. What the data looks like (sample bundle)

One run = one directory. Example (`traces/slow_db/tt_slow_db_aggressive_steady_r1/`):

```
traces/<recipe>/<run_id>/
├── kernel/kernel/channel0_*.gz      # L0 raw kernel CTF, gzipped (the bulk: ~3–5 GB/run, up to ~13 GB for stress faults)
├── ust/                             # LTTng UST session (OTel span relay / clock bridge)
├── otlp/spans.jsonl                 # distributed traces sliced to this run's window
├── logs/<container>.log             # per-container docker logs (some lines carry trace_id)
├── meta/
│   ├── docker_ps_*.txt              # container inventory
│   ├── top_<container>_1_*.txt      # docker-top → PID/TGID → service (the kernel↔service join key)
│   ├── runinfo_start.txt/_end.txt   # clock anchors (realtime/monotonic/boottime)  ← alignment
│   └── container_list_*, ps_threads_*
├── ground_truth.json                # the FAULT LABEL (see below)
├── verification.json                # QC verdict for the injection
├── kernel_l1.parquet                # L1: per-(service,window) kernel KPIs
└── kernel_l3.jsonl                  # L3: natural-language deviation digest
# siblings (per run, not inside the bundle):
<run_id>_metrics/                     # Prometheus metrics for the window (cAdvisor + node-exporter + app)
<run_id>_load.csv                     # client load: timestamp,user_id,scenario,method,endpoint,status_code,latency_ms,success
```

**`ground_truth.json`** — the label (real Train Ticket slow_db example):
```json
{"fault": {
  "family": "C_application", "name": "slow_db_mysql", "scope": "service", "intensity": "aggressive",
  "parameters": {"latency_ms": 500, "jitter_ms": 100, "stream": "downstream", "proxy": "mysql"},
  "target_service": "mysql",
  "expected_blast_radius": ["mysql","ts-auth-service","ts-user-service","ts-travel-service",
                            "ts-order-service","ts-gateway-service","ts-ui-dashboard"],
  "expected_winning_modality": "kernel",
  "target_trace_visibility": "blind_spot",
  "injection_start_utc": "2026-08-05T15:28:14Z",
  "injection_end_utc":   "2026-08-05T15:30:14Z"}}
```

**`kernel_l1.parquet`** (Train Ticket) — ~10k rows, one per `(service, 1 s window)`; **43 services**
resolved: 38 `ts-*-service` Java services + a `kernel` bucket (kswapd/ksoftirqd/… — the reclaim
actor) + a collapsed `system` bucket. That 38-way "java split" is the payoff of the PID/TGID service
map — dozens of services all report the process name `java`, but we attribute each event to the
right service via its container's TGID.

**`verification.json`** — `{"verification_status": "borderline", ...}` plus the canonical Prometheus
signal and its baseline-vs-injected values.

**Run-level index** (`release/DATASET_MANIFEST.csv`, Sock Shop):
```
fault_family,fault_name,run_id,intensity,target_service,expected_winning_modality,verification,kernel_l0_gb,has_L1,has_L3
A_host_resource,anomaly_cpu,anomaly_cpu_aggressive_steady_r1,aggressive,host,kernel,confirmed,2.29,True,True
...
```
(Train Ticket's equivalent lives on the VM as `~/tt_dataset_manifest.csv`.)

**Per-service coverage** (`release/COVERAGE_MATRIX.md`, Sock Shop): **Kernel 14/14** (sees every
service), **Logs 15 containers**, **Metrics all** (432 series/run incl. cAdvisor), **Traces 6/14** —
Tier-1 (front-end, catalogue) + the Java-4; `user`/`payment` and the DBs/rabbitmq/nginx are
**deliberate trace blind spots**. Those blind spots are *testable sub-questions* (can kernel/logs/
metrics compensate?), not accidental gaps.

---

## 9. Dataset sizes (measured)

| App | On disk (**gzipped**) | Uncompressed | Runs |
|---|---|---|---|
| **Train Ticket** | **287 GB** | ~1.5 TB | 49 |
| **Sock Shop** | **246 GB** | ~1.2 TB | 60 bundles |
| **Total** | **~533 GB** | **~2.7 TB** | |

Only the kernel CTF is gzipped (it expands **~7–8×** — measured by `zcat`); traces/logs/metrics are
uncompressed. The kernel is **~62–64%** of each bundle. Per-run: ~5–11 GB on disk (the anomaly_cpu/
disk stress runs are the biggest — 500–700 M events). Prometheus metrics + load CSVs per run are
small (~hundreds of MB total).

---

## 10. The headline finding (why the dataset is compelling)

The QC **verdicts themselves already tell the "kernel-wins" story.** For each fault we asked
"did a *resource metric* move enough to confirm the injection?":

- **CONFIRMED** — faults metrics *can* see: `anomaly_mem`, `anomaly_disk`, `noisy_neighbor` firing,
  `svc_mem_cap` (memory-limit drop).
- **BORDERLINE / UNCONFIRMED** — faults metrics *miss*: `slow_db` (a 500 ms DB toxic makes a search
  take **16–28 s**, but MySQL's CPU barely moves), `dependency_outage` (a paused service → a **30 s
  client hang**, invisible to metrics/logs), `error_storm`, `svc_cpu_cap`, `svc_net`, `anomaly_net`.

On Train Ticket the verdict split was **13 confirmed / 15 borderline / 15 unconfirmed / 6 n/a**
(the 6 normals). **≈ half the fault families are "metrics-blind"** — and for those the signal lives
in the **kernel** (threads blocked on sockets, cgroup throttling) and in **client-side latency**.
That is precisely the argument for the kernel modality. TT is a *stronger* version of the finding
than Sock Shop because TT services expose no app-latency metric at all, and its shared MySQL makes
`slow_db` a ~22-container, uninstrumented, kernel-only fault.

(Note: `borderline`/`unconfirmed` here is a *verification QC* outcome, i.e. "resource metrics didn't
clear the threshold" — it is expected and desirable for metrics-blind faults, not a data defect.
The study's actual modality claims come from the ablation, §11.)

---

## 11. How the data will be used (the study)

A **per-task, per-modality ablation study** (`msr-research.md` §7). Four tasks, four modalities,
evaluated with modality subsets under a fixed token budget, using 2–3 LLMs **plus** non-LLM
baselines:

| Task | Input | Output | Ground truth |
|---|---|---|---|
| **T1 Anomaly detection** | a telemetry window | anomalous? + fault family | injection window + family |
| **T2 Root-cause analysis (RCA)** | full-run bundle | scope (host/service) + resource/fault type + **target service** | `ground_truth.json` |
| **T3 Incident explanation** | full-run bundle | postmortem: onset, symptom, mechanism, blast radius, evidence | manifest + verification + fault cards |
| **T4 Repair** | full-run bundle | action from a fixed space + rationale | the recipe's cleanup (recorded remediation) |

**Design:** for each (task, run), evaluate 15 modality subsets (4 singletons, 6 pairs, 4
leave-one-out triples, all-four), each serialized to the **same token budget** so "traces beat logs"
means information, not token count. Research questions: **RQ1** informativeness matrix, **RQ2**
minimal sufficient bundle per task, **RQ3** marginal value (leave-one-out / Shapley), **RQ4**
cost–benefit (measured collection overhead + storage + tokens), **RQ5** intensity/workload/scope
sensitivity, **RQ6** which kernel representation (L1 vs L2 vs L3) an LLM consumes best. The 6
`normal` runs are the negative class; `ground_truth.json` + `verification.json` are the labels; the
per-request load CSV is the client-side "user-visible impact" reference.

A later paper adds **agent trajectories as a fifth modality (M5)** on the same testbed
(`msr-research.md` §9) — the dataset schema already lists modalities as a first-class, extensible set.

---

## 12. Where the data is + how to load it

- **Location:** currently on the two GCP collector VMs (`strata-tt-collector` us-east4-c;
  `stratatrace-collector` us-east1-d), being transferred to the **Trillium** cluster
  (`/scratch/yuvraj17/microservice-trace-dataset/{sockshop,trainticket}/`) and then **Nibi**, as
  **per-recipe `.tar.gz` archives** (one archive per fault family, so extraction never mixes runs).
  See `transfer/README.md` for the push/extract scripts.
- **Loading (profile-driven, no per-app code forks):** set `STRATATRACE_APP=trainticket` (or
  `sockshop`) and use the shared `stratatrace/` package:
  ```bash
  STRATATRACE_APP=trainticket python3 stratatrace/derive_kernel_l1.py <run_dir> --reader cli   # L0 → L1
  STRATATRACE_APP=trainticket python3 stratatrace/derive_kernel_l3.py <run_dir>                # L1 → L3
  ```
  `stratatrace/loader.py` reads a run bundle + its sibling metrics into aligned per-modality
  dataframes; `stratatrace/service_map.py` holds the per-app PID/TGID → service mapping.
- **Reproducing a collection:** `microservice-lttng-data-collection-scripts/` (Sock Shop) and
  `train-ticket-collection-scripts/` (Train Ticket) hold the full rig — `vm_bootstrap*.sh`,
  compose overlays, `faults/`, `collect_trace.sh`, `run_scenario*.sh`, `run_campaign*.sh`,
  `run_gate*.sh`. Deployment = layered docker-compose `-f` files (order matters).

---

## 13. Glossary

- **Run / bundle** — one baseline→inject→recovery session and all its recorded data.
- **Recipe** — a fault script in `faults/`, e.g. `slow_db.sh`.
- **Modality** — one of the four telemetry kinds (metrics, logs, traces, kernel).
- **Blast radius** — the set of services a fault's effect reaches.
- **Trace visibility (`covered` / `blind_spot`)** — whether a fault's target is trace-instrumented;
  DBs, nacos, brokers are blind spots by design.
- **Winning modality** — the modality that best reveals a fault (the study's central variable).
- **Service map** — mapping a kernel event's PID/TGID → microservice (via `docker top`), so
  same-process-name services (`java`) are split correctly.
- **CTF** — Common Trace Format (LTTng's on-disk kernel-trace format).
- **L0/L1/L2/L3** — the kernel representation ladder (raw → KPIs → wait attribution → NL digest).
- **verify_injection / audit_alignment** — the two QC gates (did the fault fire? are modalities
  time-aligned?).

---

## 14. Getting started (do this first)

1. Read `msr-research.md` (the plan) and `fault_catalog.md` (the pre-registered predictions).
2. Grab 4 runs — one `normal`, one `slow_db_aggressive`, one `svc_mem_cap_aggressive`, one
   `dependency_outage`. For each: open `ground_truth.json`, `verification.json`, and
   `kernel_l3.jsonl`, then load `kernel_l1.parquet` with `STRATATRACE_APP` set.
3. Compare the `slow_db` and `svc_mem_cap` runs: `svc_mem_cap` verifies **confirmed** (metrics see
   it), `slow_db` is **borderline** (metrics-blind) — but the kernel L1/L3 shows the DB-blocked
   waits in both. That contrast **is** the project.
4. Skim `progress-notes/06-08-2026/decisions.md` (Train Ticket completion summary) and
   `release/FREEZE-v1.md` (Sock Shop) for the current state.

**Deadlines to keep in mind:** MSR 2027 abstract **Nov 5, 2026**, paper **Nov 10, 2026**. The
modality-ablation study across both apps is the critical path.
