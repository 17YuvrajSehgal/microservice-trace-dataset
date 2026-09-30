# Paper Context: Nissist — An Incident Mitigation Copilot based on Troubleshooting Guides (2024)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is a **short 4-page paper** (arXiv, marked "work in progress"). It is one of the
> closest neighbours to our blueprint idea: written troubleshooting knowledge, turned into
> structured units, executed by an LLM agent. Read section 9 before citing the numbers -
> they come from a 20-person user study, not a benchmark.

---

## 1. Bibliographic info

- **Title:** Nissist: An Incident Mitigation Copilot based on Troubleshooting Guides
- **Authors:** Kaikai An, Fangkai Yang, Junting Lu, Liqun Li, Zhixing Ren, Hao Huang,
  Lu Wang, Pu Zhao, Lingling Zheng, Yu Kang, Hua Ding, Qingwei Lin, Saravan Rajmohan,
  Dongmei Zhang, Qi Zhang
- **Affiliations:** Peking University (first authors, during Microsoft internship) + Microsoft
- **arXiv:** 2402.17531v2 [cs.SE], 10 May 2024
- **Length:** 4 pages including references
- **Status in the paper:** "Work in progress, code will be released later"
- **Demo:** https://aka.ms/nissist_demo

```bibtex
@article{an2024nissist,
  title  = {Nissist: An Incident Mitigation Copilot based on Troubleshooting Guides},
  author = {An, Kaikai and Yang, Fangkai and Lu, Junting and Li, Liqun and others},
  journal = {arXiv preprint arXiv:2402.17531},
  year   = {2024}
}
```

---

## 2. One-paragraph summary

Microsoft on-call engineers (OCEs) write down how to fix incidents in **Troubleshooting Guides
(TSGs)**. TSGs work, but they are messy - unstructured, uneven, sometimes out of date. Nissist
uses an LLM to convert those messy guides into a **knowledge base of small executable nodes**,
then uses a **multi-agent system** to read an engineer's question, pick the right nodes, and
propose the next action. Some actions run automatically; the rest go to the engineer. It also
pulls knowledge from **past incident conversations**, not only from TSGs. In a study with 20
engineers and 5 incidents, time-to-mitigate dropped by 98.9% on simple incidents and 94.9% on
hard ones.

---

## 3. Problem and motivation

- High-severity incidents need a human. Automated pipelines only handle the easy, frequent ones.
- TSGs help, but are **unstructured**, vary in quantity, and are written for internal use.
- Some TSGs are **out of date** and miss the newest fix.
- This hits **new hires** hardest, and gets worse when an incident spans several teams.

### The measurement that motivates the paper

They analysed **~1,000 high-severity incidents over 12 months**. Incidents that had a TSG had a
**60% shorter average time-to-mitigate (TTM)** than incidents without one.

That is the number worth remembering: **written procedure cuts TTM by 60%**, before any
automation is added.

### Why prior work is not enough

- One line of work fine-tunes models to extract TSG knowledge - but unstructured TSGs limit
  how well fine-tuning works.
- Another line finds the *relevant TSG* during root cause analysis - but complex incidents
  still need a human.

---

## 4. Core idea: a TSG becomes a graph of nodes

**Step 1 - reformat.** Use an LLM plus quality criteria to rewrite an unstructured TSG into a
structured one with fixed parts: **background, terminology, FAQ, flow, appendix**. "Flow" is
the sequence of steps.

**Step 2 - split into nodes.** Each node is JSON with four fields:

| Field | Meaning |
|---|---|
| `type` | what kind of node it is |
| `intent` | what this node is *for*. Used as the retrieval index |
| `action` | what to do (often a code block, e.g. a Kusto query with placeholders) |
| `linker` | maps the **outcome** of the action to the **intent** of the next node |

**Why nodes rather than chunks.** Ordinary retrieval chunks a document. That breaks the step
sequence, and steps for one incident are often spread across several TSGs. Node granularity
also lets Nissist **discover links between different TSGs** that no single TSG contains - what
the paper calls a cross-TSG flow.

**`linker` is the interesting part.** It is what turns a document into something executable:
the result of step N chooses step N+1.

---

## 5. The multi-agent system

| Agent | Job |
|---|---|
| **Intent Interpreter** | work out what the engineer wants; decide whether Nissist should act at all; ask for clarification if needed |
| **Node Retriever** | retrieve top-k nodes by comparing the clarified intent against each node's indexed `intent` (not against document text) |
| **Node Selector** | pick the most relevant of those k. Needed because keywords can match while meaning does not. If nothing fits, it says the incident is out of scope and hands back to the engineer |
| **Action Planner** | the central component. Proposes the next action from the selected nodes plus memory |
| **Post Processor** | corrects the plan using a **fine-tuned LLaMA2** expert model trained on Microsoft Cloud documentation |

### Two design choices they argue for explicitly

**1. Semi-automated, not fully automated.** They say the usual interleaved reason-act-observe
style (ReAct and similar) is **unsuitable here**. Fully automatic tools cannot handle every
incident; the risk is calling the wrong plugin or skipping a step. So actions the execution
engine cannot run are handed to a human. They give **security** as a reason.

**2. A fine-tuned expert model instead of self-reflection.** Self-reflection works in open
domains. Here a general model (they name GPT-4) lacks domain knowledge and can hallucinate, so
corrections come from a LLaMA2 fine-tuned on Microsoft Cloud docs.

---

## 6. How a session runs (Figure 1)

1. Offline: build the knowledge base from unstructured TSGs + incident mitigation history.
2. Engineer asks a question.
3. Nissist clarifies the intent, retrieves and selects nodes, plans an action.
4. If the execution engine can run it (plugin, API, or LLM code generator) it runs, and the
   **result feeds the next round automatically**.
