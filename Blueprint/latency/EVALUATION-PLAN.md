# Evaluation plan for the blueprints and the agent

Status: **proposal, 24-11-2026. Nothing here has been run.** The numbers for cost are
estimates from the single runs of 20 to 24 November and from the earlier tool sweeps. The
splits and the scoring rules in this file are meant to be fixed BEFORE the runs start; after
that they change only with a dated note at the end of this file.

## 1. What we have today, and why it is not enough

- 25 blueprints in the new form. 17 have a tool sweep on all 304 labelled runs.
- The agent was run once per family: one Sock Shop run, one model (`gpt-6-luna`).
- The tool sweeps took the slice time from the label. An agent on a real trace has no label.
- The harness and the scan tool were changed between tries on the same runs.

So today we can say "it can work". We cannot give a rate.

## 2. Questions

| # | Question | Answered by |
|---|---|---|
| Q1 | Does a blueprint find its own fault when the time is not given? | arms T and A, own-family runs |
| Q2 | Does it stay silent on other faults and on normal runs? | arms T and A, other runs |
| Q3 | What does the agent add to the tools alone? | arm A against arm T |
| Q4 | Which part of a blueprint gives the gain? | arm B (ablation) against arm A |
| Q5 | Do the rules hold on data they were not set on? | section 5 |
| Q6 | Does the result depend on the model, or on chance? | arm M (second model), arm R (repeats) |

## 3. Data

Sock Shop 170 runs, Train Ticket 134 runs, 304 in total, 20 of them normal (fault-free).
Counts per family are in `blueprints/docs/DATASET-v2-INVENTORY.md`.

Left out of every count, and listed as such in the results:

- `code_lock_across_io` (5 runs): no blueprint, no signal at this load.
- The two runs that cannot be sliced (`anomaly_mem_subtle_steady_r3`,
  `svc_mem_cap_aggressive_steady_r5`).
- Blueprints 0, 8, 9, 10: their traces are the partner's and are not part of this plan.
- Blueprint 7: no labelled family.

Runs with a known caveat (11, listed in the inventory) stay in, and are reported as a
separate row so they can be taken out.

## 4. Arms

**T. Tools only, no model.** For every run and every blueprint whose decisive check prints a
verdict line: the scan as the harness does it (slices end to end over the trace, the check
on each, first and last slice as baselines). Fixed rule: the blueprint "fires" if any slice
gives its confirming line. No judgment anywhere. This is the baseline a reviewer will ask
for, and it also measures how much a result depends on where the slice falls (TO-FIX C32).

**A. Agent, blueprint given.** The graph harness as it is on the frozen commit.

- Own family: every usable fault run with its own blueprint, once. About 275 runs.
- Other runs: for each of the 21 blueprints, 4 normal runs and 6 runs of other families,
  drawn once with a fixed seed and written to a file before the runs. About 210 runs.

**B. Ablation.** On 2 runs per family per application (about 85 runs), two more variants:

- B1: the tools and their descriptions, no blueprint steps.
- B2: the blueprint as one text in the prompt (how we used blueprints before), same tools.

Arm A is the third variant. B1 and B2 need a small harness change, which must be made and
self-checked before the freeze.

**M. Second model.** The arm A runs of the ablation subset (about 85 own-family runs and
60 other runs) with one more model. Which model is open (section 9).

**R. Repeats.** The ablation subset of arm A two more times with the main model, to see how
much one run varies.

Not in this plan: a selector that picks the blueprint. Every arm here is given the
blueprint. That is a limit of the claim, and it is stated with the results.

## 5. Held-out testing: what we can and cannot claim

A clean held-out test needs runs the rules were never set on. We do not have that for all
blueprints: several rules were changed after sweeps on all 304 runs of both applications
(for example the disk-wait bar of blueprint 16, the freeze-moment rule of 15, the two rules
of 24).

Two levels, both reported, and named as what they are:

1. **Weak, now.** For each blueprint, the rule history says which runs changed a rule.
   Blueprints whose rules were set on Sock Shop only are reported on Train Ticket as
   "application not used for the rule". The others are reported as "rule set with both
   applications in view". The table of which blueprint is which is made from the rule
   histories and the decisions files before the runs.
2. **Strong, later.** Freeze the tools and the blueprint files with a git tag. Any run
   collected after that tag is a clean test. The next collection is already planned
   (`CANDIDATE-PROBLEMS.md`); adding 2 fresh runs per existing family to it gives a clean
   test for all of them. This needs a new VM and is a cost decision (section 9).

