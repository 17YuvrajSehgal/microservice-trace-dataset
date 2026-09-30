# Paper Context: Exploring LLM-based Agents for Root Cause Analysis (FSE 2024, Industry)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> **The most directly useful of the LLM-agent papers for our harness design.** It evaluates a
> ReAct agent on real Microsoft incidents, hand-labels every success and failure, and reports the
> trade-off nobody else does: **the agent that hallucinates least is the one that most often says
> it does not know.** §7 turns that into two checks on our own runs.

---

## 1. Bibliographic info

- **Title:** Exploring LLM-based Agents for Root Cause Analysis
- **Authors:** **Devjeet Roy** (Washington State University), Xuchao Zhang, Rashi Bhave,
  Chetan Bansal, Pedro Las-Casas, **Rodrigo Fonseca**, Saravan Rajmohan (Microsoft)
- **Venue:** FSE 2024, Industry track
- **arXiv:** 2403.04123

```bibtex
@inproceedings{roy2024exploring,
  title     = {Exploring {LLM}-based Agents for Root Cause Analysis},
  author    = {Roy, Devjeet and Zhang, Xuchao and Bhave, Rashi and Bansal, Chetan and Las-Casas, Pedro and Fonseca, Rodrigo and Rajmohan, Saravan},
  booktitle = {FSE 2024 Industry Track}, year = {2024}
}
```

Same Microsoft group as [[rcacopilot-2024]] and [[aiopslab-2025]]; this paper is explicitly
positioned as fixing a limitation of RCACopilot.

---

## 2. One-paragraph summary

Prior LLM work on incident RCA — including RCACopilot — **cannot dynamically collect diagnostic
information**. RCACopilot needs **hand-engineered handlers**; other work uses only the incident
title and description. But *"one of the first steps an OCE takes is to collect additional
information not present in the incident report."* So the authors evaluate a **ReAct agent with
retrieval tools** on a static dataset of real production incidents, **hand-label 97 predictions**
into success and failure modes, test whether **historical discussion comments** help, and then
build a **real agent with a Microsoft team**, equipped with the team's own database query tool,
knowledge-base articles, and a human-in-the-loop channel. The headline result is a trade-off:
**ReAct's correctness (35%) is slightly below the baselines (39%), but its hallucination rate is
4% against 12% for chain-of-thought and 40% for plain retrieval.**

---

## 3. Why an agent, not a classifier

Their argument, and it is the cleanest statement of it in the pack:

> When OCEs receive an incident, they systematically perform a series of troubleshooting steps to
> identify the root cause. **Each troubleshooting step yields previously unknown information**,
> helping the OCE narrow down the set of plausible root causes. This highlights a key aspect of
> root cause analysis: **the process of collecting additional diagnostic information related to
> the incident.**

And the gap they name in prior work: *"neither equips the LLM to dynamically query real time
diagnostic information about the service(s) affected by an incident. RCACopilot relies on
predefined handlers that must be engineered by hand."*

Context on how hard RCA is: *"Even a veteran software engineer might need to spend several years
on a team before they are able to effectively perform RCA on a team's services."*

---

## 4. RQ1 and RQ2 — evaluation on real incidents

**Setup:** **100 incidents** sampled for evaluation, **500** for the retrieval corpus. Baselines
all use historical-incident retrieval and **no fine-tuning**: a Retrieval Baseline (RB) at k=3 and
k=10, Chain-of-Thought (CoT), IR-CoT variants, and ReAct variants.

**Metrics:** lexical (BLEU corpus and segment level, ROUGE-L, METEOR) and semantic (BERTScore) —
plus, crucially, **manual annotation of every prediction**.

### Quantitative

- **CoT has the highest corpus-BLEU**; ReAct variants follow; **IR-CoT lags**.
- On **semantic similarity the whole envelope is under 1 point** — *"neither reasoning nor
  additional historical incidents drastically change the semantic content of predictions."*
- Automatic metrics are unreliable here: their noted failure mode is **predictions that merely
  restate the incident** scoring well.

