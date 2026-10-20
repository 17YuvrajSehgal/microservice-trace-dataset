# 19-10-2026 — decisions

## Wrote a context pack for the abstract presentation

`thesis/msc-thesis-abstract-presentation/CONTEXT.md` (~2450 lines), separate
from `presentation-plan.md`.

Why separate: the plan says *what* to put on each slide and in what order. It
does not say *why* the artifact has the shape it has, or where each number came
from. A deck-building agent needs both, and the plan was already at its useful
length.

Design rules baked into the file:

- **Every number carries a source path.** The explicit rule at the top is: if a
  number is not in the file and not in a source file, it does not go on a slide.
- **"Numbers you must not use" grew from 3 entries to 12.** Each of the 12 has
  been mis-quoted or retracted at least once in this repo's history, so the
  banned list is now as load-bearing as the allowed one.
- **Generations are labelled everywhere.** `blueprints/` (previous, source of
  all published numbers) vs `Blueprint/` (active, the October matrices), and the
  two scorers (`runs.py` vs `q2_judge.py`) are flagged as non-mixable.

## Five verification findings that change what can be claimed

These came out of checking the plan's numbers against the files rather than
trusting either.

1. **"40/40 detected, 0 false alarms" is not substantiated.** It appears only in
   `Blueprint/README.md` as that doc's one-line description of
   `1_svc_cpu_cap/EVALUATION-on-agentic-runs.md`. The evaluation file is a
   1-fault / 1-baseline qualitative case study with **no detection tally**, and
   its verdict is the opposite shape: method correct, fails out of the box on
   the agentic kernel, works after a one-line fix. The "40" in
   `provenance/campaign3.log` is a progress counter — 40 runs *collected*.
   **Removed from the slide-safe set; recorded as a doc bug to fix.**

2. **The with/without doc contradicts its own raw data, and the original is the
   correct one.** Its "CORRECTED 18 September" section claims
   `n_with_a_pick: 57, n_no_pick: 0` and concludes the 30 identical-input runs
   "do not exist in this data". Counting the raw rows in
   `blueprints/results/withwithout.json`: **30 `with`-arm runs record
   `skill: "none"`**, and on those 30 the arms score **15 vs 13**. The summary
   field counts the literal string `"none"` as a pick. So the ±2 noise argument
   stands.
   **Decision: present the doc's own recommended number instead — 56% with, 56%
   without on the 36 covered runs** (independently verified either way), and
   keep the 30-run noise argument as the backup if challenged. Safer than
   leading with the pooled 56/51, which invites exactly this argument.

3. **The fault-family count is 27, not ~24**, and
   `DATASET-v2-INVENTORY.md` has four arithmetic inconsistencies (per-family
   table sums to 303 not 304; verdicts table sums to 309; "fully usable by
   verdict" sums to 287 not 293; `no_metric_signature` reads 27 in one table and
   14 in another).
   **Decision: the slide formulation is "~304 runs — 170 SS + 134 TT — 27 fault
   families, four modalities plus a per-run metrics export", and never a
   breakdown that has to sum.** Fixing the inventory arithmetic is a separate
   job; the presentation should not wait on it.

4. **The plan's pre-slide warning about `deadlock-lock-order/blueprint.json`
   (trailing comma, invalid JSON) is stale.** All 16 `blueprints/problems/*/
   blueprint.json` parse cleanly. Checked, not assumed. Nothing to fix.

5. **`PROPOSAL.md` §5.3 and `RESULTSv2.md` disagree on the healthy-run count**
   — "declined all 8 healthy runs" vs 5/5. Use 5/5 and cite `RESULTSv2.md`, or
   say "declined every healthy run" with no number.

## Three items the 14-10 plan missed, added to the evidence act

The plan was written before the last two sessions and before these were read
closely. All three are stronger than things already on the slide list.

- **The portability finding** (`WHEN-A-BLUEPRINT-HURTS.md`, 600 runs): *a
  blueprint whose deciding check is a threshold on a quantity the deployed tools
  cannot compute will make an agent abstain, even when the signal is plainly
  visible.* Why it matters here: it is the only result that says something about
  blueprints as **portable artifacts** rather than as content, and it comes with
  its own correction history (the first explanation was wrong and re-running 360
  cells proved it).

