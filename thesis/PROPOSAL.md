# M.Sc. Thesis Proposal (draft v1)

**Agentic Software Observability: Capturing, Transferring, and Re-executing
Diagnostic Expertise**

Yuvraj Sehgal · Department of Computer Science, Brock University
Supervisor: Dr. Naser Ezzati-Jivan
Draft: 3 September 2026

> **Draft status.** Content is grounded in work already done and measured; every number below
> is traceable to a results file in this repository. Three things still need confirming and are
> marked `[CONFIRM]`: the department's required format and length, the submission deadline, and
> the committee composition. Section order follows a conventional CS proposal and can be
> remapped to a departmental template without changing the content.

---

## 1. Problem

Modern cloud systems are observed through four kinds of telemetry: metrics, logs, distributed
traces, and kernel traces. When something goes wrong, an engineer reads this data and works out
why. That investigation is skilled work: it requires knowing *which* signal separates one cause
from another, *which* events to collect, and *which* thresholds mean something on this system
rather than in general.

**Today that work is thrown away.** Every trace-analysis system follows the same shape — input,
analysis, output — and runs it once. The engineer's reasoning survives only as a resolved
ticket. The next similar incident starts from nothing.

This matters more now that AI agents are being pointed at the same task. An agent given raw
telemetry and a goal will re-derive an investigation from scratch each time, and a large
language model has no particular knowledge of what a CPU cap looks like in a scheduler trace.
The knowledge exists — in engineers, in resolved tickets, in published analyses — but it is not
in a form an agent can execute.

**Thesis problem.** Can the experience of solving one observability problem be captured as a
reusable, executable artifact, such that an agent can use it to solve the *next* similar
problem — and can we measure honestly where that helps and where it does not?

---

## 2. Proposed idea: the observability blueprint

An **observability blueprint** is a self-contained, executable record of one solved
investigation. It states:

| Part | What it fixes |
|---|---|
| Problem statement and when it applies | tells a selector whether this is the right blueprint |
| Reproduction recipe | makes the claim checkable by someone else |
| **Collection order** — exactly which events to enable | the blueprint drives collection, not just analysis |
| Runnable processing steps | the analysis is a command, not a description |
| Output specification | downstream tools know what to expect |
| Decision rule with measured thresholds | the verdict is reproducible, not a judgement call |
| Stopping conditions and retractions | says when *not* to use it, and what was disproven |

Two properties distinguish this from a runbook or a prompt template.

**It is executable.** Each processing step binds to a real command through a capability
registry, so an agent runs the blueprint rather than paraphrasing it.

**It is evidence-bound.** No discriminator may enter a blueprint unless it has been measured on
our own data, and — critically — measured against *every* fault family, not only its own. A
validator rejects uncited claims.

Blueprints accumulate into a library. The library, not any single blueprint, is the
contribution: it turns trace analysis from a stateless pipeline into something that gets better
as it is used.

### Framing

Naser's guidance is that "root cause analysis" undersells the work. The framing adopted here is
**agentic software observability**: the object of study is not one diagnosis but the mechanism by
which diagnostic expertise is captured, transferred, selected, and re-executed by an agent.

---

## 3. Background and gap

### 3.1 Observability datasets

Incident datasets for AIOps research are now common — RCAEval, LEMMA-RCA, OpenRCA, the AIOps
Challenge corpora, MSDS, Nezha, LO2 — and live agent testbeds exist (AIOpsLab, ITBench).
`[CONFIRM full citations]`

Every one of them shares a boundary: **none includes a kernel layer.** Metrics, logs and
application traces stop at the application. When a fault lives below that line — a co-tenant
stealing CPU, a cgroup quota, a saturated block device — the dataset simply cannot see it.

### 3.2 Agent knowledge and skills

Recent work equips LLM agents with retrieved procedures, tool documentation, or learned
"skills". Agent-failure datasets (TRAIL, Who&When, TraceElephant) study trajectories.
AgentSight instruments agents at the eBPF level, but as a tool, not a dataset.
`[CONFIRM full citations]`

