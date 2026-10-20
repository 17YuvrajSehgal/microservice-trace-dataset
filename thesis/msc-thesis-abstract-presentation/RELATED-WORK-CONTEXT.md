# Context pack — prior work and motivation

**For:** writing the motivation / related-work section of the thesis, the
proposal, or the "why this matters" slides. Written 19 October 2026.

**Sources:** the curated library at `DOCS/reading-papers/` (111 sources, 72-row
reading tracker), plus the repo's own analysis in `thesis/PROPOSAL.md` §3,
`non-llm-baseline.md`, `msr-research.md` and
`blueprints/REFERENCE-PACK-FOR-KERNEL-TRACE.md`.

---

## 0. Read this before citing anything

The library is large and **not uniformly read**. Two separate tracks, with
different levels of rigour:

| Track | What it is | Reliability |
|---|---|---|
| `DOCS/reading-papers/sources/` | **111 sources** with `meta.yaml` carrying `status` and `type`. Built from a manifest, PDFs verified to be the paper they claim to be | **This is the trustworthy track** |
| `DOCS/reading-papers/claude-recommendations/` | 77 PDFs + a 72-row `reading_tracker.csv`, themed and tiered | **Every row reads `Status: Not Started`.** Downloaded, not read |

Within the trustworthy track:

| `status` | meaning | count |
|---|---|---|
| **V** | read in full, verified | **54** |
| **S** | seen only as a search snippet | 33 |
| **M** | written from memory, not re-checked | 24 |

| `type` | count |
|---|---|
| peer_reviewed | 63 |
| doc (official documentation) | 24 |
| industrial (vendor/engineering writing) | 17 |
| issue (a bug tracker entry) | 7 |

> **The rule this implies.** Cite `status: V` freely. For `S` and `M`, read the
> paper before it goes in a thesis sentence — a snippet is enough to know a
> paper exists, not enough to characterise what it claims. The library's own
> README says exactly this, which is why the field exists.

The library also records **two traps worth repeating in a methods chapter**:

- *"A valid PDF can be the wrong paper."* A guessed URL at an institutional
  repository returned HTTP 200 and a perfectly good PDF — of a paper about
  power flow in LVDC grids, where kernel tracing was wanted. Checking magic
  bytes passes that file happily. `tools/verify_pdfs.py` exists because of it.
- *Relative URLs resolve against where a page was fetched from, not against
  what the page says about itself.* A canonical-URL declaration pointing at a
  dead host silently lost a stylesheet and two logos while the page still
  "downloaded fine".

---

## 1. The motivation, in four moves

This is the narrative spine. Each move is a claim prior work supports, and the
fourth is the gap.

**Move 1 — diagnosis from telemetry is skilled work, and the skill is tacit.**
Knowing *which* signal separates one cause from another, *which* events are
worth recording, and *which* threshold means something on *this* system is
expertise. Today it lives in engineers' heads and in closed tickets.

**Move 2 — automated RCA has been studied for a decade, and the reusable
artifact is always the model, never the investigation.** Statistical, causal and
graph-based localisers (§2A) all take telemetry in and emit a ranked list of
suspects. Each incident runs the pipeline once. Nothing accumulates.

**Move 3 — LLM agents inherit the same statelessness.** The recent wave (§2B)
gives an agent tools and a goal and lets it reason. It re-derives every
investigation from first principles, and a language model has no particular
knowledge of what a CPU cap looks like in a scheduler trace.

**Move 4 — and the evaluation substrate stops at the application boundary.**
Every public incident dataset (§2C) carries metrics, logs and application
traces. **None carries a kernel layer.** So faults below that line are outside
both the analysis *and its evaluation*.

> **The sentence that ties it together:** *"You cannot score a method on a fault
> your data cannot see."*

---

## 2. Prior work, by family

### 2A — Classical RCA for microservices (statistical, causal, graph-based)

The established line. 16 papers in the tracker under "RCA (Non-LLM)".

