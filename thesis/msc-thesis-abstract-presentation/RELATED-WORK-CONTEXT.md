# Context pack — prior work and motivation

**For:** writing the motivation / related-work section of the thesis, the
proposal, or the "why this matters" slides. Written 19 October 2026.

**Sources:** the curated library at `DOCS/reading-papers/` (111 sources,
`table.md`, `index.yaml`), the repo's own analysis in `thesis/PROPOSAL.md` §3,
`non-llm-baseline.md`, `msr-research.md`,
`blueprints/REFERENCE-PACK-FOR-KERNEL-TRACE.md`, and the measured comparisons in
`agentic-rca/RESULTS-nonllm-baselines.md` and
`blueprints/docs/RESULTS-comparison.md`.

---

## 0. Read this before citing anything

### The `status:` field does NOT mean "we read it" — this trips people up

`sources/<slug>/meta.yaml` carries `status: V | S | M`. Its own manifest header
says it *"mirrors the reference pack's tags: V seen, S snippet only, M from
memory."* **It was set when files were fetched (30 Sept 2026) and never updated
after the papers were read.**

Measured on disk, 19 Oct 2026:

| Signal | Count | What it actually means |
|---|---|---|
| source directories | **111** | the whole library |
| **have `paper.md`** | **55** | **a real summary exists — this is the read-evidence** |
| `status: V` | 54 | the file was *seen* when fetched |
| `verified: true` | 54 | the fetched file is **the right document** — not that it was read |

The two sets do not coincide:

- **24 fully-summarised papers still carry a stale `S` or `M` tag.** Filtering on
  `status: V` wrongly excludes `giraldeau-2016-wait-analysis`,
  `pham-2024-rcaeval`, `zhou-2018-train-ticket`, `gunawi-2016-cloud-outages`,
  `jin-2012-performance-bugs`, `aiopslab-2025`, `weiner-2022-tmo`,
  `ezzati-2020-depgraph`, `replicawatcher-2024` and 15 others.
- **8 sources are `status: V` with no summary at all** —
  `wert-thesis-dissertation`, `wert-thesis-book`, `ghosh-tracing-patterns-thesis`,
  `vostokov-crash-dump-encyclopedia`, `huang-2022-metastable-wild`,
  `kalliamvakou-2016-mining-github`, `cheshire-nagle-delayed-ack`, and
  **`denys-2023-distributed-critical-path`, which has no file on disk at all.**

> ## The rule
> **Cite a source only if `DOCS/reading-papers/sources/<slug>/paper.md` exists.**
> That is 55 sources. Everything else needs reading first.

### The second library is entirely unread

`DOCS/reading-papers/claude-recommendations/` holds 77 PDFs and a 72-row themed
`reading_tracker.csv`. **Every row reads `Status: Not Started`.** It is a useful
map of the field; it is not a bibliography.

**This matters more than it sounds**, because several papers you would expect to
cite exist *only* there — see the coverage gaps in §2E, §2I and §2J.

### Five things that must not appear in your text

| Do not write | Why |
|---|---|
| **"CARE"** as an RCA method | **There is no RCA method called CARE.** `research-agentic-rca.md` §3 says "RCAEval / CARE-style" — a misremembered name, caught in `non-llm-baseline.md`. The family is **RCAEval / BARO / TORAI** (Pham et al.) |
| "we compare against FSE'26 SOTA" | **TORAI was never run** (deferred, needs Python 3.8). "Published SOTA" in our tables means **multi-source BARO**, the FSE'24 lineage |
| any agent difference **under 9 points** as a finding | the A/A protocol measured a **±9-point noise band**. `04-method.tex`: *"never quote a difference inside the band as a finding"* |
| **"our injection is realistic"** | *"Your injected faults copy the **symptom**, not the cause. Cite the empirical studies as 'this symptom occurs in practice.'"* |
| the Wert cluster as "read" | the two short papers have **user-written** summaries; the dissertation (329 pp), the book (486 pp), the Ghosh thesis (147 pp) and the Vostokov encyclopedia (1200 pp) are **unsummarised** |

### A live bug in the library

`sources/chen-2014-orm-antipatterns/meta.yaml` still carries the refuted note
*"Reports an order-of-magnitude execution-time penalty for N+1"*. **Correction #9
explicitly refutes this** — Chen reports no such thing. Do not propagate it.

---

## 1. The motivation, in five moves

**Move 1 — diagnosis from telemetry is skilled work, and the skill is tacit.**

**Move 2 — a decade of automated RCA keeps the model, never the investigation.**
Statistical, causal and graph-based localisers (§2A) run once per incident.
Nothing accumulates.

**Move 3 — LLM agents inherit the same statelessness.** (§2B)

**Move 4 — where procedure *is* reused, it is prose for humans, and the prose is
measurably broken.** (§2C) This is the strongest and least-used move.

**Move 5 — and the evaluation substrate stops at the application boundary.**
(§2D) No public incident dataset carries a kernel layer.