The gap: prior work reports **accuracy on a pipeline**. The artifact under study is the model or
the prompt. Nobody treats **the investigation itself** as the transferable deliverable and then
measures its reuse.

### 3.3 The gap this thesis addresses

1. No public incident dataset time-aligns **kernel traces** with application traces, logs and
   metrics under labeled fault injection.
2. No study asks whether a **captured investigation transfers** to a new incident, a new
   service, or a new application.
3. No RCA work lets the diagnostic knowledge **feed back into collection** — deciding what to
   record next time.

---

## 4. Research questions

**Scope, as set by the supervisor on 3 September 2026.** Draft v1 of this proposal recorded the
2 September working decision to narrow to latency observed through kernel traces. That was the
*first step*, not the thesis boundary. The confirmed scope is:

- **Around ten classes of operational issue**, beginning with latency.
- **Telemetry in general** — metrics, logs, distributed traces, kernel traces — beginning with
  kernel traces, because that is the layer existing incident datasets omit.
- **Systems spanning microservice, monolithic, and agentic** applications, where an AI agent is
  itself a subject under observation as well as the consumer of the blueprint library.
- **No industry partner is named** in the thesis; the framing stays on agentic software
  observability.

Practically, the near-term work is still latency on kernel traces — that is where the evidence
and tooling already are. The difference is that this is now stated as a starting point rather
than a boundary, and the design must not assume one issue class, one telemetry type, or one
system class.

| RQ | Question | Status |
|---|---|---|
| **RQ1** | Does an agent with a blueprint diagnose better than the same agent without one? | **measured once** (§5.2) |
| **RQ2** | Does a blueprint written from one incident transfer to a different incident, service, and application? | partially measured |
| **RQ3** | Does a blueprint beat a strong deterministic control, not just a naive agent? | **measured** (§5.2) |
| **RQ4** | On faults no blueprint covers, does the library stay quiet or mislead? | **measured** (§5.2) |
| **RQ5** | Does shipping *executable code* in a blueprint beat prose describing the same step? | **strong preliminary signal** (§5.3) |
| **RQ6** | Can a blueprint's collection order cut the data needed without losing accuracy? | designed, not run |
| **RQ7** | Can a selector choose the right blueprint from evidence alone? | **measured — this is the bottleneck** (§5.2) |
| **RQ8** | Can blueprints be *mined* from past investigations rather than hand-written? | future work |

RQ5 and RQ7 are where this thesis can say something others cannot: RQ5 because the harness is
leak-audited and can measure run-to-run variance, RQ7 because the library is large enough for
wrong selections to actually happen and be counted.

---

## 5. Preliminary results

This is not a proposal for unstarted work. The infrastructure exists and the headline
experiment has been run once.

### 5.1 What is built

- **StrataTrace**: 109 labeled fault-injection runs across two applications (Sock Shop, ~16
  services; Train Ticket, 40+ services), each with metrics, logs, application traces and
  **kernel traces**, time-aligned to 0.001 ms clock drift. 13 fault families × 2 intensities.
- **Six blueprints**, each built by the measure-first method: host CPU saturation, co-tenant CPU
  contention, service CPU throttling, datastore wait, network path degradation, host disk
  saturation.
- **A deterministic rule engine** that reads kernel evidence and issues a verdict with no model
  involved.
- **An evaluation harness** with a leakage lint that refuses any blueprint mentioning a real
  service name or ground-truth wording.

### 5.2 The with/without experiment (RQ1, RQ3, RQ4, RQ7)

57 incidents, both applications, same model, same evidence. One difference: blueprint library
available or not. Both arms received a deterministic investigation brief, so the control is the
strong version that already matched a full tool-using agent in earlier work.

| Arm | Fully correct |
|---|---|
| Without blueprints | 32 / 57 |
| With blueprints | 29 / 57 |

Read alone this says blueprints hurt. **It does not.** On 30 of the 57 runs the selector chose
no blueprint, so both arms had identical input — and still scored 15 against 13. The noise floor
is therefore about ±2 runs and the headline gap of 3 sits inside it. **The result is a tie.**

What moved underneath the tie is the useful part:

- Blueprints **fixed 3** runs. Two were co-tenant CPU contention, a fault the unaided model got
  right **0 times out of 6**.