### The manual labelling — the real result (their Table 3, 97 examples)

| | RB (k=10) | CoT | ReAct-BM25 |
|---|---|---|---|
| **Correct — precise** | 26 | 30 | 29 |
| Correct — imprecise | 2 | 7 | 5 |
| **Correct — hallucination** | **10** | 1 | **0** |
| **Total correct** | **38 (39%)** | **38 (39%)** | **34 (35%)** |
| **Incorrect — hallucination** | **29** | 11 | **4** |
| **Incorrect — insufficient evidence** | 11 | 19 | **39** |
| Incorrect — other | 19 | 27 | 8 |
| Incorrect — reasoning error | 0 | 2 | **10** |
| Incorrect — retrieval error | 0 | 0 | 2 |
| Total incorrect | 59 | 59 | 63 |

**The two numbers that matter:**

- **Hallucination in correct predictions: 26% (10/38) for retrieval, <1% for CoT, 0% for ReAct.**
- **Hallucination in incorrect predictions: 49% (29/59) for retrieval, 18% (11/59) for CoT, 6%
  (4/63) for ReAct.**
- **66% of ReAct's incorrect predictions say it lacks the information to decide** (Insufficient
  Evidence), against 32% for CoT and 18% for retrieval.

Their summary: *"higher correctness rates of the RB come at the cost of factual accuracy, despite
the grounding offered by retrieval ... The ReAct agent also benefits from reasoning, offering the
lowest rates of hallucinations ... albeit at a slightly lower overall accuracy rate."*

**Other observations:**

- **28 of 97 examples are solved by all three** models.
- ReAct uniquely gets **4** right — in every case because it **filtered out historical incidents
  that were lexically similar but semantically different**, which the others wrongly included.
- CoT makes **fewer reasoning errors** than ReAct (2 vs 10); the authors blame ReAct's more
  complex prompting and the zero-shot setting, plus **difficulty maintaining prompt format over
  long trajectories**.
- ReAct retrieves **a mean of 4 unique historical incidents over ~2 lookups**, with duplication
  because **the retrieval tool is stateless** and does not know what it already returned.
- **32% of RB errors and 45% of CoT errors have no clear cause** — many are **too generic** ("a
  non-specific configuration issue") or plausible-but-wrong.

**RQ2 — discussion comments** from historical incidents give **mixed results** on lexical metrics.

---

## 5. RQ3 — the real deployment, with a Microsoft team

Built with **Azure Fundamental Team**, who maintain core services. They add three tool types:

1. **Database Query Tool** — the team's database uses a **custom SQL-like query language**. Split
   into a **Query Execution Engine** and a **Pandas component**, which reduces query complexity and
   makes the tool reusable across teams.
2. **KBA Q/A Tool** — a vector store over **14 knowledge-base documents** plus an LLM. They
   noticed the agent's *"eager interleaving of thoughts and actions"* caused problems, so they
   added a **KBA Planning Tool** variant: identical, but introduced explicitly as a planning step.
3. **Human Interaction Tool** — engineers can **observe tool executions and give explicit feedback
   to the agent**.

### What worked

On a **simple incident with a clear KBA and a straightforward diagnostic sequence** (a cluster
setting drift), the agent **consistently identified the false-positive case**: it read the KBA for
the steps, adapted and ran the sample query, and correctly assessed the returned table —
*"with no prior knowledge of the domain, the incident or the syntax of the database query
language."*

**And the detail that matters most to us:**

> We observed that the agent would sometimes fail to execute the database query in its first
> attempt. However, **since we surface appropriate error messages to the agent as observations, it
> was consistently able to rectify these mistakes** and complete the troubleshooting process.

An engineer: *"amazed by the tool's capability to automatically discern the right parameters and
even rectify mistakes when the parameters are initially incorrect by querying the documents."*

### What did not

- **Case 2 of the same incident** needed **an extra filtering step** on the returned table. The
  agent **could not do this consistently**; engineers used the human-in-the-loop channel to fix it.
- **Complex incidents needing multiple KBAs** — which team engineers say require **at least a year
  of experience** — failed. The agent *"initially produces a plausible high level plan, [but] was
  only ever able to successfully execute one or two diagnostic steps before reaching the iteration
  limit (20)."* The cause: information is spread across KBAs (sample queries and cluster addresses
  in different documents), so it burned steps on repeated Q/A lookups.