## 6. Scoring, by script

Each run gets one of five labels. The script reads the result file and the run's
`ground_truth.json`; nobody reads reports by hand.

| label | rule |
|---|---|
| right | verdict `confirmed`, the fault type is the labelled family, and the named process belongs to the labelled target |
| right fault, wrong process | verdict `confirmed`, fault type right, process not the target |
| not committed | `unconfirmed` or `inconclusive` |
| missed | `rejected` on an own-family run |
| false alarm | `confirmed` on a run of another family or a normal run |

Fixed in advance:

- `dependency_outage` and `queue_backlog` count as one family (the trace cannot tell them
  apart; the blueprint says so).
- A fault whose target is the host (`anomaly_*`, `noisy_neighbor`) is "right" when the
  injected program is named.
- "The process belongs to the target" is checked with the container list in the run's
  `meta/` folder. If that list cannot map a process, the run is scored by fault type only
  and counted in a separate column. I have not yet checked that every run has this list.
- Known look-alikes that are real (the edge router in blueprint 12, `resource_abuse` under
  blueprint 11) are counted as false alarms AND shown as their own row.

Also reported per run: error of the found fault window against the label, steps followed
and left, share of evidence lines found in tool output, model calls, tokens, wall time.

## 7. Where it runs

The tools need babeltrace and the traces, so they run on Trillium. The model needs the
internet. Two things I do not know yet and will test with one short job before anything
else:

- Whether a Trillium compute node can reach the API. If yes, the agent runs inside the job.
- If not: the agent process stays on the login node (it only makes API calls) and sends its
  tool calls to a compute node held by a batch job. The runner already works over ssh.

No sweep runs on the login node. Before each submission: `sbatch --test-only`, and the
LevelFS number.

LevelFS today (24-11): group `def-naser2` 24.05, user 0.25. The group has used far less
than its share; within the group this user has used most of it.

## 8. Cost (estimates, to be replaced by the pilot's numbers)

| arm | runs | compute | model tokens in / out |
|---|---|---|---|
| pilot: 10 runs through T and A | 10 | under 1 node-hour | about 0.6M / 0.03M |
| T | 304 x about 18 checks, 12 slices each | 8 to 12 node-hours (one 192-core node) | none |
| A | about 485 | 6 to 10 node-hours | about 27M / 1.5M |
| B1, B2 | about 170 | 2 to 4 node-hours | about 9M / 0.5M |
| M | about 145 | 2 to 3 node-hours | about 8M / 0.4M |
| R | about 290 | 4 to 6 node-hours | about 16M / 0.8M |
| total | | 22 to 35 node-hours | about 60M / 3.2M |

Where the numbers come from: one agent run used 13k to 120k input tokens (about 55k with a
scan) and 1k to 5k output tokens. One slice cost about 1.2 core-minutes in the earlier
sweeps. I do not know the price per token of `gpt-6-luna`, so there is no dollar figure
here; the token count has to be multiplied by the current price.

The lock blueprints (11, 14) cut very large slices. Their scans may need shorter slices or
fewer of them; the pilot decides.

## 9. Order, with a stop after each step

1. **Freeze.** Close the harness items that would change results (ablation variants, the
   scorer, the list of runs per arm with its seed). Tag the commit.
2. **Pilot**, 10 runs. Fixes the cost numbers and shows that the scorer works.
3. **Arm T.** No API cost. Its result alone answers Q1 and Q2 for the tools.
4. **Arm A.**
5. **Arms B, M, R.**
6. **Write-up**: one table per question, and every failed run listed with its cause.

Decisions needed before step 1:

- The pass bars of METHOD.md Steps 4 and 5 (they are still my proposal).
- The second model for arm M (a local model on Nibi costs GPU hours and no API money).
- The API budget: about 60M input tokens in total, or a smaller plan (arm A only is 27M).
- Whether the next collection gets 2 fresh runs per existing family for the strong
  held-out test.

## 10. What this plan will not show

- Nothing about choosing the blueprint (no selector).
- Nothing about faults outside the 27 labelled families, or about two faults at once.
- Two applications on one kind of machine. Bare-metal hosts are not covered.
- Blueprints 1 and 3 enter with no earlier tool sweep; their rows are a first measurement.

## Changes after the freeze

(none)
