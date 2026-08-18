# [FSE 2027 — first draft, 2026-08-18]

# How Much Observability Does an LLM Agent Need?
## Leakage-Controlled Root-Cause Analysis over Four Telemetry Modalities

> Working titles (pick one):
> 1. *How Much Observability Does an LLM Agent Need? Leakage-Controlled RCA over Four Telemetry Modalities*
> 2. *Honest Agents: Quantifying and Eliminating Evaluation Leakage in LLM-Based Root-Cause Analysis*
> 3. *Kernel Deep, Trace Thin: Stress-Testing an LLM RCA Agent's Observability Diet*

**Authors:** Yuvraj Sehgal, [Mahsa —], [Naser —], … *(TODO: order, affiliations)*

---

## Abstract (draft, ~200 words)

LLM agents are rapidly being adopted for root-cause analysis (RCA) in microservice
systems, but their reported accuracy is difficult to trust: benchmark artifacts —
fault-encoding run identifiers, injection containers named after their faults — hand the
agent the answer. We present a leakage-controlled evaluation methodology (identifier
masking with cross-tool identity preservation, full-fidelity audit transcripts, and an
automated leak auditor) and apply it to a new dataset: 95 labeled fault injections across
two architecturally distinct microservice systems, recorded simultaneously in **four**
time-aligned telemetry modalities — metrics, logs, distributed traces, and **kernel
traces** — with pre-registered fault→modality predictions. We find that naming leaks alone
inflate an agent's fault-classification accuracy by **57 percentage points**; after
closing them, a tool-using agent with generic cross-modality tooling still reaches **83–87%
top-1 service localization**, roughly double two non-LLM baselines including published
state-of-the-art, at ~$0.01 per incident. Degradation experiments yield three
counter-intuitive results: accuracy survives 20× trace sampling unchanged; removing kernel
telemetry entirely costs little accuracy but 34% more investigation effort; and a
*partial* kernel view (raw KPIs without interpretive framing) is **worse than none**.
An experience layer of reusable "skills" helps only when skill selection is reliable —
mis-selected skills cost more than they contribute. All 500+ diagnoses ship with
machine-checkable no-leakage certificates. *(TODO: tighten to venue word limit.)*

---

## 1. Introduction

**The problem.** Automated RCA for microservices matters (incident cost, MTTR) and LLM
agents are the current frontier: they read heterogeneous telemetry, form hypotheses,
and explain conclusions. But an uncomfortable question precedes any accuracy claim:
*did the agent diagnose the fault, or read the answer off the benchmark?* Fault-injection
datasets — including ours, initially — encode labels everywhere: run IDs like
`tt_slow_db_aggressive_steady_r1`, injection containers named `noisy-neighbor`, metric
fields named `injection`. A model that sees any of these needs no telemetry.

**What we did.** We built (i) *StrataTrace*, a two-application, four-modality incident
dataset whose kernel-trace layer no existing public dataset provides; (ii) a tool-using
LLM RCA agent with deterministic, byte-accounted telemetry tools; and (iii) a
leakage-control harness — masking, transcripts, automated audit — that lets us report,
for the first time we are aware of, *certified hint-free* agent RCA numbers, plus the
exact price of the hints we removed.

**The arc as a finding.** Our agent initially scored 74/74/61 (service/fault/both).
Closing the leaks collapsed it to 48/17/9 — proof it had been leaning on names. Rebuilding
with strictly generic tooling (baseline-vs-incident discipline, call-graph topology with
peer-edges, host and limit-proximity channels, fault-taxonomy definitions) recovered
83/48/48 — *above* the leaky number on localization, with every crutch removed. The
sequence quantifies both the contamination risk (26 pts service, 57 pts fault) and the
recoverability by honest means.

**Contributions.**
1. **Methodology:** leakage-controlled agent evaluation — evidence-preserving identifier
   masking (with a cross-tool identity theorem-in-practice: masking must not fragment one
   entity into several pseudonyms), full-fidelity transcripts, an automated leak auditor,
   and an A/A variance protocol that bounds single-run claims (±9 pts here).
2. **Dataset & system:** StrataTrace (95 labeled runs, 4 aligned modalities, ~0.001 ms
   clock skew, kernel representation ladder L0→L3, pre-registered predictions) and an
   open agentic RCA harness with two non-LLM baselines and a published-SOTA adapter.