---

## 6. What kind of paper this is

- An **empirical study of an off-the-shelf agent (ReAct)** in an **out-of-domain, zero-shot**
  setting, plus a **real deployment case study**.
- Data is **real Microsoft production incidents** — tickets, discussions, KBAs, team databases.
- **No fine-tuning.** **No fault injection, no ground-truth window, no kernel data.**
- Its most valuable contribution is the **manual labelling scheme**, not the scores.

---

## 7. What this means for our work

**Three findings map onto changes we made this week, and two of them we should now check rather
than assume.**

### 1. Surfacing error messages as observations — confirmed, independently

> since we surface appropriate error messages to the agent as observations, **it was consistently
> able to rectify these mistakes**

That is precisely what our `codetool.py` `_HINTS` and the `ctf_tool` actionable error messages do.
**A Microsoft team observed the same effect on a different tool, a different query language and a
different agent.** Good independent support for that fix, and worth citing when we describe the
harness.

### 2. The iteration limit is where complex cases die

Their agent hit the **20-step limit** on multi-KBA incidents after *"one or two diagnostic
steps"*, burning the rest on repeated lookups. We raised `MAX_WORKER_STEPS` from 12 to 18.
**AIOpsLab says accuracy improves with steps then plateaus; Roy says the limit is exactly where
the hard cases fail.** Both point the same way: **the fix is not more steps, it is fewer wasted
ones.** Their specific waste was a **stateless retrieval tool that re-returned documents it had
already given** — worth checking whether any of our tools does the same.

### 3. The trade-off we have not measured: abstention versus hallucination

This is the finding to take seriously.

| | Correctness | Hallucination (incorrect preds) | "Insufficient evidence" |
|---|---|---|---|
| Retrieval baseline | **39%** | **49%** | 18% |
| CoT | 39% | 18% | 32% |
| **ReAct agent** | **35%** | **6%** | **66%** |

**The agent that is most honest is the least accurate**, and the gap is only 4 points of
correctness for an 8× reduction in hallucination.

**Our scoring has no abstention category.** A run either names a container or it does not, and
"unknown" scores the same as a confident wrong answer. **These are not the same failure**, and
after this week's work we know our harness produces both: the `out_of_steps` and `late_findings`
health rows in `run_digest.py` exist because 98 workers recorded nothing. **Two cheap additions:**

- Count how often our agent **declines** versus **asserts wrongly**. We have the data.
- Report them separately. A 27/30 with 3 abstentions is a different result from 27/30 with 3
  confident errors, and right now we cannot tell them apart.

### 4. Their framing of why an agent is needed is the best in the pack

*"Each troubleshooting step yields previously unknown information, helping the OCE narrow down the
set of plausible root causes."* That is the argument for an **agent with tools** over a
**classifier on a fixed feature vector**, and it is why our harness looks the way it does. **Cite
this, not our own reasoning.**

### 5. A caution on metrics that applies directly to us

They found **automatic lexical metrics rewarded predictions that merely restate the incident**,
and that semantic similarity varied by **under 1 point across every model**. So they **hand-labelled
97 predictions**. Our WHERE axis is exact-match against a container name, which is much harder to
game than free-text similarity — **but our fault-label axis is a string match against
`FAULT_TYPES`**, and a plausible-but-generic answer is exactly what their "Other" category (32-45%
of baseline errors) captures. **Worth a manual read of a sample of our judgements** rather than
trusting the scorer alone.

### Scope

