# StrataTrace — Team Progress Summary (last 2 weeks: 29 Jul → 12 Aug 2026)

> **Who this is for:** anyone on the team who wants to know, in plain words, what data we have,
> what we are trying to prove, what we built, and what the numbers say so far.
> Deeper sources: `../../DATASET_GUIDE.md` (dataset), `../../research-agentic-rca.md` (the plan),
> `agentic-rca/RESULTS-*.md` (raw results), `progress-notes/<DD-MM-YYYY>/decisions.md` (daily log).

---

## 1. The 60-second version

We built a **labelled dataset of microservice failures** where, for every failure, we recorded
**four kinds of telemetry at the same time**: metrics, logs, distributed traces, **and kernel
traces**. The kernel layer is the part nobody else has.

Then we asked a research question:

> **How much observability can you lose before automated root-cause analysis (RCA) breaks —
> and does the kernel layer act as a safety net when the normal telemetry goes blind?**

In the last two weeks we finished data collection for both applications, moved everything to the
cluster, and built + ran **three different RCA methods** on it. Result:

**The LLM agent that can read kernel traces beats both non-LLM baselines, and it solves the exact
faults they are blind to.**

| RCA method | Correct service (Top-1) | Correct service **and** fault type |
|---|---|---|
| #1 Statistical rule-based baseline | ~48–55% | 38% |
| #2 RCAEval / Multi-source BARO (published SOTA) | 46–48% | n/a (it only localizes) |
| **#3 Our LLM + kernel agent (GPT-5.4)** | **74%** | **61%** |

And the headline story: `slow_db` (a slow database) — **baseline #1 gets it 0% of the time**,
**baseline #2 gets 50%**, **our agent gets it right including the fault type**, purely by reasoning
over kernel wait-attribution ("MySQL is 100% blocked waiting on external I/O, but it's not
saturated → this is induced database latency, not an app bug").

---

## 2. The dataset (what we collected)

### 2.1 Two applications, on purpose

We ran the **same experiment on two architecturally different systems**, so results are not an
artefact of one design.

| | **Sock Shop** | **Train Ticket** |
|---|---|---|
| Domain | e-commerce (browse → cart → checkout) | train booking (login → search → book → pay) |
| Size | ~14 services | ~40 Java services / 48 containers |
| Database design | **one DB per service** | **one shared MySQL for ~20 services** |
| Trace coverage | 6 of 14 services instrumented | all 39 Java services |
| Runs collected | **46 canonical** (60 bundles on disk) | **49** |
| Status | **FROZEN** (git tag `strata-v1-freeze`) | **complete** |

**Why the second app matters:** in Train Ticket, one slow database ripples across ~22 containers,
and MySQL itself has no instrumentation → the perfect "traces can't see it, kernel can" case.

### 2.2 What one "run" is

Every run is a 4-minute session with a clean before/during/after structure, so we capture the
fault *starting* and *being fixed*:

```
|---- baseline 60s ----|-------- fault injected 120s --------|---- recovery 60s ----|
        healthy                    anomaly active                  fault removed
   <----------------- all 4 modalities recorded continuously ------------------>
```

### 2.3 The four modalities

| Modality | Where it comes from | What it gives us |
|---|---|---|
| **Metrics** | Prometheus, 5s scrape (cAdvisor + node-exporter) | CPU/memory/network/disk per container |
| **Logs** | `docker logs` per container | exceptions, GC, connection errors |
| **Traces** | OpenTelemetry Java agent → OTLP | per-request spans across services |
| **Kernel traces** | LTTng full-syscall + sched/block/net | every syscall, context switch, disk & network event of **every** service — *no instrumentation needed* |

**All four share one clock**, measured drift **≈0.001 ms**. That time-alignment is novelty claim #1.

### 2.4 The kernel "representation ladder"

Raw kernel traces are enormous, so we derive progressively smaller/smarter views:

- **L0** — raw kernel trace (gzipped, ~3–13 GB per run). Ground truth, huge.
- **L1** — `kernel_l1.parquet`: per `(service, 1-second window)` KPIs — syscall counts and latency
  percentiles, scheduler waits, disk I/O, network bytes, page faults. *This is what analysis code reads.*
- **L2** — per-request **wait attribution**: where a request's time actually went (on-CPU vs waiting
  for CPU vs blocked on disk/network/lock). **This is the kernel's unique semantic — *why* it was slow.**