- Blueprints **broke 4** runs. **All four were the wrong blueprint being selected** — not one was
  a blueprint giving bad advice about its own fault.
- The network blueprint was selected **zero times across 9 network incidents**, while the rule
  engine scores 9/12 on those same faults using that same blueprint.

**Conclusion: the content is not the bottleneck; the routing is.** That reframes the rest of the
thesis.

### 5.3 Rules versus prose (RQ5)

The deterministic engine, reading the same kernel data with no model at all, names the right
fault **38 times out of 41 when it fires** (93% precision), stays correctly silent on 26 of 29
runs it should ignore, and declined all 8 healthy runs. Overall 64 of 81 runs correct (79%).

The same knowledge, rendered as markdown and handed to a capable model, gets roughly half that.

**The rules transfer; the prose does not.** This is the strongest preliminary finding and it
directly shapes what a blueprint should ship as.

### 5.4 Honest negative results

Two faults were proven **not diagnosable** from kernel traces alone, after six and one measured
attempts respectively: a frozen service and a silent queue backlog. Both are defined by
*absence* — the container stops answering without losing packets or going quiet in the
scheduler. This matches what the pre-registered fault catalogue predicted before collection
began.

Recording these matters. Naser's standing instruction is that a negative result is a result: the
thesis should say where blueprints do not help, not claim they always do.

### 5.5 Method finding: reproducibility

While validating a performance change, the same script was found to produce different output
row order on consecutive runs of the same trace. Values were always correct; ordering followed
the interpreter's per-process string hashing through 23 un-tie-broken sorts. Two of those sorts
feed a verdict by reading the top row, so a tie could in principle name a different service.

Fixed and verified under forced hash seeds. This is worth reporting: a blueprint claims to be a
**re-runnable** investigation, and reproducibility is therefore part of the claim, not a detail.

---

## 6. Proposed work

### Phase 1 — Latency cause taxonomy (weeks 1–2)

Enumerate 5–10 causes of latency, isolated and combined, and state for each whether kernel
traces can observe it. Our current six blueprints cover six of ten common causes; the gap is
lock contention, interrupt storms, memory pressure, and critical-path wait chains.

Two of those gaps may be answerable from **data already collected** — we record all syscalls
(so `futex` waits are present) and the IRQ families — and have never been analysed.

### Phase 2 — Hierarchical selection (weeks 2–5)

The measured bottleneck. Replace the flat library with a **parent latency blueprint** that routes
to children, so the agent narrows rather than guessing from a flat list. Evaluate as RQ7:
selection precision, abstention recall, and confusion between families.

This addresses the supervisor's structural suggestion and our measured failure mode with the
same change.

### Phase 3 — Purpose-built micro-benchmarks (weeks 4–8)

Write small programs that each induce exactly one latency cause, and trace each 5–10 times. Two
reasons: fault isolation is clean, and it removes the objection that results depend on two
particular applications. Kernel-level lock contention is the first case.

### Phase 4 — The stronger experiment (weeks 6–9)

Re-run with/without under the harder condition: **neither arm receives pre-computed evidence.**
The current run gave both arms the evidence pack, so it tested only the interpretation half of a
blueprint and never the collection half — the half a blueprint is best at. Include repeats so
the noise floor is designed in rather than inferred.

### Phase 5 — Transfer and external validation (weeks 8–12)

RQ2 in full: author on one run, test on another service, another intensity, another
application. Then a dataset that is not ours, with a known latency problem.

### Phase 6 — Writing (weeks 10–16)

Technical report per problem, using a fixed template: what the problem is, how it is generated,
what data and how much, which events were enabled, blueprint content, and results with and
without. Then the thesis itself.

---

## 7. Contributions

1. **The blueprint format and the method for producing one** — a measure-first discipline in
   which no discriminator enters a blueprint until it is measured against *all* fault families,
   enforced by a validator. The method is the contribution, not any single blueprint.
2. **StrataTrace** — the first public incident dataset time-aligning kernel traces with
   application traces, logs and metrics under labeled fault injection.