> **Closing sentence:** *"You cannot score a method on a fault your data cannot
> see."*

---

## 2. Prior work, by family

Every entry marked **[S]** has a summary on disk and is safe to cite. Entries
without it need reading first.

### 2A — Classical RCA for microservices

| Work                                                                                                               | Venue            | Status                                                                                                                                                                                                   |
|--------------------------------------------------------------------------------------------------------------------|------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **BARO** (Pham et al.)                                                                                             | FSE 2024         | see §2D — same authors as RCAEval                                                                                                                                                                        |
| **DepGraph** (**Ezzati-Jivan** et al.)                                                                             | SCAM 2020        | **[S]** waiting-dependency graph: who is blocked on whom, from kernel traces. Fills the gap Giraldeau leaves — *which* thread holds the resource                                                         |
| **CPI²** (Zhang et al., Google)                                                                                    | EuroSys 2013     | **[S]** learns normal CPI per job, flags at 2σ, correlates victim CPI against suspect CPU to name the **antagonist**. Source of the victim/antagonist vocabulary. Deployed on all Google shared clusters |
| **NetPoirot** (Arzani et al.)                                                                                      | SIGCOMM 2016     | **[S]** **blame allocation** — client / network / server — from a client-side TCP agent only, no app knowledge. Up to 96%                                                                                |
| **ASFC** (Song et al.)                                                                                             | FGCS 2024        | **[S]** autonomous selection of fault-classification models. **Uses Sock Shop**                                                                                                                          |
| **MSoFSAnomaly** (Fu et al.)                                                                                       | JSS 2025         | **[S]** multi-source failure analysis for fault-sensitive microservices                                                                                                                                  |
| **Mining root cause knowledge** (Saha & Hoi)                                                                       | ICSE-SEIP 2022   | **[S]** 2,000 Salesforce Sev0/1/2 post-mortems → causal knowledge graph, 60 symptom clusters. *Weights are cluster weights, not incident counts*                                                         |
| CIRCA · RCD · MicroRCA · MicroCause · MicroRank · TraceRCA · Nezha · Eadro · DeepTraLog · ε-Diagnosis · DiagFusion | KDD'22 … ICSE'23 | **in `claude-recommendations/` only — unread.** Characterised in `non-llm-baseline.md` but not summarised                                                                                                |

**Why this family is insufficient — four structural arguments** from
`non-llm-baseline.md`:

1. **It needs a dependency graph real deployments do not have.** *"They either
   require a service dependency/call graph (breaks under per-service coverage
   removal) or need many high-resolution time points for conditional-independence
   tests."* Telling detail: RCAEval's own authors *"engaged a DevOps engineer to
   reconstruct dependency graphs for graph-requiring baselines."*
2. **Statistical sample starvation.** At 60 s resampling over ~100 s runs there
   are *"only ~2–3 metric points per run. **Every** conditional-independence
   method breaks."*
3. **Middling on their own data.** Quoting RCAEval: *"CIRCA and RCD obtain the
   best average Avg@5 score of 0.46 and 0.54."*
4. **No kernel modality exists in the field.** *"RCAEval has no kernel modality."*

### 2B — LLM-based and agentic RCA

| Work | Venue | Status |
|---|---|---|
| **RCACopilot** (Chen et al.) | EuroSys 2024 | **[S]** found *"incidents stemming from similar or identical root causes often recur"* — **direct support for reusable blueprints.** (No row in `table.md` — invisible if you read that alone) |
| **Exploring LLM-based Agents for RCA** (Roy et al.) | FSE Companion 2024 | **[S]** ReAct on real Azure incidents. Correctness 35% vs 39% baseline, but **hallucination 6% vs 49%**, because 66% of wrong answers say it lacks evidence |
| **AIOpsLab** (Chen et al.) | MLSys 2025 | **[S]** four-level taxonomy: detection, localisation, RCA, mitigation. Best overall 59.32%; localisation Acc@1 46–62%; **non-LLM baselines 15.38% / 7.69%.** Agents waste steps on non-existent APIs |
| **Beyond Fault Localization** (Lu et al.) | 2026 | **[S]** 3,500 trajectories. **Edge F1 never exceeds 0.67** while Node F1 is far higher; Acc@1 collapses with causal depth **85.5% → 57.1%** |
| **From General Agents to RCA Experts** (Huang et al.) | 2026 | **[S]** **specialised RCA agents lose to general agents**: 36.1% vs 17.9% (RCA-Agent) and 5.6% (mABC). RCA-Agent drops **31.8% → 1.9%** off its own benchmark |
| **Xpert** (Jiang et al.) | ICSE 2024 | **[S]** KQL recommendation. Defines **Xcore** = validity + semantic soundness + output correctness |
| **SiriusHelper** (Shen et al., Tencent) | — | **[S]** 73% accuracy vs DeepSearch 62%, RAG 57%, CoT 54%. **CoT least accurate *and* slowest (25.91 s)** |
| OpenRCA · RCAgent · mABC · Ahmed et al. · ITBench · TRAIL · AgentSight · Stalled-Biased-and-Confused | ICLR'25 … FORGE'26 | **unread** — in `claude-recommendations/` only |

