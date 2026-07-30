# Agent-First, Collection-Aware Observability — Robust MVP & Demo Plan

**Purpose.** Both (a) the *architecture document* Naser wants tonight and (b) the *build
spec* for a robust, fully-functional demo for tomorrow. The research artifact
(`meeting-notes/compass_artifact_*.md`) estimates 4–6 weeks — **that assumes a human
writing every line.** With Claude Code implementing and testing live on the GCP VM, we
build the *impressive* version tonight. This plan is scoped up accordingly.

**Design principle that keeps it robust:** attempt the ambitious version of every
component, but give each one a **proven fallback that already works**, so the demo
physically cannot fail. (Real Babeltrace2 graph → subprocess CTF reader we already have;
live scoped capture → replay over the 40 collected runs; live agent+MCP → deterministic
CLI.) Robust = ambitious *and* guaranteed.

**What this MVP proves:** *a library of "skills" turns a plain-language problem into a
machine-readable collection spec — a different one per problem — that scopes what kernel/
trace/log/metric data is captured, then runs a kernel-deep RCA that is correct while
touching a tiny fraction of the data.* No incumbent (Datadog Bits AI, Dynatrace Davis) or
academic system (TMLL, TAAF, HolmesGPT) decides *what to collect from the problem
statement*, and none go kernel-deep. That is the wedge.

