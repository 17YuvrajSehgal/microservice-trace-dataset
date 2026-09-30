# Paper Context: SiriusHelper — An LLM Agent-Based Operations Assistant for Big Data Platforms (Tencent)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> The most peripheral of the related-work set — a deployed **big-data-platform assistant**, not a
> microservice RCA system. **Two results are worth taking anyway**: iterative retrieval beats
> single-shot by a measured margin, and **CoT without grounding evidence was both least accurate
> and *slowest***. §6.

---

## 1. Bibliographic info

- **Title:** SiriusHelper: An LLM Agent-Based Operations Assistant for Big Data Platforms
- **Authors:** Yu Shen, Shiyang Liu, Qihang He, Yihang Cheng, Haining Xie, Zhiming He, Huahua Fan,
  Xianzhi Tan, Teng Ma, Shaoquan Zhang, Danqing Huang, Fan Jiang, Yang Li, Chongqing Zhao,
  Peng Chen, Jie Jiang (**Tencent TEG**); **Bin Cui** (Peking University)
- **Status:** preprint / industry paper. **Deployed on the Tencent Big Data platform.**

```bibtex
@misc{shen2026siriushelper,
  title  = {SiriusHelper: An {LLM} Agent-Based Operations Assistant for Big Data Platforms},
  author = {Shen, Yu and Liu, Shiyang and He, Qihang and others and Cui, Bin},
  note   = {Tencent, preprint}
}
```

---

## 2. One-paragraph summary

A deployed assistant for Tencent's big data platform, answering both **general consultation** and
**specialised troubleshooting** (e.g. SQL/Flink execution diagnosis). It fixes three problems the
authors observed in LLM+RAG assistants: **limited scenario coverage**, **inefficient knowledge
access** from flat knowledge stores with poor multi-hop retrieval, and **high maintenance cost**
because escalated tickets are unstructured and hard to turn into improvements. Their answers are a
**DeepSearch "Plan-Retrieve-Filter" loop** over a **priority-based hierarchical knowledge base**,
and **automated ticket understanding with SOP distillation**. Deployed, it achieves **73% accuracy
and 81% usefulness** against baselines, and **reduced online ticket volume by about 20.8%**.

---

## 3. The three problems they name

1. **Coverage** — one assistant must handle general questions *and* domain-specific
   troubleshooting workflows.
2. **Knowledge access** — sources sit *"in a flat collection (documents, FAQs, tickets), which
   makes it difficult to prioritize important sources (e.g., scenario SOPs)"*, and multi-hop
   retrieval is inadequate.
3. **Maintenance** — when the assistant fails, the case escalates to a ticket. In principle those
   tickets improve the assistant, but *"it requires extensive manual effort"*: tickets must be
   analysed, and for specialised scenarios the resolution process must be **manually consolidated
   into reusable SOPs**.

---

## 4. Design

**DeepSearch engine** — a closed loop of three modules:

- **Plan** — decide what to look for next.
- **Retrieve** — fetch candidates.
- **Filter** — *"evaluates the retrieved candidates against the"* current need.

They note that **unlike conventional DeepSearch pipelines, they explicitly introduce a reflection
step**, and that this is what improves robustness for specialised agents.

**Priority-based hierarchical knowledge base** — so scenario SOPs outrank generic documents,
enabling **multi-hop retrieval without context overload**.

**Automated ticket understanding and SOP distillation** — the assistant **diagnoses its own failure
reason** (e.g. *missing knowledge* vs *wrong routing*) and extracts SOPs from categorised tickets
to enrich the knowledge base. This runs as a **"generate-verify" loop with stability evaluation**
across three agents:

| Agent | Role |
|---|---|
| **SOP Author** | extracts the diagnostic logic from the ticket |
| (second agent) | selects the most defensible root cause |
| **SOP Reviewer** | evaluates **multiple drafts generated from the same ticket** for cross-version consistency |

**Intent routing** — identifies user intent and routes to the right path, including **dedicated
expert workflows** for specialised scenarios.

---

## 5. Results

Benchmark built from **production incidents**, with the real resolution as ground truth.

| Method | **Accuracy** | **Usefulness** | Avg latency (s) | P90 (s) |
|---|---|---|---|---|
| CoT (prompting only, no external knowledge) | **54%** | 62% | **25.91** | 42 |
| RAG (single-turn) | 57% | 68% | **19.96** | 30 |
| Vanilla DeepSearch (multi-turn) | 62% | 71% | 19.93 | 31 |
| **SiriusHelper** | **73%** | **81%** | 24.16 | 42 |

**Online impact: total ticket volume down ~20.8%** after accounting for overall ticket growth.

### Knowledge-base ablation (their Table 2)

| Setting | Accuracy | Usefulness | Avg latency | Retrieval iterations |
|---|---|---|---|---|
| Vanilla DeepSearch, **flat** | 62% | 71% | 19.93 | 1.16 |
| Vanilla DeepSearch, **hierarchical** | **65%** | **73%** | 19.18 | 1.26 |
| SiriusHelper, **flat** | 67% | 76% | 27.78 | 1.63 |

**Both methods perform worse with a flat knowledge base.**

### Two observations from their analysis

