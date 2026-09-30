# Paper Context: StepFly — End-to-End Agentic Framework for Troubleshooting Guide Automation (FSE 2026)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Our pack calls it *"closest to your blueprints"*, and that is right — structured steps executed
> by an agent. Its **empirical study of 92 real TSGs** is the most useful part: a quality taxonomy
> that reads as a checklist for our blueprint schema, and a **46% parallelisation opportunity**
> we do not exploit. See §7.

---

## 1. Bibliographic info

- **Title:** StepFly (full title per our pack: an end-to-end agentic framework for troubleshooting
  guide automation)
- **Authors:** Mao, Li et al. (Microsoft, with academic co-authors)
- **Venue:** **Proc. ACM Softw. Eng. 3(FSE), Article FSE136, July 2026**
- **DOI:** 10.1145/3808143 — **arXiv:** 2510.10074
- **Code:** https://github.com/microsoft/StepFly

```bibtex
@article{mao2026stepfly,
  title   = {StepFly: End-to-End Agentic Framework for Troubleshooting Guide Automation},
  author  = {Mao and Li and others},
  journal = {Proc. ACM Softw. Eng.}, volume = {3}, number = {FSE}, articleno = {136}, year = {2026},
  doi     = {10.1145/3808143}
}
```

---

## 2. One-paragraph summary

Generic LLM agents lack **specialised support** for what TSG execution actually needs. StepFly
starts from an **empirical study of 92 real TSGs from 9 teams**, then builds a three-stage
framework: offline, it extracts an **execution DAG** from unstructured TSG prose and creates
**Query Preparation Plugins (QPPs)**; online, a **DAG-guided scheduler-executor** with a memory
system runs the steps. **~94% success rate on GPT-4.1** (~84% on a weaker model), with **less time
and fewer tokens than baselines**, and a **32.9% to 70.4% execution-time reduction for
parallelisable TSGs**.

---

## 3. The empirical study — 92 TSGs, 9 teams

### Finding 1 — size and structure

- Most TSGs are around **3K tokens** (GPT-4o tokenizer); **outliers exceed 10K**.
- Most have **5-15 steps**; complex ones reach **30**.

> **TSGs are often lengthy documents with many steps and complex conditional connections. This
> inherent complexity makes it challenging for LLMs to follow the correct execution path**, as
> confirmed by our experiments ... where **baselines often fail to navigate through the steps
> correctly**.

### Finding 2 — parallelism, the observation nobody else makes

**~46% of TSGs have steps that could run concurrently** — defined as no data dependency and no
sequential constraint. Their four categories:

| Category | Share | What it is |
|---|---|---|
| **Independent Paths (IP)** | **40.5%** | diagnostic branches — known issues, service health checks — explorable concurrently |
| **Multiple Data Sources (MD)** | 28.6% | parallel queries to disparate sources |
| **Multiple Analysis Types (MA)** | 26.2% | different analytical dimensions of the same data |
| Loop Iterations (LI) | 4.8% | repeated queries with varying parameters |

Their framing: authors **write steps sequentially** but that is **often not a requirement** —
*"inspired by how a team of SREs would collaborate."*

### Finding 3 — query templates dominate

- **Query templates are ~35.85% of the total tokens per TSG** on average.
- **405 query templates across the corpus, averaging 4.4 per TSG.**
- Dynamic LLM query generation fails three ways: **instruction drift** (ignoring the template and
  rewriting), **structural omissions** (missing sub-queries or conditions), and **syntax errors**.
- **Query generation is their primary bottleneck** in evaluation. KQL being less common than SQL
  makes it worse, and *"query verbosity consumes significant [tokens]"*.

### Finding 4 — TSG quality, with a second taxonomy

Manual annotation with inter-rater agreement reported per category (**κ = 0.85** for the concrete
Database Instruction issues, **κ = 0.72** for the subjective Clarity issues; **~12% needed a third
annotator**).

| Category | Share | Dominant sub-issues |
|---|---|---|
| **Clarity and Precision (CP)** | **37.4%** | **"Missing Description of the Action"**, **"Unquantifiable Condition"** |
| **Database Instruction (DI)** | **27.2%** | query templates with **hardcoded parameters such as time ranges** |
| **Data Flow (DF)** | 20.4% | **"Unknown Input Source"**, "Wrong Input Source", "Missing Parameters" |
| Presentation and Structure (PS) | 9.9% | formatting |
| **Control Flow (CF)** | 5.1% | **"Unable To Infer Next Step"**, "Wrong Next Step" |

