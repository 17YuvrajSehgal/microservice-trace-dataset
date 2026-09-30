# Paper Context: Beyond Fault Localization — A Trajectory-Level Study of LLM Agents for Microservice Root Cause Analysis

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> **This paper is a direct critique of the way we score.** It argues that endpoint correctness —
> "did the agent name the right service" — is exactly our WHERE axis, and that it *"provides no
> indication of the evidentiary basis for a diagnosis"*. It uses **Train Ticket**. §7 works out
> what to do about it.

---

## 1. Bibliographic info

- **Title:** Beyond Fault Localization: A Trajectory-Level Study of LLM Agents for Microservice
  Root Cause Analysis
- **Authors:** Qisheng Lu, Aoyang Fang, Junjielong Xu, Songhan Zhang, Yifan Yang, Xiaochuan Yan,
  **Pinjia He** (CUHK-Shenzhen); Jin'ao Shang (Xi'an Jiaotong University)
- **Status:** preprint (recent; venue not established in the copy we hold)
- Prototype: **DIAGGUARD**

```bibtex
@misc{lu2026beyond,
  title  = {Beyond Fault Localization: A Trajectory-Level Study of {LLM} Agents for Microservice Root Cause Analysis},
  author = {Lu, Qisheng and Fang, Aoyang and Xu, Junjielong and Shang, Jin'ao and Zhang, Songhan and Yang, Yifan and Yan, Xiaochuan and He, Pinjia},
  note   = {preprint}
}
```

---

## 2. One-paragraph summary

Every RCA evaluation scores the same way: **did the method localise the responsible service?**
The authors argue that tells you nothing about **why** the agent believed it, or **how the fault
propagated** — and an on-call engineer needs both before acting. So they **manually annotate
service-level fault-propagation paths** for a public microservice benchmark, build a framework
that normalises heterogeneous agent trajectories against those paths, and analyse **3,500
trajectories across seven framework-model configurations**. The headline: **answer correctness and
diagnostic quality come apart** — an agent can name the right service and still fail to
reconstruct how the fault reached it. They mine a **three-family failure taxonomy** from 154
hand-coded failed trajectories and use it to build **DIAGGUARD**, which raises **Acc@1 from 43.5%
to 52.5%** on a held-out model, dataset and topology.

---

## 3. The argument against endpoint-only scoring

> Existing evaluations ... uniformly assess diagnostic performance by **endpoint correctness**:
> whether a method localizes the responsible service. Although this criterion enables direct
> comparison, **it provides no indication of the evidentiary basis for a diagnosis or the
> propagation route** linking the fault source to the observed symptoms. **Both are necessary for
> an on-call SRE to assess whether an automated diagnosis warrants action.**

Their reframing: **treat RCA as an observable diagnostic process.** Agents leave **trajectories** —
records of what they queried and concluded — and those can be scored, but only against
**process-level ground truth**, which is why they annotate propagation paths by hand.

---

## 4. Method

- **Annotated propagation-path dataset:** manual service-level fault-propagation paths for a
  microservice RCA benchmark. Verified against the **Train Ticket service-call graph**.
- **Trajectory normalisation:** heterogeneous agent runs made comparable. Every SQL action gets an
  **intent label** plus a multi-valued set over **six deterministic tag axes**; **11 intents** in
  total.
- **Metrics:** outcome-level **Acc@1**, plus **Node F1** (did it reach the affected services) and
  **Edge F1** (did it reconstruct the propagation between them), each split by correct/incorrect
  outcome, plus rounds and token budget.
- **Scale:** **3,500 trajectories**, **seven framework-model configurations** (six frameworks under
  one model, one rerun on a second).
- **Failure coding:** two authors open-code failed trajectories into a stabilised codebook, then
  independently code **all 154 failed trajectories (50 Sonnet, 104 Qwen)**. An LLM assists evidence
  retrieval but *"every code is verified by hand against the cited SQL, returned evidence, and the
  TrainTicket service-call graph."*

---

## 5. Findings

### Finding 1 — difficulty is uneven, and edges are harder than nodes

- **Acc@1 falls as the causal chain deepens.** Every Qwen framework loses ground from depth 2
  onward (one arm drops to **42.9%**); on a matched pair, **Qwen falls 85.5% → 57.1%** across
  depth while **Sonnet holds flat at 85.7-96.8%**.
- **Edge F1 trails Node F1 by a wide margin across every row**, and **never exceeds 0.67**.
  Best row: Sonnet + ThinkDepth.ai, **Acc@1 90.0%, Node F1 0.79, Edge F1 0.64**.
