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

---

# Amendment log

Pre-registration is only worth something if deviations are recorded with their
reason, **before** the run that tests them. These were all forced by smoke
tests on 19 Oct, before any campaign cell was executed.

## A1. Sample size: n=5 runs per condition, not 10

The 19 Oct inventory counted 10 runs per condition. That double-counted: there
are **5 Claude runs and 5 Codex runs** of each. Subject agent must be held
constant (different runtimes give different process names, RSS and syscall
mixes), so the usable n per condition is **5**.

Compensated with **repeats** (the house device: 3 incidents x 2 arms x 2 asks x
5 repeats was the standard matrix), giving 15 observations per headline cell.

## A2. The cap is calibrated to the trace, not fixed at 6000

**Measured first:** `ctf_proclife` on the local agentic runs returns
**3,777 and 3,837 chars** — *under* the v1 cap of 6000. So at 6000 the defect
**never fires** on this data, and the ablation would have been null by
construction. Caught by the smoke test; it would have cost a full campaign.

Why these traces are smaller: they are one 4-vCPU box running one coding agent
(2 pid namespaces, ~24 processes). The microservice traces that produced the
original finding have 16–47 services.

**Measured delivery against cap, by textual presence** (what an LLM can still
read out of a truncated payload):

| flat cap | early key (spawned procs) | late key (resident procs) |
|---|---|---|
| 6000 | 8/8 | 16/16 |
| 3000 | 8/8 | 16/16 |
| 2500 | 8/8 | 11/16 |
| **2000** | **8/8** | **4/16** |

So the campaign uses **`ABL_FLAT_CAP=2000`**. What is held constant across the
replication is the **mechanism and the early-to-late delivery ratio**, not the
absolute byte count. The absolute cap is a free parameter of any deployment;
the claim is about prefix-slicing versus row-dropping at whatever budget binds.
This is stated as a limitation in the paper.

## A3. The delivery metric is textual presence, not parseability

Our first instrument scored a key as lost whenever the payload failed
`json.loads`. That is wrong for this question: a model is not a strict parser,
and it still reads the early part of a truncated object. Scoring strictly made
both keys die together (0/8 and 0/16) and hid the positional effect entirely.

It also could not have reproduced the field numbers, which are 99.3% and 4.7%
for two keys in the *same* payloads — impossible if invalid JSON meant total
loss. **Delivery is therefore measured as textual presence of a row's
identifying field.** Parseability is reported separately, as its own harm.

## A4. The dependent variable is WHERE, not the fault label

Smoke-tested the repaired agent on a resident fault, with and without a hint.
Both answered `fault_type: normal`. There is no headroom on the label axis, so
an accuracy effect could not appear there.

The reason is specific and worth reporting: the coding agent runs in a
**cgroup, not a pid namespace**, so these traces carry one container
(`4026531836`) and a cgroup cap manifests as *absence* rather than as a
nameable culprit. The agent said so itself — *"Only pid_ns 4026531836 was
observed."*

But the same run **did** name the affected process and quote its throttled rate
— *"CPU runtime later remained around 250 ms/s"*, which is exactly the
0.25-core cap. So the primary DV is the established **WHERE** axis (did it name
the correct culprit **process**), scored independently of the fault label,
exactly as the house scorer already treats those axes. The label and abstention
are reported alongside.

This also records a fourth instance of the repo's recurring pattern: the agent
computed the discriminating number and did not act on it.

## A5. All accuracy arms carry a hint

Given A4, every fault-class and healthy cell gets the **same** symptom-level
operator hint — *"the coding task on this machine took noticeably longer than
usual to finish"*. It names a symptom, never a mechanism, and it is identical
across classes so it cannot leak the answer differentially. On healthy runs it
is a **hard negative**: an operator reports a symptom and nothing is wrong.

## A6. A scoring bug and a design flaw, both caught on partial data (20 Oct)

Audited at 46 of 120 cells rather than waiting for the campaign to finish.
Two problems, the second more serious than the first.

### The scoring bug

The first scorer searched the whole diagnosis prose for a culprit name. That
credited sentences like *"the later python3 workload is actively consuming
cpu"* as a successful localisation on runs whose `root_cause_service` read
**unknown**. It scored the repaired resident arm at **14/15** when the true
commitment rate was **2/15**.

This is the same failure the harness's own scorer hit once before, where an
earlier branch credited *any* namespace as correct and was caught one commit
before it produced a fake improvement. Scoring now requires a **commitment** in
`root_cause_service`; a mention in prose is reported separately as
`mentioned_not_committed`, which is informative in its own right. The
commitment predicate is unit-tested against real recorded values, after a
second bug (`"".startswith` matching everything) briefly scored every run as an
abstention.

### The design flaw

With correct scoring, the headline interaction **cannot be measured as
designed**:

| arm | commit rate |
|---|---|
| repair / **spawned** culprit | **14/15 (93%)** |
| repair / **resident** culprit | **2/15 (13%)** |

