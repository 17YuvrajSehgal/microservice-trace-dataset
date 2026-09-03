# Meeting 2 Sept 2026 — summary and todo points

Present: Naser Ezzati-Jivan, Mahsa Panahandeh, Sneh Patel, Yuvraj Sehgal.
Source: `transcript-02-09-2026.txt`.

---

## The short version

Three things changed.

1. **Narrow the scope to latency, on kernel traces only.** Drop anything kernel traces
   cannot see.
2. **Build our own small test cases**, not just the Sock Shop / Train Ticket dataset. Write
   tiny programs that cause one latency reason each, and trace them.
3. **Aim at hard problems.** If the agent already solves a problem without a blueprint, that
   is a fine result — say so. The blueprint has to earn its place on the hard cases.

---

## What was decided

| Topic | Decision |
|---|---|
| Data | **Kernel traces only for now.** LTTng today; eBPF and perf later (all write CTF). |
| Problem type | **Latency.** Everything else waits. |
| Out of scope | Faults kernel traces cannot see. Error storm was named as an example — a dead service puts no pressure on the kernel. "If that doesn't work, forget about it." |
| Logs / metrics | **Do not start these yet.** The partner cares about the kernel part. Same design will extend later. |
| Naming | Say **blueprint** in the paper, not "skill". |
| Structure | **Hierarchical.** One parent blueprint for latency, smaller child blueprints under it. The agent should walk parent → child. |
| Next meeting | **Full demo**: about 5 real problems, each with a blueprint, each shown with and without. |

---

## The plan Naser laid out

Do these in order, for latency:

1. **List the causes.** 5 to 10 reasons for latency. Both single causes and combined ones.
   Use AI for this — it is textbook knowledge, not a literature review.
2. **Generate a test case per cause.** Have AI write a small program that causes it. Trace it
   with LTTng. 5–10 traces per cause.
3. **Build a blueprint** for one cause.
4. **Test with and without** on the rest.
5. **Then try real data** — a public trace or a paper's dataset with a real latency problem.
   See if our system finds it and explains it.

---

## Todo points

### A. Do this week

- [ ] **A1. Research the latency causes.** Write a list of 5–10 latency reasons, isolated and
      combined. Say for each whether kernel traces can see it.
- [ ] **A2. Fix blueprint selection.** This is the known weak spot. Yuvraj told the meeting
      the with/without results were poor because the agent picked the wrong blueprint. Our own
      measurement says the same thing (see the last section).
- [x] **A3. Make kernel analysis faster.** DONE 2026-09-03. We were already using the C
      command line, not the Python binding, so there was nothing to switch. The real waste
      was reading the same trace 14 times per run. Now we read it once and save the parts
      each script needs: **23 min -> 7 min** per run. Checked the answers are unchanged.
      Details in `progress-notes/03-09-2026/decisions.md`.
- [ ] **A4. Cut the non-latency faults** from the current blueprint set, or mark them clearly
      as out of scope.
- [ ] **A5. Start the report** even with simple cases. A first version is better than waiting.

### B. New test cases to build

- [ ] **B1. Kernel-level lock contention.** Named directly by Naser as a good case. Kernel
      locks, not user-level spinning. Easy to generate, many variants possible. Real examples
      exist (Google Chrome was mentioned).
- [ ] **B2. Small generated programs**, one per latency cause from A1, each traced 5–10 times.
- [ ] **B3. Find a real, outside dataset** with a known latency problem to test against.

### C. Critical path analysis

- [ ] **C1. Add critical path analysis to the work.** Naser: "the most complex cases come from
      critical path."
- [ ] **C2. Get the paper from Sneh Patel** on critical path analysis with microservices. He
      offered to share it.
- [ ] **C3. Talk to Sneh.** He already did a review of what cases you can generate with
      critical path analysis. He also covers Trace Compass, so we do not need to.

### D. Writing

- [ ] **D1. Technical report on the study part only.** One template per problem:
      what the problem is · how we generate it · what scenarios · what data and how much ·
      which events were enabled · with blueprint vs without · what the blueprint is.
      Naser thinks this alone can be a paper.
- [ ] **D2. Check the ICSE 2027 NIER deadline.** The meeting landed on **23 October** for the
      "New Ideas and Emerging Results" track. There was confusion on the call between January,
      June and October — **confirm on the site before planning around it.**
- [ ] **D3. Write the MSR abstract.** Naser asked twice, said do it soon.
- [ ] **D4. Think about the thesis framing.** Naser thinks "root cause analysis" is too small a
      name. Something closer to agentic software observability.

### E. Open questions to answer, not just do

- [ ] **E1. One blueprint or many?** Is the mapping problem→blueprint one-to-one or one-to-many?
      Currently ours is per category — all database problems share one blueprint.
- [ ] **E2. Mahsa's isolation problem.** If a blueprint contains specific hints ("if you see
      this dependency, do that"), then a good result may come from *those hints*, not from
      *having a blueprint*. How do we separate the two? Her suggestion: try several different
      blueprint designs, so we can say the effect holds across designs.
- [ ] **E3. Who writes blueprints, and how?** Naser liked our answer and wants it made explicit
      as a method: collect evidence → analyse → abstract → link to a cause → write the
      blueprint, with a human able to review and edit. He said the **method** is the
      contribution, not any one blueprint that works well.

### F. Later, not now

- [ ] **F1. Mahsa's idea:** an agent that reads GitHub repos of other anomaly-detection and RCA
      tools and turns their functions into blueprints. Interesting as its own project.
- [ ] **F2. Partner's real incidents.** They said they will share documented issues after the
      first demo. Those become blueprints.
- [ ] **F3. Logs, metrics, spans.** Explicitly parked.

---

## The point Naser repeated most

**A negative result is a good result.**

> "For this very simple problem, blueprint doesn't do anything. AI agent is smart enough."

He does not want a paper that says blueprints always help. He wants to know **where they help
and where they do not**. Simple problems should not need a blueprint, the same way a simple
meal does not need a recipe. So the effort should go to the complex cases.

---

## How this lines up with what we measured yesterday

Useful, because the meeting and our measurement agree.

| Meeting point | What our data says |
|---|---|
| "Results were not good because it used the wrong skill" | Confirmed. All 4 runs a blueprint broke were the **wrong blueprint being picked**. None was a blueprint giving bad advice about its own fault. |
| Blueprints should not help on easy problems | Confirmed. Host CPU 6/6 and disk 3/3 were already perfect **without** any blueprint. |
| Blueprints should help on hard problems | One clear case. Noisy neighbour went **0/6 without → 2/6 with**. The model cannot do that fault alone. |
| Selection needs work | Our network blueprint was picked **zero times in 9 network incidents**, while our rule engine scores 9/12 on those same faults with it. |

Full numbers: `blueprints/docs/RESULTS-withwithout.md`.

**One caveat to carry into the demo.** In our run both arms got the pre-computed evidence
pack, so we only tested the *reading the numbers* half of a blueprint, never the *what to
collect* half. Naser's plan — generate a trace, hand it over, ask the system to find the
problem — tests both halves. That is the stronger version of the experiment and we should run
it that way from now on.
