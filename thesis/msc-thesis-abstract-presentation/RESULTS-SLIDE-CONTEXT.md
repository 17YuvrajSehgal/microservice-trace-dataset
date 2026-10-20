# Context pack — the preliminary results slide(s)

**For:** a Claude agent building the results slides. Written 19 October 2026.

**Every number below was recomputed from the raw JSON in `blueprints/results/`
on 19 Oct 2026**, not copied from a write-up. That matters: the prose and the
raw data disagree in two places, and both times the raw data is right (§1.4,
§2.3).

---

## 0. What is actually in `blueprints/results/`

| File | What | Use it? |
|---|---|---|
| `withwithout.json` | **the 57-incident with/without study** — summary blocks *and* all 114 per-run rows | **Yes — the authority for §1** |
| `ruler.json` | **272 evidence packs**, 12 measured signals, and the rule engine's verdict per pack | **Yes — the authority for §2** |
| `verification_index.json` | 303 per-run verification verdicts | **No — stale.** See §4 |
| `q2/plan.json` | `matrix: []`, `n_runs: 0` | **No — an empty stub.** The Q2 matrices live in `results-download/` |

**Two headline results live in this folder. The other three do not** — see §3
for where to find them.

---

## 1. Result one — the with/without study

### 1.1 The design

57 incidents, both applications, same model, **same evidence pack to both
arms**. One difference: the blueprint library is available, and the agent must
**choose** from it. Both arms got a deterministic investigation brief, so the
control is strong, not a strawman.

Verified from `rows`: 57 paired runs (36 Sock Shop + 21 Train Ticket), 0
errors, 0 no-answers in either arm.

### 1.2 The headline — and the honest way to say it

| Fully correct | n | Without | With |
|---|---|---|---|
| **the fault HAS a blueprint** | 36 | **20 (56%)** | **20 (56%)** |
| the fault has none | 21 | 12 (57%) | 9 (43%) |
| pooled | 57 | 32 (56%) | 29 (51%) |

> **Lead with the covered split, not the pooled number.** On the faults the
> library actually covers it is **56% against 56% — a dead tie**. The pooled
> figure drops only because the agent reached for a blueprint on faults no
> blueprint covers.

### 1.3 The noise floor, measured rather than assumed

On **30 of the 57 runs the agent picked no blueprint at all**, so both arms had
**byte-identical input**. They still scored differently:

| | n | Without | With |
|---|---|---|---|
| no blueprint picked — **identical input** | 30 | **15** | **13** |
| a blueprint was picked | 27 | 17 | 16 |

**Two runs of difference on identical input. That is the noise floor**, and the
pooled gap of 3 sits inside it.

### 1.4 ⚠ The summary block in the file is wrong — the rows are right

`withwithout.json → selection` reads:

```json
{ "n_with_a_pick": 57, "n_correct_pick": 19, "n_no_pick": 0 }
```

**`n_no_pick: 0` is a bug** — it counts the literal string `"none"` as a pick.
The same file's own `by_blueprint` block contradicts it with
`"none": {"n": 30, ...}`, and recomputing from the 114 raw rows confirms **30
runs with no pick, 27 with one**.

`blueprints/docs/RESULTS-withwithout.md` has a "CORRECTED 18 September" section
built on that buggy field, which concludes the 30 identical-input runs *"do not
exist in this data."* **They do.** If challenged, recompute from `rows` —
it takes four lines of Python.

### 1.5 What moved underneath the tie

| | count | detail |
|---|---|---|
| blueprints **fixed** | **3** | 2 × `noisy_neighbor` (correct blueprint picked), 1 × `dependency_outage` |
| blueprints **broke** | **6** | 4 had a blueprint picked — **all four were the wrong one**; 2 had **no blueprint at all** |

3 − 6 = −3, which is exactly 32 → 29. The arithmetic closes.

