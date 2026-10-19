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
