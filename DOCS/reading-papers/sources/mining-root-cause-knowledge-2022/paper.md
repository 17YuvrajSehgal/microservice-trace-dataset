# Paper Context: Mining Root Cause Knowledge from Cloud Service Incident Investigations for AIOps (ICSE-SEIP 2022)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Related work on knowledge extraction for RCA. **Its unexpected value to us is prevalence
> evidence:** its mined clusters from **2,000 Salesforce Sev0/1/2 incidents** name several of our
> fault families by their own vocabulary — connection pools, thread starvation, deadlock, high CPU.
> See §6.

---

## 1. Bibliographic info

- **Title:** Mining Root Cause Knowledge from Cloud Service Incident Investigations for AIOps
- **Authors:** **Amrita Saha**, **Steven C. H. Hoi** (Salesforce Research Asia)
- **Venue:** **ICSE-SEIP 2022**, 21-29 May, Pittsburgh
- **System:** ICA (Incident Causation Analysis)

```bibtex
@inproceedings{saha2022mining,
  title     = {Mining Root Cause Knowledge from Cloud Service Incident Investigations for {AIOps}},
  author    = {Saha, Amrita and Hoi, Steven C. H.},
  booktitle = {ICSE-SEIP 2022}, year = {2022}
}
```

---

## 2. One-paragraph summary

RCA normally uses **error logs and service call traces**. The authors argue *"a rich goldmine of
root cause information is also hidden in the natural language documentation of past incident
investigations by domain experts"* — **Problem Review Board (PRB)** documents. Because PRBs are
raw and unstructured, that knowledge is not reusable. So they build **ICA**, which uses neural NLP
to extract targeted information from PRBs and assemble a **structured Causal Knowledge Graph**,
then use it for **retrieval-based RCA**: given a new incident's symptom, search and rank past
incidents and predict likely root causes. Built at Salesforce over **2,000 documented cloud
service incident investigations**, validated by **domain experts** and by **real incident case
studies after deployment**.

---

## 3. The data

**2,000 PRB records**, all **Sev0/1/2** — *Catastrophic, Critical, ...* severity levels.

Their field statistics (length in non-stopwords, mean ± sd):

| Field | Length |
|---|---|
| PRB **Subject** text | **5.2 ± 2.9** |
| Full **Investigation** document | **309.7 ± 732.2** |
| **Resolution** document | 18.3 ± 24.8 |
| **RCA** document | **110.1 ± 159** |

**The standard deviation on the investigation document (732.2) is more than twice its mean
(309.7)** — these documents vary enormously in length, which is part of why they are hard to mine.

---

## 4. Method

- **Neural information extraction** from each unstructured PRB: topics, summaries, root causes,
  resolutions.
- **Neural knowledge mining** into a **Causal Knowledge Graph** linking **symptom → root cause**
  and **symptom → resolution**. Clustering produced **60 symptom clusters**, visualised by t-SNE
  over node embeddings.
- **Downstream RCA:** an information-retrieval system searches and ranks past incidents; symptoms
  from the top-k results feed the Causal Knowledge Graph to predict top-k likely root causes.
- **Evaluation** by expert annotation, varying the fraction of graph edges used in training (1%,
  2%, 5%, 10%, 20%).

**Human validation of extracted content:**

- **Topics:** 1,320 sampled uniformly from the topic-score distribution, labelled for
  well-formedness, informativeness, clarity, over-genericness, and irrelevant words.
  **Most are well-formed and ~76% are informative and useful.**
- **Summaries:** 525 PRB documents, labelled satisfactorily informative / too specific / too
  generic.

---

## 5. The mined clusters — read these

Their tables of mined symptom, root-cause and resolution phrases include, with cluster weights:

| Phrase cluster | Weight |
|---|---|
| `db nodes, ops sfdc net mq, high cpu` | 7.41 |
| `sandbox service disruption, service failure, edge services` | 7.08 |
| `org migration, intermittent conn pools, service shard, mq sfdc` | 5.89 |
| `a bug in, packet loss latency, db psu` | 6.56 |
| `blocks db lgwr, wait encounters deadlock, async signal safe` | 5.16 |
| `high memory, redo generation, concurrency issue` | 5.5 |
| `message queue processing, refocus test, thread starvation` | 4.89 |
| `on the app, conn pool errors, custom lwc component` | 3.18 |
| `issue self resolved, auto throttle, rebalanced balancing` | 3.31 |
| `self resolved, high db cpu, active session` | 3.05 |
| `conn pool, disabled node, was restarted` | 4.1 |
| `logfile switch, writer process waiting, checkpoint incomplete` | 3.05 |
| `requests sec, bounced broker, restart of` | 2.73 |

---

## 6. What this means for our work

**As related work it is a minor entry** — knowledge extraction from post-mortem prose, no
telemetry, no localisation. **Its real value to us is in §5, and it is prevalence evidence we did
not have.**