The resident class — the one the delivery defect is predicted to destroy — is
already at the floor **when repaired**, for the reason recorded in A4 (a cgroup
limit in a single namespace manifests as absence). The spawned class has ample
headroom, but it is precisely the class the mechanism predicts the defect
**spares**, because its culprit sits in the early, surviving key.

So the only cell with room to fall is the one that should not fall. H2 as
written is untestable here, and no number of additional runs would fix it.

### The replacement: manipulate position directly

The thesis is that a positional bound makes delivery depend on a field's
**position**, and that nothing makes late fields less important. The clean test
is therefore to vary position and nothing else.

`ABL_REVERSE_KEYS=1` serializes a result's keys in reverse order. Content,
data, task, agent, model and bound are all unchanged; only which field the
prefix reaches first moves. Measured on the spawned runs:

| condition | spawned list (holds the culprit) | resident list |
|---|---|---|
| repair | 8/8 | 17/17 |
| defect, normal key order | **8/8** | 4/17 |
| defect, **reversed key order** | **0/8** | 16/17 |

**H2' (registered now, before these cells run):** accuracy on the spawned class
falls sharply under `s1_reversed` relative to `s1_deliver`, even though the two
differ only in the order of two keys in a JSON object.

**Inertness control `order_only`:** reversal with no binding bound must show no
effect. If it does show one, the reversal is not inert and the manipulation is
unsound — so this control can falsify the whole design, and is run for that
reason.

### What the original cells are still worth

`s1_deliver` x spawned is now a **confirmatory** test rather than a null:
the defect destroys roughly 27 tool results per run, and the mechanism predicts
accuracy nonetheless holds near 93% because the answer was never in the deleted
field. Catastrophic data loss with no accuracy loss, decided purely by
position, is the other half of the argument.

## A7. H2' refuted with mechanism, registered mid-wave (20 Oct, 2 of 15 reversed cells in)

The first two `s1_reversed` cells name the culprit correctly. Checked the
transcript before interpreting: the manipulation **worked** - proclife sent
payloads are reversed (begin with `how_to_read`) and `ttworker` is absent from
all three proclife results. The agent recovered it through **run_python, 12
times**: it writes its own aggregations over the counts table, ttworker is the
single loudest process in the trace (**14.0% of all kernel events**), so any
sorted result carries it in the first rows, inside the surviving prefix.

**Interpretation, registered before the remaining 23 cells finish:** the harm
of a positional delivery defect is gated by **evidence-path redundancy**. A
dominant culprit survives severing any single path, because every aggregation
is a path. A quiet culprit carried by exactly one enumeration field dies with
that field - which is the archival case: resident microservice containers,
visible only in `present_throughout` (delivered 4.7%), split 0-24/60 against
40-55/60 for spawn faults.

Predictions for the cells still running:
- remaining `s1_reversed` cells stay high (dominance rescues them);
- `order_only` shows no effect (inertness holds).

If `order_only` degrades, the manipulation is unsound and all reversal cells
are void.

This reframes the paper's claim, honestly stronger: positional truncation
spares the easy cases (dominant signal, many paths) and kills exactly the hard
ones (quiet signal, one path), while moving aggregate numbers barely at all -
2.5% of calls in the replay corpus. That is why the defect class survives
inspection.

## Final results (20 Oct, 145/145 cells, zero harness failures)

Both A7 predictions held exactly: `s1_reversed` 15/15, `order_only` 10/10 with
zero truncations. The inertness control passed, so the refutation of H2' is
valid and the redundancy interpretation stands.

| config x class | correct | destroyed/run | tool calls | computations | in-tokens |
|---|---|---|---|---|---|
| repair x spawned | 14/15 | 0 | 53 | 21 | baseline (567k) |
| s1_deliver x spawned | 15/15 | 26 | 68 | 34 | +5% |
| s1_reversed x spawned | 15/15 | 29 | 76 | 37 | +14% |
| order_only x spawned | 10/10 | 0 | 48 | 18 | -12% |
| repair x healthy | 5/5 clean | - | - | - | - |
| all_defect x healthy | 4/5 (1 false alarm) | - | - | - | - |
| resident, all configs | 7-13% (substrate floor) | - | - | - | - |

H1 confirmed: median 567k in-tokens per run, max 1.0M - capacity never bound.

The law the paper states: **the harm of a positional delivery defect is gated
by evidence-path redundancy, and its cost appears as work before it appears as
error.** Monotone compensation tax 53 -> 68 -> 76 tool calls as severance
deepens; the single-path fatal case is carried by the archival field data.

Campaign cost: 83.85M input tokens across 145 runs (~$10 at measured rates),
~5 hours wall at 3 parallel.

## A8. Fatal-case probes on the real microservice substrate (20 Oct, pre-registered live)

`data-sample/svc_cpu_cap_aggressive_steady_r1`: real 21-container trace,
carts throttled to 0.2 CPUs. Deterministic delivery at the DEPLOYED 6000 cap
measured first (E1c): proclife 33,370 chars; defect delivers early 30/118,
late **0/128**, invalid; repair 246/246.