> **Say it precisely.** The write-ups say *"broke 4, all four were the wrong
> blueprint."* The raw rows say **6 got worse**: 4 with a wrong pick, and **2
> with no pick at all — identical input, so noise.** The careful sentence is:
>
> *"Six runs got worse. Four of them had a blueprint selected, and **every one of
> those four was the wrong blueprint**. The other two had no blueprint at all —
> the same noise we measured on the other identical-input runs. **Not once did a
> blueprint give bad advice about its own fault.**"*
>
> This is stronger than the prose version, not weaker: the two noise cases
> corroborate the ±2 floor instead of being charged to the library.

One more honest detail: of the 3 fixes, **one was fixed by the *wrong*
blueprint** (`dependency_outage` rescued by `db-latency-dependency-wait`,
`skill_ok = false`). Only the two co-tenant fixes were the right blueprint doing
its job.

### 1.6 The fault that carries the argument

| family | n | Without | With |
|---|---|---|---|
| `anomaly_cpu` | 6 | 6/6 | 6/6 |
| `anomaly_disk` | 3 | 3/3 | 3/3 |
| **`noisy_neighbor`** | 6 | **0/6** | **2/6** |
| `svc_cpu_cap` | 6 | 4/6 | 4/6 |
| `dependency_outage` | 6 | 4/6 | 4/6 |
| `slow_db` | 6 | 4/6 | 3/6 |
| `svc_net` | 6 | 3/6 | 2/6 |
| `anomaly_mem` | 6 | 6/6 | **4/6** |
| `svc_mem_cap` | 3 | 2/3 | 1/3 |
| `anomaly_net` | 3 | 0/3 | 0/3 |
| `error_storm` | 3 | 0/3 | 0/3 |
| `queue_backlog` | 3 | 0/3 | 0/3 |

**`noisy_neighbor` is the slide-worthy row: 0 out of 6 unaided.** The model
never once diagnosed co-tenant CPU contention on its own. With a blueprint it
got 2.

Note also the four families at **0/6 or 0/3 in both arms** — `anomaly_net`,
`error_storm`, `queue_backlog` — these are where neither arm can reach, and two
of them are the faults we later proved unreachable from kernel traces.

### 1.7 Selection — the measured bottleneck

| Blueprint | times picked | right | fully correct |
|---|---|---|---|
| *(none picked)* | **30** | — | 13 |
| `cpu-contention-co-tenant` | 9 | 6 | 3 |
| `service-cpu-throttle` | 7 | **3** | 3 |
| `host-cpu-saturation` | 5 | 5 | 5 |
| `db-latency-dependency-wait` | 3 | 2 | 2 |
| `host-disk-saturation` | 3 | 3 | 3 |
| **`network-path-degradation`** | **0** | — | — |

**27 picks, 19 of them right (70%).** And the line that lands hardest:

> **The network blueprint was selected zero times across the nine network
> incidents.** On those nine the agent picked nothing 7 times and picked
> `service-cpu-throttle` — the wrong blueprint — twice. Meanwhile the
> deterministic engine scores **22/22** on network faults using that same
> blueprint (§2).

`service-cpu-throttle` is the other problem: picked 7 times, right 3. It fires
too easily.

> **The conclusion the slide should carry:**
> **The content is not the bottleneck. The routing is.**

---

## 2. Result two — the deterministic rule engine

Computed from `ruler.json`: **272 evidence packs**, both applications, 12
measured signals, **no model involved at any point**.

### 2.1 The headline

| | |
|---|---|
| packs scored | **272** |
| the engine fired | 104 |
| fired **and was right** | **85** → **82% precision when it fires** |
| stayed silent | 168 |
| **healthy `normal` runs** | **20 — fired on none of them** |

### 2.2 The result worth building the slide around

Precision is **not evenly distributed**. Six of the seven wired blueprints are
perfect; one is broken:

| Blueprint | fired | right | precision |
|---|---|---|---|
| `network-path-degradation` | 22 | 22 | **100%** |
| `cpu-contention-co-tenant` | 15 | 15 | **100%** |
| `host-disk-saturation` | 10 | 10 | **100%** |
| `host-cpu-saturation` | 9 | 9 | **100%** |
| `datastore-wait` | 9 | 9 | **100%** |
| `service-cpu-throttle` | 5 | 5 | **100%** |
| **`service-memory-cap`** | **34** | **15** | **44%** |

