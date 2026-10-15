# 20-minute M.Sc. abstract presentation — plan

Date: 2026-10-14. For the abstract submitted as `thesis/abstract-merged.txt`
(title: *Agentic Software Observability: Executable Blueprints for Reusing
Diagnostic Expertise*).

Plan assumes ~17 minutes of talking + buffer. A cut list for a 15-minute slot
is at the end.

---

## The one message

> Diagnostic work is thrown away today. This thesis makes it a durable,
> executable artifact — and measures honestly where that helps, where it is
> unnecessary, and where it misleads.

Closing line (use it word for word, it is the thesis in one sentence):
**"from work that is repeated toward work that accumulates."**

## What the committee needs to hear

Three things, in this order of importance:

1. **This is not unstarted work.** The dataset, the agent, 16 blueprints, and
   the first experiments already exist. Every number is traceable to a file.
2. **The evaluation is honest.** Strong deterministic control, negative
   results kept, a tie reported as a tie.
3. **The remaining work is targeted.** We measured the bottleneck (blueprint
   selection) and the proposed work attacks exactly that.

## Storyline — four acts, same as the abstract's four paragraphs

| Act | Abstract paragraph | Slides | Time |
|---|---|---|---|
| 1. Problem | expertise lost + datasets stop at app boundary | 2–4 | 4 min |
| 2. Idea | the blueprint + the framework around it | 5–7 | 4 min |
| 3. Evidence | what is built + what we measured already | 8–13 | 6 min |
| 4. Plan | evaluation questions, scope, timeline, contributions | 14–17 | 3 min |

---

## Slide-by-slide

### 1. Title (0:00–0:30)
- Title, name, supervisor, Brock.
- One spoken line: "Software is now diagnosed by AI agents. My thesis is
  about making that diagnosis something that accumulates instead of being
  redone every time."

### 2. Background: how we diagnose software (0:30–2:00)
- Four telemetry types: metrics, logs, distributed traces, kernel traces.
- A small diagram: app layer (metrics/logs/traces) vs below-app layer
  (kernel). Say most tooling stops at the line.
- "Diagnosis is skilled work: which signal, which events, which thresholds."

### 3. Problem 1: the expertise is thrown away (2:00–3:30)
- An investigation runs once. The reasoning survives only as a closed ticket.
- AI agents inherit this: they re-derive every investigation from scratch,
  and an LLM has no idea what a CPU cap looks like in a scheduler trace.
- Spoken hook: "We keep the fix. We throw away the method."

### 4. Problem 2: datasets stop at the application boundary (3:30–4:30)
- One table: RCAEval, LEMMA-RCA, OpenRCA, AIOps Challenge, Nezha, LO2 —
  metrics ✓ logs ✓ traces ✓ kernel ✗ (all of them).
- So faults below the app (co-tenant CPU theft, cgroup caps, saturated disk)
  are outside both the analysis and its evaluation.
- Source: `thesis/PROPOSAL.md` §3.1.

### 5. The idea: the observability blueprint (4:30–6:30)
- Definition: one solved investigation, written down so it can be
  **re-executed** — what to collect, what to run, how to decide, when not to
  trust it.
- Show the anatomy as a short list (from the schema): applies-when,
  reproduction, collection order (exact tracepoints), runnable steps,
  decision rule with measured thresholds, rule-out conditions.
- **Show one real discriminator** from `blueprints/problems/host-cpu-saturation/blueprint.json`:
  host utilisation ≥0.99 — measured 0.991–0.998 for saturation vs 0.619–0.681
  co-tenant vs 0.462–0.531 healthy (n=17). "Every claim carries the
  measurement that proved it."

### 6. Two properties that make it more than a runbook (6:30–7:30)
- **Executable.** Steps bind to real commands through a capability registry.
  A blueprint never names a tool — swap babeltrace2 for Trace Compass and
  the blueprint does not change.
- **Evidence-bound.** A validator rejects any claim without a measurement —
  measured against *every* fault family, not just its own. Retracted claims
  stay in the file as "do not claim", with the measurement that killed them.

### 7. The framework around the blueprint (7:30–8:30)
- One diagram: incident → evidence-based **selection** → **hierarchy**
  (issue class → cause) → blueprint **executes** → verdict → **feedback**
  into what to collect next time.
- Say: the library is the contribution, not any single blueprint.

### 8. What exists: the dataset (8:30–9:30)
- **StrataTrace v2: 304 runs** (170 Sock Shop + 134 Train Ticket),
  **~24 fault families**, all four modalities in every run, time-aligned to
  0.001 ms; 779 GB compressed, 1.18 TB raw.
- The kernel layer is the one no public incident corpus has.
- Source: `blueprints/docs/DATASET-v2-INVENTORY.md`.