Our reference pack records an **honest gap: no peer-reviewed MSR paper focused only on
connection-pool exhaustion**. Zhou 2021's F5 narrowed it. **This narrows it further from a
different direction.** Salesforce's mined clusters over **2,000 Sev0/1/2 incidents** contain
**three separate connection-pool clusters**:

- `org migration, **intermittent conn pools**, service shard, mq sfdc` (5.89)
- `on the app, **conn pool errors**, custom lwc component` (3.18)
- `**conn pool**, disabled node, was restarted` (4.1)

And several other families of ours appear by name:

| Their cluster phrase | Our family |
|---|---|
| **conn pool** (×3 clusters) | `connection-pool-exhaustion` |
| **thread starvation** | `priority-inversion-nice` / `lock-contention-futex-storm` |
| **wait encounters deadlock** | `deadlock-lock-order` |
| **high cpu**, **high db cpu** | `host-cpu-saturation`, `cpu-contention-co-tenant` |
| **high memory** | `service-memory-cap` |
| **packet loss latency** | `network-path-degradation` |
| **auto throttle** | `service-cpu-throttle` |

**Caveat, and it matters:** these are **unsupervised cluster labels over incident prose**, with
weights, not counts of incidents. **Do not quote the weights as frequencies.** What they support
is a weaker but still useful claim: *these fault families appear by name in the post-mortem record
of 2,000 severe production incidents at a major cloud provider.* That is a legitimate "it happens
in the wild" anchor for families where we have little else.

**Two cluster phrases are interesting for a different reason.** `issue self resolved, auto
throttle, rebalanced balancing` and `self resolved, high db cpu, active session` — **"self
resolved" appears in two separate clusters.** Incidents that fix themselves are a real category,
and they are the hardest kind to diagnose after the fact. Our dataset has ground-truth windows so
this cannot happen to us, but it is worth remembering that a substantial share of real incidents
leave a record with no confirmed cause — which is Gunawi's 59% again, from a second source.

**Their framing is also a fair description of what our blueprints are.** *"Root cause knowledge
hidden in the natural language documentation ... not directly reusable by manual or automated
pipelines."* Their answer is to **mine** it; ours is to **measure** it. Same problem, opposite
method, and worth one sentence in related work.

**A number that should temper any mining approach:** **~76% of extracted topics were judged
informative and useful.** That is the ceiling on automated extraction from expert prose, validated
by the experts themselves, and it is well short of what a diagnostic procedure needs.

---

## 7. Safe claims

- RCA normally uses **error logs and service call traces**; **Problem Review Board (PRB)**
  documents hold root-cause knowledge in natural language that is **not directly reusable** because
  it is unstructured.
- Dataset: **2,000 documented cloud service incident investigations at Salesforce**, all
  **Sev0/1/2** (Catastrophic / Critical / ...).
- Field lengths in non-stopwords: **Subject 5.2 ± 2.9**, **Investigation 309.7 ± 732.2**,
  **Resolution 18.3 ± 24.8**, **RCA 110.1 ± 159**.
- **ICA** extracts topics, summaries, root causes and resolutions with neural NLP, and builds a
  **Causal Knowledge Graph** of symptom → root cause and symptom → resolution edges; clustering
  yields **60 symptom clusters**.
- Downstream RCA retrieves and ranks similar past incidents, then predicts top-k root causes
  through the graph. Evaluated with **1%, 2%, 5%, 10%, 20%** of edges in training.
- Human validation: **1,320 topics** sampled and labelled — **most well-formed, ~76% informative
  and useful**; **525 summaries** labelled for informativeness and specificity.
- Validated by **domain experts** and by **real incident case studies after deployment**.
- Mined clusters include phrases naming **conn pool errors (three separate clusters)**, **thread
  starvation**, **deadlock**, **high CPU**, **high memory**, **packet loss latency**, **auto
  throttle**, and **self resolved**.

## 8. Do NOT claim

- That the cluster weights are incident counts or frequencies. They are **cluster weights from
  unsupervised mining over prose**.
- That it performs localisation or uses telemetry. It works entirely from **post-incident
  documentation**.
- That ~76% is an accuracy. It is the share of sampled **topics** judged informative by
  annotators.
- That its root-cause predictions were evaluated end-to-end against ground truth. Evaluation is by
  **expert annotation and case studies**, and the paper describes itself as validating
  **feasibility**.

## 9. Reusable ideas

- **Post-mortem prose is a data source.** Nobody else in our reference set mines it, and it is the
  only record of incidents that produced no usable telemetry.
- **Validate extraction with the experts who wrote the source.** 1,320 topics and 525 summaries,
  hand-labelled, is what makes the pipeline credible.
- **Report the variance, not just the mean.** An investigation document of 309.7 ± 732.2 words
  tells you the corpus is wildly heterogeneous, which is the real engineering problem.
- **Mined vocabulary is free prevalence evidence.** Their cluster phrases name seven of our fault
  families without anyone setting out to study them.
