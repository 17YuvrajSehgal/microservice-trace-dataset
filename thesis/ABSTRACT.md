# Thesis abstract (proposal stage)

> **No results are stated here on purpose.** The study is in progress, so this abstract
> describes the problem, the proposed artifact, and how it will be evaluated. It makes no claim
> about outcomes and contains no measurements. A results sentence gets added once the final
> numbers exist.

**Scope set by supervisor, 3 September 2026** (email reply to four questions):

| Question | Answer |
|---|---|
| Only microservices, or other system classes? | **Mention agentic systems.** |
| Only kernel traces, or other telemetry later? | **Telemetry in general.** |
| Mention the industry framework? | **No mention of the industry partner.** |
| Only latency, or more problem categories? | **"Latency is only the first step. We will cover around 10 different issue types."** |

---

## Abstract (~330 words)

Software systems are observed through telemetry: metrics, logs, distributed traces, and
kernel-level traces. Turning that telemetry into a diagnosis is skilled work. It requires
knowing which signal separates one cause from another, which events are worth recording, and
which thresholds carry meaning on the system at hand rather than in general. That work is
currently discarded. Analysis follows a single pass of input, analysis, and output, and the
reasoning behind an investigation survives only as a closed ticket, so the next similar incident
begins with nothing. The problem sharpens when AI agents are given the same task: an agent
re-derives an investigation from scratch on every incident, and a language model carries little
specific knowledge of how a given fault appears in low-level telemetry.

This thesis proposes the **observability blueprint**: a self-contained, executable record of one
solved investigation. A blueprint states the problem it addresses and the conditions under which
it applies, the telemetry to collect, the processing steps as runnable commands, the form of the
output, the decision rule that yields a verdict, and the conditions under which it should not be
used. A blueprint enters the library only once its discriminating signals have been measured
against every class of issue under study, not only the one it targets, so that a library can
grow without accumulating claims that fail elsewhere. Because a blueprint is written to be
executed rather than read, an agent can select one from the library and re-run the investigation
without human guidance.

The intended coverage is around ten classes of operational issue, beginning with latency, and
telemetry in general, beginning with kernel traces because they are the layer existing incident
datasets omit. The systems studied span microservice and monolithic applications and **agentic
systems**, where an AI agent is itself the subject under observation as well as the consumer of
the blueprint library.

Evaluation compares the same agent, on the same incidents, with and without the blueprint
library, measured against a deterministic control rather than an unaided baseline. It further
examines whether a blueprint authored from one incident transfers to a different incident,
service, and system; whether a library stays silent on issues it does not cover instead of
misleading; whether executable steps outperform prose descriptions of the same procedure; and
whether the correct blueprint can be identified from evidence alone. The intended contribution
is a method for capturing diagnostic expertise in a reusable, executable form, together with an
account of where such capture helps and where it does not.

---

## Short version (~160 words), for forms and submission portals

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