3. **Empirical results:** (a) leak-free agent ≈2× non-LLM baselines on top-1 service;
   (b) no accuracy cliff down to 5% trace sampling — traces are ~20× over-collected for
   this task; (c) kernel telemetry buys efficiency (−25% agent effort) and fault-typing
   for induced-DB-latency, while its accuracy-rescue role is absorbed by good
   cross-modality tooling; (d) *interpreted* kernel summaries beat raw KPIs — a partial
   kernel view degrades below kernel-blind; (e) an experience/skill layer is
   net-negative without reliable evidence-based skill selection; unseen-fault incidents
   under a full skill library cost ~18 pts (distractor effect), quantified via
   leave-one-family-out.

*(TODO: 1-paragraph roadmap.)*

---

## 2. Background and Related Work *(stubs — TODO: citations)*

- **Non-LLM RCA**: spectrum/statistical methods; RCAEval/BARO/TORAI family (Pham et al.)
  — we adopt RCAEval 1.6 as the published baseline. MicroRank, TraceRCA as trace-only.
- **LLM/agentic AIOps**: (TODO: HolmesGPT, RCACopilot, mABC, etc.) — none report
  leakage-controlled numbers; typically evaluated with dataset-native identifiers.
- **Benchmark contamination / label leakage** in ML evaluation (TODO: cites) — we bring
  this discipline to AIOps agents.
- **Observability datasets**: (TODO: Nezha, RCAEval datasets, Train Ticket corpora,
  AIOps challenge) — none include kernel traces; none pre-register predictions.
- **Kernel tracing**: LTTng, eBPF diagnosis literature (TODO).

---

## 3. The StrataTrace Dataset

*(Condensed from DATASET_GUIDE / FREEZE docs — TODO: compress to ~1 page + table.)*

Two subjects chosen for architectural contrast: **Sock Shop** (14 services, one DB per
service, 6/14 trace-instrumented *by design* — trace blind spots are a variable) and
**Train Ticket** (~40 Java services, one shared MySQL — a structurally trace-blind
choke point). 12 fault types across 5 families (host cpu/disk/mem/net; service cpu/mem
caps; induced DB latency; error storms; frozen dependency; silent queue backlog; noisy
neighbor; per-service network). Each run: 60 s baseline → 120 s injection → 60 s
recovery; all modalities on one clock (measured skew ≈0.001 ms). 95 canonical labeled
runs (46 SS + 49 TT), ~533 GB compressed.

**The kernel ladder.** L0 raw LTTng CTF (full syscalls + sched/block/net; 2–13 GB/run);
L1 per-(service, second) KPIs via container PID attribution; L2 per-service *wait
attribution* (on-CPU / runnable / disk / off-CPU-external) — the "why it waited" signal;
L3 templated natural-language deviation digests (hallucination-resistant numbers).
Collection overhead, measured on the collection host at 200 concurrent users:
−0.5% throughput, +12.6% P95 latency.

**Pre-registration.** Fault→winning-modality predictions and scoring rules were frozen
before the study (fault_catalog); deviations are recorded in its amendment log — including
one this study forced (§6.3).

---

## 4. Agent, Tools, and Leakage Control

### 4.1 Agent and tools
A provider-agnostic tool-use loop (GPT-5.4 in all experiments) over six deterministic,
byte-accounted tools: service inventory; server-span latency; **call-graph topology**
(span parent/child edges *plus peer-edges from terminal client spans*, so span-less
components — databases, queues, proxies — appear as callees); log **error-rate change**
with new-signature detection (chronic noise is flagged, never decisive); metrics
(baseline→incident per container, host/node channel, **limit-proximity signals** —
throttled-seconds, memory-cap evidence); kernel (L1 KPI changes, L3 digests, L2 wait
attribution); and source-code search over the subject's repository. A deterministic
**Investigation Context Builder** runs the survey once and injects a compact evidence
brief; a claim store (Shared Investigation Context) records typed findings with
provenance. Output contract: {service, fault type, evidence, confidence}.

### 4.2 Leakage control (the methodological core)
- **Masking:** the agent receives an opaque incident alias (never the run ID); all
  fault-vocabulary identifiers (injection containers, proxy names) are deterministically
  pseudonymized. *Identity preservation:* the injected-workload class maps to ONE
  pseudonym per incident across all tools — we show (v1 vs v2 gates: 26 pts) that naive
  per-string hashing fragments identity and destroys legitimate cross-modality evidence.
  Real service names are the answer space and stay visible. The agent answers in alias
  space; unmasking happens harness-side before scoring.
- **Transcripts:** every diagnosis records the exact prompts, every raw model response,
  every tool result both in full and precisely as sent (masked+truncated), all usage,
  and the unmask map — ground-truth-free by construction, so the artifact itself proves
  no label reached the model.
- **Auditor:** an automated scanner over every model-visible string (run IDs,
  fault tokens under any separator, container names, ground-truth vocabulary; static
  answer-space text exempted) — exit-nonzero on any hit. Every number in this paper is
  backed by an auditor PASS over its transcripts (500+ diagnoses).
