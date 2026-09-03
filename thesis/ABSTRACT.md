# Thesis abstract (proposal stage)

> **No results are stated here on purpose.** The study is in progress, so this abstract
> describes the problem, the proposed artifact, and how it will be evaluated. It makes no claim
> about outcomes and contains no measurements. A results sentence gets added once the final
> numbers exist.

---

## Abstract (~300 words)

Cloud systems are observed through several kinds of telemetry — metrics, logs, distributed
traces, and kernel traces. Turning that data into a diagnosis is skilled work: it requires
knowing which signal separates one cause from another, which events are worth collecting, and
which thresholds carry meaning on the system at hand rather than in general. That work is
currently discarded. Trace analysis follows a single pass of input, analysis, and output, and
the reasoning behind an investigation survives only as a closed ticket. The next similar
incident begins with nothing. The problem sharpens when AI agents are given the same task: an
agent re-derives an investigation from scratch each time, and a language model carries little
specific knowledge of how a scheduler trace or a block-layer trace reveals a particular fault.

This thesis proposes the **observability blueprint**: a self-contained, executable record of one
solved investigation. A blueprint states the problem it addresses and the conditions under which
it applies, the events to collect, the processing steps as runnable commands, the form of the
output, the decision rule that yields a verdict, and the conditions under which it should not be
used. Blueprints are admitted to a library only when their discriminating signals have been
measured against every fault class under study, not only the one they target, so that a library
can be assembled without accumulating claims that fail elsewhere. Because a blueprint is written
to be executed rather than read, an agent can select one from the library and re-run the
investigation without human guidance.

The work is scoped to latency problems observed through kernel traces of containerised
microservice systems, supported by a dataset of labelled fault injections in which kernel traces
are time-aligned with the other telemetry modalities.

Evaluation compares the same agent, on the same incidents, with and without the blueprint
library, against a deterministic control rather than an unaided baseline. It further examines
whether a blueprint authored from one incident transfers to a different incident, service, and
application; whether a library remains silent on faults it does not cover instead of misleading;
whether executable steps outperform prose descriptions of the same procedure; and whether the
correct blueprint can be identified from evidence alone. The intended contribution is a method
for capturing diagnostic expertise in a reusable form, together with an account of where such
capture helps and where it does not.

---

## Short version (~150 words), for forms and submission portals

Diagnosing faults in cloud systems from telemetry is skilled work, and today that work is
discarded: each investigation runs once and its reasoning survives only as a closed ticket. AI
agents given the same task re-derive everything from scratch and carry little specific knowledge
of how kernel-level signals reveal a fault.

This thesis proposes the **observability blueprint** — a self-contained, executable record of one
solved investigation, stating what to collect, how to process it, how to decide, and when not to
apply it. Blueprints enter a library only after their discriminating signals are measured against
every fault class under study, and because they are executable an agent can select and re-run
them without human guidance.

Scoped to latency problems in kernel traces of containerised microservices, the work evaluates
whether captured expertise transfers to new incidents, and reports where it helps and where it
does not.

---

## Notes on choices made here

- **Tense.** Present tense for the artifact, future or neutral for the evaluation. No sentence
  asserts an outcome.
- **No numbers.** Not even the preliminary ones already measured. They are real, but they are not
  final, and an abstract that quotes interim figures invites a committee to hold the thesis to
  them.
- **"Where it does not help" is stated as an intended contribution.** This is deliberate and
  matches the supervisor's standing position that a negative result is a result. It also protects
  the abstract: it stays accurate whether the library turns out to help a lot or a little.
- **The control is named.** Saying the comparison is against a deterministic control, not an
  unaided baseline, signals the evaluation is not built to be easy to win.
- **What is missing until results exist:** one or two sentences after the evaluation paragraph
  giving the finding. Placeholders are marked in `PROPOSAL.md` §5, which holds the measurements
  taken so far.