- **Reconstructing how a fault propagates is harder than identifying which services it reaches**,
  even when the source is localised correctly.
- The **top band of frameworks spans only 2.0 pp** under the same model — i.e. **the model matters
  more than the framework**; the Sonnet arm gains **10.8 pp** over Qwen.

### Finding 2 — success and failure are properties of the process

- **Successful runs stay on the fault-impact surface and act on the evidence they retrieve**, and
  **the breadth of their intent repertoire sets how deep the search reaches**.
- **Failing runs drift off the surface, leave decisive evidence unused, or circle in shallow
  loops.** Qwen in particular *"perseverates in shallow loops over a limited slice of the
  evidence."*

### Finding 3 — the failure taxonomy

Three families, by how the agent relates to decisive evidence:

| Family | Meaning |
|---|---|
| **OMIT — protocol omission** | **evidence reachable in telemetry but never queried** |
| **MIS — semantic misread** | retrieved evidence **misinterpreted or scoped to the wrong dependency** |
| **GEN — general reasoning** | a reasoning failure not tied to a single evidence unit |

Their GEN sub-modes are specific and recognisable:

- **GEN1** — cannot aggregate scattered evidence or drill deep enough to discard distractors, so
  **locks onto an early anchor**.
- **GEN2** — overconfident, **fabricates an out-of-schema cause**.
- **GEN3** — **abandons an evidence channel** after a failed or empty query rather than retrying.

**The two models fail differently:** **Qwen predominantly by omission**, staying on the most
superficial signals and rarely redirecting; **Sonnet predominantly by misreading**, hypothesising
well but hallucinating (GEN2) and failing to pin down the crux among contradictory signals
(MIS2, MIS3).

> **Agent failures reduce to three evidence-handling modes: decisive evidence is never gathered,
> is gathered but misread, or is overridden by ungrounded reasoning.**

### The intervention

**DIAGGUARD** wraps the agent in a **Grounder** (grounding defence) and a **Verifier**
(verification defence), each closing specific failure modes from the taxonomy. On a **held-out
model, dataset and service topology**, it raises **Acc@1 from 43.5% to 52.5%**, confirming the
mined modes transfer.

---

## 6. What kind of paper this is

- An **evaluation-methodology paper** plus an empirical study and a small intervention.
- Works on a **public microservice RCA benchmark** with **SQL-queryable telemetry**; verified
  against the **Train Ticket** service-call graph.
- **No kernel traces, no fault injection of its own** — it studies agents on an existing benchmark.

---

## 7. What this means for our work

**This is the most pointed critique of our evaluation in the whole reference set, and it lands.**
Our WHERE axis is exactly the endpoint correctness they object to: the agent names a container, we
check it against ground truth. **Their argument is that a correct name with no evidentiary basis is
not actionable**, and they have 3,500 trajectories showing the two come apart.

**We are partly defended and should say how.** Our scoring is not purely endpoint:

| | Our axis | What it captures |
|---|---|---|
| WHERE | `named` / `container` / `container_wrong` / `container_unverified` / `scope` / `wrong` | **more than binary** — `container_unverified` is close to their point |
| Window IoU | overlap with the injected window | **when**, which they do not score |
| Fault label | family name | **what** |
| Earliness | gated on IoU | how fast |

**But we score no propagation and no evidence chain**, which are their two central claims. And
`container_unverified` exists precisely because we noticed the gap between "said the right thing"
and "showed why" — we just did not build the second half out.

**Three things to do, in increasing cost:**

1. **Cheap and immediate.** We already log every `run_python` result to the scratchpad. **Check
   whether the winning container appears in the evidence the worker actually retrieved**, not just
   in the conclusion. That is a weak Node-F1 analogue and it is a string check.
2. **Worth doing before the campaign.** Their **three failure families are directly measurable in
   our logs**, and we have seen all three:
   - **OMIT** — our `out_of_steps` and `late_findings` health rows are omission.
   - **MIS** — scoping to the wrong `pid_ns` is the container-level version of "wrong
     dependency".
   - **GEN3** — *"abandons an evidence channel after a failed or empty query"* is **exactly** the
     `ctf_lines` silent-empty bug we fixed. The tool returned nothing, the worker moved on.
     **Their taxonomy names the failure our fix addressed.**
3. **The expensive one.** Annotating propagation paths for our faults. **Our faults mostly do not
   propagate across services** — a CPU cap on one container is local — so the Edge-F1 concept
   partly does not apply. **That is a legitimate difference worth stating**, not a gap: their
   benchmark's faults cascade, ours are mostly contained, and `dependency-outage-retry-storm` is
   the one family where a propagation path would be meaningful.