- **Declared non-leaks:** the exact injection window as "alert time" (standard
  benchmark assumption, identical for all methods); stress-tool process signatures
  (co-tenant processes are legitimate SRE evidence); the closed fault-type taxonomy
  (static answer space, with operational definitions in the prompt).

### 4.3 Variance protocol
Identical-configuration re-runs (A/A) across two full campaigns: ~20% of per-condition
cells flip; condition aggregates carry ±~9 pts. We therefore (i) never quote single-run
per-condition deltas inside that band, (ii) run r=3 repeats on identified borderline
incidents, (iii) prefer per-family flip lists over headline deltas.

---

## 5. Experimental Setup

93 working-set incidents; a 23-incident gate (one per fault family per app) for
agent-cost-bounded sweeps; all non-LLM baselines swept over the full 93×15 grid.
Methods: statistical rule-tree; RCAEval/mmbaro (published, FSE'24 artifact-award
lineage); MicroRank/TraceRCA (trace-only); our agent. Metrics: top-1 service (AC@1),
fault-type accuracy, both-correct; AC@3/MRR for ranking baselines; tool calls, bytes
touched, tokens, and dollar cost per diagnosis. *(TODO: hardware/model/versions box.)*

---

## 6. Results

### 6.1 RQ-A: Honest agent vs. baselines

| Method | Top-1 service | Both (svc+fault) | Degradation behavior |
|---|---|---|---|
| Statistical rule-tree | ~48% | 38% | flat (kernel-blind; 0% on slow_db, queue_backlog) |
| RCAEval/mmbaro | 46% (AC@3 63) | — | flat 100→5% traces |
| MicroRank / TraceRCA | ~0% / ~5% | — | floor, no cliff |
| **Agent (leak-free, brief)** | **83–87%** | **57%** | §6.4 |

Cost: ~25k input tokens (50–73% prompt-cache-served), ~500 output, ≈$0.01/incident.
Naive kernel-feature fusion into mmbaro changes nothing (kernel columns rank ~195th);
the two non-LLM baselines have complementary blind spots — motivating an agent that
*reasons* across modalities. *(Tables from RESULTS-nonllm-baselines / campaign docs.)*

### 6.2 RQ-B: The price of leakage

| Configuration | service | fault | both |
|---|---|---|---|
| Leaky (run-ID + names visible) | 74% | 74% | 61% |
| Masked, original tools | 48% | 17% | 9% |
| Masked, generic tooling rebuilt | **83%** | **48%** | **57%** * |

Naming hints alone were worth ~26 pts localization and ~57 pts fault classification —
fault labels were being read off the run ID. Honest tooling then *exceeded* the leaky
localization number. (*both=57% is the campaign figure with the brief; the immediate
post-rebuild gate was 48%.*) *(TODO: reconcile the two masked-gate rows into one table
with footnotes.)*

### 6.3 RQ-C: What is kernel telemetry worth? (tier ablation, 92 diagnoses)

| Kernel view | service | fault | both | agent effort (calls) |
|---|---|---|---|---|
| L1+L2+L3 | 83% | 61% | 61% | **9.1** |
| L1 only | 74% | 48% | **43%** | 10.1 |
| L3 only | 78% | 57% | 57% | 10.0 |
| none | 78% | 57% | 57% | 12.2 |

**K1** Removing kernel entirely costs ≤4 pts (within noise) but **+34% investigation
effort** — with strong cross-modality tooling, kernel's robust value is *efficiency*.
**K2** The one stable loss is induced-DB-latency *typing*: wait attribution converts
"the DB is the locus" into "induced latency, not an app bug". **K3** *A partial kernel
view is worse than none*: raw KPIs without interpretive framing send the agent chasing
kernel noise (−14 pts vs kernel-blind; 4 families lost, 0 gained). **K4** Pre-registered
H2 ("removing kernel causes the largest drop on blind-spot faults") is **not confirmed
at full telemetry** — our own limit-signal/topology/host tools absorbed the blind-spot
signal; recorded in the pre-registration amendment log. H2's remaining test is the
kernel×degraded-traces interaction *(TODO: run + report)*. Behaviorally, the
kernel-blind agent also wastes ~30% of calls re-probing the empty modality unless the
tool answers definitively once — an agent-design lesson in itself.

### 6.4 RQ-D: Trace degradation — no cliff (115 diagnoses)