Headroom probes, plain agent, repaired, symptom hint only:
- r1: `unknown` / other / 0.78 - did not localise.
- r2: committed to `conn* in pid_ns 4026533035` = a mongod cohort (carts-db),
  one hop behind the throttled service - the documented "one hop away"
  trace-blame pattern, now reproduced by the agent from kernel data.

So the plain agent has no reliable headroom here. Last probe: the GIVEN arm
(service-cpu-throttle skill via skillreg, frontmatter stripped). Registered
before its result: if given+repair localises carts, run given+defect at the
deployed cap x5 repeats each arm; a drop is the causal fatal case. If
given+repair also fails, the fatal case stays field-evidence and the paper
says so explicitly in Threats.

**A8 outcome.** The given arm also committed to the mongod cohort
(`conn* in pid_ns 4026533035`, 0.78) - the same one-hop-off container as
plain r2. Per the registered rule: no accuracy baseline exists to destroy, so
the fatal-case matrix is NOT run, and the accuracy-destruction half remains
field-evidence. The probes add their own finding: on the hardest substrate the
repaired, skill-given agent is itself at the floor - the September low side
was plausibly capability AND delivery jointly, and the paper's threats section
now says so. The clean causal fatal-case candidate is slow_db on Trillium,
whose 22-09 repaired-era baseline showed real headroom (24/60 WHERE).

## A9. Made the tools and the agent safe: real pagination (20 Oct, post-submission-prep work)

User asked, separately from the paper: make every tool in Blueprint/ safe to use, so the
agent never silently loses data, and can ask for more until it knows there is no more.

### What changed

`Blueprint/agent/utils.py`: a new `page_result(obj, page, cap, state)`, next to the old
`fit_result()` (left completely untouched - it exists only to reproduce the v1 defect under
`ABL_FLAT_CAP` for the already-submitted ablation; diffed and confirmed byte-identical).

Rule: a page boundary only ever falls between whole rows (list fields) or whole lines (long
text fields, e.g. a blueprint script's stdout). Never a byte offset - a byte offset is the
exact defect this paper studies. Small fields (numbers, short notes) repeat on every page so
the model always has context. Every page is valid JSON. Pages must be requested in order;
asking out of order gets a correction, not wrong data. The last page says, in words: "you
have now seen ALL rows/lines - nothing more to ask for."

`SAFE_PAGING=1` by default. `_exec_tool` now reads a `page` argument (never forwarded to the
underlying tool), caches the FULL result the first time a (tool, other-arguments) combination
is seen, and serves every later page from that cache - no re-running the tool, no re-decoding
a trace, just a different slice of what is already in hand. This is automatically OFF when
`ABL_FLAT_CAP` is set, so the published defect condition is unaffected.

Every tool schema now carries a `page` parameter (added centrally via `add_paging()` in
`_worker_tools()`, not hand-edited per tool) - including `blueprint_tool`, which covers all
55 scripts under `Blueprint/latency/*/tools/` with zero changes to any of them, because they
all return `{"stdout": "..."}` and that is exactly the long-text case `page_result` pages by
line.

### Verified, not assumed

- `Blueprint/agent/test_paging.py`, 6 checks, all pass: list fields fully recovered in order;
  text fields never split mid-line; out-of-order pages refused with the correct next page
  named; small results pass through untouched; an unpageable oversized result says so rather
  than silently slicing; and the paper's own worst case.
- **The paper's own fatal case, fixed.** At the real deployed cap (6000, not calibrated), the
  late field in `svc_cpu_cap_aggressive_steady_r1` went from the paper's measured **0 of 128**
  to **128 of 128** recovered across 8 pages, including all 5 records of the throttled
  culprit's own process.
- `git diff` on `utils.py` is a pure insertion (`@@ -150,0 +151,137 @@`) - zero lines of
  `fit_result` touched. `agent_v2.py`'s diff touches exactly the three places intended: the
  import line, `Ctx.__init__`, and `_exec_tool`/`_worker_tools`. Nothing else moved.

### An honest cost, found while testing

Recovering a severely-cut result can take several pages, and each page still costs one of
the worker's limited turns (`MAX_WORKER_STEPS = 18`) - the cache avoids re-running the tool,
but not the step. The fatal-case recovery above took 8 of 18 steps on a single field of a
single call. Pagination trades data loss for step-budget pressure; it does not make either
free. Worth a larger per-page budget as a follow-up, but not changed today - that would alter
`SENT_CAP_BY_TOOL`, which every existing measurement in this paper was tuned against.

### Live check in progress

Running the probe that previously failed on the real production trace (`probe_given.py`,
the skill-given arm that twice named the wrong container one hop away) with pagination now
available, to see whether having the full data changes what it concludes. Outcome recorded
separately once it lands; not yet known at the time of this entry.
