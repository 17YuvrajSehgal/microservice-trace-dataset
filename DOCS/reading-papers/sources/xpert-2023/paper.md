# Paper Context: Xpert — Empowering Incident Management with Query Recommendations via Large Language Models (2023)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Related work on LLM-assisted incident management. **Its most transferable idea is not the
> recommender — it is `Xcore`, a way to score generated code that does not rely on text
> similarity.** We have the same problem with `run_python` output and no equivalent check. §7.

---

## 1. Bibliographic info

- **Title:** Xpert: Empowering Incident Management with Query Recommendations via Large Language
  Models
- **Authors:** Yuxuan Jiang (University of Michigan), Chaoyun Zhang (Microsoft, corresponding),
  Shilin He, Zhihao Yang (Peking University), **Minghua Ma**, Si Qin, Yu Kang, Yingnong Dang,
  Saravan Rajmohan, Qingwei Lin, Dongmei Zhang (Microsoft)
- **arXiv:** 2312.11988, 19 December 2023 (ICSE 2024)

```bibtex
@inproceedings{jiang2024xpert,
  title     = {Xpert: Empowering Incident Management with Query Recommendations via Large Language Models},
  author    = {Jiang, Yuxuan and Zhang, Chaoyun and He, Shilin and Yang, Zhihao and Ma, Minghua and others},
  booktitle = {ICSE 2024}, year = {2024}
}
```

---

## 2. One-paragraph summary

On-call engineers analyse telemetry by **writing KQL queries by hand**, and *"even a minor mistake
in the query can [mislead]"*. The authors run the **first empirical study of KQL usage** in
Microsoft's incident management, then build **Xpert**, which recommends or generates a KQL query
for a new incident from **two years of historical incidents and their query records**, using an
LLM's **few-shot** ability so no fine-tuning is needed. Because text-similarity metrics are wrong
for code, they define **Xcore** — a composite of **executability, semantic soundness, and output
correctness** — and deploy the system in **Microsoft production**.

---

## 3. The empirical study of KQL usage

Three findings:

1. **Most incidents are handled with a small number of KQL queries.**
2. **Most queries are relatively simple in structure.**
3. **Queries show a long-tail pattern in templates, and significant variation over time.**

Why writing them is hard: an engineer must find the right tables, possibly **across multiple
databases**, then compose joins, counts and aggregations. The process is error-prone and slow, and
a wrong query sends the investigation the wrong way.

Finding 3 is why they use an LLM's **few-shot** ability rather than fine-tuning: the long tail and
the drift mean a fine-tuned model would need **frequent, costly retraining**, whereas few-shot
*"allows them to quickly adapt to novel and evolving incident types by leveraging historical data
in an online fashion."*

---

## 4. Design

- Extract **common patterns — tables and templates — from historically similar incidents**, and
  use them as few-shot context.
- **Post-Validator:** runs a **grammar and syntax check using the compiler's abstract syntax
  tree**, and analyses the query's data flow.
- **No parameter tuning** anywhere.

---

## 5. Xcore — the metric

Their objection to BLEU/METEOR for this task: they measure **lexical similarity**, which says
nothing about whether code runs or is right. Xcore evaluates **three perspectives**:

| Component | What it checks |
|---|---|
| **V — Validity / executability** | two-step: the **built-in KQL syntax checker**, then execution |
| **S — Semantic soundness** | **infers column data types from semantics** to judge whether the query makes sense |
| **O — Output correctness** | correctness of the **data source and the return types** |

`Xcore = α·V + β·S + γ·O`, with α + β + γ = 1 and **equal weights by default**; all components and
the total range **0 to 1**. They note the weights can be re-balanced per application, and that
**Xcore generalises to any DSL with a syntax checker**.

---

## 6. Results

Recommending KQL **templates** and **full queries** (their Table 2; higher is better):

| Model | BLEU | METEOR | **Xcore** | TableAcc | **Identicality** | Validity |
|---|---|---|---|---|---|---|
| Bart | 2.91 | 24.90 | 39.29 | 31.15 | 0.43 | 75.23 |
| T5 | 60.90 | 60.84 | 38.17 | 31.02 | 10.52 | 49.98 |
| CodeT5+ | 73.50 | **69.77** | **61.38** | **48.58** | 20.00 | **82.90** |
| **Xpert (GPT-3.5)** | **75.55** | 67.18 | 58.19 | 45.68 | **30.58** | 80.87 |

(Second block, full queries: CodeT5+ 66.17 / 65.35 / 60.75 / 55.53 / 16.13 / 80.37;
Xpert 66.51 / 64.36 / 60.27 / 53.46 / **24.44** / **83.01**.)

**Xpert's clearest win is Identicality — exact match with ground truth — at 30.58% against
CodeT5+'s 20.00%**, and it does it **without fine-tuning**, where CodeT5+ is trained.

### The post-processing result

Their Table 3 compares before and after post-processing:

| | Before | After |
|---|---|---|
| BLEU | 34.95 | 36.61 |
| **Xcore** | **11.63** | **35.99** |