5. If not, the engineer runs it by hand.
6. Repeat until mitigated.

---

## 7. Worked example (Figure 2)

Query: *"Service A to Service B connection is lost."*

1. Clarify intent → retrieve a node whose action is a Kusto query → run it → outcome: "network
   monitor values are mostly zeros in the last 30 minutes".
2. The node's `linker` says consistent zeros means a genuine problem, so check other clusters.
   Nissist generates the next intent **by itself**.
3. Incident count > 1 → check TCP connectivity of all virtual IP endpoints.
   - Branch 3b uses a node **from a different TSG**, which an engineer would previously have
     had to hunt for, since such knowledge is rarely in a TSG title.

---

## 8. Evaluation

- **20 OCEs**, mixed new-hire and experienced.
- **5 incidents**, labelled simple or hard from their mitigation history. Simple does **not**
  mean automatable - these all needed a human.
- Each OCE did all five. Each incident was assigned one approach, Nissist or manual, balanced
  so each incident got equal numbers of both.
- Each session kept to 30-60 minutes per OCE.

| Metric | Meaning |
|---|---|
| SR | success rate - mitigated with no human intervention |
| IR | share of steps needing human intervention |
| Turns | number of mitigation turns |
| TTM ↓ | time-to-mitigate reduction vs manual |

### Results (Table 1)

| Category | SR | IR | Turns | TTM ↓ |
|---|---|---|---|---|
| Simple | 77.19% | 11.28% | 2.56 | **98.93%** |
| Hard | 52.63% | 15.79% | 5.74 | **94.85%** |

Hard incidents need more than twice as many turns, as expected.

---

## 9. Limits — read before citing the numbers

1. **4-page work-in-progress paper.** No code released at the time of writing.
2. **5 incidents.** The TTM reductions come from a very small incident set.
3. **No ablation.** We cannot tell how much comes from the structured nodes, how much from the
   multi-agent design, and how much from the fine-tuned expert model.
4. **TTM ↓ of 98.93% is against manual mitigation by a human reading unstructured TSGs.**
   That is the honest framing. It is not a comparison against another automated system.
5. **No baseline system.** No comparison to plain RAG, to AutoTSG, or to a single-agent ReAct
   loop - even though the paper argues against the ReAct style.
6. The knowledge base quality depends on the LLM reformatting step, which is not evaluated
   separately.
7. Everything is internal to Microsoft: private TSGs, private incidents, private platform. Not
   reproducible outside.

---

## 10. What this means for our work

**This is a close neighbour, and a useful contrast.**

| | Nissist | Our blueprints |
|---|---|---|
| Knowledge source | existing human-written TSGs, reformatted by an LLM | written from measurement on our own data |
| Unit | node = intent + action + linker | blueprint = discriminators + rule-outs + stopping conditions |
| Data the agent sees | Kusto queries over cloud telemetry | raw kernel traces |
| Execution | semi-automatic; humans do what plugins cannot | fully automatic, read-only tools |
| Evidence | 20-person user study, 5 incidents | 60-cell matrix per problem, with a no-blueprint control |

**The gap we fill.** Nissist, like every paper in this group, works from logs, metrics and
queries. **None of them works from kernel traces.** That is the sentence our related-work
section needs, and this paper is part of the evidence for it.

**Two ideas worth stealing.**

- **`linker`: outcome → next intent.** Our blueprints have "stop and switch" conditions, but
  they are prose. Nissist makes the branch a field. That is a cleaner encoding of the same
  idea and it is machine-readable.
- **Retrieve on `intent`, not on document text.** Indexing what a step is *for*, rather than
  what it says, is why their retrieval survives the vocabulary mismatch between a question and
  a procedure.

**One claim of theirs that supports ours.** The 60% TTM gap between incidents with and without
a TSG is independent evidence that **written procedure helps** - measured on ~1,000 real
incidents, not on a benchmark. That is a better motivating citation than their own TTM numbers.

**One design point where we deliberately differ.** They reject the ReAct-style loop as unsafe
for mitigation, because actions change production. Our agent only *reads* traces, so that
argument does not apply to us, and we do use an autonomous loop.

---

## 11. Safe claims

- Microsoft maintains TSGs for incident mitigation; incidents with a TSG had **60% shorter
  average TTM** across ~1,000 high-severity incidents over 12 months.
- Nissist converts unstructured TSGs into a knowledge base of executable nodes
  (intent / action / linker) using LLMs.
- It uses a multi-agent design: intent interpretation, node retrieval, node selection, action
  planning, post-processing by a domain fine-tuned model.
- Node granularity lets it combine steps from different TSGs into one flow.
- In a 20-engineer study on 5 incidents it reported 98.93% (simple) and 94.85% (hard) TTM
  reduction, with 77.19% and 52.63% full automation.
- The authors argue a fully automated ReAct-style loop is unsuitable for incident mitigation.

## 12. Do NOT claim

- That Nissist was benchmarked. It was not - it was a user study on five incidents.
- That the TTM numbers compare against another tool. They compare against manual work.
- That it works from traces or low-level telemetry. It works from TSGs and Kusto queries.
- Any generalisation beyond Microsoft's internal environment.

## 13. Reusable ideas

- **Reformat before retrieving.** Impose a fixed structure (background / terminology / FAQ /
  flow / appendix) on messy documents first.
- **Node = intent + action + linker.** Small, retrievable, and chainable.
- **Index by purpose, not by text.**
- **Outcome-driven branching** written as data, not prose.
- **Say "out of scope" when nothing matches**, instead of answering anyway - the same discipline
  our blueprints use with "not applicable".
- **Mine past incident conversations** to patch procedures that have gone stale.