3. **An honest map of where captured expertise helps** — including that it is a tie overall, that
   it rescues faults a model cannot do unaided, and that every observed harm came from
   misrouting rather than bad content.
4. **The rules-versus-prose result** — executable decisions transfer to an agent; the same
   knowledge as text does not. This has a direct design consequence for anyone building agent
   skill libraries.
5. **Reproducibility as a requirement** for executable diagnostic artifacts, with a concrete
   failure mode and fix.

---

## 8. Evaluation plan

| RQ | Design | Metric |
|---|---|---|
| RQ1 | with/without, same model, same incidents, repeats | fully-correct rate, with a measured noise floor |
| RQ2 | author on run A, test on run B / other service / other app | transfer rate, autonomy gap |
| RQ3 | blueprint arm versus deterministic-brief control | difference against the strong control |
| RQ4 | leave-one-family-out; healthy-run controls | false-fire rate, abstention recall |
| RQ5 | code-in-blueprint versus prose describing the same step | accuracy and run-to-run variance |
| RQ6 | collection ladder: full kernel trace down to a named event set | accuracy versus bytes collected |
| RQ7 | hierarchical versus flat selection | selection precision, confusion matrix |

Controls that must stay in place: the leakage lint, healthy runs as negative controls, and the
deterministic brief in both arms.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Selection does not improve enough to change RQ1 | The tie is itself reportable, and the failure analysis is already precise about why. |
| Micro-benchmarks are too artificial to persuade | Keep both: two real applications and controlled programs; report separately. |
| No suitable external dataset with kernel traces exists | Fall back to generating a held-out application; state the limitation. |
| Kernel-only scope limits which faults are reachable | Already measured and bounded — two faults proven unreachable, documented rather than hidden. |
| Small n per fault (2–7 runs) | Expand runs for the families that carry the claims; report the noise floor everywhere. |

---

## 10. Timeline `[CONFIRM against programme milestones]`

| Weeks | Work |
|---|---|
| 1–2 | latency taxonomy; cut out-of-scope faults |
| 2–5 | hierarchical selection (the bottleneck) |
| 4–8 | micro-benchmarks, starting with lock contention |
| 6–9 | stronger with/without, with repeats |
| 8–12 | transfer study; external dataset |
| 10–16 | technical report, then thesis chapters |

Two external deadlines interact with this: an ICSE NIER-track submission
(`[CONFIRM date — the 2 Sept meeting landed on 23 October but was unsure]`) and the MSR 2027
Data & Tool Showcase (abstract 5 November 2026, paper 10 November).

---

## 11. References

`[CONFIRM]` — these are the works the related-work analysis in this repository relies on. Full
bibliographic details must be verified before submission; they are listed here by name and venue
only, exactly as recorded, and not reconstructed from memory.

- RCAEval — ASE 2024 / WWW 2025 / FSE 2026
- LEMMA-RCA — NEC Laboratories
- OpenRCA — ICLR 2025
- AIOpsLab — Microsoft
- ITBench — IBM
- AgentSight — eBPF agent observability
- TRAIL; Who&When; TraceElephant — agent-failure datasets
- AIOps Challenge; MSDS; Nezha; LO2 — incident corpora
- LTTng; babeltrace2; OpenTelemetry — instrumentation used
- Sock Shop; Train Ticket — subject applications

---

## Appendix A — evidence index

Every claim above traces to a file:

| Claim | Source |
|---|---|
| with/without numbers | `blueprints/docs/RESULTS-withwithout.md`, `blueprints/results/withwithout.json` |
| rule-engine accuracy | `blueprints/docs/RESULTSv2.md` |
| per-signal measurements, F1–F19 | `blueprints/docs/FINDINGS-phase1.md` |
| what could not be built, and why | `blueprints/docs/BLUEPRINT-BACKLOG.md` |
| dataset design and modality gap | `msr-research.md` |
| pre-registered fault predictions | `fault_catalog.md` |
| blueprint concept and RQ origin | `blueprint-idea.md` |
| reproducibility fix | `progress-notes/03-09-2026/decisions.md` |
| supervisor scope decisions | `progress-notes/02-09-2026/todo-points.md` |
