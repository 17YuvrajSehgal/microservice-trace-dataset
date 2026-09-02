# 01-09-2026 — the with/without experiment

## What we set out to measure

The supervisor asked for this on 26-08-2026 and we had never measured it: **does having a
blueprint beat not having one?**

Design, and why each part is there:

| Arm | Gets |
|---|---|
| without | model + evidence pack + deterministic brief |
| with | model + evidence pack + deterministic brief + the 6 blueprints |

Same model (azure/gpt-5.4), same evidence, same incidents. One difference.

**Why the brief is on in BOTH arms.** It would be easy to win by comparing against a weak
control. The brief-only agent is the version that already tied the full tool-using agent in
our earlier work, so it is the strong control. If blueprints only beat a strawman, they are
worth nothing.

**Why the selector cannot cheat.** It sees only the masked evidence survey. Nothing in it
states the problem, and `covers:` is harness metadata stripped before the model sees
anything.

Scope: 12 families on Sock Shop, 7 on Train Ticket — every family with a complete evidence
pack. Four parallel streams (app x arm).

## Three bugs found while wiring it up

All three were on our side, and two of them would have produced a believable but wrong
number. Worth recording because the pattern repeats.

**1. Two leak lists that disagreed.** `blueprint_to_skill.py` had its own list of
answer-bearing words; `agentic-rca/skillreg.py` lints with a different one and *refuses* a
dirty library. Our validator said 6/6 fine; the harness killed the job at load time.

Fix: the generator now imports the harness regex. A producer should never get to hold its
own opinion about what the consumer will accept.

**2. `ground_truth` in the runnable commands.** Our analysis scripts take
`--gt <ground_truth>`, and that string reached the skill body. The lint is right to ban it
bluntly even as a placeholder — a skill telling the model to open a ground-truth file is
exactly the shape of a leak. Renamed to `<window>`, which is also more honest about what the
file is used for.

Note the fix had to go in `providers.json`, not `blueprint.json`. Steps declare a
*capability*; the command text comes from the binding. Editing the obvious file was not
enough and the second regeneration caught it.

Two English false positives came out of the same lint: "orders of magnitude" and "collection
orders" both contain a real service name. We reworded rather than special-casing the lint.
A blunt banned-word list that occasionally catches prose is the right trade; loosening it to
allow "orders" would let the real leak through.

**3. `covers:` swallowed a trailing comment.** We rendered
`covers: noisy_neighbor    # harness metadata...`. `skillreg` parses frontmatter with
`split(":", 1)` and keeps the whole remainder, so the value never equalled any ground-truth
family. **Every selection would have scored wrong** and the with-arm would have looked far
worse than it is — a quiet, plausible, completely wrong result.

This is the second time this field has bitten us (28-08: invented `fault_type` labels).
Both times the cause was the same: a field that is read by two different consumers.

**Method note.** We verified the fix by loading through the harness itself in strict mode,
not by re-running our own validator. Our validator was the thing that was wrong.

## Report design

`blueprints/lib/withwithout_report.py` deliberately does **not** lead with one pooled
average. It splits by whether a blueprint covers the family, because:

- lift should land on covered families — that is the claim
- uncovered families are the control for the opposite risk: that an irrelevant library
  misleads a model that would otherwise have been right

It also reports silent runs. Abstention is the honest outcome when kernel data cannot
separate a fault, and the without-arm has no particular reason to abstain, so a rise in
"don't know" is a result, not a failure.

First draft of that report was written against guessed field names and would have scored
every run zero — caught by reading `evaluate.py` before the arms finished, not after.

## The run itself: Slurm was the wrong place, and we already knew

First launch was an sbatch. Every completed incident came back **"Request timed out."**, 0
tool calls, no diagnosis — 29 zeros on Train Ticket before we killed it.

Cause was measured months ago and written down in `agentic-rca/RESULTS-agent-sanitygate.md`:

> Compute nodes have no internet (verified: curl to the Azure endpoint times out, no proxy)
> — so agent runs cannot be Slurm batch jobs.

The sbatch was wrong the moment it was written. What made it worse: the two `with` arms died
early on the skill lint, so the only thing left running was the arm that *looked* like it was
working. A file of 29 zeros scores as "the model got everything wrong", which is a believable
number. Deleted rather than kept.

**Lesson for this repo, not a general one:** before running anything that calls the model,
check whether it is on a node that can reach the model. The constraint is in
RESULTS-agent-sanitygate.md and it is easy to walk past.

Now on the login node, following the v4 campaign pattern that is known to work there:

- one fresh python **per family** — the login-node watchdog kills long cumulative processes
  (one incident is fine, 23 back-to-back got killed)
- skip-if-exists, so it resumes instead of restarting
- four streams (arm x app) at once; ~7 GB each against 755 GB is free
- `--per-family 3`, so up to 36 Sock Shop + 21 Train Ticket incidents per arm

Smoke-tested one incident on the login node first (correct, real diagnosis) before spending
the rest.

Two more small bugs on the way, both caught by running rather than reading:

- `local dir=... out="$dir/..."` — bash expands every word of a `local` before assigning any,
  so `dir` was unset. Fatal under `set -u`; all four streams died in under a second.
- the first scorer was written against guessed field names and would have scored every run
  zero. Caught by reading `evaluate.py` while the arms were still running.

Three of the four failures so far would have produced a plausible wrong number rather than an
obvious crash. That is the pattern worth remembering from today.