### 9. What exists: blueprints + a leakage-controlled agent (9:30–10:30)
- 16 blueprint folders, 11 wired into the experiment harness.
- The agent (plan → parallel workers → review → synthesise) has read-only
  tools over the raw kernel trace plus a Python sandbox. Ground truth is
  unreachable; generated skills are leak-scanned; 19 adversarial escape
  attempts checked the sandbox.
- Say: "The agent is never told a fault happened, let alone when."

### 10. Early evidence — the headline (10:30–12:00)
- Kernel traces only. Same agent, same incidents. Only difference: blueprint.

| problem | with blueprint | without |
|---|---|---|
| deadlock | **30 / 30** | 3 / 30 |
| connection-pool exhaustion | **27 / 30** | 2 / 30 |

- Add the earliness detail: without a blueprint the agent reports the
  *recovery* (+180 s onset error on a 125 s fault); with one it hits the
  incident window (+1 s).
- Source: `blueprints/README.md`, `progress-notes/29-09-2026/decisions.md`.

### 11. Early evidence — executable beats prose (12:00–13:00)
- A deterministic rule engine built from the same blueprints, no model at
  all: when it fires it names the right fault **38/41 (93%)**; 3 false fires
  in 826 opportunities.
- The same knowledge handed to a capable model as markdown: roughly half.
- Say: "Rules transfer; prose does not. This is why the abstract says
  *executable* — and it is one of the four evaluation questions."
- Source: `blueprints/docs/RESULTSv2.md`, `blueprints/problems/RESULTS-v2-all-blueprints.md`.

### 12. Early evidence — the honest tie, and what it taught us (13:00–14:30)
- The first full with/without study (57 incidents, both apps): 56% without
  vs 51% with. **A tie** — the gap sits inside the ±2-run noise floor.
- But underneath: blueprints fixed faults the unaided model got 0/6; every
  harm came from the **wrong blueprint being selected**, never from a
  blueprint being wrong about its own fault; the right blueprint was picked
  only 19/57 times.
- Say: "The content is not the bottleneck. The routing is. That is exactly
  why selection and the hierarchy are in the proposal."
- This slide is the credibility slide. A committee trusts a presenter who
  leads with their own null result and explains it.
- Source: `blueprints/docs/RESULTS-withwithout.md`.

### 13. Early evidence — knowing when to say nothing (14:30–15:15)
- Two faults proven *not* diagnosable from kernel traces alone (frozen
  service, silent queue backlog) — matching the pre-registered predictions.
- A blueprint must be able to say "not applicable here". Anti-pattern
  screening cut wrong fires 29% → 12% with zero lost diagnoses.
- Say: "A blueprint that always answers is not carrying knowledge; it is
  guessing with structure."

### 14. Evaluation plan (15:15–16:15)
- The four questions from the abstract, each already designed and some
  already run once:

| question | design | status |
|---|---|---|
| transfer across services/systems? | author on run A, test on service B, app B | partially measured |
| abstain when nothing fits? | leave-one-family-out + healthy runs | measured once |
| executable > prose? | code-in-blueprint vs same step as text | strong early signal |
| selection from evidence alone? | hierarchical vs flat routing | the measured bottleneck |

- Controls that stay: deterministic brief in both arms, leakage lint,
  healthy runs as negatives, repeats so the noise floor is designed in.

### 15. Scope: ten issue classes, three system kinds (16:15–17:00)
- ~10 operational issue classes (latency first — taxonomy and 6 causes
  already covered by blueprints).
- Microservice ✓ (two apps, done), monolithic (planned, micro-benchmarks),
  **agentic** — the agent is also the system under observation.
- One proof point for the agentic leg: our kernel-trace study of coding
  agents under cgroup limits — 260 runs, two agents; ~84% of wall time is
  model wait on a healthy box, and a CPU cap adds up to +75% wall. The same
  method, pointed at the agent itself.
- Source: `Blueprint/latency/OS-NOISE-FOR-AGENTIC-AI.md`, `Blueprint/research-paper/paper2.tex`.

### 16. Timeline (17:00–17:30)
- Six phases from `thesis/PROPOSAL.md` §6, one line each: taxonomy →
  hierarchical selection (the bottleneck) → micro-benchmarks → the stronger
  with/without (no pre-computed evidence) → transfer + external validation →
  writing.

### 17. Contributions + close (17:30–18:00)
- Four bullets: the blueprint format + measure-first method; StrataTrace
  (first public dataset with the kernel layer); the honest map of where
  captured expertise helps/misleads; executable-vs-prose with its design
  consequence for anyone building agent skill libraries.
- End on: **"…moving trace analysis from work that is repeated toward work
  that accumulates."** Stop. Questions.

---

## Numbers cheat sheet (all traceable)

