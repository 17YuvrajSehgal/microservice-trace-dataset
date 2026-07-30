# Agent-First, Collection-Aware Observability Analysis via Packaged "Skills": A Design & Strategy Report for Ciena

## TL;DR
- **Build a skill-driven, collection-aware agentic RCA system.** The defensible, patentable, and academically novel core is a two-phase "Skill" that first emits a machine-readable *data/collection requirements spec* from a plain-language problem ("my database is slow"), then executes a targeted collect→correlate→analyze→report pipeline over LTTng kernel traces (via Babeltrace2), OTel traces, logs, and metrics. No shipping AIOps product or academic system (Datadog Bits AI, Dynatrace Davis, TMLL, TAAF, HolmesGPT, OpenRCA) decides *what to collect upstream from the problem statement* — they all analyze pre-existing telemetry. That is the gap.
- **The wedge vs. Ciena's "collect-everything-into-a-zip" status quo is measurable:** a skill that collects only the events it declares it needs should hit equal RCA accuracy on the ground-truth `slow_db` fault while collecting a fraction of the data — the same class of result the ICSE-2024 adaptive-tracing work showed (77.1% trace reduction with 5.8% event loss). Lead with "X% less data, equal RCA accuracy" as both the research claim and the sales pitch.
- **MVP is ~4–6 weeks:** one "database-slowness RCA" skill, a JSON skill spec, a Python/Babeltrace2 pipeline over the existing Sock Shop `slow_db` run, and a FastMCP server exposing `discover_skills` + `run_skill`, driven by Claude. The demo must visibly show the requirements spec *scoping collection* (pulling only `sched_*`, `block_*`, targeted syscalls + the DB service's OTel spans/logs — not the 150+ GB everything-bundle).

---

## Key Findings

1. **The market is large and consolidating around agentic RCA, but every incumbent starts from already-collected data.** The AIOps market is USD 18.95 billion in 2026 per Mordor Intelligence, projected to reach USD 37.79 billion by 2031 (14.8% CAGR) — corroborated by Research Nester's USD 19.5 billion 2026 estimate — while the broader observability market is about USD 34 billion in 2026. Datadog shipped Bits AI SRE to GA on December 2, 2025 (its first GA AI agent, tested across more than 2,000 customer environments with tens of thousands of investigations before GA); Dynatrace's Davis is causal-AI over the Grail lakehouse + Smartscape topology; a wave of venture-backed AI-SRE startups (Resolve.ai, Traversal, Cleric) investigate incidents agentically. **Not one of them controls upstream instrumentation from the problem statement**, and none go to kernel-trace depth (LTTng syscalls, scheduling, block I/O).

2. **Anthropic's "Agent Skills" (SKILL.md) is the right prior-art format to align with — but it does not do collection.** A skill is a folder with a `SKILL.md` (YAML frontmatter + instructions), optional `scripts/`, `references/`, `assets/`, loaded via progressive disclosure. It is now an open standard (agentskills.io). We should adopt the packaging convention and extend it with a **machine-readable collection-requirements block and a workflow DAG** — that extension is the novel unit.

3. **The closest academic work (TMLL and TAAF, both from the Trace Compass/LTTng world) confirms the gap precisely.** TMLL (Eclipse project; Shahedi, Khouzam, Li, Lamothe, Khomh) is a Python ML library of six fixed modules (anomaly detection via z-score/IQR/Isolation Forest, memory-leak, correlation, change-point, capacity planning, idle-resource) over *already-imported* traces — no agent, no LLM, no collection control, and its own n=40 survey shows RCA is the most-wanted-but-unmet capability (75.0%). Its central thesis, the "Excellence Paradox," is that "technical excellence can actively impede adoption when conflicting with usability, transparency, and practitioner trust." TAAF (Ezaz, Khodabandeh, Babaei, Ezzati-Jivan; accepted ICSE 2026, DOI 10.1145/3744916.3787832) builds a *per-query* knowledge graph from the Trace Compass State System and lets an LLM answer questions — analysis-only, single-shot, no MCP/agent, no collection control; it improved weighted QA accuracy by an average of 21.5% (up to +31.2%) via graph grounding, and explicitly relegates "autonomous agent workflows" to future work. Neither is collection-aware, skill-driven, or two-phase. That combination is open.

4. **Babeltrace2 is the correct technical foundation and can unify all four data modalities.** Its graph architecture (source → filter → sink component classes, C + Python bindings) already mirrors OpenTelemetry's pipeline shape and scales to GB/TB traces. Custom Python/C source plugins can ingest OTel spans, logs, and metrics into the same time-ordered message stream as LTTng CTF, and the `filter.utils.muxer` + `filter.utils.trimmer` components give time-ordered multi-source correlation and windowing for free.

5. **MCP is now the de-facto agent interface for observability, and skills map cleanly onto its three primitives.** Grafana, Datadog, Sentry, Honeycomb, New Relic, PagerDuty and Dynatrace all shipped MCP servers by early 2026; Azure SRE Agent and AWS DevOps Agent (both GA April 2026) consume observability MCP servers as their primary data layer. We expose skills as an MCP `discover_skills` + `run_skill` tool pair (plus resources for results and prompts for canned investigations), and use summarization/query patterns so the agent never reads raw GB-scale traces.

---

## Details

### 1. State of the art / competitive landscape (mid-2026)

**Commercial AIOps / AI-SRE.**
- **Datadog Bits AI SRE** — GA December 2, 2025 (Datadog's first GA AI agent). Autonomous investigation agent inside the Datadog platform; reads metrics, APM traces, logs, dashboards, Change Tracking, Watchdog, DBM, profiler, GitHub. Built on a "flexible system of shared tasks" reused across agents (SRE/Dev/Security). Tested across more than 2,000 customer environments with tens of thousands of investigations before GA. **Limitation for us:** operates only on data already in Datadog; no kernel depth; no upstream collection decision.
- **Dynatrace Davis** — deterministic *causal* AI traversing the Smartscape real-time topology over the Grail lakehouse; the CTO's positioning is "only causal AI can deterministically know the root cause." Strength: topology-aware causal RCA. **Limitation:** bound to OneAgent-collected data and Dynatrace's proprietary model; no problem-statement-driven collection.
- **AI-SRE startups** — Resolve.ai raised a $125M Series A led by Lightspeed at a $1B headline valuation (announced December 19, 2025; the blended valuation was lower due to a multi-tranched structure; ARR ~$4M; founders Spiros Xanthos and Mayank Agarwal, ex-Splunk), targeting ~80% autonomous resolution. Traversal (causal ML; $48M Series A from Kleiner Perkins and Sequoia) reports in its American Express case study 82% root-cause-analysis accuracy across in-scope applications and a 32% reduction in MTTR while "ingesting 250 billion logs of interest every day." Cleric is read-only, self-learning, and a Gartner Cool Vendor 2025. These "investigation agents" actively fetch *new* evidence during an incident (kubectl, cloud APIs) — the closest philosophically to us — but they gather runtime state, **not declaratively-scoped kernel/OTel collection driven by a packaged skill spec.**
- **Open source:** HolmesGPT (CNCF Sandbox, Robusta.dev) is the most architecturally similar OSS: an agentic ReAct loop with **toolsets** and **runbooks** (YAML), read-only, RBAC-respecting, MCP-compatible. The published field lesson ("the runbooks mattered more than the model") strongly validates our skill thesis. **But** HolmesGPT toolsets read existing observability backends; they do not configure tracing sessions or decide what to capture.

**MCP servers for observability.** As of 2026 the main servers are Grafana (mcp-grafana, ~2,600+ stars), Datadog, Sentry, Honeycomb, New Relic, PagerDuty, IBM Instana, OpenObserve, OneUptime, Dynatrace. Consistent community lesson: agents work better with *fewer, well-scoped* tools than with 40+ tool descriptions — an argument for our skill-as-scoped-capability approach and progressive disclosure.

**Academic RCA/AIOps.** Microsoft's **AIOpsLab** (holistic evaluation framework) and the **OpenRCA** benchmark (Xu et al., ICLR 2025; 335 failures from three enterprise systems, over 68 GB telemetry across Market/Telecom/Bank; RCA-agent baseline writes Python to avoid stuffing raw telemetry into context) are the reference evaluations. OpenRCA reports that even the best-performing LLM solved only 11.34% of failure cases, and independent analysis of AIOpsLab found current LLM agents solve only ~18% end-to-end on complex scenarios. Traversal's own critique shows several OpenRCA labels aren't even recoverable from the provided telemetry — i.e., **evaluation is an open problem, and a clean ground-truth kernel-level dataset (ours) is valuable.** Telecom-specific work (TN-AutoRCA, alarm-based RCA over base-station knowledge graphs) confirms strong Ciena-relevant interest. RCAEval (735 failure cases; Online Boutique, Sock Shop, Train Ticket; 11 fault types) is the standard microservice RCA benchmark and notably observes **Sock Shop ships with no built-in tracing instrumentation** — meaning our curated Sock Shop kernel+OTel dataset is differentiated.

**The precise gap we fill (none of the above do all four):**
(i) the skill emits a **collection requirements spec from the problem statement** and scopes what is captured; (ii) **kernel-trace depth** via LTTng/Babeltrace2 alongside OTel/logs/metrics; (iii) **skills as self-contained, packaged, composable units** (requirements + workflow DAG + output contract + code); (iv) **agent-first / MCP-native** from day one. Datadog/Dynatrace have (iv) and topology but not (i)/(ii); TMLL/TAAF have (ii) but not (i)/(iii)/(iv); HolmesGPT has (iii)-ish + (iv) but not (i)/(ii).

### 2. What to build — full system architecture

```
                          ┌─────────────────────────────────────────────┐
   User / Agent  ──prompt──►            ORCHESTRATING AGENT LOOP          │
   "my DB is slow"         │  (Claude etc.; plans, calls MCP tools)       │
                          └───────────────┬─────────────────────────────┘
                                          │ MCP (JSON-RPC)
                          ┌───────────────▼─────────────────────────────┐
                          │              MCP SERVER LAYER                │
                          │  tools: discover_skills, run_skill,          │
                          │         phase1_requirements, query_result    │
                          │  resources: skill catalog, result artifacts  │
                          │  prompts: canned investigations               │
                          └───────┬───────────────────────┬──────────────┘
                                  │                        │
                     ┌────────────▼───────┐     ┌──────────▼────────────┐
                     │  SKILL REGISTRY /   │     │  TWO-PHASE EXECUTION  │
                     │  CATALOG (SKILL.md+ │     │  ENGINE               │
                     │  requirements JSON) │     │  P1 resolve reqs →    │
                     └─────────────────────┘     │  P2 collect→analyze   │
                                                 └──────────┬────────────┘
                                                            │
      ┌───────────────────────────────┬─────────────────────┼──────────────────┐
      │ COLLECTION ORCHESTRATION       │  BABELTRACE2 GRAPH   │  STORAGE /       │
      │  - lttng session control       │  src.ctf.lttng-live  │  CORRELATION     │
      │  - OTel sampling config         │  src.otel (custom)   │  - unified msg   │
      │  - log scoping                  │  flt.muxer/trimmer   │    stream (CTF)  │
      │                                 │  flt.<skill analysis>│  - (later) RAG/  │
      │                                 │  sink.summary/json   │    GraphRAG idx  │
      └───────────────────────────────┴──────────────────────┴──────────────────┘
                                                            ▲
                    (LATER PHASE) adaptive-tracing feedback: analysis sink emits
                    "need more of event X in window T" → re-enters P2 collection
```

**Skill specification schema (draft).** Extend Anthropic's SKILL.md with two machine-readable blocks. YAML frontmatter (`name`, `description`, `triggers`) for progressive disclosure + a JSON body:

```json
{
  "skill": "db-slowness-rca",
  "version": "0.1.0",
  "triggers": ["database is slow", "db latency", "slow queries"],
  "requirements": {
    "kernel_lttng": {
      "events": ["sched_switch", "sched_wakeup", "sched_waking",
                 "block_rq_issue", "block_rq_complete"],
      "syscalls": ["read","write","fsync","recvfrom","sendto","futex"],
      "scope": {"target_processes": ["mysql*","mongod*"], "cpus": "all"},
      "mode": "snapshot", "max_duration_s": 60
    },
    "otel": {"services": ["catalogue-db","orders-db"],
             "signals": ["traces","metrics"], "sampling": "tail:latency>p95"},
    "logs": {"sources": ["catalogue-db","orders-db"], "level": "WARN+"},
    "metrics": ["container_cpu","disk_io_wait","db_conn_pool","query_latency_p99"]
  },
  "workflow": [
    {"id":"collect","op":"orchestrate_collection","from":"requirements"},
    {"id":"sync","op":"time_align","inputs":["collect"]},
    {"id":"critpath","op":"critical_path","inputs":["sync"]},
    {"id":"detect","op":"anomaly_detect","method":"iforest+changepoint","inputs":["sync"]},
    {"id":"reason","op":"llm_rca","inputs":["critpath","detect"]}
  ],
  "output": {"format":"text+table","contract":{"root_cause":"string",
             "evidence":"list","confidence":"float","recommended_fix":"string"}}
}
```

**Babeltrace2 plugin layer.** Use the native `source.ctf.fs` / `source.ctf.lttng-live` for kernel traces; write a custom `source.otel` (Python bindings are fastest to prototype) that emits OTel spans/logs/metrics as Babeltrace messages carrying real timestamps; chain `filter.utils.muxer` (time-order merge across all sources) and `filter.utils.trimmer` (window to the incident); add skill-specific `filter.<analysis>` components (critical path, anomaly scoring); terminate in a `sink.summary` that writes the compact JSON/table the agent consumes (never the raw stream). Because Babeltrace can *also* write CTF via `sink.ctf.fs`, collected multi-source data can be persisted as a single normalized artifact importable by the teammate's Trace Compass/TMLL track — satisfying the loose-coupling requirement.

**Multi-modality synchronization.** Kernel CTF timestamps are high-resolution monotonic clock; OTel spans carry wall-clock start/end; logs carry wall-clock. Align by (a) recording a clock-offset anchor at collection time, (b) muxing all messages into one monotonic stream, (c) correlating OTel spans to kernel threads via PID/TID injected as span attributes at collection. This kernel↔distributed-trace correlation is exactly the technique validated in the combined distributed+kernel tracing literature.

**Adaptive-tracing feedback loop (later phase).** The analysis sink can emit a *re-collection request* ("insufficient `block_rq_*` in window T; raise fsync syscall capture") that re-enters Phase 2 — the packaged, skill-scoped realization of the ICSE-2024 adaptive-tracing result (77.1% trace reduction at 5.8% event loss) and the LMAT idea. Defer past MVP.

**Central RAG/GraphRAG index (candidate contribution, deferred).** A shared index analogous to the Trace Compass State System that all skills query instead of re-reading raw traces — TAAF demonstrates the State-System→knowledge-graph→LLM value (up to +31.2% QA accuracy with graph grounding). Start with simple matching; add GraphRAG later.

### 3. How to make the MCP

**Primitives mapping.** MCP has three primitives — **tools** (model actions), **resources** (read-only data), **prompts** (reusable templates). Map skills as:
- **Tools:** `discover_skills(problem_text)` → ranked skill matches; `phase1_requirements(skill_id, problem)` → requirements JSON (lets the agent *see and approve* the collection scope — this is the differentiator made visible); `run_skill(skill_id, params)` → executes phases; `query_result(run_id, query)` → drill into large results without dumping them.
- **Resources:** the skill catalog (`skill://catalog`), and each run's artifacts (`result://{run_id}/rca`, `result://{run_id}/critical_path`) as read-only endpoints.
- **Prompts:** canned investigation templates ("investigate DB slowness") that pre-wire the right skill.

Rationale for a *skill-discovery + skill-execution* tool pair rather than one-tool-per-skill: it keeps the agent's tool list small (the consistent 2026 community lesson that fewer tools beat 40+), and it uses progressive disclosure the way Agent Skills intend.

**Large-data handling.** Agents cannot read GB traces. Enforce a **summarize-then-query** pattern: skills always return a compact structured summary + handles; the agent uses `query_result` for targeted follow-ups; use the HolmesGPT-style `llm_summarize` transformer for any oversized tool output. Stream long-running collection/analysis via progress notifications.

**Security & sandboxing (enterprise).** Read-only-by-default on analysis; collection actions (LTTng session control) are privileged and gated behind explicit approval + RBAC, with a full audit log of every tool call — matching how enterprises are wiring observability MCP servers (read-only creds, restricted writes, audit logs to standard sinks). Run skill code in a sandboxed executor. Support both remote-hosted and self-hosted deployment (Ciena will want on-prem).

**Backend abstraction.** The MCP layer defines a backend interface so the same `run_skill` can dispatch to our Babeltrace2 engine *or* the teammate's TMLL/Trace Compass Trace-Server (TSP) connectors; outputs conform to the skill's output contract so they're importable across both tracks.

### 4. Skill catalog — what to build

| # | Skill | Data required (LTTng / OTel / logs / metrics) | Techniques | Output | Effort | Novelty |
|---|-------|-----------------------------------------------|-----------|--------|--------|---------|
| 1 | **DB-slowness RCA** (demo) | `sched_*`, `block_rq_*`, read/write/fsync/futex syscalls; DB-service OTel spans+metrics; DB logs; disk-io-wait, conn-pool, p99 | Critical path + IO wait attribution + change-point + LLM RCA | text+table | **Med** | **High** |
| 2 | **CPU saturation RCA** | `sched_switch/wakeup`, IRQ/softirq; CPU metrics | Per-CPU run-queue, top-consumer, anomaly (iforest) | graph+table | Low | Med |
| 3 | **Lock/contention analysis** | `futex`, `sched_switch`, `sched_waking` | Waiting-dependency graph (DepGraph-style) | graph | Med | **High** |
| 4 | **Critical-path analysis** | scheduling + syscalls + OTel spans | Active/blocked path extraction across kernel+span | graph | Med-High | **High** |
| 5 | **Memory-leak detection** | mmap/brk/malloc-free (uprobe), RSS metrics | Growth-trend + allocation-site (TMLL-style) | table+chart | Med | Med |
| 6 | **IO bottleneck** | `block_rq_*`, fsync/read/write | Queue-depth, latency attribution | table | Low-Med | Med |
| 7 | **Network latency / packet-loss RCA** | net softirq, `net_dev_*`, recv/send syscalls; OTel spans | Latency decomposition host vs service | graph | Med | **High (telecom)** |
| 8 | **Cross-service cascading-failure triage** | OTel spans (all), logs, per-service metrics | Dependency-graph propagation + blast radius | graph+text | High | **High** |
| 9 | **Disk saturation** | `block_rq_*`, disk metrics | Threshold + forecast (ARIMA) | table | Low | Low |
| 10 | **Container/K8s resource throttling** | cgroup metrics, `sched_*`; K8s events | Throttle-correlation | table | Med | Med |
| 11 | **Compound/complex anomaly detection** | multi-source | Multi-metric PCA + change-point voting + composition | text+chart | High | **Very High** |
| 12 | **Log-anomaly → JIRA triage** | logs + detected anomaly | Log-similarity + auto-file (prior JIRA work) | ticket | Med | Med |

**Build first (2–3): #1 DB-slowness RCA, #4 critical-path analysis, #3 lock contention.** Rationale: #1 is the agreed demo and has a calibrated ground-truth `slow_db` fault; #4 is the reusable analytical spine most other skills compose on and is exactly the "cross-view reasoning" gap TMLL leaves open (its own survey lists RCA as the most-valued-but-unmet capability); #3 is high research novelty (waiting-dependency graphs), telecom-relevant, and reuses #1's collection scope.

### 5. How skills are used — end-to-end + worked example

**Flow:** user prompt → agent calls `discover_skills` → matches `db-slowness-rca` → calls `phase1_requirements` → **agent shows the requirements JSON and the scoped collection plan to the user for approval** (the visible differentiator) → engine runs Phase 2: `lttng enable-event` only the declared kernel events on the DB processes in snapshot mode, sets OTel tail-sampling on the DB services, scopes logs → Babeltrace2 graph muxes+trims+analyzes → skill returns RCA summary + critical path + evidence table → agent renders it → optional escalation (`file_jira`, or adaptive re-collection).

**Worked example (`slow_db` on Sock Shop).** Prompt: *"My database is really slow — find the root cause."* Phase 1 emits the requirements above. Phase 2 enables only `sched_*`, `block_rq_issue/complete`, and fsync/read/write syscalls on the `catalogue-db`/`orders-db` processes plus those services' OTel spans, DB-warn logs, and disk-io/conn-pool/p99 metrics — **on the order of a few hundred MB, versus the 150–164 GB, 40-run everything-bundle.** The critical-path filter attributes request latency to blocked-on-disk-I/O time; change-point detection localizes onset; the LLM reasons over the compact evidence and reports: *root cause = elevated fsync/block-device wait on the DB service*, with the evidence intervals, confidence, and a recommended fix. Ground truth confirms the `slow_db` fault → this is your accuracy datapoint and your data-reduction datapoint in one run.

### 6. How to make and sell the skills (commercialization)

- **Skill marketplace/registry.** Mirror the Anthropic Agent Skills / agentskills.io model: a catalog of versioned, signed skill packages. Licensing options: per-skill purchase, subscription to a curated catalog, and **enterprise private catalogs** for a customer's proprietary formats.
- **Ciena adoption path.** Ciena is a $4.8B FY2025-revenue optical/networking vendor (19% YoY growth, 9,000+ employees including 4,500+ R&D specialists, 1,700+ customers in 80+ countries) with heavy AI-driven-bandwidth tailwinds — a credible enterprise adopter. Integration: (a) wrap Ciena's existing **Sherlock** log pipeline as a skill backend/toolset so skills can call it; (b) author **private skills for Ciena's non-standard partner log format** (exactly the case a custom `source.<format>` Babeltrace plugin + a private skill package handles); (c) position skills as the "decision layer" upstream of Ciena's current collect-everything-into-a-zip diagnostics — turning a blind data dump into a scoped, explainable collection plan.
- **Patentability.** The novel, non-obvious, and (per the prior-art review) unclaimed mechanism is: *deriving a machine-readable telemetry-collection requirements specification from a natural-language problem statement and using it to configure upstream instrumentation (tracepoint/syscall selection, sampling, log scope) before running a packaged analysis pipeline, with an optional analysis-driven re-collection feedback loop.* File around (i) the two-phase requirements→execution engine, (ii) skill packages as declarative "diagnostic contracts" binding requirements→workflow→output, (iii) cost-aware collection planning, (iv) the adaptive re-collection loop. Existing patents cover feedback-driven tracer configuration and telecom log troubleshooting, so claims should center on the *problem-statement-to-collection-spec compilation* and the *skill package* structure.
- **Open-core vs proprietary.** Open-source the skill *format/SDK* and the Babeltrace2/MCP plumbing (drives adoption and standardization, the way FastMCP became the de-facto MCP framework); keep the *premium skill catalog*, the collection-planning optimizer, and enterprise features (RBAC, audit, private catalogs) proprietary. Skills-as-packages create defensibility: a growing curated catalog + proprietary collection-cost models + private customer skills are hard to replicate.
- **Market framing.** Position into the USD 18.95B 2026 AIOps market as the "collection-aware, kernel-deep" tier that incumbents (data-already-ingested SaaS) structurally can't reach.

### 7. Unique idea / brainstorm (research contribution beyond the notes)

Propose the framing **"Skills as declarative Diagnostic Contracts with a cost-aware Collection Compiler."** A skill declares *what evidence would prove/disprove each hypothesis*; a **collection compiler** turns the problem statement + skill contracts into a **minimal, staged collection plan** — collect the cheapest discriminating events first, escalate only if the hypothesis remains unresolved (a cost-aware, hypothesis-driven generalization of adaptive tracing). Compose skills into DAGs for compound anomalies (e.g., cascading-failure = critical-path ∘ lock-contention ∘ IO-bottleneck).

Pair this with a **formal evaluation methodology** against the ground-truth Sock Shop fault catalog:
- **RCA accuracy** (top-1 / top-k root-cause localization) vs. a collect-everything baseline;
- **Data-volume reduction** at equal accuracy (the headline metric — the ICSE-2024 adaptive-tracing precedent is 77.1% reduction at 5.8% loss);
- **Time-to-RCA** and **collection overhead** (tracing % overhead).
This yields the crisp, dual-purpose claim — *"equal RCA accuracy while collecting X% less data than collect-everything"* — that serves as both the paper's thesis and Ciena's ROI case, and it addresses the open evaluation problems flagged in OpenRCA/AIOpsLab (best LLM solved only 11.34% of OpenRCA cases; ~18% end-to-end on AIOpsLab) by using clean kernel-level ground truth.

### 8. MVP section

**Goal:** land the "skill dictates collection" differentiator on the `slow_db` run.
**Scope:** one skill (`db-slowness-rca`); the JSON skill spec above; a Python pipeline (Babeltrace2 Python bindings or direct CTF read via the TMLL client) over the existing calibrated `slow_db` Sock Shop run; a FastMCP server exposing `discover_skills`, `phase1_requirements`, `run_skill`, `query_result`; Claude as the front-end.
**Tech stack:** Python 3.11, `fastmcp`/`mcp` SDK, Babeltrace2 + LTTng CTF traces, pandas/scikit-learn (Isolation Forest + change-point), Claude via MCP.
**Milestones (≈4–6 weeks):**
1. Week 1 — skill spec schema + registry + `discover_skills`.
2. Week 2 — Phase-1 requirements emission; wire `phase1_requirements` to show the scoped plan.
3. Week 3 — Phase-2 pipeline over `slow_db`: Babeltrace2 muxing of kernel + OTel + logs, IO-wait/critical-path + anomaly detection.
4. Week 4 — LLM RCA + output contract; MCP `run_skill`/`query_result`; Claude end-to-end.
5. Weeks 5–6 — measure data-volume reduction vs. everything-bundle; polish demo.
**What to show:** side-by-side — the everything-bundle (150–164 GB) vs. the skill's scoped requirements JSON; the agent pulling *only* the declared events/spans/logs; the RCA report naming the `slow_db` root cause with evidence; and the headline number: **~X% less data collected, correct root cause.**

---

## Recommendations

1. **Now (MVP, 4–6 wks):** build skills #1/#4/#3 spine, the FastMCP server, and the `slow_db` demo. Success threshold to proceed: correct top-1 root cause on `slow_db` **and** ≥50% data-volume reduction vs. the everything-bundle at equal accuracy. If reduction <50% or accuracy drops, narrow skill scope before adding skills.
2. **Next (1–2 quarters):** benchmark all 12 fault types in the catalog; publish the "collection-compiler + diagnostic-contract" methodology (target ICSE/FSE/USENIX; the TAAF/TMLL Trace-Compass lineage is a natural venue community). File the provisional patent around problem-statement→collection-spec compilation before publishing.
3. **Then (Ciena productionization):** wrap Sherlock as a backend toolset; author a private skill for Ciena's partner log format via a custom Babeltrace source plugin; add RBAC/audit/on-prem; enable the adaptive re-collection loop. Benchmark that would change strategy: if incumbents ship problem-statement-driven collection (watch Traversal/Datadog), pivot emphasis to kernel-depth + telecom-specific skills where they can't follow.
4. **Positioning:** always lead with the measurable "less data, equal accuracy" claim; keep the skill format open, the catalog and collection optimizer proprietary.

## Caveats
- **Market-size figures vary widely by analyst** (AIOps 2026 estimates range from ~USD 3B to ~USD 47B depending on scope/definition); treat the USD 18.95–19.5B figure as a mid-range anchor and cite the range rather than a single number in any external deck.
- **Vendor performance claims are self-reported** (Traversal's 82% accuracy / 32% MTTR reduction at Amex, Resolve.ai's ~80% autonomy target and $1B headline-but-blended valuation, Datadog's 2,000-environment testing) and unaudited; present as vendor claims.
- **The two closest academic works are single preprints** — TMLL is an experience/lessons study (n=40 survey, some informally reported numbers) and TAAF is an ICSE-2026-accepted preprint with internally inconsistent response counts; both are analysis-only, which is precisely why our collection-aware angle is defensible, but cite them carefully.
- **OTel-to-Babeltrace ingestion is a build item, not off-the-shelf** — no standard OTLP→CTF source plugin exists today; the custom `source.otel` component is real engineering risk and should be de-risked early in the MVP.
- **The Sock Shop dataset's known limitation** (ships without built-in distributed-trace instrumentation) means OTel-span coverage in the demo depends on how the 40-run dataset was instrumented; confirm span availability for the DB services before promising span-level critical-path in the demo.
- **~18% end-to-end resolution on AIOpsLab and 11.34% best-case on OpenRCA** for current LLM agents is a sobering baseline: scope the demo to RCA *localization + evidence*, not fully autonomous remediation.