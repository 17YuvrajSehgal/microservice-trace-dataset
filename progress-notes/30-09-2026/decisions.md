# 30 September 2026

# Part 1: thirteen citation corrections, and a result we did not have

Continuation of yesterday's rule: nothing enters a blueprint until it is measured. Today's
version of it is: **nothing stays cited until the paper has been read.** Eleven of the papers in
`blueprints/REFERENCE-PACK-FOR-KERNEL-TRACE.md` were cited from abstracts. Reading them turned up
twelve problems.

**None of them reached a blueprint or a generated skill.** All were confined to the reference pack
and `DOCS/reading-papers/FUTURE-BLUEPRINT-REFERENCES.md`. No completed run is affected. Summaries
live in `DOCS/reading-papers/sources/<slug>/paper.md`; the index is `table.md`.

### The thing worth keeping — four independent studies measuring the same shortfall

This is now a TL;DR bullet in the reference pack, and it should go in the paper's introduction.

| Source | What is missing |
|---|---|
| **Zhou et al. 2021**, 22 industrial faults | **2 could not be debugged at ANY tooling level**, and both are *environment* faults |
| **Dai et al. 2018**, 156 timeout bugs | **60%** produce no error message, 12% a misleading one |
| **Gunawi et al. 2016**, 597 outages | **59%** have no publicly reported root cause |
| **Ghanavati et al. 2020**, 491 leak issues | **1 of 491** found by static analysis; **63%** only visible at runtime |

Four different failure families, four different methods, one conclusion: **the evidence needed to
diagnose these is not in the code, the logs, or the spans.**

**Why this matters more than the individual numbers.** We had been arguing the kernel modality
from what our own runs show. That is fine but it is our data arguing for our method. These four
are independent, published, and none of them set out to make our point. Zhou's is the strongest
because it is a *failure*: they had distributed trace visualisation and two faults still defeated
them, and their own sentence is *"most fault cases **except those caused by environmental
settings** can benefit from trace visualisation."* The environment is the kernel's layer.

### Blueprint 10's discriminator was published in 2021 and we did not know

Gelle, Ezzati-Jivan & Dagenais, *Electronics* 10(21):2610, §4.3. They cap a Cassandra cpu cgroup
at 1% and read the result out of an LTTng kernel trace:

- requests go from ~5 ms to ~2 s
- `PREEMPTED` dominates the critical path
- preemption recurs **every 100 ms**
- the CPU becomes **underused**
- the deciding event, printed in their Table 5:
  `sched_switch prev_comm=java, prev_tid=7949, prev_state=0, next_comm=swapper/2`

That is our `service-cpu-throttle` discriminator — preempted but **not replaced**, `prev_state=0`
plus `next_comm=swapper` — measured independently four years before we wrote it. **Added as a
supporting row.** They do not name the 100 ms as `cfs_period_us`; we can.

**Decision: cite it as confirmation, not background.** It is the only external evidence in the
pack for a `sched_switch` field-level test we rely on, and it came from an injected fault, not
from reasoning.

### Blueprint 3's "honest gap" is narrower than we recorded

The pack says there is **no peer-reviewed MSR paper focused only on connection-pool exhaustion**.
That is still true, but Zhou's **F5** is a verified industrial instance in a peer-reviewed venue:
a microservice whose **thread pool is shared between two request types**, high load of one
exhausts it, the other fails on timeout. Six days to locate. **Replicated in TrainTicket**, so we
can run it. Noted in the pack rather than deleting the gap claim.

### The twelve corrections

Eight were logged yesterday. Today's four:

| # | Where | What it said | What the paper says |
|---|---|---|---|
| 9 | `FUTURE-BLUEPRINT-REFERENCES.md`, `code_n_plus_one` | Chen 2014 reports N+1 costing "more than an order of magnitude" | **It does not.** That figure (130 s → 2 s) is the *excessive data* pattern in Pet Clinic. **One-by-one processing is -17%** in their micro-benchmark, **+8% to -32%** across Broadleaf, significant in **5 of 10** suites |
| 10 | same file + `meta.yaml`, `resource_abuse` | "Suneja et al., IPDS 2020" | **Karn, Kudva, Huang, Suneja & Elfadel, IEEE TPDS 32(3):674-691, 2021.** Suneja is the *fourth* author; "IPDS" is not the venue; 2020 is the acceptance year |
| 11 | Cross-cutting §8 + blueprint 9 | Zhou et al. "IEEE TSE, 2018/2021" | **TSE 47(2):243-260, 2021.** The repository PDF's 2018 header is a stale draft template |
| 12 | Blueprint 10 (addition, not an error) | no empirical source for the `prev_state=0` / swapper test | Gelle 2021 §4.3 publishes it |

**Correction 9 was load-bearing.** It was the stated reason to expect the N+1 signal to be large
enough to see. Chen's actual numbers say the opposite, and say why: *"when the response time of a
program is small, adding batches will not give much improvement... not all anti-patterns are
worth fixing."* **Schema cardinality and baseline latency decide.**

### What that changes for the `code_*` campaign

**Decision: treat injection strength as an open question for `code_n_plus_one` and
`code_serial_awaits` before reading anything into their results.** This is the `noisy_neighbor`
"KPIs barely move" problem again, and we now have published reason to expect it:

- **Chen 2014**: the same anti-pattern ranges +8% to -32% depending on schema shape.
- **DrAsync (Turcotte et al., ICSE 2022)**: refactoring **every** executed instance in two whole
  projects removed ~1.1K and ~1.2K runtime promises and changed test-suite run time **not at all,
  twice**. Their two good numbers (16.4%, 36.1%) are hand-picked fragments, and the larger one
  involved copying a **7.8 GB directory**. Sock Shop's front-end awaits are short local HTTP
  calls.

**But their failure to measure it is an argument for our modality, and it is the sharpest one in
the set.** DrAsync's stated reason is that the eliminated promise lifetimes hide inside a longer
wait. That is a **wall-clock** problem. Serial awaits and `Promise.all` issue **the same number**
of round trips — the difference is **overlap**, whether two requests are ever in flight at once.
That is readable off socket-event timestamps and invisible to every method in their paper.

Same shape for `code_n_plus_one`: Chen measures response time, we count round trips, and a count
survives noise a duration does not.

**Three discriminators fell out of the reading and are now recorded as hypotheses, not findings:**

| Pair | Separator |
|---|---|
| `code_n_plus_one` vs `slow_query` | **many small round-trips** vs **one long one** |
| `code_n_plus_one` vs eager over-fetch | many small vs **few with huge payloads** (Yang 2018) |
| `code_event_loop_block` vs `svc_cpu_cap` | **one thread busy on-CPU** vs **nobody running, CPU idle, 100 ms period** |

The third is half-confirmed already — Gelle publishes the throttling side.

### One thing to check in a recipe before we cite a paper for it

Karn et al. detect cryptomining from **which syscalls**, not CPU share, because *"CPU usage is a
good first-order metric"* that false-alarms on legitimately busy workloads. That is our coverage
sweep's `resource_abuse` problem stated by someone else, and it looked like a rescue.

**It may not be.** Their miners are real binaries doing real work — pool network I/O, file writes,
timers — which is where the 12 distinctive syscalls come from. **If our `resource_abuse` recipe
is a bare spin loop, it may emit no distinctive syscalls at all**, and their method does not
apply. Noted in the future-references doc as a precondition on the citation. Their own data also
warns against a rate-based discriminator: **Hadoop and Cassandra, both benign, out-emitted 4 of
the 5 named miners.**

### Method notes worth stealing