| Work | Venue | What it does |
|---|---|---|
| **BARO** (Pham et al.) | FSE 2024, Best Artifact | multivariate Bayesian online change-point detection + robust ranking |
| **RCAEval / "How Far Are We"** (Pham, Ha & Zhang) | ASE 2024 | evaluates causal-inference RCA methods head to head |
| **Nezha** (Yu et al.) | ESEC/FSE 2023 | interpretable fine-grained RCA, multi-modal |
| **Eadro** (Lee et al.) | ICSE 2023 | end-to-end troubleshooting, multi-source |
| **CIRCA** (Li et al.) | KDD 2022 | causal-inference-based RCA for online services |
| **RCD** (Ikram et al.) | NeurIPS 2022 | hierarchical causal discovery over failures |
| **MicroRCA** (Wu et al.) | NOMS 2020 | attributed-graph localisation of performance issues |
| **MicroCause** (Meng et al.) | IWQoS 2020 | causality inference over metric series |
| **MicroRank** (Yu et al.) | WWW 2021 | latency issue localisation via spectrum analysis on traces |
| **DeepTraLog** (Zhang et al.) | ICSE 2022 | trace + log combined anomaly detection |
| **ε-Diagnosis** (Shan et al.) | WWW 2019 | unsupervised, real-time, small-window diagnosis |
| **Chain-of-Event** (Yao et al.) | FSE Companion 2024 | interpretable RCA through event chains |
| **TORAI** (Pham et al.) | FSE 2026 (forthcoming) | **multi-source RCA for "blind spots"** — closest in spirit to our gap claim |

**What this family does well:** it is fast, deterministic, reproducible, and it
needs no model. On the faults it is designed for it is very strong.

**What it does not do:**
1. The artifact that survives is a **model or a ranking function**, not the
   investigation. Nothing accumulates across incidents.
2. It localises to a *service*, rarely to a *mechanism* — it says "carts is
   suspect", not "carts is being held off the CPU by a cgroup quota".
3. It is evaluated on corpora that stop at the application boundary, so the
   faults it cannot see are also the faults it is never scored on.

### 2B — LLM-based and agentic RCA

The current wave. 14 papers in the tracker, plus a cluster in
`blueprint-references/misc/`.

| Work | Venue | What it does |
|---|---|---|
| **OpenRCA** (Xu et al.) | ICLR 2025 | can LLMs locate root causes? A benchmark |
| **Exploring LLM-based Agents for RCA** (Roy et al.) | FSE Companion 2024 (industry) | ReAct-style agents on real cloud incidents |
| **RCACopilot / Automatic RCA via LLMs** (Chen et al.) | EuroSys 2024 | LLM diagnosis over cloud incident data |
| **AIOpsLab** (Chen et al.) | MLSys 2025 | a live testbed for evaluating autonomous-cloud agents |
| **ITBench** (Jha et al.) | ICML 2025 | evaluating agents across real-world IT automation |
| **RCAgent** (Wang et al.) | CIKM 2024 | autonomous agents with tool augmentation |
| **mABC** (Zhang et al.) | EMNLP Findings 2024 | multi-agent collaboration for RCA |
| **Flow-of-Action** (Pei et al.) | WWW Companion 2025 (industry) | **SOP-enhanced multi-agent RCA** — the closest existing idea to a blueprint |
| **Recommending Root-Cause and Mitigation Steps** (Ahmed et al.) | ICSE 2023 | LLMs over incident histories |
| **X-lifecycle Learning** (Goel et al.) | FSE Companion 2024 | incident management across the lifecycle |
| **Stalled, Biased and Confused** (Riddell et al.) | FORGE 2026 | **reasoning failures in LLMs for RCA** — useful negative evidence |
| **TRAIL** (Deshpande et al.) | 2025 | trace reasoning and agentic issue localisation |
| **Which Agent Causes Task Failures and When?** (Zhang et al.) | ICML 2025 Spotlight | automated failure attribution for agents |
| **AgentSight** (Zheng et al.) | ML-for-Systems 2025 | **eBPF-level observability of AI agents** — the nearest neighbour to our agentic leg |

A second cluster, in `blueprint-references/misc/`, is about **reusing written
procedure** — and this is the group the thesis is most directly in conversation
with:

- **Nissist** — an incident-mitigation copilot driven by troubleshooting guides
- **AutoTSG** — learning and synthesis for incident troubleshooting
- **StepFly** (FSE 2026) — agentic troubleshooting-guide automation
- **FixItFlow** — automated troubleshooting-guide generation from incidents
- **Xpert** — query recommendation for incident management via LLMs
- **Mining root cause knowledge from cloud service incident investigations**
- **From General Agents to RCA Experts** — a self-evolving harness
- **Beyond Fault Localization — a Trajectory-Level Study of LLM Agents for
  Microservice RCA**

**What this family does well:** it handles the open set, explains itself, and
adapts when evidence does not fit a fixed schema.

**What it does not do, and this is the thesis's opening:**
1. The reusable asset is **the model or the prompt**. The investigation is not
   preserved in a form a later run can execute.
2. Where procedure *is* reused — Nissist, AutoTSG, StepFly, Flow-of-Action —
   it is **prose for humans**, retrieved and read, not executed. Nobody measures
   whether an executable procedure beats the prose version of itself.