### 2C — Troubleshooting guides and runbooks — the family blueprints are *most* in conversation with

`table.md`'s own section heading: **"The TSG line — three approaches, and none
of them creates the knowledge."**

| Work | Venue | Status |
|---|---|---|
| **AutoTSG** (Shetty et al.) | ESEC/FSE 2022 Industry | **[S]** |
| **Nissist** (An et al.) | 2024 | **[S]** |
| **StepFly** (Mao, Li et al.) | Proc. ACM Softw. Eng. 3(FSE) 2026 | **[S]** |
| **FixItFlow** (Unnikrishnan et al.) | 2026 | **[S]** |
| **Flow-of-Action** (Pei et al.) | WWW Companion 2025 | unread |
| **RunbookFX** (Xiao, Li & Ge) | PACMPL 10(ICFP) 2026 | **no file — ACM DL 403. Do not cite** |

**The numbers that make the case:**

1. **The practice is large and it works.** AutoTSG mapped **4,000+ TSGs** to
   incidents by real on-call click-throughs, and measured **mean time-to-mitigate
   19 h without a linked TSG vs 13 h with one** (sev 1–2). Nissist reports
   incidents with a TSG had **60% shorter TTM** across ~1,000 real incidents.
2. **But the guides themselves are broken.** AutoTSG's quality taxonomy from
   400+ feedback items: Completeness **32.24%**, Broken Link **13.32%**,
   **Correctness 11.21%**, Readability 10.28%, UX 10.05%, **Empty 7.24%**.
3. **And automating them inherits the breakage.** AutoTSG converts *existing
   prose* into executable workflows (0.89 / 0.94 / 0.91 on statement
   identification and parsing), so **it inherits everything in its own taxonomy,
   including the 11.21% whose steps do not work.**

> **The argument, and it is the sharpest available:** *"Automating a wrong
> procedure faithfully is still wrong."* That is exactly what measure-first
> authoring plus a validator exist to prevent — a blueprint cannot be the
> 11.21%, because no discriminator enters it unmeasured.

**Two more findings worth using:**

- **StepFly is the most actionable paper in the whole related work.** 92 real
  TSGs: ~3K tokens, 5–15 steps, **~46% have parallelisable steps**. Its defect
  taxonomy names **"Unquantifiable Condition"** — which is *precisely a
  discriminator written before its threshold was measured*. And
  `table.md` draws the link: **"our rule-out lists are their Independent
  Paths"** — parallelising independent rule-outs attacks the step-limit problem
  that both AIOpsLab and Roy identify as where hard cases die.
  *Caveat: its ~94% on GPT-4.1 is **procedure adherence, not diagnosis
  accuracy**.*
- **FixItFlow is a useful negative result.** Satisfaction **2.58/5, NPS −100,
  0% adoption.** *"Generate-from-history produces readable guides nobody uses"* —
  which strengthens the case for measure-first.

### 2D — Incident datasets and benchmarks

From `msr-research.md` §2: *"Closest related datasets/benchmarks — **none has a
kernel layer**"*:

| Work | Metrics | Logs | App traces | **Kernel** | LLM harness | Collection cost | Trajectories |
|---|---|---|---|---|---|---|---|
| RCAEval (735 cases, 3 systems, 11 fault types) | ✓ | ✓ | ✓ | **✗** | partial | ✗ | ✗ |
| LEMMA-RCA (NEC) | ✓ | ✓ | ✗ | **✗** | ✗ | ✗ | ✗ |
| OpenRCA (335 failures, 68 GB) | ✓ | ✓ | ✓ | **✗** | ✓ (RCA only) | ✗ | ✗ |
| AIOps Challenge / MSDS / LO2 / Nezha | ✓ | some | some | **✗** | ✗ | ✗ | ✗ |
| AIOpsLab, ITBench (live) | ✓ | ✓ | ✓ | **✗** | ✓ | ✗ | ✗ |
| AgentSight | – | – | – | ✓ *(tool)* | ✗ | ✗ | ✓ *(tool)* |
| TRAIL / Who&When | ✗ | ✗ | ✗ | **✗** | ✓ | ✗ | ✓ |
| **This work** | ✓ | ✓ | ✓ | **✓** | **✓** | **✓** | ✓ |

**The limitations are exactly the four empty columns.**

**RCAEval** (Pham et al., WWW 2025 Companion) **[S]** — 735 failure cases, 3
systems **including Sock Shop and Train Ticket**, 11 fault types, 15 baselines.
Best Avg@5 ≈ 0.80, but **DISK 1.00 vs DELAY 0.47**. `table.md`: *"Our nearest
dataset neighbour. **It has no kernel traces** — that is the gap we fill, in the
most complete public benchmark available."* Also: Sock Shop in RE2/RE3 has logs
but **N/A traces** — relevant to our partial-coverage framing.