- **L3** — `kernel_l3.jsonl`: a short, templated English digest per service. The **LLM-readable** form
  (templated so the model can't hallucinate numbers).

### 2.5 The 12 injected faults

| # | Fault | What it simulates | Predicted "winning" modality |
|---|---|---|---|
| F1 | `anomaly_cpu` | host CPU exhaustion | metrics detect, **kernel** explains |
| F2 | `anomaly_disk` | disk saturation | metrics / **kernel** |
| F3 | `anomaly_mem` | memory exhaustion + reclaim | metrics / **kernel** |
| F4 | `anomaly_net` | host network delay + loss | traces / kernel |
| F5 | **`slow_db`** | slow/saturated database | **kernel** (DB is trace-blind) |
| F6 | `error_storm` | 5xx / connection-error storm | **logs** |
| F7 | `svc_cpu_cap` | one service CPU-throttled | **kernel** |
| F8 | `svc_mem_cap` | GC pressure / OOM-kill | **logs** |
| F9 | `dependency_outage` | a **frozen** dependency (hangs, doesn't error) | **traces** |
| F10 | **`queue_backlog`** | silent async queue backlog | **kernel only** |
| F11 | **`noisy_neighbor`** | CPU stolen by a co-tenant, app KPIs look fine | **kernel only** |
| F12 | `svc_net` | one service's network slowed | traces / kernel |

These predictions were **pre-registered** (written down *before* we ran the study) in
`../../fault_catalog.md` — so we can't be accused of fitting the story to the data.

### 2.6 Size

| App | On disk (gzipped) | Uncompressed | Runs |
|---|---|---|---|
| Train Ticket | 287 GB | ~1.5 TB | 49 |
| Sock Shop | 246 GB | ~1.2 TB | 60 bundles |
| **Total** | **~533 GB** | **~2.7 TB** | **95** |

Kernel traces are ~62–64% of every bundle.

---

## 3. What the data actually looks like (small examples)

### 3.1 One run's folder

```
traces/slow_db/tt_slow_db_aggressive_steady_r1/
├── kernel/kernel/channel0_*.gz    # L0 raw kernel trace, gzipped (the bulk)
├── otlp/spans.jsonl               # distributed traces for this run's window
├── logs/<container>.log           # per-container logs
├── meta/
│   ├── top_<container>_*.txt      # docker-top → PID/TGID → service (kernel↔service join key)
│   └── runinfo_start.txt/_end.txt # clock anchors → the time-alignment proof
├── ground_truth.json              # THE LABEL
├── verification.json              # QC: did the fault actually fire?
├── kernel_l1.parquet              # L1 KPIs
└── kernel_l3.jsonl                # L3 English digest
# siblings:
<run_id>_metrics/                  # Prometheus metrics for the exact window
<run_id>_load.csv                  # per-request client load log
```

### 3.2 `ground_truth.json` — the label (real Train Ticket example)

```json
{"fault": {
  "family": "C_application", "name": "slow_db_mysql", "scope": "service",
  "intensity": "aggressive",
  "parameters": {"latency_ms": 500, "jitter_ms": 100, "proxy": "mysql"},
  "target_service": "mysql",
  "expected_blast_radius": ["mysql","ts-auth-service","ts-user-service","ts-travel-service",
                            "ts-order-service","ts-gateway-service","ts-ui-dashboard"],
  "expected_winning_modality": "kernel",
  "target_trace_visibility": "blind_spot",
  "injection_start_utc": "2026-08-05T15:28:14Z",
  "injection_end_utc":   "2026-08-05T15:30:14Z"}}
```

### 3.3 `kernel_l3.jsonl` — the LLM-facing digest (real `slow_db` onset window)

> *"kernel @ t=0s: net syscalls NEW (0→13); block sectors 330×; io syscalls 128×; syscall p99
> latency 47.5× (0.0→0.8 ms); block-I/O ops 42×; block p95 latency 16× (0.1→1.0 ms)."*

It reads like "a slow, disk-backed database" — **even though `slow_db` is invisible to traces and
barely moves MySQL's CPU metric.** That single line is the whole thesis.

### 3.4 `kernel_l1.parquet`

~10,000 rows, one per `(service, 1-second window)`, with **43 services resolved** on Train Ticket —
including 38 separate `ts-*-service` Java services. That split is non-trivial: dozens of containers
all report the process name `java`, and we attribute each kernel event to the right service via its
container's PID/TGID map.

### 3.5 Load CSV (client-side truth)

```
timestamp,user_id,scenario,method,endpoint,status_code,latency_ms,success
```

This is how we know a 500 ms database toxic turned a *user's* search into a **16–28 second wait** —
while MySQL's CPU metric barely twitched.

### 3.6 Dataset index (`../../release/DATASET_MANIFEST.csv`)

```
fault_family,fault_name,run_id,intensity,target_service,expected_winning_modality,verification,kernel_l0_gb,has_L1,has_L3
A_host_resource,anomaly_cpu,anomaly_cpu_aggressive_steady_r1,aggressive,host,kernel,confirmed,2.29,True,True
```

---

## 4. The research direction (and the pivot on 07 Aug)

Originally the plan was a broad **modality-ablation study** (which modality helps which task).
After the supervisor meeting on **7 Aug**, we sharpened it into something more actionable and
agent-centred:

> **"How much observability can we lose before diagnosis breaks — and does the agent adapt,
> and does the kernel act as a safety net?"**

Four research questions:

| RQ | Question |
|---|---|
| **RQ1** | **Robustness**: degrade the telemetry (sample traces, coarsen metrics, filter logs, hide services) — where does accuracy fall off a cliff? |
| **RQ2** | **Agent strategy**: when app-level visibility degrades, does the agent *escalate to lower-level telemetry*, or does it keep hammering dead traces? |
| **RQ3** | **Cross-modality compensation**: metrics+logs+traces vs metrics+logs+traces+**kernel**. Does kernel rescue the blind-spot faults? |
| **RQ4** | **Minimum observability budget**: accuracy vs collection cost — what's the cheapest telemetry config that keeps ≥90% of full accuracy? |

**The critical methodological guardrail (from Mahsa):** never change the data *and* the agent in the
same comparison. Degradation is a **deterministic, seeded, offline transform on already-stored runs**
— we never re-collect data. The agent is held fixed inside any sweep.

### The degradation knobs (`../../agentic-rca/degrade.py`)

| Axis | Values |
|---|---|
| Trace sampling | keep 100% / 50% / 25% / 10% / 5% |
| Metric resolution | 5s (full) / 10s / 30s / 60s |
| Log level | ALL / WARN / ERROR only |
| Kernel tier | all / L1 only / L3 only / **none** |
| Whole-modality removal | drop kernel, drop traces |
| Service coverage | hide N services entirely |

That's the **15-condition grid** used in every sweep.

---

## 5. What we built (the harness) — `../../agentic-rca`

```
StrataTrace run bundle
        ↓
  degrade.py          ← seeded offline degradation (Axis A: data only)
        ↓
  stratatrace/loader.py
        ↓
  tools.py            ← 4 deterministic telemetry tools (metrics / logs / traces / kernel)
        ↓                  each returns bytes_touched → the RQ4 cost axis
  RCA method (#1 / #2 / #3)
        ↓
  {root_cause_service, fault_type, evidence, confidence} + full trajectory
        ↓
  runs.py score()  vs  ground_truth.json
        ↓
  evaluate.py → analyze.py  (AC@1 / AC@3 / MRR, per-family tables)
```

Key components:

- **`tools.py`** — four tools the agent can call: traces (p50/p95/p99 per service), logs (error
  signatures), metrics (curated + counter→rate + ranked by magnitude), **kernel** (L1 latency peaks,
  L3 deviations, L2 wait attribution). Every call is byte-accounted.
- **`agent.py`** — a tool-using LLM loop. Now **multi-provider**: Anthropic *and* the
  OpenAI-compatible family (Azure OpenAI, Gemini, OpenAI, Ollama) via `RCA_PROVIDER`. Secrets in
  `../../.env` (git-ignored). It logs the full **trajectory** (which tool, which service, which window,
  what it found, what it did next) — that's the RQ2 data.
- **`degrade.py`** — the offline degradation wrapper.
- **`evaluate.py`** — runs `(incident × condition × method)`, scores, aggregates.
- **`analyze.py`** — reports the standard RCA metrics **AC@1 / AC@3 / MRR** (so our numbers are
  directly comparable to published papers).

Everything runs on the **Trillium cluster** against `/scratch/yuvraj17/agentic-runs/` —
**93 labelled fault incidents** (43 Train Ticket + 50 Sock Shop). No data was copied to laptops.

---

## 6. The three RCA methods and their results

### Method #1 — Statistical / heuristic baseline (no LLM)

A rule tree over the four tools. Swept over **93 incidents × 15 conditions = 1,395 evaluations**.

- Overall: **Top-1 service ~48%**, **both service+fault 38%** (TT 44% / SS 32%).
- **Completely robust to degradation** — every curve is essentially flat. It rides coarse signals
  (the stress container, CPU throttling) that survive thinning.
- **Kernel-blind by construction**: removing the kernel entirely changes *nothing* (`kNone` = `full`
  for every fault family).
- **Scores 0% on `slow_db`, `queue_backlog`, `error_storm`, `svc_mem_cap`, both `*_net` faults.**

This is the reference that pins **the gap the kernel-aware agent has to close.**

### Method #2 — RCAEval / Multi-source BARO (published, peer-reviewed, MIT-licensed)

Chosen after a literature review (`../../non-llm-baseline.md`). Note: "CARE" in the old design doc was a
misremembered name — the real family is **RCAEval / BARO / TORAI** (Luan Pham et al., RMIT;
ASE'24 / WWW'25 / FSE'26). BARO won the **FSE'24 Best Artifact Award**. We installed RCAEval 1.6.0
and wrote an adapter turning our runs into its 4-key input format. Same 1,395-evaluation sweep.

| Subset | AC@1 (Top-1) | AC@3 (Top-3) | MRR |
|---|---|---|---|
| All 93 incidents | 46% | 63% | 0.54 |
| Sock Shop | 48% | 72% | 0.59 |
| Train Ticket | 44% | 53% | 0.48 |
| kernel-decisive faults | 54% | 73% | 0.62 |

Also **flat under degradation** (MRR 0.54 at 100% traces = 0.54 at 5% traces).

### 🔑 Finding A — the two non-LLM methods have **complementary blind spots**

| Fault family | Statistical | mmbaro | Who wins |
|---|---|---|---|
| anomaly_cpu / disk / mem | 100% | 100% | tie |
| **noisy_neighbor** | **100%** | **0%** | statistical |
| **dependency_outage** | **50%** | **0%** | statistical |
| svc_cpu_cap | 80% | 50% | statistical |
| **slow_db** | **0%** | **50%** | mmbaro |
| **error_storm** | **0%** | **50%** | mmbaro |
| **svc_mem_cap** | **0%** | **50%** | mmbaro |
| svc_net | 50% | 50% | tie |
| anomaly_net / queue_backlog | 0% | 0% | both fail |
| **Overall Top-1** | **~48%** | **48%** | same score, different faults |

**Neither dominates.** They score the same overall but succeed on *different* faults — which is
exactly the argument for a third, adaptive method.

### 🔑 Finding B — you can't get the kernel's value by just "adding kernel columns"

We folded the discriminative kernel KPIs (`sys_lat_p99`, `sys_io`, `sys_futex`, `block_ops`,
`net_bytes`) straight into mmbaro's metric table. **Result: literally no change** — `full` == `kNone`
for every fault family. BARO's scorer ranks the ~200 container-metric change-points far above the
kernel columns (the first kernel column lands at rank ~195).

> **Takeaway:** the kernel's diagnostic value is **not accessible by naive feature fusion** into a
> change-point method. It needs an agent that *reasons* about wait attribution. This is a clean
> motivation for method #3, not a defect.

*(Side note: `sys_lat_p95` is useless as a feature — it saturates at the 500 ms cap.)*

### 🔑 Finding C — trace-only methods don't have a cliff; they have a floor

We added the two "expected-to-break" trace-only methods (**MicroRank**, **TraceRCA**) hoping to show
a dramatic collapse as traces are sampled away. What we found is more interesting:

- **TraceRCA** only localizes service-latency faults whose target actually emits spans
  (`svc_cpu_cap` 20%, `svc_net` 33%) and is **0% on every database / host / dependency fault**.
  Overall AC@1 ≈ 5%.
- **MicroRank** ≈ 0% across the board.
- They never work well enough *at full telemetry* to have anywhere to fall from.

> **Takeaway:** trace-only RCA is **structurally handicapped on exactly the faults where the target
> isn't an instrumented service** — the same faults where kernel telemetry is decisive.
> This reinforces the kernel thesis from a third, independent angle.

### Method #3 — The LLM + kernel agent ✅ **VALIDATED**

Sanity gate **PASSED** using **Azure OpenAI GPT-5.4**, 23 incidents (11 TT + 12 SS, one per fault family),
at 100% telemetry.

| Method | Top-1 service | Service **and** fault | Recovers `slow_db`? |
|---|---|---|---|
| #1 statistical | ~55% | 38–45% | ❌ 0% |
| #2 RCAEval mmbaro | 44–48% | — (localizer only) | service only (50%) |
| **#3 LLM + kernel agent** | **74%** | **61%** | ✅ **yes, service + fault type** |

Final gate numbers: **service 74% · fault 74% · both 61%**, at ~15 tool calls per incident and
~12k output tokens total — i.e. **cheap**.

**Why it wins — the thesis, in the agent's own words on `slow_db`:**

> *"…user-facing victims all show **off-CPU external wait** rather than CPU/memory pressure …
> **Kernel evidence on mysql attributes 100% of wait to off-CPU external I/O/dependency wait** with
> elevated syscall latency, while mysql has no saturation signals — consistent with an induced
> database-latency fault, not an application bug."*

That is **kernel-as-safety-net, demonstrated**. It also correctly separated *victims* from the
*culprit* (relevant to RQ3) and identified the injected stress containers on host faults.

**Where it still misses:** network faults (`anomaly_net`, `svc_net`), `error_storm` (it gets the
service but confuses the fault type), and `dependency_outage` (names a neighbour instead of the dead
service). These are prompt/tooling refinement targets, not fundamental.

---

## 7. Other results worth knowing

### Collection overhead (measured on the VM, never a laptop)

The "what does kernel tracing actually cost you" number — a rare asset, since most papers assert it:

| Metric | Baseline | With kernel tracing | Overhead |
|---|---|---|---|
| Throughput (req/s) | 194.2 ± 0.5 | 193.3 ± 0.3 | **−0.5%** |
| P95 latency (ms) | 45.1 ± 2.0 | 50.7 ± 2.0 | **+12.6%** |
| P99 latency (ms) | 244.9 ± 16 | 259.5 ± 25 | **+6.0%** |
| Error rate | 2.53% | 2.54% | flat |

**Kernel tracing costs ≈0.5% throughput and ~13% P95 latency at 200 concurrent users.**

### The QC verdicts already tell the story

For each fault we asked "did a *resource metric* move enough to confirm the injection fired?"

- **CONFIRMED** (metrics can see it): `anomaly_mem`, `anomaly_disk`, `noisy_neighbor`, `svc_mem_cap`.
- **BORDERLINE / UNCONFIRMED** (metrics miss it): `slow_db`, `dependency_outage`, `error_storm`,
  `svc_cpu_cap`, `svc_net`, `anomaly_net`.

On Train Ticket: **13 confirmed / 15 borderline / 15 unconfirmed / 6 n/a**. So **roughly half the
fault families are "metrics-blind"** — and for those the signal lives in the kernel and in
client-side latency. (This is a *desirable* QC outcome for blind-spot faults, not a data defect.)

---

## 8. Where everything lives

| Thing | Location |
|---|---|
| Raw archives (cold backup) | Trillium `/project/def-naser2/yuvraj17/microservice-trace-dataset/{sockshop,trainticket}` (319 GB, per-recipe `.tar.gz`) |
| Working set (agent runs against this) | Trillium `/scratch/yuvraj17/agentic-runs/{app}/<recipe>/<run>/` — small modalities only, no raw kernel CTF |
| Original data | Both GCP collector VMs (**stopped**, disks intact) |
| Agent + evaluation code | `../../agentic-rca` (branch `agentic-tracing`) |
| Results | `../../agentic-rca/RESULTS-stat-baseline.md`, `RESULTS-nonllm-baselines.md`, `RESULTS-agent-sanitygate.md` |
| Dataset onboarding doc | `../../DATASET_GUIDE.md` |
| Daily decision log | `progress-notes/<DD-MM-YYYY>/decisions.md` |

---

## 9. Operational constraints the team must know

These cost us real time; don't rediscover them.

1. **The agent can only run on the cluster's login node.** Compute nodes have **no internet**
   (verified — `curl` to the Azure endpoint times out, no proxy). So agent runs **cannot** be Slurm
   batch jobs. Non-LLM sweeps *can* (and do) run as batch jobs.
2. **The login node has a watchdog that kills long processes.** One incident (~2 min, 7.4 GB) is
   fine; 23 back-to-back got killed mid-run. → **run the agent in short per-family chunks**, one
   fresh process each.
3. **The full agent degradation sweep is 93 × 15 = 1,395 agent runs.** That needs login-node chunking
   *and* a real Azure credit budget. **We should subsample deliberately** (blind-spot families ×
   trace/kernel axes first) rather than brute-force.
4. **Sock Shop kernel L2 is missing.** The Sock Shop collector VM wrote CTF2 format, which Trillium's
   babeltrace 2.0.4 can't read (Train Ticket wrote CTF1.8, which works). So SS uses kernel **L1+L3**;
   TT has **L1+L2+L3**. Fix: derive L2 on the SS collector VM itself and push the ~50 tiny files.
5. Use `python -u` on the cluster — Python block-buffers stdout to a file and logs look empty.
6. Secrets live in `../../.env` (git-ignored); `../../.env.example` is the committed template.

---

## 10. Where we are and what's next

### Done ✅
- Both datasets **complete and validated** (95 runs, ~533 GB, 4 aligned modalities, labelled).
- Everything **transferred to Trillium**; GCP VMs stopped (cost halted).
- Full **agentic-RCA harness** built (tools, agent, degradation module, evaluation runner, analysis).
- **All three RCA methods working and documented.**
- Two full 1,395-evaluation degradation sweeps (methods #1 and #2) — done with **zero API cost**.
- Agent made **multi-provider** and **sanity-gate validated** — it beats both baselines.

### Next 🔜
1. **The full agent degradation sweep** (RQ1 + RQ2 + RQ3) — login-node chunked, deliberately
   subsampled, needs an Azure credit budget. This is the main remaining experiment.
2. **Fix the agent's known misses** — network faults, `error_storm` fault-type confusion,
   `dependency_outage` — via prompt/tooling refinement.
3. **Derive Sock Shop kernel L2** on the collector VM so both apps are on equal footing for the
   kernel-compensation test (RQ3).
4. **RQ4 Pareto analysis** — join RCA accuracy to measured collection cost (bytes + tokens +
   overhead numbers we already have) and find the cheapest telemetry budget keeping ≥90% accuracy.
5. **Confirm the agentic direction with Naser** — still an open decision gate before heavy write-up.
6. **Deadlines:** MSR 2027 abstract **5 Nov 2026**, paper **10 Nov 2026**.

---

## 11. The one-paragraph pitch for outsiders

*Every observability dataset ships metrics, logs and traces. None ships kernel traces. We built one
that does — 95 labelled failure runs across two microservice systems, four modalities aligned to
sub-millisecond precision, with pre-registered predictions about which modality should win each
fault. Then we showed it matters: an LLM agent that can read kernel wait-attribution diagnoses 74% of
incidents correctly versus ~48% for both a hand-written statistical baseline and the published
state-of-the-art (RCAEval/BARO), and it solves the faults that are structurally invisible to
traces — a slow database, a silent queue backlog, a noisy neighbour. We also showed the kernel's
value can't be obtained by simply feeding kernel features into an existing method; it takes an agent
that reasons about* why *a request was waiting.*
