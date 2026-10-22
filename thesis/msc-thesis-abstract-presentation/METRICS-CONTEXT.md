# Context pack — evaluation metrics

**For:** writing the evaluation-plan slide, the thesis methods chapter, or
answering "how do you score it?" in Q&A. Written 20 October 2026.

**Every metric below was read out of the scorer source**, not from a write-up:
`blueprints/lib/q2_judge.py`, `blueprints/lib/q2_run_one.py`,
`agentic-rca/runs.py`, `agentic-rca/evaluate.py`, `agentic-rca/run_digest.py`,
plus the designed-but-unbuilt lists in `blueprints/docs/AGENT-DESIGN.md` and
`blueprints/docs/EVAL-PLAN-effectiveness.md`.

---

## 0. The governing principle

> **One accuracy number is not enough, because "right answer" has several
> independent parts. A run can get one right and the others wrong.
> They do not sum to anything.**

That sentence is the design rationale for everything here, and it is the right
thing to say first on an evaluation slide. Three axes — *where* the fault is,
*when* it happened, and *what kind* it was — are scored and reported separately.

Two further rules shape the whole scheme:

- **Abstention is scored as nothing, not as wrong.** The answer schema tells the
  agent a wrong window is worse than an admitted gap. If the metric disagreed,
  the instruction would be a lie and the agent would be punished for honesty.
- **Check the harness before believing the score** (§5). Three times a low score
  was read as a limit of kernel traces, and all three times it was our own bug.

---

## 1. IN USE — the four-axis agent scorer

Source: `blueprints/lib/q2_judge.py` and `q2_run_one.py`. This produces every
recent number.

### WHERE — six-way, not binary

A kernel trace carries **no service names**, only a numeric `pid_ns` per
container, so "naming the container" means answering something like
`python3 in pid_ns 4026533609`. The scorer matches on `\b402[0-9]{7}\b`.

| Verdict | Meaning |
|---|---|
| `named` | identified the injected thing by name |
| `container` | named a pid_ns **and it matched the true one** |
| `container_wrong` | named a pid_ns, wrong one — a real error, different in kind from "I don't know" |
| `container_unverified` | named one, but the scorer **could not resolve the truth** — credited nowhere, penalised nowhere |
| `scope` | answered "host" for a genuinely host-scoped fault — true, but less useful |
| `ambiguous` | a shared runtime (`java`, `node`, `python3`, `dockerd`…) mapping to several services |
| `wrong` | anything else |

**Truth is resolved by the scorer, never taken on trust.** `nsmap.ns_for_service`
handles a service-targeted fault; `nsmap.ns_for_workload` handles one that runs
in its own container. `score.json` records `true_ns` and `true_ns_via`
(`service` / `workload` / `unresolved` / `error`), so a verdict is auditable
afterwards rather than re-derived by hand.

> **`container_unverified` is a harness health check, not a result.** If it is
> high, the scorer is blind and the other two numbers are understated. It read
> **8** on one matrix before re-scoring — and all 8 were correct answers.

An earlier version credited **any** pid_ns as correct. That was harmless while
no blueprint asked the agent to pick a container, and it was caught **one commit
before** it would have produced a fake improvement.

### WHEN — window overlap, with abstention as a first-class outcome

| Field | What it is |
|---|---|
| `iou` | intersection ÷ union against the true injection window |
| `recall` | how much of the real incident the claim covers. Low = missed it |
| `precision` | how much of the claim is really incident. Low = claimed half the recording |
| `verdict` | **`hit`** if IoU ≥ 0.5 · `partial` if any overlap · `miss` if none · **`abstained`** |

Two numbers sit behind IoU deliberately, because one hides the failure modes.

### Earliness — four numbers, not one

```
onset_error_s   = claimed_start − true_start      SIGNED; negative = noticed EARLY
detect_delay_s  = max(0, onset_error_s)           lateness only
earliness       = 1 − detect_delay_s ÷ duration   clamped 0..1
earliness_gated = earliness × iou                 <- the headline
```