| number | meaning | source |
|---|---|---|
| 304 runs, ~24 families, 4 modalities, 779 GB | dataset v2 | `blueprints/docs/DATASET-v2-INVENTORY.md` |
| 0.001 ms | cross-modality clock alignment | `progress-notes/28-07-2026/` |
| 30/30 vs 3/30; 27/30 vs 2/30 | with/without blueprint, kernel only | `blueprints/README.md` |
| 13% → 93% | best single cell (noisy_neighbor, no hint) | `blueprints/docs/Q2-FULL-6-problems.md` |
| 93% (38/41) | rule-engine precision when it fires | `blueprints/docs/RESULTSv2.md` |
| 3 false fires / 826 opportunities | rule-engine false-fire rate | `blueprints/problems/RESULTS-v2-all-blueprints.md` |
| 56% vs 51% (= tie) | 57-incident with/without | `blueprints/docs/RESULTS-withwithout.md` |
| 19/57 | correct blueprint selections — the bottleneck | same file |
| 29% → 12% | wrong fires after anti-pattern screen | `blueprints/docs/RESULTS-antipattern-ceiling.md` |
| 84% / +75% / 260 runs | agent OS-noise study | `Blueprint/research-paper/*-RESULT.md` |
| $5 per 60-run matrix, ~$120 full campaign | measured cost | `blueprints/README.md` |

## Numbers NOT to use

- **"50% → 70–80%"** — appears in no result file; `RESULTS-withwithout.md`
  explicitly bans it.
- **The pooled "+0" blueprint effect** across the 6-problem matrices without
  the per-problem split — it is an averaging artifact (ceiling + floor
  problems cancel the middle).
- **"<1% variation"** for the OS-noise work — Mahsa's review proved it false
  (wall varies 10–15% from LLM noise alone).
- Before putting 30/30 on a slide: `blueprints/problems/deadlock-lock-order/blueprint.json`
  currently has an uncommitted edit that leaves a trailing comma (invalid
  JSON). The result predates the edit, but fix the file so nobody loads it
  and fails during Q&A.

## Likely questions, with answers

1. **"How is this different from a runbook / playbook?"** A runbook is prose
   for a human. A blueprint is executable (steps bind to real commands), its
   claims are measured against every fault family, and it must say when it
   does not apply. The validator rejects anything that is just prose.
2. **"Isn't this just retrieval / prompt engineering?"** We tested that: the
   same knowledge as markdown gets roughly half the accuracy of the
   executable form. The artifact under study is the investigation, not the
   prompt.
3. **"If the deterministic rules score 93%, why have an agent at all?"**
   Rules only cover faults someone already solved, and abstain elsewhere.
   The agent handles the open set, adapts when evidence does not fit, and
   explains. The thesis measures the division of labour, not one side.
4. **"Two applications — will this generalize?"** That is a research
   question, not an assumption: transfer across services, apps, and to
   monolithic + agentic systems is RQ2, plus purpose-built micro-benchmarks
   to remove the two-app objection.
5. **"Who writes the blueprints? Does this scale?"** The method (measure
   first, validator-enforced) is the contribution; mining blueprints from
   past investigations is named future work.
6. **"What if selection never gets good enough?"** Then that is the finding:
   the tie is reportable, and we already know the failure is routing, not
   content. The hierarchy is the designed fix; abstention is measured.
7. **"Why kernel traces first?"** The layer every public corpus omits, and
   the hardest case — no service names, no request ids. If a blueprint helps
   there it carries real method, not a restatement of a log line.
8. **"How do you know the agent isn't cheating?"** Ground truth is
   unreachable by construction, tool results are leak-masked, skills are
   leak-scanned, and every transcript is audited. Checked with 19
   adversarial escape attempts.
9. **"Which ten issue classes?"** Show the fault-family list from the v2
   dataset (CPU cap, co-tenant, memory, disk, network, DNS, locks, deadlock,
   pools, outage, code defects…). Latency is the entry point.
10. **"Monolithic systems — where is the data?"** Honest answer: not
    collected yet; micro-benchmarks and a held-out app are the plan, and the
    agentic leg already has 260 runs.

## Reusable assets

- Charts: `blueprints/docs/charts-ss/`, `blueprints/docs/charts-tt/`.
- Old deck to mine for visuals: `blueprints/docs/presentations/presentation1/`
  (`slides.html`, `ciena-slides.html` + notes).
- Method figure: `fig_method` in `Blueprint/research-paper/paper2.tex`.
- Per-family run table: `temp.md` (uncommitted — move it somewhere stable).

## If the slot is 15 minutes

Cut in this order: slide 13 (fold abstention into slide 12 as one bullet),
slide 6 (fold the two properties into slide 5), slide 16 (say the timeline
over slide 17). Never cut slides 10–12 — they are the proof the committee
came for.

## Next steps

1. User confirms: exact date, audience (committee? department seminar?),
   whether 20 min includes Q&A, and slide format (PowerPoint / HTML / LaTeX).
2. Build the deck from this plan.
3. Dry run against the timing column.