100/50/25/10/5% whole-trace retention: both-correct stays 43–57% (noise band; 10%
scores best), 18/23 incidents identical at every level, tool mix constant. Mechanism:
the agent consumes spans as *aggregates* (brief latency tops, topology edge p95s) that
survive sampling; direct raw-trace reads are nearly absent. The baselines were flat
because they never used traces; the agent is flat because its trace use is statistical
and redundantly backed — same curve, opposite reason. **Implication: ~20× trace
collection-cost reduction without diagnostic loss** at otherwise-full telemetry.
*(TODO: metric & log axes — running; add table. TODO: harsher regimes: modality
removal, per-span drops.)*

### 6.5 RQ-E: Does an experience ("skills") layer help?

Evidence-selected skill library (12 evaluation-grade, service-agnostic skills; selector
sees only the masked evidence digest, may abstain; agent may override):

| Condition | service | fault | both |
|---|---|---|---|
| No skills (floor) | 83% | 57% | 57% |
| + Context-Builder brief | **87%** | **61%** | 57% (at −41% calls, −58% tokens) |
| + full skill library | 78% | 43% | 43% |
| leave-one-family-out (unseen fault) | 70% | 39% | 39% |

The deterministic Context Builder is the clear win. Skills lift individual families
(e.g., co-tenant contention fixed only by its skill; cap-fault typing) but mis-selection
— concentrated on the shared-datastore application, where background DB edges attract
db-flavored skills — costs more than skills contribute (selection 15/23). Under LOFO the
selector almost never abstains (1–3/23); distractor skills cost ~18 pts vs the skill-free
floor, though agent-override caps the damage (19/23 cells unchanged). **Conclusion:
experience layers require selection quality before they are safe**; we release the
selection-confusion data. *(TODO if time: selector-v2 replay experiment.)*

### 6.6 Cost accounting (toward minimum observability budgets)
Every diagnosis carries bytes-touched, tokens, and dollars; combined with collection
overhead and §6.4's 20× trace finding, we sketch the Pareto argument *(TODO: formal
RQ4 join + figure)*.

---

## 7. Discussion

- **For benchmark authors:** injected-fault benchmarks leak by construction; masking
  must preserve cross-tool identity; publish transcripts + auditors, not just scores.
- **For agent builders:** representation beats raw access (K3); definitive negative
  tool answers prevent dead-modality thrashing; deterministic context builders buy
  more than prompt cleverness per dollar.
- **For observability practice:** at full stacks, sampling traces at 5% appears safe
  for LLM-agent RCA; kernel telemetry is a cheap efficiency multiplier (−0.5%
  throughput to collect, −25% agent effort to use) and the sole source of
  induced-DB-latency *typing*.
- **Label semantics vs mechanism:** a fixed fault taxonomy penalizes mechanically
  correct explanations (connection-reset storms read as outages); we report label-strict
  scores and release evidence text for mechanism-level judgment *(TODO: mechanism-correct
  secondary metric)*.

## 8. Threats to Validity
Single LLM (GPT-5.4) — multi-provider harness exists, cross-model replication TODO;
23-incident sweep gate (93 available) with r=3 only on borderline incidents; single-run
±9 pt noise band explicitly reported; two subject systems; injected (not organic)
faults; label taxonomy semantics (§7); trace degradation limited to uniform whole-trace
sampling so far; window-as-alert assumption shared by all methods.

## 9. Data Availability
Dataset (95 runs, 4 modalities, kernel L0–L3), harness, skills, all 500+ audited
transcripts with sha256-manifested bundles, drivers and analysis scripts. *(TODO:
Zenodo DOI, anonymized review artifact.)*

## 10. Conclusion *(TODO)*

---

# Appendix / TODO tracker for the draft
- [x] Metric & log axes results — DONE 2026-08-18, both flat within noise (metric
      43–52% both across 5→60s; log 57/43/52 with ERROR>WARN); consolidated four-axis
      RQ-D table now in 06-results.tex; source RESULTS-agent-metric-log-sweeps.md
- [ ] kernel×trace interaction grid (H2's sharpened test)
- [ ] RQ4 Pareto figure; mechanism-correct secondary metric
- [ ] Related-work citations (RCAEval/BARO, HolmesGPT etc., contamination literature,
      Nezha/AIOps datasets, LTTng/eBPF)
- [ ] Reconcile §6.2 table footnote; per-family appendix tables from RESULTS-*.md
- [ ] Venue check: FSE 2027 submission deadline (verify — likely Sep 2026; MSR 2027
      abstract Nov 5 remains the fallback/dataset-track pairing)
- [ ] Decide single paper vs (dataset paper + study paper) split
- [ ] Figures: honesty-arc bar chart; tier/retention curves with noise band; selector
      confusion heatmap; as-built architecture (new_design.md §2b mermaid → vector)