> **Exclude the one broken blueprint and the engine fires 70 times and is right
> 70 times — 100% precision, zero false fires, across six blueprints on 272
> packs.**

And its failure is **completely isolated and named**: every one of
`service-memory-cap`'s 19 wrong fires is a single confusion —
**15 × `anomaly_mem`** and **4 × `fd_exhaustion`**. There are no other wrong
fires anywhere in the 272 packs.

That is exactly the retraction already on record: `service-memory-cap` was once
reported at 16/16 with zero false fires, and the claim was withdrawn when the
negative set was widened to include `anomaly_mem`, its closest look-alike. **The
raw data shows precisely that failure, and nothing else.**

### 2.3 How this relates to the published 93% figure

`blueprints/docs/RESULTSv2.md` reports **38/41 = 93% precision when it fires**.
That is a **different, smaller experiment** — 81 runs, 5 blueprints. `ruler.json`
is the larger and later evidence base: 272 packs, 7 blueprints.

**Both are real. Quote whichever you use with its n, and do not present one as
superseding the other.** If you want one number for a slide, the strongest
defensible pair is:

> **"Across 272 evidence packs, six of seven blueprints fired 70 times and were
> right 70 times. The seventh is a known, isolated confusion with its nearest
> look-alike."**

### 2.4 The twelve measured signals

`ruler.json → signals` carries every per-run measurement behind the rules, with
a label, a unit and a point per run: `host_util_incident`, `thief_cores`,
`thief_share`, `util_ratio`, `iops_per_irq`, `hardirq_x`, `worst_retrans_pct`,
`socket_block_x`, `fork_newcomer_per_s`, `tx_newcomer_bytes_per_s`,
`emfile_error_share`, `emfile_per_s`.

Useful if a slide needs a real distribution plot — each point carries `app`,
`family`, `run`, `n_cpus`, `verification` and the value `v`.

---

## 3. The other preliminary results — not in this folder

| Result | Number | Where |
|---|---|---|
| **With vs without, kernel only, per-arm** | `deadlock` **30/30 vs 3/30**; `conn_pool_exhaustion` **27/30 vs 2/30** | `results-download/{deadlock,conn_pool_exhaustion}/DIGEST.md` |
| **Earliness** | blueprint arm **+1 s** onset; unaided arm **+180 s** on a 125 s fault | same |
| **Blueprint vs 5 alternatives** | blueprint **83%** fully correct, 100% precision, $0; every LLM arm **58%**; statistical 42%; **BARO 0%** | `blueprints/docs/RESULTS-comparison.md` |
| **Kernel data cannot be bolted on** | fusing kernel features into BARO changed **nothing**; first kernel column ranked **~195th** | `agentic-rca/RESULTS-nonllm-baselines.md` |
| **Large head-to-head** | 93 incidents × 15 conditions = **1,395 evaluations**; agent **83–87%** vs mmbaro **46%** | same |
| **Anti-pattern screening** | wrong fires **29% → 12%**, zero correct diagnoses lost | `blueprints/docs/RESULTS-antipattern-ceiling.md` |
| **Portability finding** | a threshold on an uncomputable quantity makes the agent abstain: **1/30 → 14/30** | `blueprints/docs/WHEN-A-BLUEPRINT-HURTS.md` |
| **The agent-feedback loop** | 5 blueprints, 24 verdict cells, **zero confident wrong answers** | `progress-notes/12-10` … `17-10-2026` |
| **Agentic OS-noise** | 311 runs, 2 agents; **~84%** model wait; **+75%** wall at a quarter core | `Blueprint/latency/OS-NOISE-FOR-AGENTIC-AI.md` |

---

## 4. ⚠ `verification_index.json` is stale — do not use it