**Real incidents, text and team databases, no injected ground truth, no telemetry of the kind we
use.** Their 35-39% correctness is on **free-text root-cause prediction for arbitrary Azure
incidents**. **Not comparable to our numbers in any direction.**

---

## 8. Safe claims

- Prior LLM approaches to incident RCA **cannot dynamically collect diagnostic information**;
  RCACopilot needs **hand-engineered handlers**, and other work uses only the incident title and
  description.
- *"Each troubleshooting step yields previously unknown information"* — collecting additional
  diagnostic information is the key aspect of RCA. A veteran engineer *"might need to spend several
  years on a team"* before performing RCA effectively on its services.
- Evaluation: **100 real incidents**, 500 in the retrieval corpus, **no fine-tuning**, against
  retrieval, chain-of-thought, IR-CoT and ReAct variants, scored by lexical and semantic metrics
  **plus manual labelling of 97 predictions**.
- **Manual correctness: RB (k=10) 39%, CoT 39%, ReAct-BM25 35%.**
- **Hallucination among correct predictions: 26% (RB), <1% (CoT), 0% (ReAct).** Among incorrect
  predictions: **49% (RB), 18% (CoT), 6% (ReAct).**
- **66% of ReAct's incorrect predictions cite insufficient evidence**, against 32% (CoT) and 18%
  (RB).
- **28 of 97 examples were solved by all three** models. ReAct uniquely solved 4, in every case by
  **filtering out lexically similar but semantically different historical incidents**.
- ReAct made **more reasoning errors** than CoT (10 vs 2) and had **difficulty maintaining prompt
  format over long trajectories**. Its retrieval tool is **stateless**, causing duplicate
  retrievals.
- **32% of RB errors and 45% of CoT errors had no clear cause**; many were **too generic**.
- Automatic metrics were unreliable: **predictions that restate the incident score well**, and
  semantic similarity varied by **under 1 point across all models**.
- Adding **historical discussion comments** gave **mixed results**.
- In the deployment: a **Database Query Tool** split into query engine plus Pandas, a **KBA Q/A
  tool over 14 documents**, a **KBA Planning Tool** variant added because of *"eager interleaving
  of thoughts and actions"*, and a **human-in-the-loop** feedback channel.
- **Surfacing error messages as observations let the agent consistently rectify failed queries.**
- The agent **succeeded** on a simple incident with a single clear KBA, **with no prior knowledge
  of the domain or the query language**; it **failed** on a variant needing an extra filtering
  step, and on **multi-KBA incidents**, where it executed *"only one or two diagnostic steps
  before reaching the iteration limit (20)"*.
- Engineers said the multi-KBA incidents require **at least a year of experience** with the team's
  services.

## 9. Do NOT claim

- That 35-39% correctness is comparable to ours. It is **free-text root-cause prediction on
  arbitrary real Azure incidents**, hand-labelled, with no injected ground truth.
- That ReAct is worse. It is **4 points less correct and 8× less likely to hallucinate** — the
  authors present this as a trade-off, not a ranking.
- That the agent works on hard incidents. **It failed on every multi-KBA case**, and on a
  one-extra-filtering-step variant of a case it otherwise solved.
- That automatic metrics validated anything here. The authors say they are unreliable for this
  task and hand-labelled instead.

## 10. Reusable ideas

- **Separate "wrong" from "did not know".** Their Table 3 splits incorrect predictions into
  hallucination, insufficient evidence, reasoning error, retrieval error and other. **Our scoring
  has one bucket for all of these.**
- **Hand-label a sample.** Automatic metrics rewarded restating the question; only manual coding
  revealed the hallucination gap.
- **Surface tool errors as observations.** Confirmed twice now — here and in our own harness.
- **Make retrieval stateful.** A tool that re-returns what it already gave wastes the step budget
  that the hard cases need.
- **Add an explicit planning step** when eager thought/action interleaving misfires. Their KBA
  Planning Tool is the same instinct as our plan node.
- **Report where the iteration limit bites.** "One or two diagnostic steps before hitting 20" says
  far more than an average step count.