**Their Finding 1 is a warning about our headline numbers.** **Acc@1 falls as the causal chain
deepens** — 85.5% → 57.1% for one model. Our best results (`deadlock` 30/30) are on faults with a
**short causal chain**: inject in one container, observe in that container. **A reviewer will ask
whether the result holds for deeper chains, and we should answer before being asked.**

**Finding: the model matters more than the framework.** The top frameworks span **2.0 pp** under
one model; swapping the model gains **10.8 pp**. That is worth knowing before we invest further in
harness engineering — though it cuts against [[self-evolving-rca-harness]], which argues the
opposite. **Two recent papers disagree on this and we should note the disagreement rather than
pick a side.**

**And one methodological idea to steal outright.** **Hand-code the failures into a stabilised
codebook, independently, with agreement reported.** They did 154 failed trajectories with two
coders. We have 60 cells from the last two matrices and a `run_digest.py` that reports health
rows but not failure *kinds*. **A single afternoon of coding our failures against their
OMIT/MIS/GEN taxonomy would tell us what to fix next**, and the taxonomy is already validated.

---

## 8. Safe claims

- Existing RCA evaluations assess **endpoint correctness** only, which *"provides no indication of
  the evidentiary basis for a diagnosis or the propagation route"* — both needed before an SRE can
  act.
- They **manually annotate service-level fault propagation paths** for a microservice RCA
  benchmark, verified against the **Train Ticket service-call graph**, and normalise trajectories
  with **11 intents** over **six deterministic tag axes**.
- **3,500 trajectories across seven framework-model configurations.**
- **Edge F1 trails Node F1 by a wide margin in every configuration and never exceeds 0.67** —
  reconstructing propagation is harder than identifying affected services, **even when the source
  is correctly localised**.
- **Acc@1 falls as the causal chain deepens**: one Qwen arm drops to **42.9%**, and a matched pair
  shows **Qwen 85.5% → 57.1%** across depth while **Sonnet holds at 85.7-96.8%**.
- **The top band of frameworks spans only 2.0 pp under the same model**, while the model swap
  gains **10.8 pp**. Best row: **Sonnet + ThinkDepth.ai, Acc@1 90.0%**.
- **Successful runs stay on the fault-impact surface and act on retrieved evidence**; failing runs
  **drift off-surface, leave decisive evidence unused, or circle in shallow loops**.
- **Three failure families: OMIT** (evidence reachable but never queried), **MIS** (retrieved
  evidence misinterpreted or scoped to the wrong dependency), **GEN** (reasoning failure untied to
  a single evidence unit) — with GEN1 early anchoring, **GEN2 fabricating an out-of-schema cause**,
  **GEN3 abandoning a channel after a failed or empty query**.
- **Qwen fails predominantly by omission, Sonnet by misreading.**
- **154 failed trajectories hand-coded by two authors** (50 Sonnet, 104 Qwen) against a stabilised
  codebook, verified by hand against SQL, returned evidence and the service-call graph.
- **DIAGGUARD** (Grounder + Verifier) raises **Acc@1 from 43.5% to 52.5%** on a **held-out model,
  dataset and service topology**.

## 9. Do NOT claim

- That its Acc@1 numbers are comparable to ours. **Different benchmark, SQL-queryable telemetry,
  different fault set**, and their faults propagate across services where most of ours do not.
- That 90.0% is a general result. It is **one model + one framework**, and the same table shows
  42.9% at depth for another.
- That trajectory evaluation is settled. This is a **preprint proposing a framework**, with
  hand-annotated ground truth for one benchmark.
- That "the framework does not matter" is established. Their 2.0 pp spread is **within one model
  on one benchmark**, and OpsHarness argues the opposite.

## 10. Reusable ideas

- **Score the process, not only the answer.** Node F1 and Edge F1 against an annotated propagation
  path is the concrete version of that, and their Edge-F1 ceiling of 0.67 shows it measures
  something the answer does not.
- **Stratify accuracy by causal depth.** A single Acc@1 hides an 85% → 57% collapse.
- **Hand-code the failures into a stabilised codebook.** OMIT / MIS / GEN is a ready-made taxonomy,
  validated on 154 trajectories, that our logs can be coded against directly.
- **Derive the intervention from the failure modes.** DIAGGUARD's Grounder and Verifier each close
  a specific mined mode; the 43.5% → 52.5% gain on held-out data is what validates the taxonomy.
- **"Abandons an evidence channel after a failed or empty query" is a named failure mode.** Every
  tool we ship should make an empty result distinguishable from a nothing-to-see result.