**REPLICAWATCHER** (NDSS 2024) **[S]** — compares a container against its own
replicas on Sysdig kernel events. 13 real-CVE scenarios, avg AUC 0.9960/0.9827.
*"Closest published work to our setting."*

### 2E — Distributed tracing

> ⚠ **There is no Dapper entry in the citable library. No Canopy, Pivot
> Tracing, Sambasivan, Jaeger, Zipkin or OpenTelemetry source either.** They
> exist only as unread PDFs in `claude-recommendations/`. **If your related work
> needs the tracing lineage, every one of those citations must be read and added
> from outside the `sources/` catalogue.**

What the library *does* have is the kernel+trace **fusion** line:

| Work | Venue | Status |
|---|---|---|
| **Gelle, Ezzati-Jivan & Dagenais** | Electronics 2021 | **[S]** patches the Jaeger client to emit an LTTng-UST event per span; LTTng's shared clock joins them free. Overhead <4–5% on HotROD. **§4.3 injects a 1% cpu cgroup cap and reads out `sched_switch prev_state=0, next_comm=swapper` at 100 ms periodicity** — the empirical source for our CPU-cap signature |
| **Kohyarnejadfard et al.** | J. Cloud Computing 2022 + PhD thesis | **[S]** a span is a sentence; LSTM over LTTng predicts the next event *and its arguments*. **F-score 0.9759 over 4,028 classes is next-key prediction, NOT a fault-detection rate** |
| **Nemati et al.** | IEEE TCC 2022 | **[S]** recovers guest process states from host hypervisor tracing only. Overhead ~0.3% vs 3.65–6.13% in-VM. *Needs `kvm_*` events we do not collect* |
| **Denys et al.** | SPE 2023 | **no file — Wiley 403. Do not cite** |

**The argument:** a span records *that* a call was slow, not *why*. And
`table.md`'s positioning note on Gelle: *"**the right paper to position
against: they had request context and still needed a human to read the
views.**"*

### 2F — Kernel tracing, off-CPU and wait analysis — our lineage

| Work | Venue | Status |
|---|---|---|
| **Giraldeau & Dagenais** | IEEE TPDS 2016 | **[S]** blocking changes control flow; **the wake-up names the cause of the wait**; follow it backwards recursively, O(n). Overhead 18.3% worst / 5.1% typical |
| **Rezazadeh et al.** | ISSRE-W 2020 | **[S]** Giraldeau's kernel-only method **cannot see spinlocks or Apache's filelock**. **Cite for the limitation, not the capability** |
| **Gassais et al.** | J. Cloud Computing 2020 | **[S]** an LTTng host IDS. **Publishes its full tracepoint list** — closest paper to *our collection setup*, security-shaped where ours is performance-shaped |
| **Ghosh, "System and Application Performance Analysis Patterns Using Software Tracing"** | MSc thesis, 147 pp | **UNREAD.** `table.md`: *"**The closest of the four to our work** — performance analysis patterns from software tracing is the same idea as a blueprint. Worth doing first"* |
| Gregg — USE Method, Off-CPU Analysis | — | industrial, unsummarised |
| LTTng tracer papers (Desnoyers & Dagenais 2006; Gebai & Dagenais 2018) | OLS / CSUR | **unread** — `claude-recommendations/` only |

> **A limit found by reading Giraldeau in full, and it constrains our claims:**
> the method needs `sched_ttwu` (a kprobe — the stock `sched_wakeup` fires on the
> *destination* CPU and loses the wake-up **source**) and socket-level netfilter
> events. **We collect neither.** *"Cite the principle — the wake-up identifies
> the wait — not the implementation. **We have not done active-path analysis.**"*

### 2G — The closest prior art outside AIOps

**A knowledgeable committee member will raise this.** It is where "a catalogue
of diagnosable problems with detection procedures" already exists. From the
supervisor's own recommendation folder.

| Work | Venue | Read status |
|---|---|---|
| **Supporting Swift Reaction** (Wert et al.) | **ICSE 2013** | summary exists, **written by the user** |
| **DynamicSpotter** (Wert et al.) | **ICPE 2015** | summary exists, **written by the user** |
| **Performance Problem Diagnostics by Systematic Experimentation** (Wert) | KIT dissertation, 329 pp + book, 486 pp | **UNREAD** — `table.md` says *"summarise one, not both"* |
| **Discovering Performance Archetypes** (Shahedi, Li, Lamothe, Khomh) | **ASE 2026** | summary exists, **written by the user** |
| **Encyclopedia of Crash Dump Analysis Patterns** (Vostokov) | book, 1200 pp | **UNREAD.** *"A commercial reference book, not a research result"* |
| **Detecting Performance Anti-patterns for ORM Applications** (Chen et al.) | ICSE 2014 | **[S]** |
| **DrAsync** (Turcotte et al.) | ICSE 2022 | **[S]** |