- **The result-cap measurement.** 3,827 of 11,189 tool results were cut, every
  cut one unparseable JSON, and the field that identified an *already-running*
  container reached the model 4.7% of the time while the field identifying a
  *spawned* one reached it 99.3%. The WHERE scores split exactly along that
  line on both apps (spawn 40–55/60, already-running 0–24/60) — while peak
  context use was 6.6%. Why it matters: it is the most convincing possible
  argument for "check the harness before believing the score", and it reads as
  rigour rather than as an admission.

- **`RESULTS-blueprint-cards.md`'s "one number alone vs the whole rule" table.**
  Retransmission alone gets 44 of 272 runs wrong; the whole rule gets 268 of
  272 right. *"A threshold is not a blueprint, and now we can say by how much."*
  Why: it answers the runbook question and the threshold question in one table,
  with no model involved.

## The introduction comes from `blueprint-idea.md`, not from the abstract

Decision: build the problem slides on the 26-08 meeting's own words rather than
on an abstract framing of knowledge loss.

Why: the two anecdotes in that file are concrete and human in a way the abstract
deliberately is not — *"there is no history, the history is in Mohammed's
brain"*, and Naser's own account of an AI tool that works well when pointed at a
document and *"again tries to download a 50 GB model from Hugging Face and
reinvent the workflow"* when he forgets to mention it. The second one is the
whole thesis in one paragraph, including the part about a human verifying the
document first.

Second reason: the same file shows the **six-step validation loop was
pre-registered in August** and is, verbatim, what the five October blueprint
matrices executed. That ordering is worth stating out loud to a committee.

Also surfaced from it and now in the context pack: the **21 August control
measurement** — a one-shot model call with a good deterministic brief ties the
full tool-using agent (78% / 52% both ways, at 27% of the tokens). That is why
the brief is in *both* arms of every with/without run, and it is the honest
reason the headline is a tie. It belongs next to RQ1, not buried in RQ3.

## Noted, not fixed

- `progress-notes/next-steps.md` is dated **17 September** and is still about
  Train Ticket collection. The required session habit kept producing daily
  `decisions.md` files but stopped updating the summary. Anyone reading the file
  named "next steps" will be a month behind.
- `CLAUDE.md` still names `agentic-rca/` as "the primary track" — one generation
  behind the 16-10 decision that `Blueprint/` is the active workspace.
- `agentic-rca/AGENT-V2-ARCHITECTURE.md` says `MAX_WORKER_STEPS = 12`; the code
  says 18.

All three are listed in the context pack's stale-docs table so the deck is not
built off them.

## Built the deck

`thesis/msc-thesis-abstract-presentation/slides.html` (22 slides) +
`SPEAKER-NOTES.md`.

**Format: self-contained HTML, not PowerPoint or Beamer.** Three reasons, in
order: the repo already presents from exactly this format
(`blueprints/docs/presentations/presentation1/`), so the visual system and the
tooling are both proven; there is no TeX engine on this box, so a Beamer deck
could not be compiled or checked here; and HTML renders anywhere without an
install, including from a phone if the projector fails. Reused that deck's
token palette rather than inventing one — teal for confirmed results, rust for
retractions and negatives — so the two decks read as one body of work. Type
scale pushed up, since this is projected rather than read at a desk.

Added for presenting: arrow-key and space navigation, a progress bar, and a
**target clock time in each slide's footer** so the dry run can be checked
against the plan's timings without a separate script. 19 content slides ending
at 17:30.

### Deck decisions that depart from the 14-10 plan

- **Split the idea slide in two.** The anatomy is one slide; the real
  discriminator gets its own. Why: the runqueue-delay row — measured at 7.12×
  and then *demoted to corroboration* — is the single thing that shows what
  "evidence-bound" buys, and it was competing with six anatomy bullets for
  attention. It now sits alone with the 52× / 15.7× / 7.1× / 3.7× table
  underneath, which shows the signal is strongest on the faults it is supposed
  to rule *out*.
- **Lead the tie slide with 56% vs 56% on the 36 covered runs**, not the pooled
  56/51. Why: that is the source doc's own recommended number, it is verified
  against the raw JSON, and it does not invite the argument about the buggy
  `n_no_pick` field. The pooled figure adds nothing the covered split does not
  already say.
- **Put the two caveats for the 30/30 result on the slide itself** (one
  incident per matrix; blueprint handed over, not chosen). Why: volunteering
  them is worth more than surviving being asked, and the result is strong
  enough to carry them.
