# 16-09-2026 — decisions

## 1. Re-ran 3 Sock Shop families. One of the three got worse.

We re-collected `fd_exhaustion`, `lock_contention` and `deadlock`. 5 runs each.

The reason for picking these three: each one had *partly* worked before. So the recipe
clearly works on this app, and the failures looked like bad luck rather than a broken
recipe. That was the guess.

| family | before | after | |
|---|---|---|---|
| `lock_contention` | 2 of 5 | 5 of 5 | better |
| `deadlock` | 4 of 5 | 5 of 5 | better |
| `fd_exhaustion` | 2 of 5 | **0 of 5** | worse |

**Why this matters:** the guess held for two families and failed for one. `fd_exhaustion`
does not fail by luck. It fails every time now. Re-running it was the wrong call.

**Next step, not yet done:** `unconfirmed` means the *metric* checks did not see the fault.
`fd_exhaustion` shows up in the kernel trace as `accept` and `socket` returning EMFILE.
That is the same shape as `dns_delay` and the code defects. If the kernel trace shows it,
the family belongs in `expected_to_fail`, not in the re-collect list. **This is a guess.
It needs checking against the 5 new traces.**

## 2. Wrote the plan for testing whether blueprints help

New doc: `blueprints/docs/EVAL-PLAN-effectiveness.md`.

**Why now:** the September with/without test came out a tie. Before running anything else
we wrote down what we will test and what would count as a win. Setting the line first
means we cannot move it later.

Three things from September drive the plan:

- Picking the wrong blueprint caused every bad case. No blueprint gave bad advice about
  its own fault.
- The rule engine gets 38 of 41 right. The same rules given to the model as text get about
  half.
- Both sides got the evidence pack. So we tested "how to read the numbers" and never
  tested "what to collect".

The plan adds two setups to fix that. One ships the decision as code instead of text. One
gives the agent **no** evidence pack, so the blueprint has to say what to collect.

It also adds early detection, which nothing measures today. Feed the agent a growing slice
of the incident window and record when the answer first becomes right. Our runs already
have the stamps needed for this, so it needs no new collection.

**Reporting note:** a setup that ties on accuracy but answers in 30 s instead of 120 s is
still worth having. Accuracy alone would hide that.

## 3. Added a reading order for the repo

New doc: `READING-ORDER.md`.

**Why:** about 120 markdown files exist and there was no way to tell which are current.
Three are exact copies of each other. One doc supersedes another while both stay in the
tree. Every entry was written after opening the file, not guessed from the name.