- **Chen et al.** rank detected anti-patterns by **measured** effect (p-value + Cohen's d), because
  static analysis found 483 of one kind. Our blueprint results tables report detection but never
  rank by how much the fault mattered.
- **DrAsync** separates **static occurrences from executed ones** — 293 found, 30 run. The most
  honest table in the `code_*` set.
- **Karn et al.** compute `Sig_fault = W_fault − W_normal` as a set difference over syscalls. That
  is computable across all 24 of our families at once and would give each blueprint a measured
  discriminative set. Expect it to be small: theirs was **12 of 100, with 88 shared**.
- **Karn et al.** also report a **decision tree beating an LSTM by 18 points at 1/500 the training
  time** on syscall data. Useful counterweight to Kohyarnejadfard's LSTM, and evidence that our
  rule-based blueprints are not a compromise.

### State

**38 of 50 papers summarised** (33 by me, 5 by the user). 12 left, listed at the bottom of
`table.md`. The Salesforce connection-pool patent still needs OCR — 21 pages of scanned images,
no text layer; the user will supply screenshots.

---

# 30 September 2026 — part 2: the rest of the papers

All 55 are now read. Only the Salesforce connection-pool patent is left, and it needs OCR.

## The one that criticises our scoring, and is right

**Lu et al., *Beyond Fault Localization*.** Their opening is about us:

> Existing evaluations ... uniformly assess diagnostic performance by **endpoint correctness**:
> whether a method localizes the responsible service ... **it provides no indication of the
> evidentiary basis for a diagnosis or the propagation route.**

They hand-annotated fault-propagation paths for a benchmark, normalised **3,500 trajectories**,
and showed **Edge F1 never exceeds 0.67 while Node F1 is far higher** — an agent names the right
service and still cannot say how the fault got there.

**Decision: do the cheap half now, skip the expensive half, and say why.**

- **Cheap, before the campaign:** check whether the winning container appears in the evidence the
  worker actually retrieved, not only in its conclusion. We already log every `run_python` result.
- **Skip:** annotating propagation paths. **Most of our faults do not propagate across services** —
  a CPU cap on one container is local. `dependency-outage-retry-storm` is the only family where an
  Edge-F1 analogue would mean anything. That is a real difference in fault design, not a gap.

**Their depth finding is the warning we should answer before a reviewer asks.** Acc@1 collapsed
**85.5% → 57.1%** as the causal chain deepened. Our 30/30 on `deadlock` is a **short-chain**
result: inject in one container, observe in that container.

## Their failure taxonomy already named one of our bugs

Three families, from **154 hand-coded failed trajectories**:

| Family | Meaning | Where we have seen it |
|---|---|---|
| **OMIT** | evidence reachable but never queried | `out_of_steps`, `late_findings` |
| **MIS** | retrieved but misread, or scoped to the wrong dependency | wrong `pid_ns` |
| **GEN3** | **"abandons an evidence channel after a failed or empty query"** | **the `ctf_lines` silent-empty bug, exactly** |

**Decision: code a sample of our failures against OMIT/MIS/GEN.** The taxonomy is already
validated; we get a ranked list of what to fix without inventing a scheme.

## The abstention gap — three papers converge on it

**Roy et al.** hand-labelled 97 ReAct predictions: correctness **35% vs 39%** for the baselines,
but hallucination **6% vs 49%**, because **66% of its wrong answers say it lacks the evidence to
decide**.

**Our scoring cannot tell those apart.** A confident wrong answer and an honest "unknown" score
identically. Beyond-FL attacks this from the trajectory side, Roy from the abstention side, and
SiriusHelper's SOP Reviewer (multiple drafts, cross-checked) from the consistency side.

**Decision: split declines from assertions in `run_digest.py` before the campaign.** We have the
data. A 27/30 with three abstentions is a different result from 27/30 with three confident errors.

## What the agent papers say about the step limit

Three findings, same direction:

- **AIOpsLab:** accuracy rises with the step limit, then **plateaus** — needing *"better planning,
  improved feedback mechanisms for intermediate steps"*, not more room.
- **Roy:** the agent died at the **20-step limit after one or two useful diagnostic steps**,
  wasting the rest on a **stateless retrieval tool** that kept re-returning the same documents.
- **StepFly:** **~46% of real TSGs have parallelisable steps** (Independent Paths 40.5%), worth
  **32.9-70.4%** wall-clock.

**Our rule-out lists are StepFly's Independent Paths.** "Is the host saturated / is a foreign task
on the CPU / is the group throttled" are independent questions over the same trace, and we run
them in sequence inside one worker's budget.

**Decision: parallelising independent rule-outs is the right next harness change**, not another
step-limit increase. We raised `MAX_WORKER_STEPS` 12→18 last week; these three say that road is
short.

**Also worth a check:** is any of our tools stateless in the way Roy's was — returning the same
thing twice and burning steps?

## Two things we cannot check today but should note

**We never verify the *code*, only the diagnosis.** Xpert's `Xcore` scores generated queries on
validity + semantic soundness + output correctness. Their post-processing moved **BLEU +1.7 but
Xcore +24.4** — most generated queries *looked* fine and were not. Our analogue: a `run_python`
block that executes cleanly, returns a plausible number, and aggregated the wrong column. **We
have no signal for that at all**, which is the same shape as the reply-cap bug: invisible because
nothing errored.

**Cheap fixes if we want them:** log whether each computation touched the columns the blueprint
names; count degenerate results (empty frame, all zeros, single row).

## A disagreement to record rather than resolve

| | Claim |
|---|---|
| **OpsHarness** | the **harness** is the bottleneck; a good one gains **+63.4%** over a bare agent |
| **Beyond-FL** | the **model** is the bottleneck; frameworks span **2.0 pp**, a model swap gains **10.8 pp** |

Both are preprints. Possible resolution: Beyond-FL compares existing frameworks, which may all be
thin; OpsHarness compares bare-agent to engineered-harness. **Note it, do not pick a side.**

OpsHarness also has a finding that should make us uncomfortable and then not: **specialised RCA
agents lose to general agents**, badly — RCA-Agent drops **31.8% → 1.9%** off its own benchmark.
Reading our design against theirs, we are mostly the *harness layer* they advocate. **Two real
gaps: no evolve/verify loop, and our system knowledge is compiled into tools rather than produced
as a readable profile.** Their K1 — a generated per-run profile replacing a hard-coded loader — is
cheap and would make the harness portable to Train Ticket without touching tool code.

## Numbers a reviewer will put next to ours

**Write the comparison ourselves.** AIOpsLab: localisation **Acc@1 46-62%**, RCA 36-45%, non-LLM
baselines **15.38%** and **7.69%**. OpsHarness: **59.0%**. Roy: **35-39%** correctness.

**None is comparable to ours** and the reasons are specific: their agents work a live cluster with
`kubectl`, their telemetry is metrics/logs/traces, and **their fault mixes are mostly functional**
— a pod at zero replicas, revoked auth. Those announce themselves. Ours are performance faults,
which per Waseem are the ones nobody files issues about.

**Also worth adopting: AIOpsLab's task taxonomy** (detection → localisation → RCA → mitigation).
It is better vocabulary than our ad-hoc axes and makes explicit that **we stop before mitigation**.
And **their Acc@3 exceeds Acc@1 by 8-15 pp** — reporting both would say whether our agent knows
the answer but ranks it badly.

## Citation correction 13

The TSG-complaint percentages our docs credit to FixItFlow — **32.24% / 13.32% / 11.21%** — are
**AutoTSG's Table 1**, from 400+ on-call feedback items. FixItFlow restates them as "an internal
study" without naming the source in that sentence. **Cite Shetty et al. 2022.**

AutoTSG also carries the measurement our blueprint idea assumes and we did not have: **mean TTM
19 hrs without a linked TSG, 13 hrs with one**, from actual on-call click-throughs. Its quality
taxonomy is a design spec for what a blueprint must not be — and by its **Empty** category
(7.24%, *"currently just has TODO"*), **our three blueprints with an empty
`evidence_from_literature` are that category.**

## Prevalence evidence that arrived sideways

Saha & Hoi mined **2,000 Salesforce Sev0/1/2 post-mortems**. Their cluster phrases name **conn
pool (three separate clusters)**, thread starvation, deadlock, high CPU, high memory, packet loss
latency and auto throttle — **seven of our fault families**. The weights are cluster weights, not
incident counts, so this is a weak claim: *these families appear by name in the post-mortem record
of 2,000 severe incidents at a major provider.* **It narrows the connection-pool gap from a third
direction** (after Zhou's F5 and Ghanavati's leak study).

## State

**All 55 summaries on disk.** 13 citation corrections, none of which reached a blueprint or a
generated skill. The Salesforce patent still needs screenshots for OCR.