- **New slide for the agent-feedback loop** (five blueprints, 24 verdict cells,
  zero confident wrong answers). The plan predates it. Framed around the
  *failure mode* rather than the pass rates — negatives clean, positives
  under-commit, cross-cells expose one missing rule — because that is what
  shows the method working rather than a score improving.
- **Said "selection is manual today" out loud on the framework slide**, three
  slides before the tie slide proves it is the bottleneck. Why: admitting it
  first makes the later null result read as diagnosis rather than as excuse.
- **Three backup slides instead of a Q&A script**: the
  threshold-vs-whole-rule table, the portability/abstention finding, and the
  scoring axes with the harness-health story. These are the three questions the
  context pack predicts are most likely, and each needs a table that cannot be
  improvised.
- **Kept the agentic OS-noise work to a single proof point** on the scope
  slide, per the 15-10 decision. It is a separate paper.

## New paper: ICSE 2027 NIER on agent context/memory structure

Deadline **confirmed from the CFP site: Fri 23 Oct 2026, 23:59:59 AoE** — four
days. 4 pages main + 1 page refs, IEEEtran 10pt conference, **double-anonymous**,
mandatory section titled **"Future Plans"**. The call explicitly rejects
"scaled-down research papers lacking evaluation" and "op-eds recycling published
work". So the paper needs a real experiment, not a retrospective.

Work lives in `nier-2027/`.

### The topic is a departure from the recorded plan, deliberately

`meeting-notes/todo-points-09-09-2026.md` records NIER as the venue for **the
blueprint work**. We are instead writing the **context/memory** paper. Why this
is the better call, and worth putting to Naser:

- The blueprint work is the **thesis**. It wants 10+ pages (dataset, library,
  method, four experiments). Cutting it to 4 pages loses exactly the evidence
  that makes it credible, and NIER's own call warns against scaled-down full
  papers.
- The context finding is **one sharp idea with a surprising result** — which is
  what NIER is for. It is also self-contained, so it does not spend the
  thesis's novelty a year early.