**Post-processing barely moves BLEU (+1.7) but triples Xcore (+24.4).** That is the paper's own
demonstration that **lexical metrics cannot see the thing that matters** — a query that is nearly
identical in text can be unexecutable.

**Deployed in Microsoft production.**

---

## 7. What this means for our work

**As related work it is a minor entry** — query recommendation, not diagnosis. **One idea in it is
directly applicable to our harness and we have no equivalent.**

### Xcore, and our `run_python` gap

Our agent writes **pandas code** through `codetool.py` and we judge the *diagnosis*, never the
*code*. Xpert's insight is that **for generated code, text similarity is meaningless and
executability is not enough either** — you need to know the code touched the right data and
returned the right kind of thing. Their three axes map onto ours:

| Xcore | Our equivalent |
|---|---|
| **V — executability** | we have this implicitly: the code ran or raised |
| **S — semantic soundness** (types inferred from column semantics) | **nothing** |
| **O — output correctness** (right data source, right return type) | **nothing** |

**Their post-processing result is the warning.** Xcore went from 11.63 to 35.99 while BLEU moved
1.7 points — meaning **most of their generated queries looked fine and were not**. We have no
check that would catch the analogous case: a `run_python` block that executes cleanly, returns a
plausible number, and aggregated the wrong column or the wrong namespace.

**Two cheap things this suggests**, both testable before the campaign:

1. **Log whether each `run_python` result touched the columns the blueprint names.** That is
   Xcore's O axis, and it is a string check against the DataFrame's columns.
2. **Count how often computations execute but produce a degenerate result** — empty frame, all
   zeros, a single row. We already added `_HINTS` for errors; **silent wrong answers have no
   signal at all.**

This is the same class of problem as the reply-cap bug we fixed this week: **the failure was
invisible because nothing errored.**

### Their few-shot argument supports our design

Finding 3 — **long-tail templates with significant time variation** — is why they use few-shot over
fine-tuning: retraining cannot keep up with drift. **Our blueprints are the same bet**: encode the
procedure, let a general model apply it, rather than train a model per fault family. Their reason
is measured, ours was assumed.

It also pairs with **RCACopilot's 24.96% unseen categories** and **ReplicaWatcher's normality
drift** — three papers saying **the target moves faster than a trained model can follow**.

### Scope

**KQL query recommendation for Microsoft incident management.** No telemetry analysis, no fault
injection, no ground-truth diagnosis. Cite it for **Xcore** and for the **few-shot-over-fine-tuning
argument**, nothing else.

---

## 8. Safe claims

- **First empirical study of KQL usage** in a large-scale cloud incident-management system.
  Findings: **most incidents need only a small number of queries**; **most queries are structurally
  simple**; **queries show a long-tail template distribution and significant variation over time**.
- Writing queries is error-prone: engineers must find the right tables, possibly **across multiple
  databases**, and compose joins, counts and aggregations; *"even a minor mistake in the query
  can"* mislead.
- Xpert recommends/generates KQL from **two years of historical incidents and their query
  records**, using **few-shot LLM prompting with no parameter tuning**, and extracts **tables and
  templates** from similar past incidents as context.
- A **Post-Validator** checks grammar and syntax via the **compiler AST** and analyses data flow.
- **Xcore** scores generated queries on **validity/executability**, **semantic soundness** (column
  data types inferred from semantics), and **output correctness** (data source and return types),
  combined as `α·V + β·S + γ·O` with **equal weights by default**, all in **[0, 1]**. It
  **generalises to any DSL with a syntax checker**.
- Results: **Xpert (GPT-3.5) BLEU 75.55, Xcore 58.19, Identicality 30.58%**, against **CodeT5+
  BLEU 73.50, Xcore 61.38, Identicality 20.00%** — Xpert wins on **exact match without
  fine-tuning**.
- **Post-processing moved BLEU from 34.95 to 36.61 but Xcore from 11.63 to 35.99.**
- **Deployed in Microsoft production.**

## 9. Do NOT claim

- That Xpert diagnoses incidents. It **recommends a query** for an engineer to run.
- That it beats CodeT5+ overall. **CodeT5+ scores higher on Xcore, METEOR, TableAcc and template
  Validity**; Xpert wins on **Identicality** and needs no fine-tuning.
- That Xcore is validated as a proxy for usefulness. It is a **composite metric the authors
  define**; the argument for it is that lexical metrics are worse.
- That its findings about query simplicity apply to our setting. It measures **KQL over Microsoft
  telemetry tables**, not analysis of raw traces.

## 10. Reusable ideas

- **Do not score generated code by text similarity.** Their post-processing result — BLEU +1.7,
  Xcore +24.4 — is the proof.
- **Three axes for judging generated analysis: does it run, is it semantically sound, does it
  return the right thing from the right source.** We check only the first.
- **Few-shot beats fine-tuning when the target drifts.** Long-tail templates plus time variation is
  a measured reason, and it is the same reason our blueprints are prompts rather than models.
- **Validate with the real compiler.** Using the language's own AST and syntax checker is cheaper
  and more reliable than teaching a model what valid means.