**Why gated:** earliness alone is trivially gamed — claim the whole recording and
lateness is zero by construction. IoU punishes an over-wide claim through
precision, so the product is only high for a window that is both **early and
tight**.

**Why it exists at all:** measured across agent versions, IoU moved
0.543 → 0.776 while onset error at p90 moved **121 s → 7 s**. IoU alone would
have called them nearly the same. On `deadlock`, the no-blueprint arms show
**+180 s median onset against a 125-second fault** — they are describing the
recovery, not the incident.

Normalising by the fault's own duration lets faults of different lengths
compare. Abstentions are **excluded from the mean**, not counted as zero.

### WHAT — concept coverage of the agent's own words

| Field | What it is |
|---|---|
| `what_score` | hit ÷ total concepts, rounded to 3 dp |
| `hit`, `missed` | which concepts were covered |
| `n_concepts` | how many the rubric defines for this problem |

A per-problem `RUBRIC` carries `culprit` names, `scope` words, a
`scope_is_defensible` flag (is "host" a real answer for this fault?), and a
concept list with generous synonyms. **Not a label match** — an agent that
describes the fault correctly in its own words should not score zero.

> Honest caveat the docs state: *"`described` is a word check, and it is the
> softest number here."* An earlier version scored `slow_db` at 97% because the
> word list contained a bare "db".

### HOW — trajectory, from the tool log

`n_tool_calls` · `distinct_tools` · `tool_sequence` · `used_raw_lines` · and the
one to watch: **`used_who_tools` / `n_who_calls`** over
`WHO_TOOLS = ("ctf_procdiff", "ctf_proclife")`.

That pair exists because the pilot's systematic error was *searching only for a
change in event volume*, rather than asking who arrived or left.

### Fault label — reported, and distrusted

The agent picks from a fixed vocabulary. **The docs call this "the least
important axis, and the one to treat with most suspicion."** It read **0/60** on
one matrix purely because the fault name was missing from the vocabulary — the
agent literally could not say the word. Four families had no entry at all.

**Never compare the label column across with/without arms**: the blueprint text
names the fault, so a `given` row can read the answer straight off it.

---

## 2. IN USE — the Top-1 campaign scorer

Source: `agentic-rca/runs.py`. Used for the degradation grid and the non-LLM
baselines.

**Per run:** `service_hit` · `fault_hit` · `both` · `no_answer` ·
`service_top3` · `rr` (reciprocal rank) · `rank`.

**Ranked mode**, emitted per axis — localisation, fault typing, and both:
`hit@1` · `hit@3` · `hit@5` · `mrr` · `p@k` · `ap`.

> A deliberate restriction, stated in the code: there is **exactly one relevant
> item per incident** today, so a second matching candidate is *the same truth,
> not extra credit* — only the first hit counts. Multi-fault runs would relax it.

**Why this scorer was superseded for blueprint work:** it required an exact label
from a list written for a four-modality view. *"An agent that said 'a foreign
process is eating CPU while the services keep working' understood the incident
perfectly and scored zero for calling it `cpu_saturation`. We are marking
vocabulary, not analysis."* It also merged `host` with the real culprit name,
which made one column move 47% → 13% between arms while the true find rate sat
flat.

---

## 3. IN USE — rule engine and blueprint metrics

| Metric | What it measures |
|---|---|
| **precision when it fires** | of the packs where a blueprint fired, how many were right |
| **recall** | of the packs a blueprint owns, how many it caught |
| **false fires** | fired on a pack no blueprint owns |
| **no verdict** | stayed silent — not an error |
| **ambiguous** | two blueprints both fired; the orchestrator must choose |
| **healthy declined** | fired on none of the fault-free `normal` runs |

Two metrics specific to this work, and both are good slide material:

