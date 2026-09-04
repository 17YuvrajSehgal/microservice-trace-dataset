# Thesis abstract (proposal stage)

> **No results are stated here on purpose.** The study is in progress, so this abstract
> describes the problem, the proposed artifact, and how it will be evaluated. It makes no claim
> about outcomes and contains no measurements. A results sentence gets added once the final
> numbers exist.
>
> **`abstract.tex` is the canonical copy.** This file mirrors it and adds the reasoning behind the wording; if the two ever disagree, the `.tex` is right.

**Scope set by supervisor, 3 September 2026** (email reply to four questions):

| Question | Answer |
|---|---|
| Only microservices, or other system classes? | **Mention agentic systems.** |
| Only kernel traces, or other telemetry later? | **Telemetry in general.** |
| Mention the industry framework? | **No mention of the industry partner.** |
| Only latency, or more problem categories? | **"Latency is only the first step. We will cover around 10 different issue types."** |

---

## Abstract (380 words)

Diagnosing a fault in a software system is expert work.
From telemetry — metrics, logs, distributed traces, and kernel-level traces — an engineer must
judge which signal distinguishes one cause from another, which events are worth recording, and
which thresholds mean something here rather than in general.
That judgement is the valuable part, and it is discarded: the investigation runs once, its
conclusion becomes a ticket, and the reasoning does not survive.
Automation has not changed this.
An AI agent rebuilds it from first principles every time, bringing broad reasoning but little
knowledge of how a fault appears in low-level telemetry.

This thesis proposes that the investigation, not its verdict, should be the durable artifact.
An **observability blueprint** is a self-contained, executable record of one solved problem:
the condition it applies to, the telemetry needed to observe it, the analysis as runnable steps,
the decision rule that yields a verdict, and when it must not be trusted.
Two properties separate it from a runbook. It is executable, so an agent runs it rather than
paraphrasing it; and it is evidence-bound,
admitting a signal only once it has been measured against every class of issue under study, not
merely the one it was written for, so the library does not accumulate rules that fail elsewhere.

The work begins with latency faults in kernel traces, the layer public incident datasets omit,
and widens to roughly ten classes of operational issue across telemetry in general.
Subjects widen in parallel: microservice, monolithic, and agentic systems, where an AI agent is
both the library's consumer and the system under observation.

Evaluation is deliberately unkind to the hypothesis: the same agent, the same incidents, with and
without the library, against a strong deterministic control rather than an unaided baseline.
Does a blueprint transfer to another service, or another system?
Does a library decline to answer on problems it does not cover?
Do executable steps outperform prose describing the same procedure?
Can the right blueprint be chosen from evidence alone, with no human to route it?
The contribution is a method for capturing diagnostic expertise in a form that executes, with a
candid account of where it helps, where it proves unnecessary, and where it misleads — moving
trace analysis from work that is repeated toward work that accumulates.
\

---

## Short version (171 words), for forms and submission portals

Diagnosing faults in software systems from telemetry is skilled work, and today that work is
discarded: each investigation runs once and its reasoning survives only as a closed ticket. AI
agents given the same task re-derive everything from scratch and carry little specific knowledge
of how a fault appears in low-level telemetry.

This thesis proposes the **observability blueprint** — a self-contained, executable record of one
solved investigation, stating what to collect, how to process it, how to decide, and when not to
apply it. A blueprint joins the library only after its discriminating signals are measured
against every class of issue under study, and because blueprints are executable an agent can
select and re-run them without human guidance.

The work spans around ten classes of operational issue and telemetry in general, across
microservice, monolithic, and **agentic** systems. It evaluates whether captured expertise
transfers to new incidents, and reports where it helps and where it does not.

---

## What changed from draft v1, and why

| Draft v1 | Now | Reason |
|---|---|---|
| "containerised microservice systems" | microservice, monolithic, **and agentic** systems | Naser: "mention agentic systems" |
| "latency problems" as the scope | ~ten classes of issue, latency first | Naser: "latency is only the first step" |
| "observed through kernel traces" | telemetry in general, kernel traces first | Naser: "telemetry in general" |
| — | no partner named | Naser: no mention of the industry partner |

The partner framework's other ideas — ticket history, source-code analysis — are left out of the
abstract. Naser answered only the naming question, so the safe reading is to keep the abstract on
agentic software observability and not import a second research agenda into 330 words.

## Notes on wording choices

- **Agentic systems appear twice, deliberately.** The agent both *uses* the library and can *be*
  the system under observation. Saying so in one clause makes the framing bigger than root cause
  analysis, which is the direction Naser asked for.
- **Breadth is stated as intent, not as done.** "Beginning with latency", "beginning with kernel
  traces". This keeps the abstract accurate today while claiming the full scope. An abstract that
  said we cover ten issue types now would be false.
- **Why kernel traces are named at all**, given "telemetry in general": they are the reason the
  supporting dataset is novel, since existing incident datasets stop at the application. Naming
  them as the starting point keeps that contribution visible without narrowing the thesis.
- **No numbers.** Not even the preliminary ones already measured. They are real, but not final,
  and an abstract that quotes interim figures invites a committee to hold the thesis to them.
- **"Where it does not help" is an intended contribution.** Matches Naser's standing position that
  a negative result is a result, and keeps the abstract true whichever way the study lands.
- **The control is named.** Saying the comparison is against a deterministic control, not an
  unaided baseline, signals the evaluation is not built to be easy to win.
- **Still missing until results exist:** one or two sentences after the evaluation paragraph
  giving the finding. Measurements taken so far are in `PROPOSAL.md` §5.
