# Experiment design + pre-registration

Written 19 Oct 2026, **before any ablation run**. Deadline 23 Oct.
Predictions are fixed here so results cannot be fitted afterwards.

## The gap this closes

What we already have is **correlational**. We observed that delivery rate and
diagnosability split along the same line, and we explained the mechanism. We
never held everything else constant and re-introduced the defect.

A reviewer can fairly say: *you had a bug, you fixed it, and the fix shipped
alongside two new tools — so you cannot attribute anything.* They would be
right. The Q2 re-run that moved scores added `ctf_procdiff` and `ctf_proclife`;
that is a **capability** change, confounded with the cap repair.

So the one new experiment is: **re-introduce each pipeline defect on its own,
with the agent, data, task and model held fixed.**

## What is already measured (reused, not re-run)

| Evidence | Source |
|---|---|
| 3,827/11,189 results cut; all unparseable | `agentic-rca/agent.py` header, 720-run campaign |
| 4.7% vs 99.3% per-key delivery over 742 calls | same |
| spawn 40–55/60 vs already-running 0–24/60 | `docs/{SOCK-SHOP,TRAIN-TICKET}-RESULTS-22-09-2026.md` |
| 6.6% median / 23k-of-400k peak context use | `agentic-rca/agent.py` header |
| step wall: flat 7–11 then 280 at exactly 12; 51% hitting it | `agent_v2.py` header, 554 workers |
| 234/554 out of steps, 98 recorded nothing | `agent_v2.py` |
| thread re-send is quadratic: 303k → 545k tokens | `agent_v2.py` |
| structure substitutes: 1.41M → 0.49M tokens, same verdict | `progress-notes/16-10-2026` |
| brief ties tool-using agent at 27% of tokens | `blueprint-idea.md` |
| ~84% of agent wall is model wait | `Blueprint/research-paper/LLM-SHARE-RESULT.md` |

## The platform (all local, no cluster, no new collection)

- **322 runs** with cgroup ground truth, local on disk.
- Raw CTF **and** decoded dumps; local `babeltrace2` is **2.1.2**, the version
  our traces need.
- Agent: `Blueprint/agent/agent_v2.py`, 13 modules, takes a run directory.
- Scorer: the existing WHERE / WHEN / earliness / WHAT axes.
- Model: fixed, temperature 0, one provider, pinned upstream.

## Independent variable: the memory pipeline

Five boundaries. Each has a **defective** setting (what v1 shipped) and a
**repaired** one (what we run now). Only the knob under test moves.

| # | Stage | Defective | Repaired |
|---|---|---|---|
| S1 | serialize / deliver | flat 6000-char prefix slice of the JSON string | per-tool budget, drop whole **rows**, label what was dropped |
| S2 | step budget | `MAX_WORKER_STEPS=12` (the measured wall) | 18 |
| S3 | within-phase retention | `THREAD_BUDGET=80,000` | 150,000 |
| S4 | phase transfer | voluntary `note_finding` only | + automatic `computed` capture |
| S5 | cross-run memory | none | none — **held constant**, never varied |

S5 stays off in every cell. Carrying memory between runs would make later runs
easier than earlier ones and destroy the independence the scores assume.

## Conditions: the interaction is the point

The mechanism predicts the defect's cost depends on **whether the culprit
process spawned during the trace.**

| Class | Runs | Why it is this class |
|---|---|---|
| **already-running culprit** | `t3_implement_cap25` | the agent's own process is throttled; it was alive before the window |
| **spawned culprit** | `t4_w16` | workers are launched by `xargs -P`, so they appear mid-trace |
| **healthy** | `t3_implement_nocap` | negative control, no fault to find |

## Cells

Core interaction (the headline), 10 runs per cell:

|  | S1 repaired | S1 defective |
|---|---|---|
| already-running | 10 | 10 |
| spawned | 10 | 10 |

One-factor-at-a-time on the already-running class, 10 each: **S2**, **S3**,
**S4** defective. Plus **all-defective** (the as-shipped v1 config), 10.
Plus healthy negatives under repaired and all-defective, 5 each.

**Total ≈ 100 agent runs.** At measured rates (~$0.08/run, 3 parallel) that is
**roughly $8 and 4–6 hours** — one overnight campaign.

## Dependent variables

**Task** (existing scorer): fault class correct; culprit container/process
correct, verified against the true namespace; window IoU; abstention.

**Attrition (the new instrument).** Per stage, per run:

| Stage | Metric |
|---|---|
| S1 | % of tool results truncated; % of truncated that are invalid JSON; **per-key delivery rate** |
| S2 | % of workers hitting the step wall; findings recorded, cut-off vs concluded |
| S3 | % of steps where trimming fired; thread chars at peak |
| S4 | % of workers transferring nothing; **evidence computed but never reported** |
| all | **evidence yield** = reached the decision ÷ produced |

**Cost**: input tokens, wall time, peak prompt as a share of the window.

## Pre-registered predictions

**H1 — capacity is not the binding constraint.** Peak context use stays under
20% of the window in **every** cell, including all-defective.
*Falsified if* any configuration exceeds 50%.

**H2 — the defect partitions the benchmark (the headline).** S1-defective costs
little or nothing on **spawned** culprits and a large amount on
**already-running** culprits. Formally: a significant interaction between S1
and fault class, with the already-running drop at least 3x the spawned drop.
*Falsified if* the two classes degrade by similar amounts, or if neither does.

**H3 — S4 changes the kind of error, not just the rate.** Removing the
automatic transfer channel shifts failures toward **confident false negatives**
("normal") rather than wrong culprits, because silence from a worker is
indistinguishable from "checked and found nothing."
*Falsified if* the wrong-culprit rate rises as much as the false-negative rate.

**H4 — attrition predicts accuracy better than context size does.** Across all
cells, evidence yield correlates with task accuracy more strongly than peak
context utilisation does.
*Falsified if* utilisation is the better predictor.

**H5 — structure beats capacity.** The blueprint-guided arm reaches the same
verdict on fewer input tokens than free exploration. Already observed at 35%;
this re-tests it inside the same harness.

## Threats we will state in the paper

- **One harness, one task domain, one model family.** We claim the defect class
  generalises because the pipeline is unavoidable, not because we tested
  others. A survey of open-source harnesses' truncation code is named as future
  work, and is the obvious next step.
- **The agentic runs are a narrower fault set** than the two microservice
  applications (4 cgroup limit classes vs 27 families). We use them because
  they are local and have exact cgroup ground truth; the 27-family data on the
  cluster is the scale-up.
- **n=10 per cell.** The noise floor on this harness has been ~2 runs in 30
  historically, so we report ranges, and H2 asks for a 3x ratio rather than a
  marginal difference.
- **We are the authors of the defect.** That is why the design is an ablation
  with pre-registered predictions rather than a narrative about our own repair.

## Order of work

1. Make the five knobs env-overridable. Defaults unchanged, so current
   behaviour is untouched and the patch is reversible.
2. Smoke-test one cell per arm, confirm the attrition logger records what the
   table above needs.
3. Launch the ~100-run campaign.
4. Analyse, make the two figures, write the 4 pages.
