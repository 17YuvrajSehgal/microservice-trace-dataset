# Decisions, 30 September 2026

## The meeting redirected the work from breadth to depth

Full task list in `meeting-notes/ACTIONS-30-09-2026.md`.

The bulk-reference approach was rejected outright. Over 100 papers collected, to be attached
across the blueprints; Naser: "trying to add those papers randomly or kind of blindly to those
blueprints. This does not work. This will not work. No, I can guarantee."

The replacement is one category, one problem, about ten papers, one blueprint done properly,
evaluated, and written up. Then repeat.

**Why this is right, not just instructed.** We have 16 blueprints and ZERO reference entries in
any of them - checked, the field is empty in all 16. So the criticism is exact. And the thing being
asked for is understanding, which is the one input a blueprint cannot fake: our own measurements
caught three cases this month where a blueprint claim was wrong, and each was caught by measuring,
not by citing.

## Consequence: the 11-problem campaign waits

This week's harness work stands - the worker cut-off fix, ctf_lines scan truncation, the cell
timeout, the raised limits. Those are needed whatever we run.

But the campaign itself is breadth, and breadth is now the wrong next move. One problem finished to
the standard described, first.

## A third evaluation arm is needed and does not exist

Naser asked to "force AI to not only follow your blueprint, but also don't use anything else, just
your blueprint and instruction".

We run `none` and `given`. `given` cannot separate "the blueprint helped" from "the model already
knew" - the agent keeps its own knowledge in that arm. A blueprint-only arm can. Worth building
before the next matrix rather than after.

Also: report TIME alongside accuracy. We already record wall seconds per cell; it just never
reached the report.

## Mahsa: prioritise the papers' source code over their prose

Her reasoning is that a repo shows how a symptom is actually detected, where the paper only claims
it. She is also openly unsure textual references help once injected into a prompt: "I don't know
how much they could be helpful when we put it or integrate it in the prompt."

That is a testable claim and we should test it rather than assume it. The blueprint-only arm is the
natural place - it isolates what the supplied text alone contributes.

## Two repo problems found while checking

- All 16 blueprints have zero references. Recorded above.
- `deadlock-lock-order/blueprint.json` does not parse - trailing comma, line 253. Invisible because
  the generated `skill.md` is what the agent runs, so the 60-cell deadlock matrix succeeded anyway.
  The validator skips unparseable files instead of failing on them, which is how it hid.

## A tracepoint in the literature no longer exists

Naser, live in the meeting: `sched_ttwu` / "try to wake up" is "gone forever. The Linux kernel
doesn't have that event anymore." Only `sched_waking` and `sched_wakeup` now.

Worth noting as a general hazard, not a one-off: papers from a few years ago name tracepoints that
have since been removed. Any event taken from a paper has to be checked against a real trace before
it enters a blueprint.
