# Speaker notes — `slides.html`

Keyed to the deck's own slide numbers. **These differ from
`presentation-plan.md`**, which had 17 slides; the deck has 19 content slides
plus 3 backup slides. The mapping is at the end.

Deck: open `slides.html` in a browser. Arrow keys / space / PageUp-PageDown
move a slide; Home and End jump to the ends. The bar across the top is
progress; the pill bottom-right is the slide count. Each slide's bottom-left
corner shows its **target clock time** — use it in the dry run and then ignore
it on the day.

Total: **17:30 of talking.** Buffer to 20 with questions.

---

## 1 · Title — 0:00

Say, once, then move:

> "Software is now diagnosed by AI agents. My thesis is about making that
> diagnosis something that accumulates instead of being redone every time."

Do not read the title aloud. It is on the slide.

## 2 · Background — 0:30

The job here is to make sure nobody is lost later. Walk the stack top to
bottom, one sentence each, then land on the dashed line.

> "The first three tell you what the application says about itself. The fourth
> records what the machine actually did — and it is the one every public
> dataset leaves out."

Then: **"Diagnosis is skilled work: which signal, which events, which
thresholds."** That sentence sets up both problem slides.

## 3 · Problem 1 — 1:45

Read the quote block out loud. It lands.

The hook, and it is worth pausing after:

> **"We keep the fix. We throw away the method."**

Then the agent consequence in one line: a new engineer re-derives it, and so
does an AI agent — except the agent has no idea what a CPU cap looks like in a
scheduler trace.

## 4 · Problem 2 — 3:00

Let them read the column of ✗. Do not narrate the table.

> "You cannot score a method on a fault your data cannot see."

## 5 · The idea — 4:00

Define it in one sentence, then walk the six cards fast. The two to dwell on:
**collection order** (a blueprint drives collection, it does not only consume
it) and **rule-outs** (it must name where to go instead).

## 6 · One real discriminator — 5:30

**This is the slide that proves the method.** Give it time.

Read the "NOT this" line out loud. Then the table: ordered by how loud the
signal is, the fault we actually want comes *third* — behind a fault it is
meant to be told apart from, and barely ahead of a healthy machine.

> "The obvious signal — the one any engineer reaches for — was measured and
> demoted to corroboration. No prose runbook does that."

## 7 · Two properties — 6:45

Capability first, 30 seconds: `needs:` a capability, not a tool — swap
Babeltrace2 for Trace Compass and the blueprint does not change.

Then the three dead claims. Say the punchline:

> **"All three would have been on a slide."**

And: retracted claims stay in the file, with the measurement that killed them,
so the agent is warned off them too.

## 8 · The framework — 7:45

Walk the flow left to right in one breath. Then the two things that matter:

- **the library is the contribution, not any single blueprint**
- **selection is manual today** — say this plainly here, because slide 13 is
  about to show why that is the problem, and admitting it first makes the
  later finding read as diagnosis rather than excuse.

## 9 · The dataset — 8:30

Numbers are on the slide; do not recite them. Say two things:

> "The kernel layer is the part no public incident corpus has."

And the 35 runs: the fault is demonstrably there and the metrics cannot see
it — for kernel-trace work those are the *most* interesting runs, not the
weakest.

Add: we have published on kernel traces before this, so the collection
expertise is not new.

## 10 · Library and agent — 9:30

The cards carry it. Deliver the line:

> **"The agent is never told that a fault happened — let alone when."**

If asked how you know it is not cheating, the answer is slide A3 plus: ground
truth is unreachable by construction, and 19 adversarial escape attempts check
the sandbox.

## 11 · The headline — 10:30

Let the table do the work. Then the detail that makes it more than a big
number:

> "The fault lasts 125 seconds. The unaided arm is not late — it is describing
> the recovery."

**State the two caveats out loud** (they are on the slide, bottom): one
incident per matrix, and the blueprint was handed over, not chosen. Saying them
yourself is worth more than being asked.

## 12 · Executable beats prose — 12:00

Rule engine first: no model at all, 93% precision when it fires, and it
declines every healthy run.

Then the pivot:

> **"Rules transfer. Prose does not."**

Then the negative control, because it is the cleanest thing in the deck: more
data handed to the model as text bought **+61% tokens and zero accuracy**.

Close: this is why the abstract says *executable*, and it is one of the four
evaluation questions.

## 13 · The honest tie — 13:00

**The credibility slide. Do not rush it and do not apologise for it.**

Lead with it as a finding:

> "On the faults we cover, it is a tie. 56 against 56."

Then the four bullets underneath, and land the line:

> **"The content is not the bottleneck. The routing is."**

A committee trusts a presenter who leads with their own null result and then
explains it. That sentence is also why the proposed work looks targeted instead
of hopeful — it is the setup for slide 16's bottom row.

## 14 · The loop working — 14:00

New since the plan was written. Keep it to 60 seconds.

The point is not the pass rates, it is the *kind* of failure:

> "Negatives clean. Positives find the right evidence but under-commit.
> Cross-fault cells expose exactly one missing rule. **Never a confident wrong
> answer.**"

One example only — pick the async one, it is the most vivid: every read took
0.0 ms while every request took 500 ms, so the tool had to be rewritten.

