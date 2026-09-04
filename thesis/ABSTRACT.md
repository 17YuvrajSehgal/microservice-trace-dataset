# Thesis abstract

> **`abstract.tex` is the canonical copy.** This file mirrors it and records the reasoning behind
> the wording. If the two ever disagree, the `.tex` is right.

**Written in the declarative — as if the work is finished**, because this is what gets presented
and defended, not a plan. Nothing here is forward-looking: no "will", "intends", "proposes to",
"future work".

**Still contains no numbers and no findings.** Every sentence about results describes what the
thesis *establishes* or *characterises*, never what it found. Those sentences stay true whichever
way the study lands, and a results line gets added once the numbers are final.

---

## Scope and framing, as set by the supervisor

| Source | Instruction |
|---|---|
| 3 Sept email | Mention **agentic systems**; **telemetry in general**; **no industry partner named**; "latency is only the first step, we will cover around **10 different issue types**" |
| 2 Sept meeting | "root cause analysis is too small a name — something closer to **agentic software observability**" |

The second instruction is why the abstract no longer opens on the blueprint. **Agentic software
observability is the subject**; the blueprint is the instrument inside it.

---

## Title

**Agentic Software Observability: Capturing, Transferring, and Re-executing Diagnostic Expertise**

---

## Abstract (405 words)

Software systems are increasingly diagnosed by AI agents rather than by people. This thesis
develops *agentic software observability*: how an autonomous agent acquires, retains, and applies
the expertise that diagnosis from telemetry demands. From metrics, logs, distributed traces, and
kernel-level traces, a diagnosis requires judging which signal distinguishes one cause from
another, which events are worth recording, and which thresholds mean something on this system
rather than in general. Engineering practice discards that judgement: an investigation runs once
and its reasoning does not survive. Agents inherit the same statelessness, rebuilding every
investigation from first principles while bringing broad reasoning but little knowledge of how a
fault appears below the application layer.

The thesis makes the investigation itself the durable artifact. An *observability blueprint* is a
self-contained, executable record of one solved problem: the condition it applies to, the
telemetry needed to observe it, the analysis as runnable steps, the decision rule that produces a
verdict, and the circumstances under which it must not be trusted. Blueprints accumulate into a
library an agent selects from and executes without human direction, admitted only after their
signals are measured against every class of issue under study — not merely the one they were
written for — so the library does not accumulate rules that fail elsewhere.

Around it sit the parts agentic observability needs in practice: evidence-based selection that
routes an incident to the right blueprint, a hierarchy that narrows from problem class to cause,
and a feedback path from diagnosis back into collection. A supporting dataset time-aligns kernel
traces with metrics, logs, and distributed traces under labelled fault injection, the layer public
incident corpora omit.

The work spans roughly ten classes of operational issue and microservice, monolithic, and agentic
systems, in which an agent is both the consumer of the library and the system under observation.
Evaluation is comparative and deliberately unkind: the same agent, the same incidents, with and
without the library, measured against a strong deterministic control rather than an unaided
baseline. It establishes whether a blueprint transfers to another service and another system,
whether the library abstains on problems it does not cover, whether executable steps outperform
prose describing the same procedure, and whether the right blueprint can be identified from
evidence alone. The thesis characterises where captured expertise helps, where it is unnecessary
because a capable agent already succeeds, and where it misleads — moving trace analysis from work
that is repeated toward work that accumulates.

---

## Shorter variant (178 words)

Kept as a comment inside `abstract.tex` so the two cannot drift. For repositories and forms that
cap abstract length.

Software systems are increasingly diagnosed by AI agents rather than by people. This thesis
develops *agentic software observability*: how an autonomous agent acquires, retains, and applies
the expertise that diagnosis from telemetry demands. Engineering practice discards that expertise
— an investigation runs once and its reasoning does not survive — and agents inherit the same
statelessness, rebuilding every investigation from first principles.

The thesis makes the investigation itself the durable artifact. An *observability blueprint* is a
self-contained, executable record of one solved problem, stating what to collect, how to analyse
it, how to decide, and when not to trust it. Blueprints accumulate into a library an agent selects
from and executes unaided, admitted only after their signals are measured against every class of
issue under study. Around it sit the parts agentic observability needs: evidence-based selection, a
hierarchy from problem class to cause, and a feedback path from diagnosis back into collection.

Spanning roughly ten classes of operational issue across microservice, monolithic, and agentic
systems, the work characterises where captured expertise helps, where it is unnecessary, and where
it misleads.

---

## How the declarative version stays honest

Worth checking before a presentation, because "sounds finished" and "claims things we have not
done" are easy to confuse.

| Sentence type | Wording used | Why it is safe |
|---|---|---|
| What exists | "An observability blueprint **is** a self-contained, executable record" | describes the artifact, which exists |
| What was built | "Around it **sit** the parts agentic observability needs" | describes the design, which exists |
| The dataset | "A supporting dataset **time-aligns** kernel traces with…" | describes the dataset, which exists |
| The study | "Evaluation **is** comparative and deliberately unkind" | describes the design, not its outcome |
| The questions | "It **establishes whether** a blueprint transfers…" | states what the study settles, not what it settled |
| The findings | "The thesis **characterises where** it helps, where it is unnecessary, and where it misleads" | true whatever the numbers say |

**What a finished abstract would add and this one does not:** one or two sentences naming the
actual findings. Measurements taken so far are in `PROPOSAL.md` §5 and are deliberately not quoted
here.

## Other wording choices

- **"Agentic software observability" is named as the thing being developed**, in the second
  sentence, so a reader meets the field before the instrument.
- **Agentic systems appear twice, deliberately** — the agent is the library's consumer *and* can be
  the system under observation. That is what makes the framing larger than root cause analysis.
- **"Deliberately unkind"** signals the comparison is against a strong control, not a strawman. A
  committee reads that as evaluation design, not modesty.
- **"Where it is unnecessary because a capable agent already succeeds"** matches Naser's standing
  position that a negative result is a result, and pre-empts the obvious challenge.
- **The closing clause** — "from work that is repeated toward work that accumulates" — states the
  thesis in one line and is the sentence to repeat when presenting.
- **Kernel traces are still named** despite "telemetry in general": they are why the supporting
  dataset is novel, since public incident corpora stop at the application.