**Why iterative retrieval wins:** it *"allows the system to refine search queries based on
intermediate hypotheses and recover from an initially suboptimal retrieval result. This is
particularly important for specialized tasks, where **the key evidence is often scattered across
different logs/docs and may not be surfaced by a single retrieval**."* Single-shot RAG *"is more
sensitive to the first retrieved set."*

**The latency finding, which is counter-intuitive:**

> **CoT shows relatively high latency (25.91 seconds), suggesting that without reliable external
> evidence the model tends to spend more time on free-form reasoning, whereas trusted knowledge
> sources can shorten the overall reasoning process.**

**The worst method was also nearly the slowest.**

---

## 6. What this means for our work

**This is the most peripheral paper in the set** — a big-data-platform assistant answering user
questions, not a microservice RCA system, and it has no telemetry analysis at all. **Cite it, if
at all, as evidence that deployed LLM operations assistants exist and are measured.** Three things
are still worth noting.

**1. The latency finding is a genuinely useful data point.** An agent with no grounded evidence
spent **more** time reasoning and was **less** accurate. That contradicts the natural assumption
that giving an agent tools costs time. It also fits what we saw: the workers that recorded nothing
were not fast, they were stuck. **If we report cost alongside accuracy — which AIOpsLab does and
we should — this is the precedent that the two are not necessarily traded off.**

**2. Hierarchical beats flat, measurably.** 62% → 65% for the same method, purely from
prioritising scenario SOPs over generic documents. **Our blueprints are a flat set**: the agent is
given the problem and must pick. With 11 problems in the campaign and 24 families in the dataset,
**some prioritisation structure may matter**, and this is a small measured argument that it does.
The effect here is modest (3 points), so it is a nudge rather than a mandate.

**3. Their SOP Reviewer is a good idea we do not have.** It **generates multiple drafts from the
same ticket and checks them against each other for consistency**. The analogue for us: **run the
same run through the agent more than once and compare the diagnoses.** We currently take one
diagnosis per cell. **Cross-run consistency would separate "the agent knows this" from "the agent
guessed and happened to be right"** — which is the same distinction
[[beyond-fault-localization]] attacks from the trajectory side and [[roy-2024-llm-agents-rca]]
attacks from the abstention side. **Three papers converging on the same weakness in endpoint-only
scoring.**

**And one honest limit.** Their 73% / 81% is **answer accuracy and usefulness on user-facing
support questions**, graded against the ticket's real resolution. **Nothing about it is comparable
to ours**, and the task is closer to documentation retrieval than to diagnosis.

---

## 7. Safe claims

- A **deployed** assistant on the **Tencent Big Data platform**, handling general consultation and
  specialised troubleshooting (e.g. SQL execution diagnosis) with **intent-based routing** to
  dedicated expert workflows.
- Three problems addressed: **limited scenario coverage**, **inefficient knowledge access** from
  flat collections where *"it is difficult to prioritize important sources (e.g., scenario SOPs)"*,
  and **high maintenance cost** because escalated tickets need extensive manual effort to become
  reusable SOPs.
- **DeepSearch engine**: a closed **Plan-Retrieve-Filter** loop with an **explicitly added
  reflection step**, over a **priority-based hierarchical knowledge base**.
- **Automated ticket understanding**: diagnoses its own failure reason (**missing knowledge** vs
  **wrong routing**) and distils SOPs, via a **generate-verify loop** with an **SOP Author** and an
  **SOP Reviewer** that checks **multiple drafts from the same ticket** for consistency.
- Benchmark from production incidents with the real resolution as ground truth. **SiriusHelper 73%
  accuracy / 81% usefulness**, vs **Vanilla DeepSearch 62%/71%**, **RAG 57%/68%**, **CoT 54%/62%**.
- **CoT was the least accurate and had the highest average latency (25.91 s)** — *"without reliable
  external evidence the model tends to spend more time on free-form reasoning."*
- **Flat knowledge bases perform worse than hierarchical for both methods**: Vanilla DeepSearch
  62% → 65% accuracy, 71% → 73% usefulness.
- Iterative retrieval matters because *"key evidence is often scattered across different logs/docs
  and may not be surfaced by a single retrieval."*
- **Online ticket volume reduced by about 20.8%** after accounting for ticket growth.

## 8. Do NOT claim

- That it does root cause analysis of microservices. It is a **big-data-platform operations
  assistant**; the benchmark is user-facing support questions.
- That 73% is comparable to any RCA accuracy in this reference set, ours included.
- That its knowledge is mined from telemetry. It comes from **documents, FAQs, tickets and SOPs**.
- That the 20.8% ticket reduction isolates the assistant's effect. It is an online deployment
  figure adjusted for overall ticket growth, not a controlled experiment.

## 9. Reusable ideas

- **Generate several drafts from the same input and check them against each other.** Their SOP
  Reviewer is cheap consistency checking, and the run-level analogue would tell us whether a
  correct diagnosis was knowledge or luck.
- **Prioritise the knowledge, don't flatten it.** 3 points of accuracy from ordering SOPs above
  generic docs.
- **Add a reflection step to the retrieve loop.** They call this out as their difference from
  conventional DeepSearch.
- **Diagnose your own failures by category.** "Missing knowledge" vs "wrong routing" is the
  minimum useful split, and it directly drives what gets added next.
- **Report latency next to accuracy.** Their CoT row — worst and slowest — only exists because they
  measured both.