> Partner = **Ciena** (transcript "Siena"); backend = **Babeltrace2** (transcript "bubble
> trace"). VM is **up**: `stratatrace-collector`, us-east1-d, has LTTng + Babeltrace2 +
> the 40-run 164 GB dataset + the Sock Shop stack + `claude` CLI.

---

## 0. The demo in one sentence

> "I ask an AI agent about five *different* problems. Each time it loads a different
> **skill**, and each skill declares it needs *different* telemetry — DB slowness needs
> kernel socket-waits + DB traces; a noisy neighbor needs kernel scheduling only; a dead
> dependency needs distributed traces; an error storm needs logs. It collects **only what
> that skill declares**, runs a kernel-deep analysis, and returns the correct root cause
> in a clean visual report — reading **tens of MB**, not the **164 GB** everything-bundle.
> This is the same system deciding, per problem, *what to even collect.*"

The multi-skill sweep is the robust pitch: it proves the thesis ("thousands of skills,
each collection-aware") **and** that different problems need different modalities — which
is exactly our modality-ablation research rendered as a live product.

---

## 1. What we prove, vs whom (honest slide)

| Capability | Datadog / Dynatrace | TMLL / TAAF | HolmesGPT | **This MVP** |
|---|---|---|---|---|
| Agent-native / MCP | ✅ | ⚠️ | ✅ | ✅ |
| Kernel-trace depth (LTTng) | ❌ | ✅ | ❌ | ✅ |
| **Skill compiles problem → collection spec** | ❌ | ❌ | ❌ | ✅ **(wedge)** |
| Skill = packaged requirements + workflow + output | ❌ | ❌ | ⚠️ | ✅ |
| Catalog of composable skills, one per problem class | ❌ | ❌ | ⚠️ | ✅ |
| Beautiful, patent-ready visual output | ✅ | ✅ | ⚠️ | ✅ |

**Pitch line:** *"Everyone analyzes telemetry you already collected. We compile the
problem statement into the minimal, kernel-deep collection plan first — a different plan
per problem — and prove equal RCA at a fraction of the data."*

---

## 2. The robust demo (4 acts, ~7 min)

**On screen:** left — the `claude` CLI (agent) on the MCP server; right — a browser
showing the **investigation dashboard** (auto-refreshes per run) and a **catalog view**.

**Act 1 — the skill catalog (breadth).** Agent calls `discover_skills` → shows a catalog
of **5 skills**, each with its declared modality footprint. Narrate: "each is a packaged
diagnostic contract; the agent picks one from the problem."

**Act 2 — collection-aware, made visible (the wedge).** Prompt: *"my database is really
slow."* Agent → `discover_skills` → `db-slowness-rca` → `phase1_requirements` prints the
**requirements JSON** + the literal `lttng enable-event …` scoping command. Narrate: "the
skill decided what to collect *before* touching data — nobody else does this."

**Act 3 — live scoped capture + kernel-deep RCA (the proof).** Agent → `run_skill`. The
engine runs a **live, scoped LTTng capture** on the running Sock Shop stack — enabling
*only* the declared events — injects the `slow_db` fault, collects, and analyzes through a
real **Babeltrace2 graph** (wait-attribution). Dashboard fills in:
- wait-attribution donut: **blocked-on-DB-socket 89%**, on-CPU 6%, disk ~0%;
- latency timeline with the injection window shaded (4.8 ms → 2.2 s);
- verdict card: *root cause = DB connection-path latency; disk and CPU ruled out; fix …*;
- data bar: **scoped capture ≈ 40 MB · curated full run 2.6 GB · everything-bundle 164 GB.**
Flip to `ground_truth.json` → Toxiproxy latency toxic on the DB path. **Match.**
*(Fallback one keystroke away: replay over the pre-collected `slow_db` run — identical
dashboard, no wait.)*

**Act 4 — different problems, different data (breadth + the research story).** Fire the
other four prompts; each renders its dashboard and, crucially, a **"decisive modality"**
badge:
- *"CPU pegged at 100%"* → **cpu-saturation** → kernel scheduling names the aggressor
  (`stress-ng`) that metrics only see as "host busy."
- *"everything's a bit slow but nothing's erroring"* → **noisy-neighbor** → **kernel-only**:
  metrics/traces flat, kernel shows contention. (The killer slide: proves kernel necessity.)
- *"orders are failing"* → **dependency-outage** → **traces** localize the dead `payment`
  edge; kernel confirms the frozen cgroup.
- *"lots of 5xx from catalogue"* → **error-storm** → **logs** win (driver-error strings).
Then the **benchmark table**: 5 skills · correct RCA · decisive modality · data-touched vs
everything-bundle. That table is the paper's thesis and Ciena's ROI in one frame.

---

## 3. Architecture — the MVP we build tonight

```
  5 problem prompts
        │
        ▼
 ┌──────────────┐   MCP (stdio/SSE)   ┌──────────────────────────────────────────────┐
 │ AGENT         │◄──────────────────►│ MCP SERVER  (FastMCP)                          │
 │ claude CLI    │                    │  tools: discover_skills, phase1_requirements,  │
 │ (SDK loop bkp)│                    │         run_skill, query_result, list_runs     │
 └──────────────┘                    │  resources: skill://catalog, result://{run}/*  │
        ▲ renders                     │  prompts: canned investigations                │
        │                             └───────────────┬────────────────────────────────┘
 ┌──────┴───────────┐                                 │ two-phase engine
 │ DASHBOARD (HTML) │◄───── writes ───────────────────┤ P1 requirements → P2 execute
 │ donut/timeline/  │                                 │
 │ verdict/data-bar │        ┌────────────────────────┴───────────────────────────────┐
 │ + catalog + bench│        │ SKILL CATALOG (5×): SKILL.md + skill.json                │
 └──────────────────┘        │   requirements(kernel events/syscalls, otel, logs, metrics) │
                             │   + workflow DAG + output contract + decisive-modality     │
                             └────────────────────────┬───────────────────────────────┘
                                                      │
     ┌────────────── EXECUTION (two modes, same output contract) ─────────────────────┐
     │ MODE A — LIVE scoped capture (the wedge, live):                                 │
     │   skill events → collect_trace.sh (KERNEL_EVENTS=<skill list>) + fault recipe   │
     │   → scoped LTTng CTF + scoped OTel/logs/metrics                                 │
     │ MODE B — REPLAY over a pre-collected run (fallback + speed): the 40-run dataset  │
     │                                                                                 │
     │   ANALYSIS:  Babeltrace2 graph  src.ctf.fs → flt.trimmer → flt.wait_attribution │
     │              (bt2 Python bindings; subprocess reader = proven fallback)          │
     │              + OTel span read + metric change-point + log scan                  │
     │   REASONING: Claude (Anthropic API) over a compact evidence block → RCA         │
     └─────────────────────────────────────────────────────────────────────────────────┘

  NEXT (name as roadmap, do NOT claim done): custom source.otel plugin to mux ALL four
  modalities into ONE bt2 CTF stream · GraphRAG central index · adaptive re-collection
  loop · Ciena Sherlock backend · skill marketplace/signing.
```

**Genuinely tonight (all testable on the VM):** the 5-skill catalog; the full FastMCP
server (tools + resources + prompts); the real Babeltrace2 graph wait-attribution engine
(with the audit_alignment.py subprocess reader as fallback); **both** execution modes
(live scoped capture reusing `collect_trace.sh`+recipes, and replay over the dataset);
Claude RCA; the HTML dashboard + catalog + benchmark table; the cross-fault benchmark run.

**Honestly next (don't overclaim):** the custom `source.otel` Babeltrace plugin that
unifies OTel into the *same* graph (tonight we read OTel/logs/metrics alongside, and show
the muxer in the architecture); GraphRAG; the adaptive loop. These are "immediate next,"
and saying so is what protects credibility.

---

## 4. Build spec

### 4.1 Layout
```
agent-first-mvp/
  skills/<skill>/SKILL.md + skill.json          # 5 skills
  engine/
    phase1.py            # problem → skill match → requirements JSON + lttng scope cmd
    phase2.py            # orchestrates mode A/B, calls analysis, assembles output contract
    bt_graph.py          # Babeltrace2 python-binding graph: ctf.fs→trimmer→wait_attribution
    ctf_reader.py        # subprocess bt2 reader (LIFT from audit_alignment.py) — fallback
    modalities.py        # OTel span read + metric change-point + log scan (reuse audit loaders)
    rca_llm.py           # Anthropic API RCA over compact evidence
    sizes.py             # data-touched vs everything-bundle measurement
    benchmark.py         # run all 5 skills over their runs → accuracy + reduction table
  live_capture.py        # MODE A: skill events → collect_trace.sh + recipe (reuse existing)
  mcp_server.py          # FastMCP (tools + resources + prompts)
  dashboard/             # self-contained HTML template + generated per-run reports
  demo_cli.py            # deterministic all-acts fallback (no MCP/agent)
  .mcp.json  README.md
```
**Reuse that makes it a one-nighter:** `audit_alignment.py` (bt2 subprocess reader, kernel
regex, tid→container map, OTLP loader, metric reader, clock handling); `collect_trace.sh`
(already has a `KERNEL_EVENTS` knob — extend to take the skill's event list);
`faults/*.sh` (proven fault injectors); `faults/verification_targets.json` (a working
proto-"requirements" file); `ground_truth.json`/`verification.json` (correctness oracle).

### 4.2 The 5-skill catalog (each maps to a real, calibrated, ground-truth fault)

| Skill | Fault (have it) | Decisive modality | Kernel signal | RCA it must produce |
|---|---|---|---|---|
| **db-slowness-rca** | slow_db | kernel + traces | blocked-on-socket (DB fd) | DB connection-path latency; rule out disk/CPU |
| **cpu-saturation-rca** | anomaly_cpu | kernel + metrics | sched run-queue; aggressor procname | host CPU saturated by `stress-ng`; name it |
| **noisy-neighbor-rca** | noisy_neighbor | **kernel only** | contention/run-queue while KPIs flat | co-located CPU hog; metrics/traces blind |
| **dependency-outage-rca** | dependency_outage | **traces** + kernel | frozen cgroup silence | `payment` down; broken orders→payment edge |
| **error-storm-rca** | error_storm | **logs** + traces | RST/short-lived conns | DB conn resets → catalogue 5xx (log strings) |

This set is the robust story: **five problems, five different collection specs, five
different decisive modalities** — i.e., the skill genuinely decides *what to collect*, and
it's different each time. Each skill's `skill.json` differs mainly in its `requirements`
block + which wait-attribution dimension it privileges; the engine is shared.

`db-slowness-rca/skill.json` (corrected for our real fault = **network latency on the DB
socket path**, not disk):
```json
{
  "skill": "db-slowness-rca", "version": "0.1.0",
  "problem_triggers": ["database is slow","db latency","slow queries"],
  "hypotheses": [
    {"id":"db_conn_path_latency","evidence":"threads blocked in socket recv/read on the DB fd"},
    {"id":"db_disk_io","evidence":"block-device wait / fsync on the DB host"},
    {"id":"service_cpu_bound","evidence":"threads on-CPU or runnable-waiting, not blocked on DB"}
  ],
  "requirements": {
    "kernel_lttng": {
      "events":["sched_switch","sched_waking","sched_wakeup"],
      "syscalls":["recvfrom","sendto","read","write","futex","epoll_pwait"],
      "contexts":["pid","tid","procname"],
      "scope":{"target_services":["catalogue","catalogue-db"]},
      "mode":"snapshot","max_duration_s":60,
      "capture_cmd":"lttng enable-event -k --syscall recvfrom,sendto,read,write,futex,epoll_pwait && lttng enable-event -k sched_switch,sched_waking,sched_wakeup"
    },
    "otel":{"services":["catalogue"],"signals":["traces"]},
    "logs":{"services":["catalogue","catalogue-db"],"level":"WARN+"},
    "metrics":["histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job=\"catalogue\"}[1m])) by (le))"]
  },
  "workflow":[
    {"id":"collect","op":"scoped_capture_or_replay","from":"requirements"},
    {"id":"attribute","op":"thread_wait_attribution","inputs":["collect"]},
    {"id":"onset","op":"change_point","inputs":["collect"]},
    {"id":"reason","op":"llm_rca","inputs":["attribute","onset","hypotheses"]}
  ],
  "output":{"format":"html+json","contract":{"root_cause":"str","evidence":"list",
    "ruled_out":"list","decisive_modality":"str","confidence":"float",
    "recommended_fix":"str","data_touched_mb":"float"}}
}
```

### 4.3 Babeltrace2 graph engine (`bt_graph.py`) — the real backend
Build an actual bt2 graph (this is Naser's "agent-first Babeltrace" point, made real):
`source.ctf.fs`(the scoped kernel trace) → `filter.utils.trimmer`(injection window) → a
**custom Python filter/sink** that, per `tid`, classifies time into on-CPU / runnable-wait
/ blocked-on-socket / blocked-on-disk / blocked-on-futex from the `sched_*` +
syscall-enter/exit stream, and emits the compact attribution. **Fallback (already works):**
`ctf_reader.py` lifted from `audit_alignment.py` (subprocess `babeltrace2 --begin/--end`
+ regex) computes the same attribution without the binding API. Build the graph version;
if bindings fight back within ~45 min, switch to the subprocess reader and keep moving.

### 4.4 Live scoped capture (`live_capture.py`) — MODE A, the live wedge
Reuse `collect_trace.sh` with the skill's event list (extend its `KERNEL_EVENTS` knob to
accept an explicit list), drive the matching `faults/<x>.sh` recipe for the baseline→
inject→recover window, and collect ONLY the declared events + scoped OTel/logs/metrics.
Measure the resulting trace size live. **Fallback:** MODE B replay over the pre-collected
run (instant, deterministic) — same output contract, so the dashboard is identical.

### 4.5 Full FastMCP server + Claude front-end
Tools `discover_skills / phase1_requirements / run_skill / query_result / list_runs`;
resources `skill://catalog` and `result://{run_id}/{artifact}`; prompts for canned
investigations. Register in `.mcp.json`; drive with the `claude` CLI on the VM (legit
"agent + MCP", minimal code). **Fallback:** `demo_cli.py` runs the identical pipeline with
no MCP/agent.

### 4.6 Dashboard (`dashboard/`) — beautiful, because Naser required it
Self-contained HTML (inline CSS/JS, no external deps) generated per investigation:
verdict card (root cause + confidence + fix + decisive-modality badge), wait-attribution
donut, latency timeline with injection window shaded, evidence table, and the
data-reduction bar (scoped vs curated-run vs 164 GB). Plus a **catalog page** (the 5
skills + their modality footprints) and a **benchmark page** (the 5-fault results table).
Render via the Artifact tool for a crisp browser view, and also save static HTML on the VM.

### 4.7 Benchmark (`benchmark.py`) — the headline number, across the catalog
Run all 5 skills in replay mode over their ground-truth runs; tabulate: RCA correct
(vs `ground_truth.json`), decisive modality, data-touched vs everything-bundle. Produces
the "equal accuracy, X% less data, and here's which modality mattered per task" table —
the artifact's headline research claim, measured, not asserted.

---

## 5. VM / infra + DATASET SAFETY

**Dataset safety (non-negotiable — the 164 GB dataset is the only copy and is gitignored):**
- ✅ **Full-disk snapshot taken before any MVP work:** `stratatrace-dataset-safe-20260729`
  (500 GB disk, ~115 GB compressed, READY). Recoverable in minutes. Verified intact first:
  40 runs, 34 ground_truth+verification, 164 GB.
- **READ-ONLY discipline (the MVP never writes into `~/traces`):** all decompression and
  outputs go under a separate `~/mvp_work/` scratch dir. To feed babeltrace2 a gzipped
  run, **copy** that run's kernel into `~/mvp_work/<run>/` and `gunzip` the copy — never
  `gunzip` in place, never `gunzip -k` inside `~/traces`. Live capture (MODE A) writes to
  `~/mvp_captures/`, not `~/traces`. Dashboards/caches live in `agent-first-mvp/` or
  `~/mvp_work/`.
- If we ever need to be extra safe, re-snapshot before a risky step; snapshots are cheap
  and incremental.

**VM:**
- **Up** (us-east1-d, IP 34.73.248.241): babeltrace2 2.1.2, Python 3.12, LTTng, the
  dataset, the Sock Shop stack, 274 GB free. **`claude` CLI is NOT installed** — reinstall
  it for the agent demo (`curl -fsSL https://claude.ai/install.sh | bash`), or use the
  Anthropic Python SDK loop as the agent (backup path).
- **Prep:** copy+gunzip the demo runs into `~/mvp_work/` (per safety rule above); bring the
  stack up (start prometheus/cadvisor) for MODE A; set the Anthropic API key.
- **Robustness:** pre-run all 5 skills in replay once and cache dashboards to the repo, so
  the CLI + cached dashboards demo with zero live dependencies.

---

## 6. Tonight — parallel tracks + robustness ladder

Claude builds these largely in parallel, testing on the VM:
- **Track 1 (engine):** ctf_reader/bt_graph wait-attribution + modalities + change-point →
  correct evidence for `slow_db`, then generalize to the other 4 faults.
- **Track 2 (skills+MCP):** 5 skill.json/SKILL.md + FastMCP + `.mcp.json` + `demo_cli.py`.
- **Track 3 (frontend):** HTML dashboard + catalog + benchmark pages.
- **Track 4 (live):** `live_capture.py` scoped capture on the running stack.

**Robustness ladder — every rung is a strong demo; ship the highest we reach:**
1. **Solid:** 5 skills + engine + `demo_cli.py` replay + **beautiful dashboards** + benchmark
   table. (Multi-skill, kernel-deep, visual, measured — already a compelling demo.)
2. **+ Agent:** `claude` CLI drives it through the full MCP server (the agent-first story).
3. **+ Live wedge:** MODE A live scoped capture on one skill (`slow_db`) — collection-aware,
   live.
4. **+ real bt2 graph** (vs subprocess) + polished 3-slide deck.

Target rung 3–4. Rung 1 alone already beats "a chatbot on MCP" decisively.

---

## 7. Honesty & "do not claim" (survives Ciena/Ericsson scrutiny)
- **Real:** kernel traces + real Babeltrace2 analysis; wait attribution; the RCA inference
  (fault label hidden from the LLM); ground-truth match; live scoped LTTng capture; the
  measured data-reduction; 5 distinct skills/modalities.
- **Staged/next (say so):** OTel/logs/metrics read alongside, not yet through a single
  `source.otel` bt2 plugin; GraphRAG/adaptive-loop/marketplace are roadmap; no autonomous
  remediation (scope to RCA localization + evidence — best LLMs solve only ~11% of OpenRCA,
  so we claim *localization*, not auto-fix).
- **The line that lands:** *"TMLL/Datadog analyze what you already collected; we compile the
  problem into the minimal kernel-deep collection plan first — a different plan per problem —
  and here's the same root cause from a fraction of the data, five times over."*

## 8. Naser's 3 slides
1. **Agent-first philosophy** — users reach observability through agents; contributions are
   skills + MCP, not UIs.
2. **Skill = collection-aware diagnostic contract** — requirements JSON + workflow DAG +
   output; two-phase engine; the 5-skill catalog with per-problem modality footprints.
3. **Live demo + benchmark** — the `slow_db` live scoped capture, the 5-skill sweep, and the
   "correct RCA, kernel-deep, tiny data, right modality per problem" table.

## 9. Post-demo roadmap (the remaining 4–6 wk artifact scope)
Custom `source.otel` plugin (unify 4 modalities in one bt2 stream — de-risk first) · live
capture-time reduction benchmark across all 12 faults · GraphRAG central index · adaptive
re-collection loop (LMAT tie-in) · Ciena Sherlock backend + private partner-format skill ·
skill SDK/marketplace + signing · provisional patent on *problem-statement→collection-spec
compilation* before publishing (target ICSE/FSE/USENIX).