> **Most TSGs, in their current form, are not readily suitable for automation due to various
> quality issues. These issues require substantial preprocessing or refinement before automation
> can be effectively implemented.**

---

## 4. The approach

**Offline:** extract a **DAG** from the raw TSG — steps as nodes, connections as edges — which
*"precisely captures control flow and step dependencies"*. Build **Query Preparation Plugins**
that handle the query templates rather than regenerating queries each time. They also ship a
**TSG Mentor** giving authors guidance on writing automation-ready TSGs, derived from the quality
findings.

**Online:** a **DAG-guided execution engine** ensures *"the agent adheres strictly"* to the
dependencies, plus a **memory system**.

Two stated benefits of the DAG: it **removes the ambiguity of natural-language control flow**, and
it **exposes the parallelism** Finding 2 identified.

---

## 5. Results

| | StepFly |
|---|---|
| Success rate, **GPT-4.1** | **~94%** |
| Success rate, weaker LLM | **~84%** |
| Time and tokens | **less than baselines** |
| **Parallelisable TSGs** | **32.9% to 70.4% execution-time reduction** |

---

## 6. What kind of paper this is

- **Empirical study + framework**, on real Microsoft TSGs and incidents.
- Works from **human-written guides**; the agent executes them against logs, DevOps, CI and
  metrics tools.
- **No telemetry analysis, no fault injection, no kernel data.** The task is *following a
  procedure correctly*, not diagnosing from raw signals.

---

## 7. What this means for our work

**Our pack is right that this is the closest published work to the blueprint idea.** It is the same
shape: a structured, step-wise diagnostic procedure executed by an agent. Four things transfer.

### 1. Their quality taxonomy is a schema review for our blueprints

Read as requirements, this is uncomfortably on target:

| Their issue | Our equivalent |
|---|---|
| **CP 37.4% — "Missing Description of the Action"** | a discriminator that names a signal but not the computation |
| **CP — "Unquantifiable Condition"** | *"futex rate is elevated"* with no threshold. **We have these.** |
| **DI 27.2% — hardcoded parameters like time ranges** | any blueprint that assumes a fixed window length |
| **DF 20.4% — "Unknown Input Source"** | a step that does not say **which tool** produces the input |
| **CF 5.1% — "Unable To Infer Next Step"** | our "stop and switch" guidance, which is prose |

**"Unquantifiable Condition" is the one to act on.** It is their second-largest sub-issue inside
their largest category, and it is exactly the failure mode of a discriminator written before the
threshold was measured. Our evidence-first rule is the defence, and this is external evidence that
the rule matters.

### 2. The 46% parallelism finding is something we are leaving on the table

**~46% of TSGs have independent steps**, and StepFly gets **32.9-70.4% time reduction** by running
them concurrently. Our `agent_v2.py` runs workers through plan → work → review → synthesise. **Our
blueprints' rule-out lists are structurally the same as their "Independent Paths" (40.5%)** —
checking "is the host saturated?", "is a foreign task on the CPU?", "is the group throttled?" are
**independent questions over the same trace**. We currently do them in sequence within a worker's
step budget.

Given that **both AIOpsLab and Roy found the step limit is where hard cases die**, and that our own
`out_of_steps` health row exists for the same reason, **parallelising independent rule-outs is a
direct attack on the binding constraint**. This is the most actionable idea in the related-work
set. **Worth designing before the full campaign**, not after.

### 3. A DAG is a stronger representation than our prose

They extract an explicit DAG because natural-language control flow is ambiguous. Our
`blueprint.json` has fields and prose; the dependency structure between checks is implicit. **Their
argument is that making it explicit both removes ambiguity and exposes parallelism** — one change
buying both.

### 4. The success rates are not comparable, and the reason is important

**~94% on GPT-4.1 is "did the agent follow the TSG correctly", not "was the diagnosis right".**
Their task is **procedure adherence** against a guide that already encodes the answer. Ours is
**producing the answer** from a trace. **A reviewer could easily read 94% as a diagnosis accuracy
and wonder why ours differs.** Say the difference explicitly.