3. None of it reaches below the application layer. AgentSight instruments agents
   at eBPF level, but as a **tool, not a dataset**.

### 2C — Incident datasets and benchmarks

| Dataset | Metrics | Logs | App traces | **Kernel** |
|---|---|---|---|---|
| RCAEval (Pham et al., WWW Companion 2025) | ✓ | ✓ | ✓ | **✗** |
| LEMMA-RCA (Zheng et al., NEC, 2024) | ✓ | ✓ | ✓ | **✗** |
| OpenRCA (ICLR 2025) | ✓ | ✓ | ✓ | **✗** |
| AIOps Challenge corpora | ✓ | ✓ | ✓ | **✗** |
| Nezha | ✓ | ✓ | ✓ | **✗** |
| LO2 (2025) | ✓ | ✓ | — | **✗** |
| Loghub (Zhu et al., ISSRE 2023) | — | ✓ | — | **✗** |

Plus the subject systems everyone uses: **DeathStarBench** (Gan et al., ASPLOS
2019) and **Train Ticket** (Zhou et al., IEEE TSE 2021) — the latter is one of
our own two applications.

And the live agent testbeds — **AIOpsLab**, **ITBench** — which share the same
boundary.

> **The gap in one line:** none of them includes a kernel layer, so a fault that
> lives below the application is invisible to the analysis *and* absent from the
> evaluation.

### 2D — Distributed tracing foundations

Context for why application traces alone are not enough.

- **Dapper** (Sigelman et al., Google, 2010) — the foundational design
- **Canopy** (Kaldor et al., SOSP 2017) — end-to-end tracing and analysis at scale
- **Pivot Tracing** (Mace, Roelke & Fonseca, SOSP 2015, Best Paper) — dynamic
  causal monitoring
- **So, You Want To Trace Your Distributed System?** (Sambasivan et al.,
  CMU-PDL 2014) — design insights, and a good source for "what tracing cannot do"
- **Enjoy Your Observability** (Li et al., EMSE 2022) — an industrial survey of
  microservice tracing practice

**The argument they support:** a span records *that* a call was slow. It does
not record *why* — whether the callee was computing, waiting for a CPU, blocked
on I/O, or starved by a neighbour. That is the boundary our kernel layer crosses.

Our own blueprint for `host-cpu-saturation` makes exactly this claim and cites
Gelle et al. for it (§5).

### 2E — Kernel tracing and wait analysis (our methodological lineage)

This is the group the work descends from, and several are from the supervisor's
own research line (DORSAL, Polytechnique Montréal).

- **The LTTng Tracer** (Desnoyers & Dagenais, OLS 2006) — the tracer we use
- **Survey and Analysis of Kernel and Userspace Tracers on Linux** (Gebai &
  Dagenais, ACM CSUR 2018)
- **Lockless Multi-Core High-Throughput Buffering** (Desnoyers & Dagenais, 2012)
  — why LTTng can run at our event rates
- **Combining Distributed and Kernel Tracing for Performance Analysis of Cloud
  Applications** (Gelle, **Ezzati-Jivan** & Dagenais, Electronics/MDPI 2021) —
  **cited by four of our blueprints.** The direct ancestor
- **Wait Analysis of Distributed Systems Using Kernel Tracing** (Giraldeau &
  Dagenais, IEEE TPDS 2016) — supports four blueprints; no open-access copy
- **wPerf** (Zhou et al., OSDI 2018) — generic off-CPU analysis to identify
  bottleneck waiting events. The tracker calls it *"the closest principled
  version of our blocking-syscall discriminator"*
- **DepGraph** (**Ezzati-Jivan** et al., SCAM 2020) — attributing a wait to who
  caused it. The tracker calls this *"our weakest step"*
- **Critical-path analysis** work (Nemati 2022; Denys 2023) — distributed
  critical path from execution traces

### 2F — The closest prior art, and the one to position against

**This is the family a knowledgeable committee member will raise.** It is not in
the AIOps literature at all, and it is where the "catalogue of diagnosable
problems" idea already exists.