**Margin** — the ratio gap between a threshold and the nearest *other* fault
family. `RESULTS-blueprint-cards.md` reports it per blueprint; the thinnest are
at **1.01×** (about 1% of room), the widest at 22×. It answers "how fitted is
this number?" in a way accuracy cannot.

**`transfers`** — every one of the 33 entries in `thresholds.json` records
whether it travels to other hardware:

| verdict | count |
|---|---|
| `yes` | 21 |
| `no` | 6 |
| `partly` | 4 |
| `no, and kept anyway` | 2 |

The rule behind it: *a threshold with **units** measures our hardware, not the
fault. A ratio to the run's own baseline, a share of capacity, or a presence
test, travels.*

---

## 4. IN USE — cost and effort

`tokens` · `n_tool_calls` · `seconds` / `wall_s` · dollars per incident.

Measured, not estimated: **60 cells ≈ $5 and 2.5–3.5 hours** at 3 parallel runs,
about 750k prompt tokens per run. A full 11-problem campaign on both
applications is roughly **$120 and 50 hours**.

Cost is a *first-class* metric here, not a footnote — one published comparison
turns on it: giving the model the kernel evidence pack cost **+61% more tokens
for zero accuracy gain**.

---

## 5. IN USE — harness health, which gates everything else

`agentic-rca/run_digest.py` prints these **above** the result, deliberately.

| Check | What a bad value means |
|---|---|
| tool results truncated | the model never saw part of an answer |
| thread messages elided | trimming dropped context |
| runs with no findings recorded | workers investigated and recorded nothing |
| workers nudged for silence | a worker stalled and had to be prompted |
| code snippets that errored | the sandbox rejected the agent's own analysis |
| peak prompt | how close to the context limit the run came |

> **Three times we read a low score as a limit of kernel traces and all three
> were our own bugs**: a reply cap slicing JSON mid-number, a fault name missing
> from the vocabulary, and a scorer with nothing to verify against. Each time the
> agent had been right and the harness could not record it.

This is a *credibility* slide, not an embarrassment — it shows the negative
results were audited before publication.

---

## 6. DESIGNED, NOT YET BUILT

From `AGENT-DESIGN.md` (*"Nothing here is measured. It is a design."*) and
`EVAL-PLAN-effectiveness.md` (*"This is a plan. Nothing here is measured yet."*).
**Do not present these as results.**

### Detection — is anything wrong at all?

`precision` · `recall` · `F1` over "is there a fault", plus a **false alarm
rate** on healthy traces. Scored against the 10 `normal` runs per application.

**Blocked on triage, which does not exist.** Every test so far told the agent a
fault happened; it only had to say which one. *"A tool that finds a fault in a
healthy system is worse than no tool."*

### Ranking and confusion

`AC@1` · `AC@3` · `AC@5` · **`Avg@5`** · `MRR` · per-fault precision/recall/F1 ·
**macro-F1** (so all faults count equally, not just common ones) · a
**confusion matrix**.

The confusion matrix matters because we already know memory faults get called CPU
faults — and the raw rule-engine data confirms it: every wrong fire across 272
packs is `anomaly_mem` or `fd_exhaustion` being called a memory cap.

### Abstention

`coverage` (how often it answered at all) · `accuracy when it answered` ·
a **risk–coverage curve** (accuracy as the agent is forced to answer more).

### Efficiency — the anti-brute-force score

**`blueprints fully run per trace`. 1 is ideal; 21 is brute force.**

This has no equivalent in prior work, and it answers the reviewer's obvious
question — *why not just run all of them and keep the best?* If the agent matches
that baseline while running one blueprint instead of twenty-one, that is the
result.

### Early detection

**`seconds of incident data needed`** before the answer is right *and stays*
right. Give the agent a growing slice — 10 s, 20 s, 30 s — and record the first
slice where it holds.