**One thing they have that we do not.** Their **Query Preparation Plugins** exist because dynamic
query generation was their **primary failure mode** — instruction drift, structural omissions,
syntax errors. Our `codetool.py` has the same exposure: the agent writes pandas code each time.
Our `_HINTS` are a reactive fix (help it recover); **QPPs are the preventive one** (do not make it
generate the query at all). For the handful of computations every blueprint needs — window
aggregates, per-`pid_ns` breakdowns, top-N by wait — **a prepared helper would remove a whole class
of failure**. Worth weighing against the flexibility we would lose.

**And one warning.** Their **TSG Mentor** exists because Finding 4 says most guides need
**substantial preprocessing before automation works at all**. Our blueprints are written to be
executed from the start, which avoids this — but only if they are written well. Their taxonomy is
the checklist for "written well", and we should run our existing blueprints against it once.

---

## 8. Safe claims

- Empirical study of **92 real TSGs from 9 teams**.
- **Most TSGs are ~3K tokens** (some over 10K) and have **5-15 steps** (some up to 30). Their
  complexity makes it hard for LLMs to follow the correct path, and **baselines often fail to
  navigate the steps correctly**.
- **~46% of TSGs have parallelisation opportunities**: **Independent Paths 40.5%**, Multiple Data
  Sources 28.6%, Multiple Analysis Types 26.2%, Loop Iterations 4.8%.
- **Query templates are ~35.85% of tokens per TSG**; **405 templates across the corpus, averaging
  4.4 per TSG**. Dynamic query generation fails through **instruction drift, structural omissions
  and syntax errors**, and is their **primary bottleneck**.
- TSG quality taxonomy: **Clarity and Precision 37.4%** (dominant sub-issues **"Missing
  Description of the Action"** and **"Unquantifiable Condition"**), **Database Instruction 27.2%**
  (hardcoded parameters such as time ranges), **Data Flow 20.4%** ("Unknown Input Source"),
  Presentation and Structure 9.9%, **Control Flow 5.1%** ("Unable To Infer Next Step").
  Inter-rater **κ = 0.85 (DI) to 0.72 (CP)**, ~12% adjudicated by a third annotator.
- *"Most TSGs, in their current form, are not readily suitable for automation ... [they] require
  substantial preprocessing or refinement."*
- StepFly extracts an **execution DAG** offline, builds **Query Preparation Plugins**, and runs a
  **DAG-guided scheduler-executor with a memory system** online. It also ships **TSG Mentor** for
  authoring guidance.
- **~94% success rate on GPT-4.1**, **~84%** on a weaker model, with **less time and fewer tokens
  than baselines**, and a **32.9-70.4% execution-time reduction for parallelisable TSGs**.

## 9. Do NOT claim

- That ~94% is a diagnosis accuracy. It is **success at executing a TSG correctly**, on guides that
  already encode the answer.
- That the 32.9-70.4% speedup applies generally. It applies to **the ~46% of TSGs that are
  parallelisable**.
- That it diagnoses from telemetry. It **follows a human-written procedure**, querying logs,
  metrics, CI and DevOps tools.
- That the two TSG-quality taxonomies (this and AutoTSG's) are the same study. **Different
  corpora, different categories** — AutoTSG codes *user feedback*, StepFly codes *the guides
  themselves*.

## 10. Reusable ideas

- **Extract an explicit DAG.** It removes control-flow ambiguity and exposes parallelism in one
  move.
- **Measure the parallelism in your procedures.** 46% with a four-way breakdown turns "we could
  parallelise" into a design decision. **Our rule-out lists are their Independent Paths.**
- **Prepare the queries instead of generating them.** QPPs target their top failure mode
  preventively; our `_HINTS` target ours reactively.
- **"Unquantifiable Condition" is a named defect.** Any discriminator without a measured threshold
  is one.
- **Report inter-rater agreement per category.** κ = 0.85 for concrete issues and 0.72 for
  subjective ones tells you which parts of the taxonomy to trust.
- **Ship the authoring guidance with the tool.** TSG Mentor exists because the study found the
  inputs were not good enough — the same reason our blueprint schema has required fields.