> **How to position, honestly.** DynamicSpotter already does *"a hierarchy of
> problem hypotheses, checked by systematic experiment"* — genuinely close to a
> blueprint plus a selector. **Do not claim the catalogue idea is new.** What is
> new is the combination: (1) executable by an **autonomous agent**, not a
> human-driven experiment harness; (2) **no discriminator admitted until measured
> against every fault class**, validator-enforced; (3) reaching the **kernel
> layer**; (4) **transfer and abstention measured**.
>
> **Before submitting, read the Ghosh thesis and one of the two Wert volumes.**
> They are the two closest documents to this thesis and both are currently
> unread.

### 2H — Resource interference and OS noise

| Work | Venue | Status |
|---|---|---|
| **TMO** (Weiner et al.) | ASPLOS 2022 | **[S]** **the paper PSI came from.** PSI measures *lost work due to lack of a resource*. **CPU `full` is only possible inside a container.** Rejects *promotion rate* — **rate thresholds do not transfer across hardware** |
| **The Linux Scheduler: a Decade of Wasted Cores** (Lozi et al.) | EuroSys 2016 | **[S]** **cores sit idle for seconds while runnable threads wait.** Cost 13–24% typical, **138× worst case.** *Fixed in 3.17–4.3; our kernel is 7.0 and CFS became EEVDF in 6.6 — cite the principle, not the bugs* |
| **Mitigating Unnecessary Throttling in CFS** (Ugedal & Kannan) | SBAC-PAD 2022 | **[S]** CFS throttles processes **that have not used their quota**. Same workload, same ratio: **0% unlimited → 6.8% at 100 ms → 49% at 10 ms.** Throttling is **per logical CPU** |
| **CPU bandwidth control for CFS** (Turner et al.) | OLS 2010, pp. 245–254 | **[S]** the design paper. *Only pp. 245–254 of a 272-page proceedings were read* |
| **Heracles** (Lo et al.) | ACM TOCS 2016 | **[S]** servers are **50–70% of TCO at 10–50% utilisation**. Coordinating **four** isolation mechanisms reaches 90% utilisation. **No single mechanism suffices.** *A motivation citation only* |
| **Cryptomining Detection in Container Clouds** | **Karn et al., IEEE TPDS 32(3), 2021** | **[S]** detects miners from **syscalls not CPU**, because *"CPU usage is a good first-order metric"* that false-alarms on busy workloads |

> ⚠ **Three OS-noise PDFs sit unregistered at the root of
> `DOCS/reading-papers/`** — *Operating System Noise in the Linux Kernel*,
> *OS noise mitigations for benchmarking…*, and *Resource Life-Cycle Aware Noise
> Detection via Kernel Event Monitoring*. **They have no slug, no metadata, no
> summary, and are referenced nowhere in the repo.** Given that the agentic leg
> of this thesis *is* an OS-noise study, these should be registered and read.

### 2I — Log analysis and anomaly detection

> ⚠ **Absent.** There is no DeepLog, Drain, LogHub, Loglizer or LogAnomaly in
> the citable library. Anomaly detection here is **trace- or syscall-based**
> (Kohyarnejadfard, REPLICAWATCHER, Gassais). **If the thesis needs a
> log-anomaly baseline, it must be sourced externally.**

### 2J — Agent frameworks

> ⚠ **Absent.** No ReAct, Toolformer, Voyager, Reflexion or MCP source exists.
> ReAct appears **only as an evaluated baseline inside other papers' summaries** —
> AIOpsLab (ReAct 55.93% overall, localisation Acc@1 53.85%) and Roy et al.
> **Every citation in this lineage must be read and added from outside.**

---

## 3. The empirical case that existing tooling fails

Other people's measurements. This is stronger than any methodological argument.

### The single best result, and it is a failure

**Zhou et al., IEEE TSE 47(2):243–260, 2021** — the paper that created Train
Ticket. 16 developers, 12 companies, **22 real industrial faults** replicated on
Train Ticket (41 services, 4 languages) and re-debugged at three tooling levels.

> **Two could not be debugged at any level — F3 and F4, both non-functional
> *environment* faults** (a JVM/Docker memory-limit conflict, which is exactly our
> `service-memory-cap`, and fine-grained SSL offloading).
>
> *"Most fault cases **except those caused by environmental settings** can
> benefit from trace visualisation."*
>
> **The environment is the kernel's layer.** `table.md`: *"**names the gap we
> fill, from industrial data, seven years early.**"*

Supporting: time to locate and fix scales **9.5 h (1 service) → 20 h (2) → 40 h
(3) → 48 h (>3)**; interaction faults take **3 h with visual traces vs 21 h with
basic logs**. And **F5 is a verified industrial case of connection-pool
exhaustion that took 6 days to locate** — which narrows the "no peer-reviewed
paper" gap our conn-pool blueprint records.

### Three independent measurements that the evidence is not in the record