| Work | Venue | Why it matters |
|---|---|---|
| **Performance Problem Diagnostics by Systematic Experimentation** (Wert) | KIT dissertation + Karlsruhe Series book | an entire thesis on *systematically diagnosing* performance problems with a structured, reusable procedure |
| **Supporting Swift Reaction: Automatically Uncovering Performance Problems by Systematic Experiments** (Wert et al.) | **ICSE 2013** | the method paper |
| **DynamicSpotter** (Wert et al.) | **ICPE 2015** | the tool — automatic, experiment-based diagnostics driven by a hierarchy of performance-problem hypotheses |
| **Discovering Performance Archetypes** (Shahedi et al.) | **ASE 2026** | critical-path-aware pattern analysis — recent, and very close |
| **Encyclopedia of Crash Dump Analysis Patterns** (Vostokov) | book | a large catalogue of named diagnostic patterns, from a different domain |
| **Detecting Performance Anti-patterns for ORM Applications** (Chen et al.) | ICSE 2014 | antipattern detection as a reusable rule |
| **DrAsync** (ICSE 2022) | | antipatterns in asynchronous JavaScript |

All of the Wert items are `status: V` — read in full — and they came from the
supervisor's own recommendation folder (`blueprint-references/prof-recommendation/`).

> **How to position against it, honestly.** DynamicSpotter already does
> "a hierarchy of problem hypotheses, checked by systematic experiment." That is
> genuinely close to a blueprint plus a selector. **Do not claim the catalogue
> idea is new.** What is new is the combination:
>
> 1. the artifact is **executable by an autonomous agent**, not driven by a
>    human-operated experiment harness;
> 2. **no discriminator is admitted until measured against every fault class**,
>    enforced by a validator;
> 3. it reaches the **kernel layer**, which that line of work does not;
> 4. **transfer and abstention are measured**, not assumed.

### 2G — Agent system design

Background for how the agent is built, not for the RCA argument.

- **ReAct** (Yao et al., ICLR 2023) — reasoning and acting interleaved
- **Toolformer** (Schick et al., NeurIPS 2023) — models learning to call tools
- **Voyager** (Wang et al., 2023) — an open-ended agent that **accumulates a
  skill library**. The nearest analogue to our blueprint library, in a games
  domain rather than observability
- **Model Context Protocol** (Anthropic, 2024) — the tool interface spec

**Voyager is the one to name** if asked "has anyone built an accumulating skill
library before?" The honest answer: yes, in an embodied-agent setting, and it
is a good prior — but its skills are not evidence-bound, not validated against
negative cases, and not required to abstain.

---

## 3. The gap, stated three ways

From `thesis/PROPOSAL.md` §3.3, verbatim:

1. No public incident dataset time-aligns **kernel traces** with application
   traces, logs and metrics under labelled fault injection.
2. No study asks whether a **captured investigation transfers** to a new
   incident, a new service, or a new application.
3. No RCA work lets the diagnostic knowledge **feed back into collection** —
   deciding what to record next time.

And the framing sentence from §3.2:

> "Prior work reports **accuracy on a pipeline**. The artifact under study is
> the model or the prompt. **Nobody treats the investigation itself as the
> transferable deliverable and then measures its reuse.**"

---

## 4. What we have actually measured against prior work

This is what makes the motivation more than an argument. All from
`blueprints/docs/RESULTS-comparison.md` — 12 incidents, Sock Shop, one shared
evidence pack, one scorer, "fully correct" = right component **and** right
fault type.

| Method | Fully correct | Precision | Cost |
|---|---|---|---|
| **Our blueprint** (rules, no model) | **83%** | **100%** | $0 |
| Agent + kernel evidence pack | 58% | 100% | $0.021 |
| Agent, no kernel pack | 58% | 100% | $0.014 |
| Model only, no tools | 58% | 100% | $0.009 |
| Statistical rule-tree | 42% | 42% | $0 |
| **BARO** (published) | **0%** | 0% | $0 |

Split by fault — the result that carries the argument:

| | Co-tenant CPU (n=5) | Slow datastore (n=7) |
|---|---|---|
| Blueprint | **5/5** | 5/7 |
| Every LLM arm | **0/5** | **7/7** |
| Statistical | **5/5** | 0/7 |
| BARO | 0/5 | 0/7 |

**Read it carefully, and present it carefully.** The statistical method wins on
co-tenant and scores 0/7 on datastore; the model is the mirror image. *Only the
blueprint is good at both* — and **knowing which method fits which problem is
exactly what a blueprint stores.**

**The caveat the file states, which must travel with the table:** *"Does not
show — that this generalises. Twelve incidents on one application, two fault
types. One incident moves the total by 8 points."* And BARO's 0% is on *these*
faults with *this* evidence pack; it is not a general claim about the method.

Two further results worth having in the motivation:

- **More telemetry handed to a model as text bought nothing.** Giving the agent
  the kernel evidence pack left the named component identical on **12 of 12**
  incidents, for **+61% more tokens**. The problem is not access to data.