Needs no new data: every run is 60 s baseline / 120 s incident / 60 s recovery
with the boundaries stamped. **Nothing measures this today**, and the docs are
explicit that the expectation — a blueprint should need less data, because it
names one thing to look at — *"is a guess we are setting out to test."*

### Per-setup comparison (the A/B/C/D plan)

For every run in every setup: right fault · right service · **picked the right
blueprint** · **abstained when it should** · tool calls · tokens · wall time.

Reported as a **table of good and bad sides**, not one score: *helps* (A wrong,
C/D right) · *hurts* (A right, C/D wrong) · *wrong pick* · *cost vs A*.

---

## 7. Statistical discipline — treat as a metric in its own right

| Rule | Why |
|---|---|
| repeat every run several times | one run tells us nothing |
| **95% ranges, not single numbers** | show the spread |
| **paired test** between setups | same traces both sides, so pair them |
| **noise floor measured first** | September guessed it from a side case |

Two measured floors that must travel with any claim:

- **±2 runs** on the 57-incident study — measured on 30 runs where both arms had
  byte-identical input and still scored 15 against 13.
- **±9 points** on agent localisation, from the A/A re-run protocol.
  `paper/sections/04-method.tex`: *"never quote a difference inside the band as
  a finding."*

---

## 8. Metric definitions that get misreported

| Trap | The correct definition |
|---|---|
| **`Avg@5` is not Top-5** | it is the mean of AC@1…AC@5. Report it separately and define it explicitly |
| `AC@k` | probability the top-k results include a true root cause. Top-1 = AC@1, Top-3 = AC@3, exact match |
| **MRR is not RCAEval-native** | we compute it ourselves from the ranked list |
| `earliness` alone | meaningless ungated — always report `earliness_gated` |
| the **fault label** column across arms | the blueprint text names the fault; the `given` arm can read it off |
| `container_unverified` | a harness check, not a score |
| **82% vs 93% precision** | different experiments — 272 packs / 7 blueprints vs 81 runs / 5 blueprints. Always attach the n |

---

## 9. Where each metric is computed

| File | What it scores |
|---|---|
| `blueprints/lib/q2_judge.py` | WHERE (six-way), WHAT (concept coverage), HOW (trajectory) |
| `blueprints/lib/q2_run_one.py` | WHEN (`score_window`) — IoU, onset error, earliness, gating |
| `blueprints/lib/nsmap.py` | resolves the true `pid_ns`; refuses when ambiguous |
| `agentic-rca/runs.py` | Top-1 campaign scorer + ranked metrics |
| `agentic-rca/evaluate.py` | the run × condition × method grid |
| `agentic-rca/run_digest.py` | harness health, printed above the result |
| `blueprints/lib/blueprint_decide.py` | rule-engine verdicts |
| `blueprints/thresholds.json` | the 33 thresholds and their `transfers` verdict |
| `blueprints/docs/SCORING-EXPLAINED.md` | **read this first** — every digest line, with a worked 60-cell example |

---

## 10. Using this on the evaluation slide

**Lead with the principle, not the list.** *"One accuracy number is not enough,
because 'right answer' has several independent parts."* Then show the four axes
as four short rows — WHERE, WHEN, earliness, WHAT — and say that abstention is
scored as nothing rather than as wrong.

**The two that distinguish this work**, and are worth naming out loud:

1. **Earliness, gated by overlap.** Nobody else measures *how early*, and the
   gate is what stops it being gamed. The 121 s → 7 s example makes it concrete.
2. **Blueprints fully run per trace.** The anti-brute-force score, and the direct
   answer to "why not run all of them?"

**The honest line to include:** the fault-label axis is the least important and
the most suspicious, and it once read 0/60 because of a vocabulary bug rather
than a diagnostic failure.

**Keep the designed-not-built set visually separate** — triage, the confusion
matrix, the risk–coverage curve and seconds-of-data-needed are the evaluation
plan, not results.