| Study | Finding |
|---|---|
| **Dai et al., IC2E 2018** | 156 timeout bugs, 11 cloud systems. **60% produce no error message**, 12% a misleading one |
| **Gunawi et al., SoCC 2016** | 597 outages, 32 services. **355 (59%) have an UNKNOWN root cause** |
| **Ghanavati et al., EMSE 2020** | 491 leak issues, 15 Java projects. **Only 1 of 491 found by a static analyser; 63% only visible at runtime** |

`table.md` on Dai: *"**The 60%/12% is the strongest argument in the pack for the
kernel modality** — measured on real organic bugs, not injected faults.
**Belongs in the introduction.**"* On Ghanavati: *"the **1-in-491** number is a
direct argument for runtime evidence."*

### Why the faults must be injected rather than mined

**Waseem et al., EASE 2021 + JSS 2023** — 2,641 issues, 15 systems, 150-practitioner survey:

| | Share of mined issues | Practitioners hitting it "often" |
|---|---|---|
| **Performance** | **1.67%** (45/2698, **16th of 19**) | **63.33%** |
| Monitoring | 3.29% (89 issues — **larger than Performance**) | 52.67% |

> *"**The gap between the two data sources is the justification for our
> dataset.** Performance faults are felt constantly and filed almost never, so a
> mining study cannot be their empirical base."* And: their Monitoring category
> is larger than Performance — **the observability stack is itself a reported
> problem.**

**Jin et al., PLDI 2012** — in Mozilla, 36 performance bugs took **935 days on
average to discover** vs **252** for functional bugs: **3.7× longer undetected,
same time to fix once found.** *"Judging whether performance bugs have
manifested is a unique challenge"* — our detection problem, stated in 2012.
Also: ~2/3 need large-scale input; >3/4 live in an input-dependent loop or
handler; **about half involve I/O or costly system calls** — the boundary a
kernel trace records.

---

## 4. The gap, stated three ways

From `thesis/PROPOSAL.md` §3.3:

1. No public incident dataset time-aligns **kernel traces** with application
   traces, logs and metrics under labelled fault injection.
2. No study asks whether a **captured investigation transfers**.
3. No RCA work lets diagnostic knowledge **feed back into collection**.

From `thesis/abstract.tex`:

> *"In both the reusable asset is a model or a prompt; the reasoning that
> resolved one incident is not preserved in a form a later investigation can
> run… **a boundary at which the datasets these methods are evaluated on also
> stop.**"*

And **the cleanest positioning sentence in the repo**, from the reference pack:

> *"Existing TSG and agent work uses logs, metrics and KQL queries; the DORSAL
> work uses kernel traces but **without reusable, agent-executable procedures**;
> your blueprints join the two."*

---

## 5. What we measured against published methods

Two studies at different scales. **Quote with their n — they are not
interchangeable.**

### 5A — 93 incidents × 15 degradation conditions = 1,395 evaluations

| Method | Top-1 service | Both (svc + fault) |
|---|---|---|
| Statistical rule-tree | ~48% | 38% |
| **mmbaro** (RCAEval 1.6, published) | **46%** (AC@3 63, MRR 0.54) | — |
| TraceRCA | ~5% | — |
| MicroRank | ~0% | — |
| **Agent (leak-free)** | **83–87%** | **48–57%** |

Per-family at full telemetry — **the complementarity is the point**:

| family | statistical | mmbaro | winner |
|---|---|---|---|
| anomaly_cpu / disk / mem | 100% | 100% | tie |
| **noisy_neighbor** | **100%** | **0%** | statistical |
| **dependency_outage** | **50%** | **0%** | statistical |
| **slow_db / error_storm / svc_mem_cap** | **0%** | **50%** | mmbaro |
| anomaly_net / **queue_backlog** | 0% | 0% | **both fail** |

### 5B — 12 incidents, 6 methods, one scorer, identical evidence pack

| Method | Component | Fully correct | Precision | Cost |
|---|---|---|---|---|
| **Blueprint** (rules, no model) | 83% | **83%** | **100%** | $0 |
| Agent + kernel pack | 100% | 58% | 100% | $0.021 |
| Agent, no kernel pack | 100% | 58% | 100% | $0.014 |
| Model only, no tools | 100% | 58% | 100% | $0.009 |
| Statistical rule-tree | 42% | 42% | 42% | $0 |
| **BARO** (published) | **0%** | n/a | **0%** | $0 |

> **BARO's failure mode:** *"it **answers every incident and is right on none,
> predicting `carts` regardless of the fault**. A method that always answers is
> not more useful than one that knows when it cannot."*

**Carry the caveat:** *"Twelve incidents on one application, two fault types.
One incident moves the total by 8 points."* BARO at 46% in 5A vs 0% in 5B is not
a contradiction — different incident sets and scoring granularity.

### 5C — The three findings that make the motivation

**1. Kernel data cannot be bolted onto a published method.** The best original
negative result in the repo:

> Fusing kernel features into mmbaro left **localization unchanged — `full` ==
> `kNone` for every family.** The RobustScorer ranked ~200 cAdvisor change-points
> above the kernel columns; **the first kernel column landed at rank ~195.**
>
> *"The kernel's diagnostic value is **not accessible by naive feature-fusion**
> into a metric-change-point method; it requires an agent that **reasons** about
> kernel wait-attribution."*

Replicated at the model level: the kernel pack left the named component
identical on **12 of 12** incidents for **+61% more tokens**.

**2. Flat is not robust.** *"None of the existing automated methods could even
express these claims, **because they cannot use the kernel layer at all and
their accuracy is flat for the uninteresting reason that it is low.**"*

**3. It is not simply "more data".** At the **minimal budget** — 115× less data
and **no kernel at all** — the agent still localises **83%**, against **46–48%**
for baselines given everything.

---

## 6. Critiques of our own approach, from the literature

**Put these in a limitations section before a reviewer finds them.**

**Our scoring is directly attacked.** *Beyond Fault Localization* argues endpoint
correctness *"provides no indication of the evidentiary basis for a diagnosis or
the propagation route."* `table.md` concedes: **"Our WHERE axis *is* the endpoint
correctness they attack."** Their **Edge F1 never exceeds 0.67** while Node F1 is
far higher — and their depth finding (**85.5% → 57.1%**) warns that **our best
results are on short causal chains.** Their failure code **GEN3, "abandons an
evidence channel after a failed or empty query", is exactly the `ctf_lines`
silent-empty bug we fixed.**

**We have no abstention category.** Roy et al. split honest "unknown" from
confident-wrong; *"a confident wrong answer and an honest 'unknown' score
identically"* in our harness, **and we have the data to split them.** Their
framing of *why* an agent — *"each troubleshooting step yields previously unknown
information"* — is better than ours.

**Specialisation may be the wrong bet.** *From General Agents to RCA Experts*
finds **specialised RCA agents now lose to general agents** (36.1% vs 17.9% and
5.6%), and RCA-Agent drops **31.8% → 1.9%** off its own benchmark. *"The
bottleneck is the harness."* We also have **no evolve/verify loop.**

**We judge the diagnosis, never the code.** Xpert's Xcore has three axes and *"we
have only the first (did it run)"*. The analogue for us is a `run_python` block
that executes cleanly and aggregates the wrong column.

**A published warning aimed at our own discriminators.** REPLICAWATCHER rejected
rate-based features — *"syscall frequency, latency, delta time, IPs/ports and
buffer length all exhibit substantial dissimilarity"* across identical replicas;
only process-based features were stable. **Several of our discriminators are
rate-based.** The recommended action: *"test our fault-window ratios against the
no-fault window-to-window variation of the same container before trusting them."*

---

## 7. Honest weaknesses in our citation posture

- **8 literature-backed claims across 16 blueprints; nine carry none.** By
  AutoTSG's own taxonomy, **those nine are the "Empty" category.**
- **No citation reaches the agent** — references live in the blueprint, not the
  generated skill.
- **55 of 111 sources have a summary.** The 72-row tracker is entirely "Not
  Started".
- **Four of the closest prior-art documents are unread** (Wert dissertation,
  Wert book, Ghosh thesis, Vostokov encyclopedia).
- **Three whole themes are missing** from the citable library: distributed-tracing
  foundations, log analysis, and agent frameworks.
- **Two sources unobtainable** — `denys-2023-distributed-critical-path`,
  `runbookfx-2026`.

### Thirteen citations were corrected on 30 Sept 2026, after reading in full

*"None of these reached a blueprint or a generated skill."* The five that change
a **citation string**:

| Was | Correct |
|---|---|
| Chen 2014 reports N+1 costs "more than an order of magnitude" | **Chen reports no such thing for N+1.** One-by-one processing is −17% micro-benchmark, +8% to −32% across Broadleaf, significant in 5 of 10 suites |
| "Suneja et al., IPDS 2020" | **Karn, Kudva, Huang, Suneja & Elfadel, IEEE TPDS 32(3):674–691, 2021.** Suneja is the *fourth* author; "IPDS" is not a venue |
| Zhou et al., IEEE TSE **2018** | **IEEE TSE 47(2):243–260, 2021.** The PDF's "2018" running header is a stale draft template |
| FixItFlow's "32.24% / 13.32% / 11.21%" | **AutoTSG's Table 1 — cite Shetty et al. 2022** |
| no empirical source for the `prev_state=0`/`swapper` test | **Gelle et al. 2021 §4.3 publish exactly that line** |

Claim-level corrections: Rezazadeh argues kernel-only tracing **cannot** see
user-space locks (a limit, not a capability); DepGraph **never mentions**
deadlock or cycle detection; CPI² correlates *because* cache interference cannot
be attributed directly, which makes `sched_switch` **stronger**; CFS throttling
is **per run-queue**, not per container.

### Do-not-quote list