- G4 (Naser's "write the NIER story in one page") is now done either way:
  `nier-2027/STORY.md`.

### The idea

Everyone treats agent context as a **capacity** problem. We instrumented a real
tool-using agent against verifiable ground truth and found the window used to
**6.6%** while **a third of all tool results were being destroyed in transit**.

Context is not a window, it is the output of a **pipeline** — serialize,
truncate, retain, transfer, persist — and every stage is a lossy transform an
engineer wrote. The failure modes are engineering defects that masquerade as
model or data limits.

The central artifact: our 6000-char cap sliced the JSON **string**, and because
key order is preserved that **deletes late keys** rather than sampling. Whether
a culprit process lands in an early or late key is decided by **whether it
spawned during the trace** — so the defect partitioned the benchmark into a
solvable and an unsolvable half along an axis with no scientific meaning.
Measured: spawn faults 40–55/60, already-running 0–24/60. We had read that as a
finding about kernel traces.

### What was decided about evidence

The existing evidence is **correlational**, and a reviewer would be right to say
so: the repair shipped alongside two new tools, so the Q2 re-run that moved
scores is confounded by a capability change. So the one new experiment is a
**controlled ablation of the memory pipeline** — reintroduce each defect alone,
agent/data/task/model fixed. Design and **pre-registered predictions** (written
before any run, so results cannot be fitted) are in `nier-2027/DESIGN.md`.

### Feasibility established today, and it is all local

- **322 local runs** with cgroup ground truth; raw CTF **and** decoded dumps.
- Local `babeltrace2` is **2.1.2** — the version our traces need. No cluster.
- Trillium is **not** reachable non-interactively (MFA), so the design
  deliberately avoids it.
- Four ablation knobs made env-overridable in `Blueprint/agent/`
  (`ABL_FLAT_CAP`, `ABL_WORKER_STEPS`, `ABL_THREAD_BUDGET`, `ABL_NO_COMPUTED`).
  **25 additive lines, defaults verified unchanged**, full import chain OK. S5
  (cross-run memory) is held constant, never varied — carrying memory between
  runs would break the independence the scores assume.
- Campaign estimate: ~100 runs, **~$8 and 4–6 h** at 3 parallel.

### E1 is already done, and it cost nothing

`nier-2027/mechanism_delivery.py` + `E1-delivery-cliff.csv`. A deterministic
sweep, no model calls, no data: as the number of short-lived processes in a
trace rises, the late key goes from fully delivered to **completely unusable**
the moment the result crosses the cap (at 40 spawned processes here), and the
payload becomes invalid JSON. Under the repair all 25 rows survive at every
size.

This matters because it explains the field number mechanically — busy hosts have
well over 40 short-lived processes, which is why the late key reached the model
in only 4.7% of 742 real calls. It also means the paper has a guaranteed
mechanism figure even if the LLM campaign misbehaves.

## Framework vision document

`thesis/msc-thesis-abstract-presentation/framework-vision.html` — four
hand-authored SVG figures plus a worked walk of "the front-end is very slow"
from complaint to verdict.

**The organising decision: a build-status encoding carried through every
figure.** Filled + solid = built and measured; hollow + dashed = designed, no
code; dotted rust = measured and proven unreachable. One literal hue (the teal)
is spent on exactly one element — the SELECT stage — because that is the
measured bottleneck, so the diagram's colour points at the research question
rather than decorating it.

Why that encoding and not a clean architecture drawing: a framework diagram
with every box drawn the same way reads as a claim that all of it exists. Half
of it does. Running a blueprint and deciding from it are built; understanding a
vague complaint and choosing from the library are not. Drawing that difference
makes the diagram honest *and* makes the proposal legible — the undrawn half is
the thesis.

Four figures, one claim each (rather than one combined diagram):

1. **the run-time path** — the library sits *above* the pipeline, not inside it,
   because it supplies two different things at two different moments: candidates
   while deciding what this might be, and instructions once decided. Also shows
   the two returns: `rule_out` sends control back to selection instead of
   forcing a verdict, and the dashed frame is the collection feedback loop.
2. **inside selection** — a funnel, 21 → 4 → shortlist → 1. The claim is the
   anti-brute-force one: a reviewer will ask why not run all 21, and the answer
   is the cheap prechecks. Caption names the gap honestly — those prechecks are
   currently prose, so a program cannot run them.
3. **the hierarchy** — latency parent routing to 12 causes, with the two proven
   unreachable ones *left on the diagram* in rust. A library that knows its own
   boundary is worth more than one that answers everything.
4. **how a blueprint is born** — the measure-first chain with the agent-failure
   return arc. Caption points at stage 02 as the one that costs something.

**Labelled the worked example as an illustration, in a callout, before the
walk.** The stages are the designed ones and the numbers are real measured
discriminators from our blueprints, but no single run produced that exact
sequence. Without the label it would read as a recorded result, which is the
exact failure mode the CONTEXT.md number discipline exists to prevent.

Included a branch-that-did-not-fire stage in the walk (what happens if the CPU
gate finds waits, or the pool check finds one slow socket). Why: the framework's
distinguishing behaviour is refusal, and a walk that only shows the happy path
would not show it.

## Laid out thesis/flow.drawio

The scratch file had the right icons but no layout and no edges. Rebuilt it as
three numbered bands — **1 COLLECT · 2 AUTHOR · 3 USE** — with a feedback loop
closing from VERDICT back to the blueprint.

Decisions worth keeping:

- **Three bands, not one flow.** The three are different *kinds* of activity on
  different timescales: collection happens once per campaign, authoring once per
  problem, use once per incident. Drawing them as a single chain would imply
  they run in sequence every time, which is the misreading to avoid.
- **The library sits between bands 2 and 3**, fed by AUTHOR and feeding SELECT.
  That placement is the whole argument for why this accumulates: the output of
  band 2 is the input to band 3, and band 3 feeds back into band 2.
- **SELECT is the only box with a different fill and a heavier stroke** (teal,
  8px). It is the measured bottleneck, so it is the one element the eye should
  land on. Everything else is uniform on purpose.
- **Kept every icon from the scratch file** so nothing fails to resolve in
  draw.io; dropped only `pc_man` and `sagemaker_model`, which had no job once
  Analysis_Services carried "measure" and the robot carried "the agent".
- **Labelled only the six edges that carry information** (`one run bundle`,
  `every claim is measured on this data`, `candidates`, `a rule-out fired`,
  `+1 in the library`, `FEEDBACK`). The eleven within-band chain arrows are left
  bare — the sequence is already obvious and labelling them would be noise.
- **`&nbsp;` replaced with `&#160;`.** draw.io tolerates the named entity but it
  is not valid XML, so anything that parses the file strictly chokes on it.

Validated programmatically rather than by eye: XML parses, 43 vertices and 17
edges with no dangling endpoints, nothing outside the page, no unintended
overlaps, and every band child actually inside its band.

Original kept at `thesis/flow.drawio.bak`.