- **No LLM arm ever diagnosed co-tenant CPU contention**, in any of three
  configurations — 0/5 each time. That is the single clearest demonstration that
  a capable model without captured method cannot reach below the application
  layer.

---

## 5. Our own lineage — say this out loud

Four of the sixteen blueprints cite **Gelle, Ezzati-Jivan & Dagenais,
"Combining Distributed and Kernel Tracing for Performance Analysis of Cloud
Applications"** as the literature basis for their central claim. The supervisor's
own line of work is the direct methodological ancestor, and the group has
published on kernel tracing before this thesis.

That matters for two reasons: it is honest provenance, and it pre-empts "why
would you use kernel traces at all?" — the answer is that this group already
established they expose causes request tracing cannot explain.

---

## 6. Honest weaknesses in our citation posture

Put these in a limitations paragraph rather than waiting to be asked.

- **8 literature-backed claims across 16 blueprints. Nine blueprints carry
  none** — `connection-pool-exhaustion`, `data-exfiltration`, `deadlock-lock-order`,
  `dependency-outage-retry-storm`, `dns-delay`, `fd-exhaustion`, `fork-storm`,
  `lock-contention-futex-storm`, `priority-inversion-nice`. Their discriminators
  rest entirely on our own measurements.
- **No citation currently reaches the agent.** The references live in the
  blueprint file; the generated skill does not carry them.
- **54 of 111 sources were read in full.** 33 are snippet-only and 24 were
  written from memory.
- **The 72-row reading tracker is entirely "Not Started."** Those PDFs are
  downloaded and themed, not read. Do not cite from that folder without reading.
- **Two sources cannot be obtained** — `denys-2023-distributed-critical-path`
  (Wiley 403 on every route) and `runbookfx-2026` (ACM DL 403, no preprint).
  Recorded as `kind: unavailable` rather than silently dropped.
- **Three sources are not at their obvious URL** and use mirrors (Semantic
  Scholar, a Padova course page, a first-author thesis standing in for a
  paywalled IEEE article). Each is recorded with the reason.

---

## 7. Where everything lives

```
DOCS/reading-papers/
├── sources/<slug>/            ONE folder per source — cite from here
│   ├── paper.pdf | page.html
│   ├── paper.md  | page.md
│   └── meta.yaml              slug, title, authors, year, venue, doi, url,
│                              type, status, verified, blueprints, files
├── blueprint-references/<N> <problem>/   READ by problem — 16 folders
│   ├── misc/                  the 37 cross-cutting + related-work files
│   ├── prof-recommendation/   the supervisor's picks — the Wert cluster
│   └── future-blueprints/     for anomalies not yet written up
├── claude-recommendations/    77 PDFs + reading_tracker.csv (all Not Started)
├── index.yaml                 GENERATED — which source supports which blueprint
├── table.md                   the catalogue
└── tools/                     fetch_refs · verify_pdfs · build_sources ·
                               complete_pages · audit_html · verify_offline
```

Rebuild with `python tools/build_sources.py`. **Do not hand-edit `index.yaml`** —
it is generated from `tools/manifest.yaml`.

The repo's own analysis lives in:

| File | What |
|---|---|
| `thesis/PROPOSAL.md` §3 | background and the three-part gap statement |
| `non-llm-baseline.md` | the non-LLM baseline we compare against |
| `blueprints/docs/RESULTS-comparison.md` | the measured head-to-head in §4 above |
| `blueprints/REFERENCE-PACK-FOR-KERNEL-TRACE.md` | per-signal literature backing for the kernel work |
| `msr-research.md` | the dataset-paper framing and its related-dataset analysis |

---

## 8. Suggested structure for the motivation section

Four subsections, in this order. The order matters: it moves from the broadest
accepted fact to the narrowest gap.

1. **Diagnosis is skilled work, and the skill is tacit.** No citation war
   needed; one or two empirical-study references on microservice issues suffice.
2. **A decade of automated RCA, and what it keeps.** §2A. End on: the artifact
   is the model, not the investigation.
3. **Agents inherit the statelessness.** §2B. End on: where procedure *is*
   reused it is prose for humans, and nobody measures executable against prose.
4. **And the evaluation substrate stops at the application boundary.** §2C with
   the ✗ column. End on: *"you cannot score a method on a fault your data cannot
   see."*

Then the gap (§3), then — and this is what makes it land — **the measured
head-to-head** (§4), because it converts the argument into evidence.

**Position against §2F explicitly, in its own paragraph.** A reader who knows
DynamicSpotter will otherwise think the catalogue idea is being presented as
new. It is not; the executable, evidence-bound, agent-consumed, kernel-reaching
combination is.