It reports 303 runs with: `confirmed` 226, `unconfirmed` **32**, `borderline`
16, `no_metric_signature` 9, `unknown` 20.

**That is a pre-re-collection snapshot.** `DATASET-v2-INVENTORY.md` records the
current state as **304 runs, `unconfirmed` 0** — *"nothing left, all re-collected
or re-scored"* — with `no_metric_signature` at 48 after six verification targets
were corrected on 16–17 September.

Using this file would show 32 unconfirmed runs that no longer exist. **Cite the
inventory for dataset counts, not this file.**

---

## 5. Numbers not to use

| Do not say | Why |
|---|---|
| **"56% vs 51%"** as the headline | true but misleading — it pools covered and uncovered faults. Lead with **56% vs 56% on the 36 covered runs** |
| **"blueprints broke 4 runs"** | the rows say **6 got worse**; 4 were wrong picks, 2 were no-pick noise. §1.5 has the precise sentence |
| **"every run picked a blueprint"** | the `selection` summary field is buggy. 30 runs picked nothing |
| **"50% → 70–80%"** | appears in no result file and is explicitly banned by `RESULTS-withwithout.md` |
| the **pooled Q2 blueprint effect** (reads +0) | an averaging artefact; the source doc says *never report the pooled number* |
| **`service-memory-cap` at 16/16** | retracted — the negative set excluded `anomaly_mem`. `ruler.json` shows it at 15/34 |
| any **verdict count** from `verification_index.json` | stale, pre-re-collection |
| mixing **82% (272 packs)** and **93% (81 runs)** as if one number | different experiments. Always attach the n |

---

## 6. Suggested slide structure

### Option A — two slides (recommended)

**Slide 1 — "The honest tie, and what it taught us."**
The covered-split table (56% vs 56%), then the three bullets underneath: fixed
3, broke 6 — *four of them the wrong blueprint, two of them noise* — and
`noisy_neighbor` at **0/6 unaided**. Close on the network blueprint picked
**zero times in nine network incidents**, and the line:
**"The content is not the bottleneck. The routing is."**

This is the credibility slide. Lead with the null result and explain it.

**Slide 2 — "Rules transfer."**
The per-blueprint precision table. Let the column of 100%s do the work, then
point at `service-memory-cap` yourself and name its confusion. Close on
**"70 fires, 70 right, zero false fires — and the one exception is a known
confusion with its nearest look-alike."** Add that it declined all 20 healthy
runs, and that no model was involved.

### Option B — one slide

Keep the covered-split table and the *"content is not the bottleneck, routing
is"* line, plus a single strip: **70/70 precision, six blueprints, zero false
fires, 20/20 healthy runs declined.** Put the per-family table in backup.

### What to say, not show

- The `selection` field bug. It demonstrates you check your own summaries
  against raw data — and it is how you answer anyone who has read the
  "CORRECTED" section of the write-up.
- That one of the three fixes came from the *wrong* blueprint. Nobody will spot
  it, and volunteering it is cheap credibility.

---

## How to re-verify any number here

```python
import json, collections
d = json.load(open('blueprints/results/withwithout.json'))
R = d['rows']
without = {r['run_id']: r for r in R['without_ss'] + R['without_tt']}
with_   = {r['run_id']: r for r in R['with_ss']   + R['with_tt']}
ids     = sorted(set(without) & set(with_))                       # 57

nopick  = [i for i in ids if with_[i]['skill'] in (None, 'none', '')]
print(len(nopick))                                                 # 30, not 0
print(sum(bool(without[i]['both_ok']) for i in nopick),            # 15
      sum(bool(with_[i]['both_ok'])   for i in nopick))            # 13
```

The rule-engine numbers come from `ruler.json → verdicts`: each row carries the
true `family` and the engine's `selected` blueprint, so precision and recall are
a two-line group-by. **Note the engine names the slow-DB blueprint
`datastore-wait`, not `db-latency-dependency-wait`** — mapping it wrongly turns
nine correct fires into nine false ones.