Then the closing detail: on unseen data each blueprint solved the *other's*
fault by routing to it. That is the library behaving like a library.

## 15 · Abstention — 15:00

Two faults proven not diagnosable, matching the pre-registered catalogue. Then
the screen: 29% → 12% wrong fires, zero correct diagnoses lost.

> **"A blueprint that always produces an answer is not carrying knowledge. It
> is guessing with structure."**

## 16 · Evaluation plan — 15:45

Read the four questions, not the designs. Point at the highlighted bottom row:
that is the measured bottleneck, and it is what Phase 2 attacks.

Then the control, because it pre-empts the obvious challenge:

> "The control is deliberately unkind. A one-shot model call with a good
> deterministic brief already ties a full tool-using agent, at 27% of the
> tokens. A blueprint has to earn its place against *that*."

## 17 · Scope — 16:15

Three system kinds, one line each. Then the agentic leg as **one proof
point** — do not fork into it, it is a separate paper:

> "Same method, pointed at the agent itself. 260 runs, two coding agents,
> kernel traces only."

The memory detail is the memorable one: a limit below the agent's own
footprint kills its tools mid-task, and the agent survives to report a failed
job without knowing why.

## 18 · Timeline — 17:00

One line per phase, fast. Dwell only on Phase 4:

> "Every experiment so far handed both arms the evidence pack. So we have
> tested how to *read* the numbers, and never yet tested *what to collect* —
> which is the half a blueprint should be best at."

## 19 · Contributions + close — 17:30

Four cards, one clause each. Then stop on the closing line, word for word:

> **"…moving trace analysis from work that is repeated toward work that
> accumulates."**

Then: "Thank you — questions." Do not add anything after it.

---

## Backup slides (A1–A3)

Not presented. Jump to them when asked.

| If they ask | Go to |
|---|---|
| "Isn't this just a threshold / a runbook?" | **A1** — network: 44 wrong alone, 268/272 with the whole rule |
| "Can blueprints hurt?" / "What about portability?" | **A2** — the abstention finding, 600 runs |
| "How do you know the agent isn't cheating?" / "How is this scored?" | **A3** — the four axes, and the harness-health story |

A1's closing line is reusable in the moment: *"A threshold is not a blueprint —
and now we can say by how much."*

---

## If the slot is 15 minutes

Cut in this order:

1. **Slide 15** (abstention) — fold it into slide 13 as one bullet.
2. **Slide 14** (the loop) — it is the newest and the most cuttable; the method
   is already on slide 7.
3. **Slide 18** (timeline) — say the six phases over slide 19.

**Never cut 11, 12 or 13.** They are the evidence the committee came for, and
13 is the one that makes the rest credible.

---

## Three things to get across, in priority order

1. **This is not unstarted work.** The dataset, the agent, the blueprints and
   the first experiments exist. Every number traces to a file.
2. **The evaluation is honest.** A strong deterministic control, negative
   results kept, a tie reported as a tie, and our own plumbing bugs published
   next to the results.
3. **The remaining work is targeted.** We measured the bottleneck and the
   proposal attacks exactly that.

---

## Numbers not to say

Full list and reasons: `CONTEXT.md` §12. The four most likely to slip out:

- **"50% → 70–80%"** — in no result file, and explicitly banned by the source doc.
- **any pooled blueprint effect** across the six-problem matrices — an
  averaging artefact; the source doc says never report it.
- **"40/40 detected, 0 false alarms"** — not substantiated; the "40" is a
  runs-collected counter.
- **"<1% variation"** for the OS-noise work — disproven; wall time varies
  10–15% from model noise alone.

Also: the deck says **27 fault families** and **~304 runs**. Do not give a
breakdown that has to sum — the inventory file has four arithmetic
inconsistencies (`CONTEXT.md` §8).

---

## Mapping to `presentation-plan.md`

| Plan | Deck | Change |
|---|---|---|
| 1 Title | 1 | — |
| 2 Background | 2 | — |
| 3 Problem 1 | 3 | now built on the "history is in Mohammed's brain" quote |
| 4 Problem 2 | 4 | — |
| 5 The idea | **5 + 6** | split: anatomy, then the real discriminator on its own slide |
| 6 Two properties | 7 | now carries the three dead claims |
| 7 The framework | 8 | adds the honest "selection is manual today" |
| 8 Dataset | 9 | **27** families, not ~24; 293 usable added |
| 9 Blueprints + agent | 10 | adds the second-generation five and the 24 cells |
| 10 Headline | 11 | per-arm table; the two caveats are now on the slide |
| 11 Executable beats prose | 12 | adds the +61%-tokens negative control |
| 12 The honest tie | 13 | leads with **56% vs 56% on covered runs**, not the pooled 56/51 |
| — | **14** | new: the feedback loop and the five blueprints |
| 13 Abstention | 15 | — |
| 14 Evaluation plan | 16 | adds the deterministic-brief control |
| 15 Scope | 17 | — |
| 16 Timeline | 18 | — |
| 17 Contributions | 19 | — |
| — | **A1–A3** | new: Q&A backup |

Still to confirm before the day: exact date, audience, whether the 20 minutes
includes Q&A, and whether the venue needs PowerPoint rather than a browser.
