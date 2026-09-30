# Paper Context: Automatic Root Cause Analysis via Large Language Models for Cloud Incidents (RCACopilot, EuroSys 2024)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited in our pack as part of the TSG/LLM-agent related work. **Its ablation contains a result
> that runs against a change we made this week** — more context made their accuracy worse, and
> summarised beat raw. §7 works out whether that contradicts our reply-cap increase. (It does
> not, but the reason matters.)

---

## 1. Bibliographic info

- **Title:** Automatic Root Cause Analysis via Large Language Models for Cloud Incidents
- **Authors:** Yinfang Chen, Huaibing Xie, **Minghua Ma** (corresponding), Yu Kang, Xin Gao,
  Liu Shi, Yunjie Cao, Xuedong Gao, Hao Fan, Ming Wen, Jun Zeng, Supriyo Ghosh, Xuchao Zhang,
  Chaoyun Zhang, Qingwei Lin, Saravan Rajmohan, Dongmei Zhang, Tianyin Xu
  (Microsoft; UIUC; Peking University; HUST; NUS)
- **Venue:** **EuroSys 2024**, 22-25 April, Athens
- **System name:** RCACopilot

```bibtex
@inproceedings{chen2024automatic,
  title     = {Automatic Root Cause Analysis via Large Language Models for Cloud Incidents},
  author    = {Chen, Yinfang and Xie, Huaibing and Ma, Minghua and Kang, Yu and others},
  booktitle = {EuroSys '24}, year = {2024}
}
```

Same core authors as [[aiopslab-2025]] and [[roy-2024-llm-agents-rca]].

---

## 2. One-paragraph summary

An **on-call system deployed at Microsoft**. When an incident arrives, RCACopilot matches it to an
**incident handler** — a hand-built, decision-tree-shaped workflow keyed to the alert type — which
**automatically collects diagnostic data from many sources**. An LLM then **summarises** that data,
retrieves similar historical incidents, and **predicts the root-cause category with an explanatory
narrative**. Evaluated on **a year of real Microsoft incidents (653)**, it reaches **micro-F1
0.766, macro-F1 0.533**, against baselines that score between **0.022 and 0.257**. The diagnostic
collection component **has been in production at Microsoft for over four years**.

---

## 3. The problem they are solving

Their framing of why on-call engineers struggle:

- Traditional RCA means manually going through **logs, traces and incident tickets**.
- Engineers face **both** problems at once: drowning in data (*"identifying relevant information
  amidst the sea of data"*) **and** lacking the information they need.
- **Troubleshooting guides fall short when new incident types emerge.**
- The core difficulty is *"efficiently collecting and interpreting comprehensive,
  incident-specific data within a limited time frame."*

**The number that justifies the whole design:** **incidents with a new root-cause category are
24.96% — 163 of 653.** A quarter of incidents are of a kind nobody has seen before, so any
approach based on matching known categories fails on one incident in four.

They also criticise prior LLM work for predicting root cause *"just by leveraging the title and
summary information available at the time of incident creation"* — i.e. before any diagnosis has
happened.

---

## 4. Design

**Incident handler** — the key artefact:

- A **workflow keyed to an alert type**, built to mirror *"the decision-making process that OCEs
  employ when handling an incident [which] resembles a decision tree's control flow."*
- **Constructed manually first**, then updated and modified dynamically. **Versioned.**
- Actions are designed to be **reusable across handlers**.
- Actions automatically collect diagnostic information from **diverse sources**.

**Then the LLM**: summarises the collected diagnostics, retrieves similar historical incidents as
in-context demonstrations, predicts the **root cause category**, and writes an explanation.

They are candid that **handlers do not always give an exact mitigation** — being pre-defined, they
cannot cover every situation — and in that case the handler **offers intermediate information**
instead.

---

## 5. Results

**Dataset: a year's worth of real incidents from Microsoft, 653 total**, with a **long-tailed,
imbalanced** category distribution.

| Method | Micro-F1 | Macro-F1 | Train (s) | Infer (s) |
|---|---|---|---|---|
| **RCACopilot (GPT-4)** | **0.766** | **0.533** | 10.562 | **4.205** |
| RCACopilot (GPT-3.5) | 0.761 | 0.505 | 10.562 | 4.221 |
| GPT-4 Embed. | 0.257 | 0.122 | 1925 | 3.522 |
| Fine-tuned GPT | 0.103 | 0.144 | **3192** | 4.262 |
| FastText | 0.076 | 0.004 | 10.592 | 0.524 |
| GPT-4 Prompt (no history) | **0.026** | 0.004 | — | 3.251 |
| XGBoost | **0.022** | 0.009 | 11.581 | 1.211 |

Their explanation for why the baselines collapse: the category distribution is **long-tailed**, so
FastText, XGBoost and fine-tuning **need large amounts of training data**; and plain GPT-4
prompting or embedding **lacks the domain-specific knowledge** to decide.

**Total overhead 4.205 s** at inference.

### The ablation — this is the part that matters to us

Table 3, varying which context goes into the prompt:

| AlertInfo | DiagnosticInfo | ActionOutput | Micro-F1 | Macro-F1 |
|---|---|---|---|---|
| | **✓ summarised** | | **0.766** | **0.533** |
| | ✓ (raw) | | 0.689 | 0.510 |
| ✓ | | | 0.379 | 0.245 |
| | | ✓ | 0.431 | 0.247 |
| ✓ | ✓ | | 0.525 | 0.511 |
| | ✓ | ✓ | 0.501 | 0.449 |
| **✓** | **✓** | **✓** | **0.440** | 0.349 |

Two findings, both stated by the authors:

1. **Summarised diagnostic information alone beats every other configuration** — 0.766 vs 0.689
   for the same information raw.
2. **All three sources together (0.440) is worse than diagnostic info alone (0.766).**
   *"This demonstrates that **an excess of information can negatively impact the LLM's prediction
   performance**."*

They also report stability: **micro-F1 consistently above 0.70 and macro-F1 above 0.50** across
their parameter sweeps (K and alpha for historical-incident retrieval).

---

## 6. What kind of paper this is

- A **deployed industrial system** evaluated on **real incidents**, not injected faults.
- The task is **root-cause category classification plus an explanation**, not localisation to a
  service.
- Inputs are **incident tickets and whatever the handler collects** — logs, metrics, queries. **No
  traces at the kernel level, no fault injection, no ground-truth window.**
- **Requires hand-built handlers per alert type.**

---

## 7. What this means for our work

**Our pack's use of it is fine — it is related work on LLM-driven RCA.** Two things in it are
worth more than that.

### The ablation, and whether it contradicts what we did this week

**It looks like it does, and it does not.** We raised `SENT_CAP_BY_TOOL["ctf_lines"]` from 25,000
to 42,000 and `THREAD_BUDGET` from 80,000 to 150,000, on the finding that **truncation was causing
wrong conclusions** — three "kernel traces can't do this" results turned out to be our own reply
cap. RCACopilot found that **more context made accuracy worse**.

These are different claims and both are true:

| | RCACopilot's finding | Ours |
|---|---|---|
| What was added | **more sources** — alert text, action output, on top of diagnostics | **more of the same source**, un-truncated |
| What it did | diluted a working signal with weakly relevant text | restored evidence that was being **silently cut** |
| Their winner | **summarised** diagnostics (0.766) over raw (0.689) | raw computation output, shown verbatim |

**The reconcilable lesson is theirs, not ours: summarise, don't just widen.** Their best
configuration is **one source, summarised** — 0.766 against 0.440 for everything at once. Our
scratchpad fix already moves that way (capture every `run_python` result and show it under its own
heading), but **we show it raw**. Their 0.766-vs-0.689 gap says a summarisation pass over tool
output might buy accuracy at lower token cost. **That is a cheap experiment worth running before
the full campaign**, and it is the kind of thing that would otherwise only surface after we had
spent the runs.

**The honest caveat:** their inputs are incident tickets and query results — prose. Ours are
numeric tables from `run_python`. **Summarising a number loses it**, which is exactly the failure
we fixed. So the experiment is "summarise the narrative parts, keep the numbers verbatim", not
"summarise everything".

### The 24.96% unseen-category number

**A quarter of Microsoft's incidents have a root-cause category never seen before.** That is a
strong argument against any approach that classifies into a fixed label set — and **our fault-type
axis is exactly a fixed label set** (`FAULT_TYPES`). We already learned this the hard way:
`fault_ok` scored 0/60 because `conn_pool_exhaustion` was missing from the list. **RCACopilot's
number says that problem is structural in production, not an artefact of our dataset.**

It also bounds a claim. Our dataset has **24 known families with ground truth**. Real incidents
are **25% novel**. So a result on our benchmark is a result on *the closed-set case*, and we
should say so rather than let it read as a general RCA claim.

### What their design has that ours does not

Their **incident handler** is a hand-built, versioned, reusable decision-tree workflow per alert
type. **That is a blueprint.** The differences are instructive:

| | RCACopilot handler | Our blueprint |
|---|---|---|
| Built by | on-call engineers, from expertise | **measurement on our own data** |
| Keyed to | **alert type** (known in advance) | fault family |
| Updated | **dynamically, versioned** | git, manually |
| Output | collected diagnostics + category | a decision with evidence |

**Their handlers are keyed to the alert**, which means they know what kind of problem it is before
they start. **We do not** — the agent gets a trace and has to choose which blueprint applies.
That is a harder starting position and worth stating.

**"Versioned handlers, updated dynamically" is worth stealing.** Our blueprints are git-versioned
but there is no mechanism for updating one from a run's outcome.

### A caution on comparing numbers

**Micro-F1 0.766 is category classification on real incidents with a long-tailed distribution.**
Our scores are exact-match on a balanced, injected 24-family set. **Not comparable**, in either
direction, and the long tail is the reason their macro-F1 (0.533) is so much lower than their
micro (0.766) — worth noting because **our per-family reporting is closer to macro than micro**.

---

## 8. Safe claims

- RCACopilot matches an incident to a **hand-built incident handler** keyed to the alert type,
  collects diagnostics automatically, summarises them with an LLM, retrieves similar historical
  incidents, and predicts a **root-cause category with an explanation**.
- Handlers mirror *"the decision-making process that OCEs employ ... [which] resembles a decision
  tree's control flow"*, are **built manually first**, **versioned**, **updated dynamically**, and
  have **reusable actions**.
- Evaluated on **a year of real Microsoft incidents, 653 total**, with a **long-tailed** category
  distribution.
- **Micro-F1 0.766, macro-F1 0.533** with GPT-4 (0.761 / 0.505 with GPT-3.5). Inference overhead
  **4.205 s**.
- Baselines: **GPT-4 Embed 0.257, fine-tuned GPT 0.103, FastText 0.076, GPT-4 Prompt 0.026,
  XGBoost 0.022** micro-F1. Fine-tuning needed **3,192 s** of training.
- **Incidents with a new root-cause category are 24.96% — 163 of 653.**
- **Ablation: summarised diagnostic information alone scores highest (0.766)**, beating the same
  information raw (0.689) and beating all three sources combined (0.440). The authors conclude
  *"an excess of information can negatively impact the LLM's prediction performance."*
- Handlers **do not always give an exact mitigation** and fall back to offering intermediate
  information.
- **The diagnostic information collection component has been in use at Microsoft for over four
  years.**

## 9. Do NOT claim

- That it localises a fault to a service. It **classifies a root-cause category** and writes an
  explanation.
- That its F1 scores are comparable to our accuracy. **Real long-tailed incidents vs a balanced
  injected benchmark**, different task, different metric.
- That it works without human effort. **Incident handlers are hand-built per alert type.**
- That "more context hurts" is a general law. Their result is about **adding weakly-relevant
  sources**; they also show **summarising helps over raw**, which is a different axis.
- That it uses traces or kernel data. It uses incident tickets and whatever the handler queries.

## 10. Reusable ideas

- **Summarise, don't just widen.** Their best configuration is one source, summarised. Worth
  testing on our tool output — for the narrative parts, keeping numbers verbatim.
- **Report the fraction of genuinely novel cases.** 24.96% unseen categories is the number that
  justifies their design and bounds ours.
- **Version the handlers and update them dynamically.** Our blueprints have the first half only.
- **Publish the ablation by data source.** Their Table 3 is the most useful thing in the paper,
  and it only exists because they tried each combination.
- **Report micro and macro F1 separately** when classes are imbalanced. The 0.766 / 0.533 gap is
  the long tail made visible.