| Number | Why not |
|---|---|
| Gassais' **100%** | labels assigned by *novelty* against a one-hour benign trace; 2 of 7 attacks failed |
| AutoTSG's **severity-1 TTM** | transposed in the paper (36 h called "lesser" than 2 h) |
| RCAEval / AIOpsLab scores as **comparable to ours** | different task, different inputs |
| StepFly's **~94%** | procedure adherence, not diagnosis accuracy |
| Kohyarnejadfard's **F 0.9759** | next-key prediction, not a fault-detection rate |
| Gunawi's **15% network** | that is of outages with a *known* cause; of all 597 it is 8.7%. **Never cite for a signature** |
| Lozi's **138×** without the caveat | fixed in 3.17–4.3; our kernel is 7.0 and CFS became EEVDF in 6.6 |
| Heracles for anything but motivation | it *prevents* interference with a real-time controller |
| Yang's DNS numbers | public Internet, not containers; measures **failure**, our fault injects **delay** |

### Language/runtime limits to state

Lu 2008 and Franke 2002 are **C/C++ only**; Ghanavati is **Java only**; Yang
2018 is **Rails only**; Chen 2014 is ORM-specific. Our `slow_query` injection is
**one shape out of Yang's nine** — *"do not imply we cover the family."*

### Inconsistencies inside the catalogue itself

`table.md` says both "thirteen corrections" and "all eight were confined to…"
(a stale remnant); it contains an orphaned table with no header row; it claims
"nothing is left to read except the Salesforce patent" while four
prof-recommendation volumes are unsummarised; and `rcacopilot-2024` has a full
summary but **no row in `table.md`** — invisible if you read that file alone.
Venue/year drift: `pham-2024-rcaeval` is really 2025, `zhou-2018-train-ticket`
is really 2021. **Trust `table.md`'s corrections over `index.yaml` and
`manifest.yaml` for these.**

---

## 8. Where everything lives

```
DOCS/reading-papers/
├── sources/<slug>/
│   ├── paper.md               ← CITE ONLY IF THIS EXISTS (55 of 111)
│   └── meta.yaml              status: is STALE — see §0
├── blueprint-references/<N> <problem>/
│   ├── misc/                  the related-work review material
│   └── prof-recommendation/   the Wert cluster (§2G) — mostly unread
├── claude-recommendations/    77 PDFs, reading_tracker.csv, ALL "Not Started"
├── index.yaml                 GENERATED — do not hand-edit
├── table.md                   the catalogue + 13 corrections + do-not-quote notes
└── tools/                     fetch_refs · verify_pdfs · build_sources · …
```

| File | What |
|---|---|
| `blueprints/REFERENCE-PACK-FOR-KERNEL-TRACE.md` | **the only citation-quality related-work review in the repo.** 75 KB |
| `DOCS/reading-papers/table.md` | per-source positioning notes, corrections, do-not-quote warnings |
| `non-llm-baseline.md` | why BARO was chosen over causal-discovery methods |
| `thesis/PROPOSAL.md` §3 | background and the three-part gap |
| `msr-research.md` §2 | the dataset comparison table |
| `agentic-rca/RESULTS-nonllm-baselines.md` | the 1,395-evaluation head-to-head |
| `blueprints/docs/RESULTS-comparison.md` | the 12-incident, 6-method study |
| `paper/fse-draft.md` §2 | a related-work **stub with TODO citations** — not usable |
| `paper/sections/*.tex` | a progress report. **No related-work section at all** |

---

## 9. Suggested structure, and what to do first

**Section order** — broadest accepted fact to narrowest gap:

1. Diagnosis is skilled work, and the skill is tacit.
2. A decade of automated RCA, and what it keeps (§2A). *The artifact is the
   model, not the investigation.*
3. Agents inherit the statelessness (§2B).
4. Where procedure *is* reused, it is prose — and the prose is measurably broken
   (§2C). *"Automating a wrong procedure faithfully is still wrong."*
5. The evaluation substrate stops at the application boundary (§2D).
6. And we know empirically that this is where diagnosis fails (§3) — Zhou's two
   undebuggable environment faults, plus Dai / Gunawi / Ghanavati.

Then the gap (§4), then **the measured head-to-head** (§5). **Lead §5 with
5C.1** — kernel data cannot be bolted onto a published method — since nobody
else has that finding.

**Position against §2G in its own paragraph**, or a reader who knows
DynamicSpotter will think the catalogue idea is being presented as new.

### Do these before submitting

1. **Read the Ghosh thesis and one Wert volume.** They are the two closest
   documents to this thesis and both are unread.
2. **Source the three missing themes** — Dapper/Canopy/Pivot Tracing, a log
   anomaly baseline, and ReAct/Toolformer/Voyager. None is in the citable
   library.
3. **Register the three orphaned OS-noise PDFs.** The agentic leg is an OS-noise
   study and its three nearest papers are not in the catalogue.
4. **Fix `sources/chen-2014-orm-antipatterns/meta.yaml`** — it still carries the
   refuted N+1 claim.
