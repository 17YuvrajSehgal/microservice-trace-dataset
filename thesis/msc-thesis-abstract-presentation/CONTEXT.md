# Context pack — M.Sc. abstract presentation

**For:** a Claude agent (or a human) building the 20-minute abstract
presentation. Written 19 October 2026.

**What this is.** One place that explains the research idea, the method, what
has been built, what has been measured, and where every file lives. Written so
you do not have to read ~120 markdown files to start.

**What this is not.** Not the slide plan. The slide plan is
`presentation-plan.md` next to this file — read that second.

**Rule for anyone using this file.** Every number here carries a source path.
If a number is not in this file and not in a source file, it does not go on a
slide. Several numbers in this repo have been mis-quoted before — see
[§12 Numbers you must not use](#12-numbers-you-must-not-use).

---

## Contents

1. [The thesis in one line](#1-the-thesis-in-one-line)
2. [The problem](#2-the-problem-in-plain-english)
2b. [Where the idea came from](#2b-where-the-idea-came-from-the-origin-story)
3. [The idea: the observability blueprint](#3-the-idea-the-observability-blueprint)
4. [How we create one — the method](#4-how-we-create-a-blueprint-the-method)
5. [A real blueprint, end to end](#5-a-real-blueprint-end-to-end)
6. [How a blueprint gets used](#6-how-a-blueprint-gets-used)
7. [How we score it](#7-how-we-score-it)
8. [What already exists](#8-what-already-exists)
9. [Preliminary results](#9-preliminary-results--every-number-with-its-source)
10. [Honest limits and negative results](#10-honest-limits-and-negative-results)
11. [The agentic leg — OS noise](#11-the-agentic-leg--os-noise-on-coding-agents)
12. [Numbers you must not use](#12-numbers-you-must-not-use)
13. [Research questions and status](#13-research-questions-and-status)
14. [Contributions](#14-contributions-the-closing-slide)
15. [Likely questions](#15-likely-questions-with-answers)
16. [Directory map](#16-directory-map--where-everything-is)
17. [Open items and cautions](#17-open-items-and-cautions-for-whoever-builds-the-deck)

---

## 1. The thesis in one line

> Diagnostic work is thrown away today. This thesis makes it a durable,
> executable artifact — and measures honestly where that helps, where it is
> unnecessary, and where it misleads.

Closing line, to say word for word:
**"from work that is repeated toward work that accumulates."**

A second quotable framing, from `blueprints/docs/blueprint-report.md`:

> "The thing we are selling is not the agent. It is that **trace analysis
> accumulates** instead of starting from zero every time."

**Canonical title** (`thesis/abstract.tex`):
*Agentic Software Observability: Preserving and Reusing Diagnostic Expertise in
Executable Form*

Author: Yuvraj Sehgal · Brock University · Supervisor: Dr. Naser Ezzati-Jivan

> Three different titles exist in the repo. `thesis/ABSTRACT.md` ends
> "*Capturing, Transferring, and Re-executing Diagnostic Expertise*";
> `presentation-plan.md` quotes "*Executable Blueprints for Reusing Diagnostic
> Expertise*". **`abstract.tex` is canonical.** Pick it and be consistent.

---

## 2. The problem, in plain English

### Problem 1 — the expertise is thrown away

Software runs on telemetry: **metrics, logs, distributed traces, kernel
traces**. When something breaks, an engineer reads that data and works out why.

That is skilled work. It means knowing:

- which signal separates one cause from another,
- which events are worth recording in the first place,
- which threshold means something *on this system*, not in general.

Today that work runs **once**. The fix is kept. The method is thrown away. The
reasoning survives only as a closed ticket.

It is worse now that AI agents do the same job. An agent given raw telemetry
re-derives the whole investigation every time. And a language model has no
particular idea what a CPU cap looks like in a scheduler trace.

Spoken hook: **"We keep the fix. We throw away the method."**

### Problem 2 — datasets stop at the application boundary

Public incident datasets exist: RCAEval, LEMMA-RCA, OpenRCA, the AIOps
Challenge corpora, MSDS, Nezha, LO2. Live agent testbeds exist too: AIOpsLab,
ITBench.

Every one of them stops at the same line: **none has a kernel layer.**

So a fault that lives *below* the application — a co-tenant stealing CPU, a
cgroup quota, a saturated disk — is invisible to both the analysis and the
evaluation.

Source: `thesis/PROPOSAL.md` §3.1.

### The thesis problem statement

> Can the experience of solving one observability problem be captured as a
> reusable, executable artifact, such that an agent can use it to solve the
> *next* similar problem — and can we measure honestly where that helps and
> where it does not?

---

## 2b. Where the idea came from (the origin story)

Source: `blueprint-idea.md`, written from the **26 August 2026** meeting (Naser
Ezzati-Jivan, Mahsa Panahandeh, Yuvraj Sehgal, Sneh Patel).

**This is the best material in the repo for the introduction slides.** It is
concrete, human, and it explains *why* the artifact has the shape it has. Use
one of the two anecdotes below — they land better than any abstract framing of
"knowledge loss".

### The idea in the document's own words

> Every trace analysis system is **input → analysis → output**. Today each
> investigation runs that pipeline once and the experience is thrown away. The
> proposal: capture the *whole* experience of solving one problem — what data to
> collect, what analysis to run, what output to produce — as one self-contained
> document: an **observability blueprint**. Blueprints accumulate into a
> database. When a similar problem appears, the database already has the
> prescription. Because a blueprint is written to be executed, an AI agent can
> read it and redo the investigation without a human.

### Anecdote 1 — "the history is in Mohammed's brain"

The motivation is a **people** problem, not a tooling one. A tool team solves
huge kernel-level problems, each one potentially a paper.

> "But there is no history. **The history is in Mohammed's brain.**"

And how it actually fails:

> "How do you resolve this? Oh, let me check. Oh, I remember I had this problem,
> but I had to remove it because I didn't have enough disk space." — so they
> remove part of the history from their system.

The goal, stated as a composite:

> "So we are training another expert like Mohammed with this framework. Not only
> Mohammed — Jason works on a problem, Mohammed works on a problem, Alex works
> on a different problem. We collect all of them together. So **the expert we're
> training will have the knowledge of all of those engineers.**"

### Anecdote 2 — the mechanism in miniature

The intuition came from Naser's own experience with AI tools, and it is the
clearest one-paragraph case for the whole thesis:

> "Every time, AI tries to invent something. I have the workflow and everything,
> but it does not use it. Once I asked it: don't create anything new, just
> document what we have done for this project. So we fully documented the whole
> thing — **I checked the documentation myself, made sure everything is there.**
> Next time, I say: first read that document, digest it, then these are the
> inputs, let's create the video. This time it does it much better, faster, more
> accurate, better quality. **Sometimes I forget to mention that document — and
> again it tries to download a 50 GB model from Hugging Face and reinvent the
> workflow.**"

Two design rules follow directly, and both are enforced in the repo today:

1. Without the document the agent **reinvents and wastes**.
2. **A human verifies the blueprint before it is trusted** — that is part of the
   loop, not an afterthought. (This is why the schema has a `verified_by` field
   at all.)

### How it relates to what companies already have

A blueprint is **an enriched Jira history**:

> "Most companies have a list of Jira histories, but now we are enriching
> that… We include problems, solution, and everything else, because AI agents
> will be able to use this. **Making this AI-agent friendly was not there. This
> is what we are adding to our architecture.**"

The comparison used in the meeting: like bug documentation, but Bugzilla only
documents the **bug** — a blueprint documents the bug **and the solution**.

### Two consequences the meeting drew out

**Blueprints drive collection, not just analysis.** This closes the loop back to
the input layer, and it is the origin of the `collection_order` field:

> "Someone comes to me: there is a problem in this part of the system. I ask
> them, we need data. But what data? I don't know. Those blueprints can tell me:
> this looks like a latency problem. We have a skill that says for this problem
> we need **5 kernel events, 3 telemetry data**. So those blueprints can even
> **dictate what data to collect**."

**The library is expertise injection for existing tooling.** A tool can have
data sources, views and retrieval and still be missing "the intelligence, the
skill, **the expertise on trace analysis**." With a library it can say: there
are 5 examples of this problem in my blueprint history — let me see how they were
solved.

### The scope instruction that shaped the work

> "You need to implement this whole framework — but not all of it, because all of
> it needs two or three years. **Implement a layer: part of each part.**"

A thin vertical slice: interface = **Babeltrace2 command line**; analysis = a
list of small Python scripts; output = an XY chart, a timeline, JSON, or text.
And: *"**Work issue-based.** Find one issue, one problem, collect data, do the
analysis, then write it down in the blueprint… but you need to come up with a
structure, a format for the blueprint."*

The first blueprint named in that meeting was **CPU contention, kernel trace
only**. That is `Blueprint/latency/1_svc_cpu_cap/`.

### The two contributions from that meeting that became method

**Mahsa's rule — put the actual code in the skill.** Recorded as a validated
industry finding, not a suggestion:

> "**But if you put the exact function in the skill, it reduces [variance] and
> increases accuracy a lot. We did it in three different industry domains and it
> worked a lot.**"

This is the direct ancestor of every `Blueprint/latency/*/tools/` folder, of the
schema's requirement that each `processing` step carry an exact callable, and of
the capability-registry design that lets that happen without naming a tool in
the portable artifact.

**The validation loop — pre-registered in August, executed in October.** This is
a strong credibility point: the method was written down *before* the results:

```
1  solve a problem by hand; document it as a blueprint; A HUMAN CHECKS IT
2  regenerate a SIMILAR BUT NOT IDENTICAL problem
3  hand only the blueprint to the AI; let it redo the whole thing unaided
4  measure the gap (maybe it gets 80% and misses 20%)
5  improve the blueprint — or add an extension, or a SECOND blueprint it can call
6  repeat
```

Step 5's "or a second blueprint it can call" is where the **discrimination pair**
came from. Steps 1–6 are, verbatim, the loop run on all five blueprints in
October (§9.8).

The headline experiment is also Naser's: *"We can compare with and without…
**with and without those blueprints.** And you should be able to see a huge
difference."* Yuvraj added **time** as a second axis.

### The honest note in that file — and why RQ3 exists

> On 21 August we measured that a **one-shot model call with a good
> deterministic briefing ties the full tool-using agent** (78% / 52% both ways,
> at **27% of the tokens**). **A blueprint has to earn its place against that
> control.**

That is why every with/without experiment uses a deterministic brief in *both*
arms. The abstract's phrase "deliberately unkind" refers to exactly this.

The file also reads it the optimistic way: it says *good up-front structure* is
what works — which is precisely what a blueprint is.

### Two warnings from Mahsa, both since confirmed

- Autonomous skill selection works on easy problems and **does not work well on
  hard ones.** (We measured this: selection is the bottleneck — §9.1.)
- The orchestrator is **biased toward the complex skill.** Given a simple skill
  and a RAG-based complex one, it usually picks the complex one. *"The
  assumption that the simplest is tried first is wrong."*

### What the meeting predicted, and what happened

§6 of `blueprint-idea.md` listed four things as missing: exact event-level
collection order, **runnable commands per step** ("the biggest single gap"), an
output spec, and Babeltrace2 CLI analysis scripts. **Three of the four now
exist** as `Blueprint/latency/*/README_v1.md` + `tools/`.

The one still open is the **output spec**: `explanation.txt` and
`recommended_action.txt` are declared by blueprints and **written by nothing**.
Worth naming as honest unfinished business if the question comes up.

---

## 3. The idea: the observability blueprint

### Plain-English version (use this on a slide)

A blueprint is **one solved investigation, written down so it can be run
again** — by a person or by an agent.

The analogy that works with non-specialists (from
`blueprints/docs/presentations/presentation1/ciena-slides-notes.md`):

> Say an engineer has a really good way to find problem X — it works 9 times
> out of 10. Today that lives in their head. A blueprint is that method written
> into one file: what data to collect, what to run, how to decide, and when not
> to trust it. Next time X happens, a person or an agent opens the file and
> executes it.

It records what to **collect**, what to **run**, and what to **produce** — not
just what was concluded.

Naser's term is **blueprint**, not "template".

### What is inside one

From `blueprints/schema/blueprint.schema.json`. Real `blueprint.json` files
carry 23 top-level sections:

| Section | What it holds |
|---|---|
| `id`, `version`, `title` | identity |
| `problem` | `summary`, `symptoms`, **`discriminators`** |
| `taxonomy` | domain → category → subcategory + `sibling_causes` |
| `applicability` | `apply_when`, `do_not_apply_when`, `cheap_precheck` |
| `reproduction` | the runnable fault script, so the claim is checkable |
| `collection_order` | **exact tracepoint names** + baseline/incident/recovery window + `why_these` |
| `processing` | ordered steps, each with an **exact callable**, what it `produces`, and what a correct result looks like |
| `outputs` | what files the run must produce |
| `decision` | `verdict_when`, **`rule_out`**, `root_cause_is`, `uses_thresholds` |
| `capabilities_required` | capabilities, not tools |
| `stopping_conditions` | when to conclude, when to switch, when to say nothing |
| `adaptation_rules` | what to do when the evidence does not fit |
| `selection`, `evidence_sufficiency`, `policies`, `scenarios`, `inputs` | routing, how much evidence is enough, approval/overhead policy |
| `mutually_exclusive_with`, `related_blueprints` | blueprints that cannot both be right |
| `evidence_from_literature` | claim + source + what we validated it on |
| `provenance` | `authored_by` (human / mined), **`verified_by`** (a named human), timestamp |

The three fields that carry the real weight:

1. **`discriminators`** — each says what *this* problem looks like **and what it
   would look like if it were the look-alike instead**. That pairing is the
   whole trick.
2. **`rule_out`** — mandatory. A blueprint must say when *not* to conclude it,
   and name the blueprint to go to instead.
3. **`collection_order`** — exact tracepoints. This is what makes a blueprint
   drive collection, not just consume it.

### The two properties that make it more than a runbook

**1. It is executable.** Each step declares a **capability**, not a tool:

```
needs: kernel.scheduler.runqueue_delay
```

`blueprints/providers.json` binds that capability to whatever tool is actually
available — our babeltrace2 script here, Trace Compass or a vendor's own
analyser elsewhere. **Swap the tool and the blueprint does not change.** 22
capabilities are registered today.

This reconciles two supervisor constraints that looked contradictory:

| Constraint | How it is satisfied |
|---|---|
| Naser: a blueprint must not name tools, only requirements | the `capability` field |
| Mahsa: the exact callable must reach the model, or accuracy drops | binding resolves to a real command *before* the agent sees it |

The registry also carries an **escalation policy**: cheapest-adequate-first —
use evidence that already exists, then low-overhead active collection, and only
escalate to high-fidelity tracing when the cheaper tier leaves the question
open. Provider entries carry overhead metadata (e.g. eBPF at ~2% overhead
first, escalate to full tracing at ~4%).

**2. It is evidence-bound.** No claim enters a blueprint until it is measured on
our own data — and measured against **every** fault family, not only its own. A
validator rejects uncited claims. Retracted claims stay in the file under
`problem.unverified_do_not_claim`, with the measurement that killed them.

### A blueprint covers a class, not one incident

Each one sits in a taxonomy (domain → category → subcategory) and lists its
sibling causes, because many historical tickets should collapse into one
reusable blueprint.

### A blueprint must be able to say "not applicable here"

Clearest case: `connection-pool-exhaustion`. Its signature is a collapse in
per-connection setup work. On an application whose callers already pool
connections there is nothing to collapse — **measured at 0.7–1.1 setup calls/s
against 169–177 where it works**. The blueprint tells the agent to report that
the check did not apply, rather than name the next most suspicious container.

> **"A blueprint that always produces an answer is not carrying knowledge; it
> is guessing with structure."** — `blueprints/README.md`

### Why a blueprint and not just a threshold — the best single table

`blueprints/docs/RESULTS-blueprint-cards.md`, measured across **all 272 runs**:

| Blueprint | Its headline number **alone** | The **whole rule** |
|---|---|---|
| `host-cpu-saturation` | separates all 272 | 271 / 272 |
| `data-exfiltration` | separates all 272 | (no gate rule yet) |
| `host-disk-saturation` | 10 wrong | 262 / 272 |
| `cpu-contention-co-tenant` | 24 wrong | 271 / 272 |
| `service-memory-cap` | 25 wrong | 253 / 272 |
| **`network-path-degradation`** | **44 wrong** | **268 / 272** |
| `service-cpu-throttle` | 68 wrong | 261 / 272 |
| `db-latency-dependency-wait` | **88 wrong** | 241 / 272 |

> "Retransmission alone gets 44 runs wrong; add 'was the baseline quiet' and
> 'was the loss in the queue' and it gets 268 of 272 right. **That is the
> argument for blueprints in one table. A threshold is not a blueprint, and now
> we can say by how much.**"

Caveats the file states: no time axis (the packs hold baseline-vs-incident
totals, not a series); three blueprints have no gates yet; every example run is
Sock Shop; nothing rebuilds these cards automatically.

---

## 4. How we create a blueprint (the method)

**This is the contribution — not any single blueprint.**

The order is fixed and never reversed:

```
1  write the measurement script
2  run it on labelled incidents — ALL families, not just the target one
3  read the numbers
4  author the blueprint from what was observed
5  validator checks it
6  generate the agent-facing skill from it
7  test it with the agent on unseen runs + negatives + cross-fault cells
8  failures -> revise the blueprint -> re-run
```

Two working rules, verbatim from `blueprints/docs/blueprint-report.md`:

> **Rule 1 — measure first, then write.** Nothing goes into a blueprint until
> it has been measured on our own data. Not one signal, not one threshold.
> **Even when we are sure.**
>
> **Rule 2 — one folder per problem.** The skill is generated from the
> blueprint, so the two can never drift apart.

Steps 7–8 are the **agent-feedback loop**. It was executed for the first time in
October 2026 — but it was **pre-registered in the 26 August meeting** as a
six-step method (see §2b). Worth saying out loud: the loop was written down
before any of its results existed.

### Why step 2 says "all families"

Because a signal that looks decisive on its own fault is usually raised
everywhere. Three first-draft claims died this way, measured across **93 runs /
310 records**:

| Draft claim | What the measurement showed |
|---|---|
| "the delayed services show raised runnable-wait" | runnable-wait **never exceeds 4%** in any family, and was **1.6%** on the co-tenant case itself. Unusable. |
| "the culprit's wait decomposition identifies it" | host-attributed faults have **no culprit-side record at all** — 5 whole fault families. Unmeasurable. |
| "the suspect shows dominant off-CPU external I/O wait" | true — and **98–99% for every fault type.** Identifies nothing. |

> "**All three would have been on a slide.**"

Best slide for the method. It shows the discipline cost us our first three
favourite ideas. Retracted claims were **kept, not deleted**, with the
measurement that killed them, and are rendered into the skill so the agent is
warned off them too.

### The five revisions (the process catching its own mistakes)

`blueprints/docs/blueprint-report.md` §5 — worth a slide on its own:

| Version | What changed and why |
|---|---|
| v1 | written from knowledge. **Wrong.** |
| v2 | measurement contradicted it — the three dead claims above |
| v3 | switched from derived summaries to the **raw trace**. Co-tenant runnable share 1.6% (invisible) vs runqueue delay **7.12×** (obvious); datastore external-wait 99.4% (same as everything) vs one syscall **36.8×** (unmistakable) |
| v4 | the blueprint must not name tools → the capability registry. This also resolved the conflict between the two supervisors |
| v5 | policies, cost, choosing between tools: overhead budget, approval rules, cheapest-first escalation, a confidence floor at 0.7, a recommended action |

### What the validator enforces

- every processing step carries a **runnable command**, not a description
- **exact tracepoint names** — "kernel data" is rejected
- **discriminators mandatory**, each stating the look-alike contrast
- **`rule_out` mandatory**
- every declared output is produced by some step
- the generated skill body is **leak-scanned** — fault labels, run ids and app
  names must not reach the model
- a capability with no *implemented* provider is rejected, so a blueprint can
  never claim to be executable where it is not
- unverified blueprints carry `verified_by: PENDING` and the validator warns

> **Caveat you must carry:** `blueprints/docs/RESULTSv2.md` states plainly
> *"Nothing is human-verified yet. Every blueprint still says
> `verified_by: PENDING`."* Do not claim human sign-off.

### Thresholds live in one file, and say whether they travel

`blueprints/thresholds.json` — **33 measured thresholds**, single source of
truth. `blueprint_decide.py` imports them; `blueprint.json` quotes them by name
in `{braces}`; the skill generator substitutes the live value. The document and
the code cannot drift.

The file exists because they *did* drift: `host-disk-saturation` told readers
"at least 2000 disk requests per second" for months after the engine had
replaced that number with a ratio — because 2000 was read off one machine and
scored 1/10 on the other.

Every threshold carries a **`transfers`** field. Strong presentation point:

> A threshold with **units** measures our hardware, not the fault. 0.5 cores is
> a lot on a 4-core box and noise on a 64-core one. A threshold that is a
> **ratio to the run's own baseline**, a **share of capacity**, or a
> **presence test**, travels to any machine.

Measured example of exactly that failing: `CONTENDED = 0.55` (a share of cores)
**inverts** on Train Ticket — `noisy_neighbor` during the fault reads
0.213–0.282 (below the threshold) while `normal` reads 0.657–0.710 (above it).
Meanwhile `SATURATED = 0.95` holds on both apps, because a full machine is full
on any hardware. Source: `blueprints/problems/RESULTS-v2-blueprint1-cpu.md`,
`RESULTS-v2-threshold-free.md`.

The same lesson from a different angle (`FINDINGS-phase1.md` F7):
**"Absolute cores travel; utilisation percentages do not."** The newcomer's core
count transfers across both apps (co-tenant 0.988–2.002 on Sock Shop vs
0.989–1.996 on Train Ticket).

### The skill is generated, never hand-written

`blueprints/lib/blueprint_to_skill.py` turns `blueprint.json` into the markdown
the agent reads. That is why the blueprint is the artifact we maintain.

The split matters for leakage: `measurement` names fault families and is for our
record; `agent_note` says the same thing **without the answer vocabulary**, and
that is what reaches the model. The `covers:` line stays in frontmatter, which
the harness strips.

### Commands (if you want to show the workflow)

```bash
# measure FIRST — nothing enters a blueprint unmeasured
python3 blueprints/lib/measure_signature.py --out evidence/signature.json

# validate, and generate the agent-facing skills
python3 blueprints/lib/blueprint_to_skill.py "blueprints/problems/*/blueprint.json"

# run one problem's full matrix
python3 blueprints/lib/q2_run_matrix.py --problems deadlock --app sockshop \
    --incidents 3 --repeats 5 --agent v2 --jobs 3

# harness health FIRST, scores second
python3 agentic-rca/run_digest.py <results-dir> --out digest.md

# open ONE run completely
python3 agentic-rca/inspect_run.py <path>/transcript.jsonl --full
```

---

## 5. A real blueprint, end to end

Use this as the one worked example.
`blueprints/problems/cpu-contention-co-tenant/blueprint.json` — **v8**, "A
co-tenant workload steals host CPU: services wait on the runqueue, not on I/O".
Fault family: `noisy_neighbor`.

**The situation.** An unrelated workload on the same host eats CPU. Our services
are never themselves busy, but every time they become ready to run they wait
longer before a CPU actually runs them. User latency moves only slightly, so
dashboards look nearly normal. The delay is only visible in the scheduler.

**What a human notices first** (`symptoms` — evidence only, never names the
fault):

- mild, intermittent latency jitter across several unrelated services at once
- no service is itself busy: per-container CPU is flat or falling
- no new error signatures; requests still succeed
- host CPU busy rises but is not exhausted

**The discriminators** (abbreviated; six in the file):

| Signal | This problem | NOT this problem |
|---|---|---|
| host CPU utilisation from `sched_switch` on-CPU time | rises but keeps **real headroom** — the host is *shared*, not exhausted | hits the ceiling (host exhaustion), **falls below** baseline (a cgroup quota), or is flat (healthy) |
| cores gained by a process that used no CPU in the baseline | a newcomer takes a bounded amount — **measured 0.99 to 2.00 cores on a 12-CPU host** | the newcomer takes several cores and pins the host; or there is no newcomer at all |
| blocking duration of socket-waiting syscalls | stays **flat** — nothing blocks longer, the threads just cannot get a CPU | one component's socket wait inflates by an order of magnitude |
| call-graph convergence | the slowdown **converges nowhere** | slow edges converge on one component |
| where the CPU went | a container consumes steady new CPU and has **no call-graph edges** | the extra CPU belongs to a service in the call graph |
| runqueue delay (`sched_waking` → `sched_switch`) | raised — **measured 7.12×** — but this is **CORROBORATION, not evidence. It must never be the deciding signal** | runqueue delay alone separates nothing: raised in *every* CPU-family fault and in healthy load bursts, and its ordering is **inverted** against severity |

**That last row is the single best slide in the deck.** The obvious signal — the
one any engineer would reach for — was measured and demoted to corroboration.
That is what "evidence-bound" buys you, and no prose runbook does it.

The supporting measurement (`RESULTSv2.md`): runqueue delay reads **52×** on
host CPU exhaustion, **15.7×** on a service CPU cap, **7.1×** on the co-tenant
fault, and **3.7×** on a *healthy but busy* machine. Ordered by severity it is
backwards from the fault we want it to find.

**The decision rule** (`decision.verdict_when`, thresholds substituted at
generation time):

- host CPU rises but stays below `{SATURATED}` (0.95) of all cores
- a process that used no CPU in the baseline now holds ≥ `{THIEF_CORES}` (0.5)
  cores but below `{BIG_THIEF_SHARE}` (0.297) of the whole host — it is
  *competing for* the machine, not consuming it
- that process has **no role in the call graph**
- runqueue delay is broadly inflated, corroborating that ready threads queue
- interrupt time is **NOT** raised with the disk quiet — that shape is a
  container against its memory limit whose stress tool happens to eat a core,
  and **it vetoes this blueprint**

**The rule-outs** (6, each naming where to go instead):

| Instead conclude | When |
|---|---|
| `host-cpu-saturation` | utilisation reaches the ceiling and the newcomer takes several cores |
| `service-cpu-throttle` | utilisation **falls below** baseline and there is no newcomer — a quota is holding work back |
| `healthy-baseline` | utilisation is flat and no newcomer took meaningful CPU, **even if a load burst raised runqueue delay** |
| a component waiting on I/O | one component's blocking syscall inflates by an order of magnitude while runqueue delay stays flat |

**Root cause is** "the co-tenant workload container itself, not any application
service it delays."

### The two-problem contrast slide

Two faults deliberately chosen as opposites — CPU contention (waiting for a turn
on the processor) and datastore wait (blocked waiting for something else). Both
look identical from outside: things are slow, nothing is obviously broken.
Measured on the raw kernel trace, each fault acting as the other's control
(`blueprint-report.md` §6):

| Signal | CPU contention | Datastore wait |
|---|---|---|
| Runqueue delay (busiest service, p95) | **7.12×** (48,886 samples) | 0.97× |
| Database `poll` wait (p95) | 1.12× (45,337 samples) | **36.83×** (17,245 samples) |
| Largest inflation of any syscall | 3.95× | 36.83× |
| Trace convergence | **none** (1.7×) | **717.7×** |

Supporting: the guilty container used **2.00 CPU cores** during the incident
against **0.00** before, and has **no place in the call graph**. Host CPU went
**5.31 → 7.96 cores (×1.5)** — busier, but **not exhausted**. That is
contention, not saturation.

Same measurements, same components, opposite answers. **That separation is what
a blueprint stores.**

### Self-routing, demonstrated

The datastore script, run unchanged on the CPU fault, returns NO plus a
redirect: **"Use the CPU-contention blueprint."** The blueprint refuses to
answer and points at the right one instead of forcing a verdict.

### The bonus finding (great closing beat for this section)

The tool itself reported: *"traces name `catalogue`, but the kernel shows
`mysqld` is the one blocked."* The fault was injected on the database. The call
graph blames **the service in front of it**.

> Traces get you one hop away from the truth; only the kernel closes the gap.
> **We did not write that in. The tool reported it.**

---

## 6. How a blueprint gets used

```
incident
   │
   ▼
evidence-based SELECTION ──► HIERARCHY (issue class → cause)
   │
   ▼
blueprint EXECUTES (capability → bound tool → runnable step)
   │
   ▼
verdict  (or "not applicable" / "I could not tell" / "healthy")
   │
   ▼
FEEDBACK into what to collect next time
```

**Say on the slide: the library is the contribution, not any single blueprint.**

**Be honest about what runs automatically today.** From
`blueprints/docs/blueprint-report.md` §9: the runtime (intent normaliser,
selector, policy engine, binder, execution planner) is **not built**. Our
blueprints *declare* everything that runtime would need, but nothing consumes it
yet.

> **"Selection is manual today."** … "The knowledge objects are built and
> proven. The machine that runs them automatically is the next phase."

### The agent

Two generations. Do not mix them up on a slide.

**Generation 1 — `agentic-rca/`.** All the published numbers come from here. A
LangGraph **plan → work → review → synthesise** loop. Workers run in parallel
and record findings to a shared scratchpad the synthesiser reads. Seven
read-only tools over the raw trace: `ctf_timespan`, `ctf_timeline`, `query_ctf`,
`ctf_lines`, `ctf_procdiff`, `ctf_proclife`, and `run_python`, plus
`submit_diagnosis` to answer. `run_python` lets the agent write and run its own
analysis, which removed the ceiling where it could only ask questions our fixed
tools could express.

**Generation 2 — `Blueprint/agent/`** (October 2026, active). Distilled from
`agentic-rca/` to the actual dependency closure of `agent_v2.py`: 13 modules, no
data-layer dependency, takes a run directory as `argv[1]`.

Concrete limits from the code: `MAX_SUBTASKS = 4`, `MAX_ROUNDS = 2`,
`MAX_WORKER_STEPS = 18`, `THREAD_BUDGET = 150,000` chars. The planner makes one
model call with no tools. Workers never call `submit_diagnosis`. **The
synthesiser has no tools at all** — it reads the scratchpad and nothing else.

> `agentic-rca/AGENT-V2-ARCHITECTURE.md` still says `MAX_WORKER_STEPS = 12`.
> **The code is authoritative at 18.** It was raised after a measurement, and
> the measurement is a nice small example of the discipline: the distribution of
> steps used was roughly flat from 7 to 11 (53, 48, 46, 54, 42 workers) and then
> **spiked to 280 at exactly 12** — *"that is a wall, not a natural stopping
> point."* **51% of workers were hitting it**, while the worst single call in 120
> runs used only 15.7% of the context window.

A related behavioural fix: 234 of 554 workers ran out of steps with tool calls
still pending, and **98 of those had recorded nothing at all**. So a worker that
ends its turn with zero findings now gets nudged once, and a worker that runs
out of steps gets one extra call restricted to `note_finding`. Separately, every
`run_python` output is now auto-captured and reaches the synthesiser as **raw
output, not a claim**, with the instruction to *"trust the numbers over the
summary."*

**The method prompt is v1's word for word**, guarded by an assertion that fails
if the wording changes. The reason is a measured one: the first v2 smoke run
proved **the model believes the prompt over the schema** — `run_python` was in
every worker's schema, but the planner wrote four subtasks phrased entirely in
the six older tools, and the agent never once wrote code.

**How it reads a 15 GB trace fast.** One decode pass (`build_ctf_index.py`)
produces two ~15 MB files: a **counts** table (100 ms buckets × event ×
procname × pid_ns) and a **line sample** (one raw line per bucket per event).
Counts answer in under a second; a filtered `ctf_lines` call falls back to
decoding the trace and takes **40–60 s**.

**"Blueprint-only mode"** (`--blueprint-only`) is worth a sentence: the agent
gets **nothing but** the blueprint's own scripts and `note_finding` — no index
tools, no `run_python`. It tests whether the blueprint's toolkit is sufficient on
its own. Because a blueprint is a **sequential** procedure, this mode skips the
planner fan-out entirely and hands one worker the steps in order.

Giving a blueprint does two things at once: the blueprint markdown is injected
into the prompts as the given method, **and** its sibling `tools/` scripts
become callable, so the agent runs the blueprint's steps with the blueprint's own
commands.

**A documented failure mode you should mention if asked about limitations.**
Anything a worker computes but does not write down is lost, and the synthesiser
has no tools to go look. Measured on a `dependency_outage` smoke run: a worker
ran exactly the right query and got the blueprint's deciding test passing as
written — pid_ns 4026532822 went from 1242.8/s to **0/s** — yet it never became
a finding (**0 of 9** findings mentioned that namespace) and the synthesiser
answered `normal`. That was the **third** time the agent computed a
discriminator and did not act on it. Proposed fix: make recording the
blueprint's deciding test mandatory.

### The leakage controls (say these out loud — a committee will ask)

- **The agent is never told** that anything went wrong, when the incident was,
  which service is the target, or the fault name. It gets a pseudonymised run
  id, the tools, and — in the `given` arm — one blueprint.
- **Ground truth is unreachable by construction.** `ground_truth.json` sits in
  the same directory as the trace, so code handed a run path is one `open()`
  from the answer. The sandbox **never receives a path** — only a pre-loaded
  table, and no filesystem. The rule is written at the top of `ctf_tool.py` and
  `codetool.py`, and **19 adversarial escape attempts** were used to check it.
  Only the scorer reads ground truth.
- **Names are masked** before the model sees them (`leakguard.py`); run ids are
  pseudonymised. Generated skills are leak-scanned.
- **Tool results are capped per tool and trimmed by dropping whole rows, never
  by slicing JSON** — and the model is told what was dropped. (This matters:
  mid-JSON slicing was one of the three bugs we once mistook for a limit of
  kernel traces.)
- **Nothing crosses between runs, deliberately.** "An agent that remembered
  incident 1 while diagnosing incident 2 would make later runs easier than
  earlier ones and break the independence the scores assume."
- Every transcript is auditable: `inspect_run.py <transcript.jsonl> --full`. And
  `audit_leakage.py` **reconstructs the model-visible input** for every run —
  system prompt, user message, tool schemas, injected skill body, and every tool
  result actually sent — then scans it. Hard failures (which would invalidate a
  result) are the run id, any fault-family token under any separator style
  (`slow_db` / `slow-db` / `slow db` / `slowdb`), the injection-container names,
  and eight ground-truth field names.

**The sandbox has four independent barriers, "so no single mistake is
enough":** no filesystem at all in the builtins whitelist (no `open`, no
`__import__`, no `eval`); a static AST scan that rejects dunder attribute access
and banned identifiers before anything runs; kernel limits in the child
(`RLIMIT_FSIZE = 0` — it cannot write one byte); and the audit trail.

Two details worth knowing because they show the reasoning is honest rather than
decorative:

- On the substring blocklist: *"The substring scan is defence in depth, **not**
  the barrier — a path can always be built up. What must hold is that a built
  path cannot be USED."*
- On Windows the resource limits are unavailable, so **every result carries a
  `limits_enforced` flag** and the difference is reported, not hidden. Research
  runs are on Linux.

**The 19 adversarial escape attempts** are a real test file, and the rationale
is stated: *"The sandbox exists to keep one promise … and a promise that is not
tested is a promise that is assumed. Every attack here is one I would actually
try."* They include reading ground truth by absolute path, building the path up
by concatenation, class-hierarchy escape via
`().__class__.__base__.__subclasses__()`, `f.__globals__`, `getattr` to dodge
the name scan, and relative traversal.

The pass criterion is two-part and worth repeating: **blocked *and* not
leaked** — *"a block that merely errors is fine; a block that RETURNS DATA is
not."* And a matching list of 11 legitimate cases must **succeed**, because
*"the tool is useless if it only says no."*

**One subtle design call in the name masking.** Aliases are keyed on a
*canonical class*, not the raw name, because the modalities use **different
names for the same injected workload** (the kernel layer says "aggressor",
metrics says "anomaly-cpu-stress"). Hashing raw names would fragment one entity
into several pseudonyms and destroy cross-tool identity — information the
unmasked names did carry.

**What is deliberately *not* masked, as a stated realism boundary:** real
service names (they are the answer space), process signatures like `stress-ng`
inside long log lines (*"seeing a co-tenant's processes is legitimate SRE
evidence — it reveals a synthetic workload, not which fault was injected"*), and
the incident window (the standard "an alert fired at [t0,t1]" assumption).
Masking can also be switched **off** on purpose, so the size of the naming
giveaway can be *quantified* — but never for headline numbers.

**A standing anti-leak rule now applies to blueprints too** (16 Oct). Because
the agent reads the blueprint *during* evaluation, a blueprint may carry no
evaluation-derived names or numbers: "stress-ng took 17%" or "idle was 96%" is
an **answer key, not a lesson**. Every "Measured: X%" in the steps is now
qualitative and worked cases are anonymised. What is **kept** is the generic
method parameters (the 50 ms long-wait marker, quiet > 50%, repeat > 0.5) —
*"procedure, not benchmark answers."*

### One more harness component worth knowing exists

`agentic-rca/degrade.py` — a **telemetry degradation module** that makes
deterministic, seeded, offline thinned copies of a stored run: trace sampling
(whole traces kept or dropped by a hash mask, not random spans), metric step,
log level, per-service coverage removal, whole-modality removal, and kernel
tier. It sits **before** the data reader, so every downstream component is
oblivious to whether it is seeing full or thinned telemetry.

That placement is the point, and it comes from Mahsa's confounding guardrail:
**the telemetry axis and the agent axis must never move in the same
comparison.** Every degraded view is reproducible from `(run_id, spec, seed)`.

This is the machinery behind the earlier v3 framing (`research-agentic-rca.md`)
and it is what RQ6 — "can a blueprint's collection order cut the data needed
without losing accuracy?" — would be run on.

### Scope: kernel traces only, for phase one

The dataset has four modalities. Phase one uses **kernel traces alone** — not
because the others do not matter, but because kernel traces are the hardest and
least studied case: **no service names, no request ids, no log lines** — just
syscalls and scheduler events with numeric namespace ids.

> "If a blueprint helps there, it is carrying real method rather than restating
> what a log line already says."

Steps a blueprint declares that kernel data cannot reach are marked **NOT
REACHABLE**. The agent is told to skip them, *say* it skipped them, and not
treat their absence as evidence.

---

## 7. How we score it

Source: `blueprints/docs/SCORING-EXPLAINED.md`.

**One accuracy number is not enough**, because "right answer" has several
independent parts. A run can get one right and the others wrong. **They do not
sum to anything.**

| Axis | What it asks |
|---|---|
| **WHERE** | `named` / `container` / `container_wrong` / `scope` / `wrong`. A kernel trace has no service names — only a numeric `pid_ns` — so "naming the container" means answering e.g. `python3 in pid_ns 4026533609`. **Verified against the true pid_ns, never taken on trust** |
| **WHEN** | window IoU against the true injection window. `hit` = IoU ≥ 0.5. `unknown` is an **honest abstention, scored as nothing rather than as wrong** |
| **earliness** | `1 − (lateness ÷ fault duration)`, clamped 0–1, then **gated** by multiplying by IoU |
| **WHAT** | concept coverage of the agent's **own prose**, not a label match |
| **fault label** | a tally convenience, and the **least important** axis |

Three design decisions worth a slide each.

**Abstention is not punished.** The answer schema tells the agent a wrong window
is worse than an admitted gap. The metric has to agree, or the instruction is a
lie and the agent is punished for honesty. Abstentions are excluded from the
earliness mean rather than counted as 0.

**Earliness is gated by IoU**, because earliness alone is trivially gamed —
claim the whole recording and lateness is zero by construction. IoU punishes an
over-wide claim through precision, so the product is only high for a window that
is both **early and tight**.

Earliness earned its place immediately: on `deadlock`, the no-blueprint arms
show **+180 s median onset against a 125-second fault** — describing the
*recovery*, not the incident. Across agent versions IoU moved 0.543 → 0.776
while onset error at p90 moved **121 s → 7 s**; IoU alone would have called them
nearly the same.

**The scorer resolves truth itself.** An earlier version credited *any* pid_ns
as correct. Harmless while no blueprint asked the agent to pick a container, and
it stopped being harmless the moment one did. Caught **one commit before it
would have produced a fake improvement**. `score.json` now records `true_ns` and
`true_ns_via` so any verdict can be audited after the fact.

### Check the harness before you believe the score

`run_digest.py` prints harness health **above** the result, deliberately:
truncations, elided messages, runs with no findings, nudged workers, errored
code snippets, peak prompt.

**Three times we read a low score as a limit of kernel traces, and all three
times it was our own plumbing:**

| Looked like a limit | Actually was |
|---|---|
| per-service faults score 0/60 | a 6000-char reply cap sliced tool results mid-JSON; the container list reached the model **4.7%** of the time |
| `conn_pool_exhaustion` names the fault 0/60 | the fault name was missing from the vocabulary — the agent **literally could not say it** |
| `deadlock` names the container 0/60 | the fault runs in its own container, ground truth says `target_service: host`, so the scorer **had nothing to verify against** |

A credibility slide, not an embarrassment. It shows we audit our own negative
results before publishing them.

**The first of those three deserves its own slide, because the measurement is
remarkable.** The old result cap was a flat 6000 characters applied as a slice
of the JSON *string*:

- **3,827 of 11,189 tool results were cut, and every single cut one was
  unparseable JSON.**
- `ctf_proclife` returns two lists. The second one, `present_throughout`,
  reached the model in **4.7% of 742 calls**. Its `how_to_read` and
  `n_containers_seen` reached it in **0%**.
- And here is the part that matters: **an injected stress process *spawns*, so
  it appears in `present_for_only_part_of_the_recording` — 99.3% delivered. A
  CPU-capped or network-degraded container was *already running*, so it appears
  only in `present_throughout` — 4.7% delivered.**
- **The WHERE scores split exactly along that line, on both applications:
  spawn faults 40–55/60, already-running faults 0–24/60.**
- Meanwhile peak context use was **6.6% of the window** at the median run.

> **The harness was destroying evidence to save room nothing was using** — and
> the damage looked exactly like a property of kernel traces.

The fix: caps are now per-tool (up to 60,000 chars) and trimming **drops whole
rows and re-grows them by binary search**, never slices the JSON, and writes a
`_truncated` key naming what went. That is why "check the harness before
believing the score" is a rule and not a slogan.

### The experiment shape

Every problem runs a **2×2 matrix**:

| | no hint | hint |
|---|---|---|
| **no blueprint** | the hardest case | is a symptom description enough? |
| **blueprint** | does the method alone carry it? | both |

The blueprint effect is the gap between rows; the hint effect the gap between
columns. Separating them matters — otherwise "the agent did better" could just
mean "we told it what was wrong."

Standard matrix: **3 incidents × 2 arms × 2 asks × 5 repeats = 60 runs** per
problem. (The `deadlock` and `conn_pool_exhaustion` matrices are a variant:
**1 incident × 2 arms × 2 asks × 15 repeats = 60** — see §9.2.)

### The four setups planned next (A/B/C/D)

Source: `blueprints/docs/EVAL-PLAN-effectiveness.md`. **This is a plan, not
results.**

| Setup | gets the evidence pack | gets a blueprint |
|---|---|---|
| A | yes | no |
| B | yes | as text |
| C | yes | as an **executable rule**, plus the model for the rest |
| D | **no** | yes — the blueprint says what to collect |

**D is the important one.** Everything run so far gave both arms the evidence
pack, which already holds the numbers the blueprint asks for. So we tested *how
to read the numbers*. We never tested *what to collect* — the half a blueprint
should be best at. "The model has no way to guess that it should measure how
long threads wait for a CPU."

Pre-registered win conditions, set before running so the line cannot move later:

| Claim | What we need to see |
|---|---|
| blueprints help | C or D beats A by more than the noise floor |
| the collection half works | D beats A **even though D gets less data** |
| executable beats text | C beats B |
| earlier answers | C or D needs fewer seconds of data than A |

If none hold, we say so. **A tie is a result.**

---

## 8. What already exists

This is not a proposal for unstarted work.

### The dataset — StrataTrace v2

Source: `blueprints/docs/DATASET-v2-INVENTORY.md`.

| | Sock Shop | Train Ticket | total |
|---|---|---|---|
| runs | **170** | **134** | **304** |
| all 4 modality dirs present | 170/170 | 134/134 | **304/304** |
| kernel traces with **no event loss** | 170/170 | 133/134 | **303/304** |

- **27 fault families** (+ `normal` as the fault-free reference) across
  **2 applications**: Sock Shop (~16–21 containers) and Train Ticket (**47
  services actually start, not 49** — two never come up).
- **1.18 TB raw → 779 GB compressed**, 51 archives on Trillium. Working copy
  ~8 TB extracted.
- Clocks aligned across modalities to **0.001 ms** drift
  (`progress-notes/28-07-2026/`).
- Every run carries: kernel CTF trace, OTLP spans, container logs, meta/clock
  anchors, plus a per-run Prometheus export (**~440 metric series**).
- Usability was *measured*, not assumed: **293 fully usable**, 11 with a
  caveat, **0 unusable as a positive**.
- **35 runs are `no_metric_signature`** — the fault is present and was
  **measured** to have no metric signature at all. For kernel-trace work those
  are the most interesting runs in the set, not the weakest.

> ⚠ **The inventory file does not add up.** Four separate arithmetic
> inconsistencies: the per-family table sums to 303 not 304 (Sock Shop column
> sums to 169); the verification-verdicts table sums to 309; the
> "fully usable by verdict" table sums to 287 not 293; and
> `no_metric_signature` reads 27 for Train Ticket in one table and 14 in
> another. The file itself uses both 303 and 304 in different places.
>
> **Safe formulation for a slide:** *"~304 runs — 170 Sock Shop + 134 Train
> Ticket — 27 fault families, two applications, four modalities plus a per-run
> metrics export."* **Do not present a verdict breakdown that has to sum.**

**The kernel layer is the one no public incident corpus has.** That is the
dataset contribution. Also worth saying: we have already published work on
kernel traces before this.

Per-family run counts are in `temp.md` and in the inventory.

### The blueprint library

- **16 blueprint folders** in `blueprints/problems/` (previous generation). All
  16 `blueprint.json` files parse as valid JSON (checked 19 Oct 2026).
- **11 are wired into the experiment harness.**
- 16 generated kernel-only skills, 11 generated four-modality skills.
- 33 measured thresholds, 22 registered capabilities.
- **5 new-generation blueprints** in `Blueprint/latency/`, each one
  measured-before-written and agent-tested. **24 agent-verdict cells** across
  their matrices (§9.8).

The 16 problems: `connection-pool-exhaustion`, `cpu-contention-co-tenant`,
`data-exfiltration`, `db-latency-dependency-wait`, `deadlock-lock-order`,
`dependency-outage-retry-storm`, `dns-delay`, `fd-exhaustion`, `fork-storm`,
`host-cpu-saturation`, `host-disk-saturation`, `lock-contention-futex-storm`,
`network-path-degradation`, `priority-inversion-nice`, `service-cpu-throttle`,
`service-memory-cap`.

### The five new-generation blueprints (`Blueprint/latency/`)

These are written as human-readable procedures (`README_v1.md`), each with a
`tools/` directory. All five share a 10-script core (`idx_summary.py`,
`idx_dump.py`, `idx_slice.py`, `extract_slice.sh`, `sched_budget.py`,
`rhythm.py`, `cpu_ceiling.py`, `cpu_hogs.py`, `victim_info.py`,
`wake_graph.py`) plus one specialist tool each.

Structure of each (blueprint 1 is the template): header table → Part 1
Background (what the fault is, what it looks like in a kernel trace, **a
look-alike table**) → Part 2 What you need → Part 3 Setup → Part 4 Procedure
(Steps 1–10) → Part 5 **Limits of this blueprint** → Part 6 References →
Appendix A index files → Appendix B **one solved case**.

| # | Fault | The discriminator in plain English | Specialist tool |
|---|---|---|---|
| 1 `svc_cpu_cap` | a container's CPU limit is too small for its work | a quota refills every period, so the victim's on-CPU time **per period sits at a flat ceiling below the period**, over and over — **and the CPUs sit idle while it waits**. Fair-sharing also flattens, but hands the CPU to someone else | `cpu_ceiling.py` |
| 2 `noisy_neighbor` | another workload on the host is eating the CPU | during the victim's waits **somebody else is actually on the CPU — and that somebody is NEW**, arriving exactly when the waits start. A cap leaves the CPU idle; overload has no single nameable group | `cpu_hogs.py` |
| 3 `slow_db` | a dependency answers slowly over a connection | the **request-to-answer gap** on one connection *pool* jumps against its own baseline while CPU waits stay at zero and answers keep arriving | `sock_lag.py` |
| 4 `svc_mem_cap` | a container's memory limit is too small | the **event name** does the work: `mm_vmscan_memcg_reclaim_*` = a cgroup wall; `mm_vmscan_direct_reclaim_*` + `kswapd` = the host is full. Then the victim re-reads the same data many times over | `mem_pressure.py` |
| 5 `svc_net` | one service's network path is degraded | a TCP segment sent twice with the same sequence number is a retransmission; these pile up **only on the broken container's flows, in both directions**, while every other container reads 0% | `net_loss.py` |

**Four quotable measurements from these five:**

- **Blueprint 3, the async trap:** *"Measured on a real victim: every read took
  0.0 ms while every request took 500 ms."* Blocking-call duration shows nothing
  on an async runtime — so measure write→read gap, not read duration. The
  solved case: the service went from ~1 ms to **419 ms**; six pool fds all at
  p50 **503–543 ms** against a **0.9 ms** baseline.
- **Blueprint 4, the kill gap — the sharpest number in the set:** a process that
  exited **inside its own reclaim, within about 1 ms** (measured 0.02–0.37 ms on
  three known kills) was **killed**. A process that *finishes* under pressure
  exits **7.9–48.3 ms** after its last reclaim (five known finishes). Measured
  on 8 runs; the file says treat the 1 ms line as a rule of thumb, not a law.
- **Blueprint 5, baseline and the measurement trap:** healthy retransmission is
  **4 segments out of 90,107 (0.0%)**; under fault, every flow touching the
  victim reads **1.4–3.2%** while every other service reads **0%**. And: a
  packet crossing container→host **fires the transmit event once per network
  device**, so counted naively every segment looks sent twice — a fake "50%
  retransmission" on every healthy flow.
- **Blueprint 1, the fair-sharing trap:** *"A flat ceiling with BUSY CPUs is not
  a cap."* N equal busy threads on C cores each settle at a flat ~C/N of a
  core — fair sharing mimics a quota ceiling. The idle test is what separates
  them.

> **Important for honesty on slides.** The `README_v1.md` files publish **no
> pass/fail score** — the agent-test results live in the progress notes and the
> transcripts (§9.8), not in the blueprints. And each blueprint *deliberately
> refuses* to publish its own numbers as thresholds — e.g. blueprint 2: *"Their exact numbers are deliberately NOT
> printed as thresholds"*; blueprint 5: *"Use them as a feel for the sizes, not
> as thresholds."* Blueprint 1 has the only validation sentence: *"Validated on
> runs with known limits: the measured ceiling matched the real quota each time,
> and an uncapped baseline pegged at the full period — correctly no cap"* — with
> **no run count given**.
>
> ⚠ **`Blueprint/README.md` claims "40/40 detected, 0 false alarms" for
> blueprint 1's evaluation. That number is not in the evaluation file.** The
> eval is a 1-fault/1-baseline qualitative case study with no detection tally
> (see §9.9). The "40" in the campaign log is a progress counter — *40 runs
> collected*, not 40 detections. **Do not put 40/40 on a slide.**

### The agent and harness

- `agentic-rca/` — generation-1 agent + all campaign machinery and 13
  `RESULTS-*.md`.
- `Blueprint/agent/` — generation-2 agent, 13 modules.
- A **deterministic rule engine** (`blueprints/lib/blueprint_decide.py`) that
  reads kernel evidence and issues a verdict with **no model involved**.
- A leakage lint that refuses any blueprint mentioning a real service name or
  ground-truth wording.

### Cost (measured, not estimated)

**60 cells ≈ $5 and 2.5–3.5 hours** at 3 parallel runs, about 750k prompt tokens
per run. A full 11-problem campaign on both applications is roughly **$120 and
50 hours**. Source: `blueprints/README.md`.

Decoding cost, for the "why is this slow" question: **~6–9 minutes per run,
~13–37 GB staged per run** (`RESEARCH-PLAN-phase1-kernel.md`).

---

## 9. Preliminary results — every number with its source

Present these in this order: **the tie first, then the wins.** That ordering is
a deliberate decision (`progress-notes/15-10-2026/decisions.md`) — the tie plus
its failure analysis is what makes the proposed work look targeted instead of
hopeful.

### 9.1 The honest tie, and what it taught us

**Design.** Run 2 September 2026. **57 incidents** (36 Sock Shop + 21 Train
Ticket), same model (`gpt-5.4`), **same evidence pack to both arms**, 3
incidents per fault per app, no repeats. One difference: blueprint library
available or not — and in the `with` arm the agent **selects** for itself.

Both arms received a deterministic investigation brief, so the control is the
**strong** version, not a strawman.

**The pooled numbers:**

| Arm | Fully correct |
|---|---|
| Without blueprints | **32 / 57 (56%)** |
| With blueprints | **29 / 57 (51%)** |

**Read alone this says blueprints hurt. It does not.** Split by whether a
blueprint for that fault even exists:

| | n | without | with | |
|---|---|---|---|---|
| the fault **has** a blueprint | 36 | 20 (56%) | **20 (56%)** | **dead even** |
| the fault has **none** | 21 | 12 (57%) | 9 (43%) | **−14 points** |
| pooled | 57 | 32 (56%) | 29 (51%) | −5 points |

**The doc's own recommended quotable number is "56% with, 56% without, no
measured gain yet"** on the 36 covered runs. Use that. It is verified against
the raw JSON.

There is also an independent noise argument: on **30 of the 57 runs the selector
chose no blueprint**, so both arms had identical input — and still scored
**15 against 13**. So the noise floor is about **±2 runs** and the pooled gap of
3 sits inside it. **The result is a tie.**

> ⚠ **If challenged on the 30 runs:** the file carries a "CORRECTED 18
> September" section claiming every run picked something (`n_no_pick: 0`). That
> claim is **wrong** — the raw rows in `blueprints/results/withwithout.json`
> record `skill: "none"` on exactly 30 `with`-arm runs, and 15 vs 13 on them.
> The summary field counts the literal string `"none"` as a pick. The **raw data
> backs the original noise argument.** The covered/not-covered split is
> independently verified either way, so the 56%/56% headline is safe.

**What moved underneath the tie is the useful part:**

- Blueprints **fixed 3** runs. Two were co-tenant CPU contention — a fault the
  unaided model got right **0 times out of 6**.
- Blueprints **broke 4** runs. **All four were the wrong blueprint being
  selected.** Not one was a blueprint giving bad advice about its own fault.
- The agent picked a blueprint on **27 of 57** runs and picked the **right one
  19 times — 70% of its picks**.
- The network blueprint was selected **zero times across 9 network incidents**,
  while the rule engine scores **9/12** on those same faults using that same
  blueprint.
- Per-blueprint: `host-cpu-saturation` 5 picks / 5 right / 5 fully correct;
  `service-cpu-throttle` 7 picks / **3 right** — it fires too easily.
- Cost was identical: median **6–7 tool calls and 79 s in both arms**.

> **Conclusion: the content is not the bottleneck. The routing is.**

That one sentence reframes the rest of the thesis, and it is why selection and
the hierarchy are the proposed work.

**Caveats the doc itself states:** one model, one temperature, no repeats; both
arms got the evidence pack, so the *collection* half of a blueprint was never
tested; and the experiment measured *selection accuracy × usefulness* while
reporting the product as usefulness alone.

Source: `blueprints/docs/RESULTS-withwithout.md`,
`blueprints/results/withwithout.json`, `thesis/PROPOSAL.md` §5.2.

### 9.2 The headline wins — blueprint vs no blueprint, kernel traces only

Same agent, same incident, never told a fault happened. Only difference: the
blueprint.

| Problem | with blueprint | without | first run |
|---|---|---|---|
| `deadlock` | **30 / 30** | 3 / 30 | 2026-09-30 |
| `conn_pool_exhaustion` | **27 / 30** | 2 / 30 | 2026-09-29 |

"With blueprint" counts naming the right container, pooled across both asks.
Both matrices ran 60 cells with **0 failures**. Model: `openai/gpt-6-luna`.

The per-arm breakdown for `deadlock` is the cleanest table in the repo:

| arm | ask | n | container right | window hit | noticed | tokens/run |
|---|---|---|---|---|---|---|
| **blueprint** | hint | 15 | **15** | **15** | +1 s | 754k |
| **blueprint** | no hint | 15 | **15** | **15** | +1 s | 678k |
| none | hint | 15 | 3 | 2 | +180 s | 766k |
| none | no hint | 15 | **0** | **0** | +180 s | 709k |

Add the earliness detail: without a blueprint the agent reports the **recovery**
(+180 s median onset on a **125 s** fault); with one it hits the incident window
(**+1 s**). And the blueprint arm produced **zero wrong containers** — all 3
wrong-container answers were in the no-blueprint arm. Its failures are
abstentions, which is the behaviour we want when evidence is thin.

> **Three caveats you must carry on this slide:**
> 1. **One incident per matrix** (2 arms × 2 asks × **15 repeats**), not three.
>    So this measures repeat-stability on one incident, not breadth.
> 2. **The blueprint was handed over, not chosen.** This does not test selection.
> 3. `conn_pool_exhaustion`'s fault-label axis reads **0/60** — almost certainly
>    the same vocabulary bug that made `deadlock` read 0/60 the previous morning.
>    Use the container/window axes, not the label.

Harness health for transparency: `deadlock` had 278 thread messages elided and
39/1294 code snippets error; `conn_pool` had 1 tool result truncated, 280
elided, 32/1166 errored.

Source: `results-download/deadlock/DIGEST.md`,
`results-download/conn_pool_exhaustion/DIGEST.md`,
`blueprints/docs/SCORING-EXPLAINED.md`, `blueprints/README.md`.

### 9.3 Executable beats prose

The deterministic rule engine, reading the same kernel data with **no model at
all**, over **81 test runs, two apps, kernel traces only**:

- names the right fault **38 times out of 41 when it fires** — **93% precision**
- stays correctly silent on **26 of 29** runs it should ignore
- **declined all 5 healthy runs** (5/5)
- overall **64 of 81 correct (79%)**; 3 wrong; 14 "I don't know"
- all 3 wrong answers are the same confusion: **memory fault → noisy neighbour**
- improvement through the session: wrong answers **13 → 13 → 4 → 7 → 3**

The same knowledge rendered as markdown and handed to a capable model gets
**roughly half** that.

> **The rules transfer; the prose does not.**

Strongest preliminary finding, and it directly shapes what a blueprint should
*ship as*. This is RQ5.

A later extension to 86 runs holds the shape: **68/86 correct (79%)**, precision
when firing **46/50 (92%)** (`FINDINGS-phase1.md` F23).

> ⚠ `thesis/PROPOSAL.md` §5.3 says "declined all **8** healthy runs";
> `RESULTSv2.md` says **5/5**. Use 5/5 and cite `RESULTSv2.md`, or say "declined
> every healthy run" without a number.

Source: `blueprints/docs/RESULTSv2.md`,
`blueprints/problems/RESULTS-v2-all-blueprints.md`.

### 9.4 Blueprint vs five alternatives — the comparison study

The strongest "compared to what" result. Sock Shop only, **12 incidents**
(5 co-tenant CPU contention + 7 slow-datastore), one shared evidence pack per
run, one scorer. "Fully correct" = right component **and** right fault type.

| Method | Component | **Fully correct** | Precision | Median time | Cost/incident |
|---|---|---|---|---|---|
| **Blueprint** (rules, no model) | 83% | **83%** | **100%** | 508 s | **$0** |
| Agent + kernel pack | 100% | 58% | 100% | 128 s | $0.021 |
| Agent, no kernel pack | 100% | 58% | 100% | 118 s | $0.014 |
| Model only, no tools | 100% | 58% | 100% | **103 s** | $0.009 |
| Statistical rule-tree | 42% | 42% | 42% | — | $0 |
| BARO (published) | 0% | — | 0% | — | $0 |

**The split by fault is the result that matters:**

| Fully correct | Co-tenant (n=5) | Datastore (n=7) | Total |
|---|---|---|---|
| **Blueprint** | **5/5** | 5/7 | **10/12** |
| Agent + kernel pack | **0/5** | **7/7** | 7/12 |
| Agent, no pack | **0/5** | **7/7** | 7/12 |
| Model only, no tools | **0/5** | **7/7** | 7/12 |
| Statistical | **5/5** | 0/7 | 5/12 |
| BARO | 0/5 | 0/7 | 0/12 |

Three things to say with it:

1. **No LLM arm ever gets co-tenant contention right — 0/5 in all three model
   configurations.** The blueprint gets 5/5.
2. **Knowing which method fits which problem is the valuable part — and that is
   what a blueprint stores.** The statistical method wins on co-tenant and
   scores 0/7 on datastore; the model is the reverse. Only the blueprint is good
   at both.
3. **Where it loses: 508 s vs 128 s — 4× slower**, roughly 7–9 minutes of trace
   decoding per run.

**Two clean negative controls inside the same study** (both excellent slides):

- **Giving the model the kernel data changed nothing.** Component identical on
  **12/12**; fault type differed on 2 incidents and in both the pack turned one
  wrong answer into a *different* wrong answer. Tokens went **105,583 → 170,493
  = +61% for zero accuracy gain.**
- **The tool loop added nothing.** One model call with no tools scored the same
  as the full 7-tool agent — both **58% fully correct**.

**Abstention, measured:** the blueprint answers 10 of 12 and is correct on all
10. Its two non-answers are subtle datastore runs — aggressive runs inflate
`poll` **30.4–36.8×**, subtle runs **4.43–4.52×**, and the threshold is **5×**.
*"We did not lower the threshold to capture them. Moving 5× → 4× would score
12/12 on this test set and would be fitting to it."* That sentence is worth
quoting — it is the discipline in one line.

**Caveat verbatim:** *"Does not show — that this generalises. Twelve incidents on
one application, two fault types. **One incident moves the total by 8 points.**"*

Source: `blueprints/docs/RESULTS-comparison.md`.

> The Ciena deck reports a different, app-transfer version of this (blueprint
> 83% shop / 88% booking; agent 58% / 0%; metrics 42% / 100%) plus the honest
> detail that the **datastore blueprint failed on transfer at first, dropping
> from 100% to 44% precision**, because the second application's database did
> not poll constantly. Re-measuring on the second app fixed it and both ended
> equally good. **Blueprints evolve; that is the point.** Source:
> `blueprints/docs/presentations/presentation1/ciena-slides-notes.md`.

### 9.5 Where the modality claim gets measured

The dataset's whole thesis, in one line
(`blueprints/problems/RESULTS-v2-all-blueprints.md`, 136 runs, 7 blueprints):

> On Train Ticket `anomaly_net` the kernel blueprint fired **8/8**, while the
> campaign's metric check could only confirm **4/8**. The other 4 are
> `no_metric_signature`.
>
> *"That is the dataset's whole thesis, measured: a modality that sees what
> another cannot."*

From the same campaign: **false fires are almost absent — 3 in 826
opportunities.** And a corrected recall figure: of 58 misses, 36 are real and 22
are defensible (the fault was never confirmed either), so **corrected recall is
58/94 = 62%, not 50%**.

Six verification targets were corrected over 16–17 September, and the inventory
calls this *"a result and not housekeeping: in every case the fault was real and
the TARGET was wrong. The common flaw is targets that measure consequences
instead of mechanisms."* Example: `svc_net` on Train Ticket asked for a
*decrease* in transmitted bytes, but packet loss drives them **up** (15,938 →
31,517); the kernel trace measures **51.9–61.8% retransmission against a 0%
baseline**.

A second measured modality split, on the five injected **code defects**: two
move a metric, three do not. **The split is Node vs Go** — same class of bug,
opposite modality outcome. Trace volume agrees independently: 14–15 GB per
visible family against 26–33 GB for the three invisible ones.

### 9.6 Agent study — the 6-problem matrices (360 runs per app)

**Design:** 6 problems × (3 incidents × 2 arms × 2 asks × 5 repeats) = **360
runs per application, 0 failed**, both apps, kernel traces only, model
`gpt-5.4-mini`. **Blueprint handed over, not chosen.**

Best single cell, Sock Shop `noisy_neighbor`, no-hint arm:

| metric | without | with blueprint |
|---|---|---|
| both right | **13%** | **93%** (+80) |
| WHERE right | 60% | 93% (+33) |
| described | 42% | 87% (+44) |

Sock Shop WHERE-right by problem (out of 60): `anomaly_cpu` 55, `anomaly_net`
50, `noisy_neighbor` 40, `slow_db` 24, `svc_cpu_cap` 1, `svc_net` 0.

**The split is by scope, not difficulty.** Host-wide faults score 40–55/60;
single-service faults score 0–1/60 — because the kernel trace carries no service
names. That is the honest shape of the kernel-only limitation.

> **Caveats the docs state, and you must repeat:**
> - *"Ignore the `fault` column when comparing rows.* The blueprint text
>   describes the fault, so a `given` row can read the answer straight off it."
> - *"Pooled across problems this came out as **+0**, which is an averaging
>   artefact … **Never report the pooled number.**"*
> - `described` is a word check and the softest number here.
> - ⚠ **`TRAIN-TICKET-RESULTS-22-09-2026.md` has stale copy-pasted prose** — its
>   narrative quotes Sock Shop numbers and even says "Train Ticket. Zero runs."
>   **Only the tables in that file are trustworthy.**

Source: `blueprints/docs/SOCK-SHOP-RESULTS-22-09-2026.md`,
`TRAIN-TICKET-RESULTS-22-09-2026.md`, `Q2-FULL-6-problems.md`.

### 9.7 When a blueprint makes an agent *worse* — the portability finding

Measured 22 September 2026 on **600 runs** across two applications. Sharp,
quotable, and underused in the current slide plan.

On `anomaly_net` the blueprint arm found the incident window **far less often**
than the arm given nothing. It did not answer wrongly — it answered `unknown`.

| abstained, out of 30 | without blueprint | with blueprint |
|---|---|---|
| Sock Shop | 1 | **14** |
| Train Ticket | 9 | **23** |

Both applications, same direction, same size. Chasing it produced two findings.

**First, we had told the agent a falsehood.** The kernel recipe said "there is no
TCP retransmission tracepoint in this profile, so a retransmission rate is not
measurable." **False** — every packet event carries the full TCP header, and a
repeating sequence number on one flow *is* a retransmission, which is exactly
how the campaign measured 51.9–61.8% retransmission from these same traces. The
agent was told its deciding check was impossible and honestly refused to
conclude. **It behaved correctly on a false premise.** Correcting the recipe
moved the gap +13 → **+8** (SS) and +14 → **+8** (TT), and Train Ticket window
hits **1 → 6**.

> Honest sub-detail: on Sock Shop the *control* arm drifted by 3 runs, which the
> recipe fix cannot have caused. So **the recipe fix is demonstrated on Train
> Ticket, not on Sock Shop.** Three runs in 30 is the noise floor here.

Also worth noting: the first explanation was **wrong**. We blamed a line in the
base method, rewrote it, and re-ran all 360 Sock Shop cells. **It made no
difference** (14/30 → 13/30) and cost `noisy_neighbor` five points. *"Quoting a
rule is not the same as being bound by it."*

**Second, and this is the finding:** the discriminator is a **threshold on a
rate**. The agent can show retransmission *is or is not* happening, but cannot
compute a **rate** — `ctf_lines` returns at most 40 raw lines. So it sees the
signal, cannot satisfy the check as written, and abstains.

> **A blueprint whose deciding check is a threshold on a quantity the deployed
> tools cannot compute will make an agent abstain — even when the underlying
> signal is plainly visible.**

That is about **portability**: a blueprint authored where a rate was computable,
deployed where it is not, silently converts a capable agent into one that
refuses to answer.

The fix is now part of the method: **every thresholded discriminator needs a
qualitative fallback**, and a blueprint must state which of its checks are
unreachable in the current deployment and what to conclude without them. And the
evidence-first rule applies to the **recipes**, not only the discriminators —
the false sentence lived in the very file that enforces the rule on everything
else.

Source: `blueprints/docs/WHEN-A-BLUEPRINT-HURTS.md`.

### 9.8 The agent-feedback loop, working (October 2026)

Newest evidence, from `Blueprint/latency/` and
`progress-notes/12-10` through `17-10-2026/decisions.md`. Each new blueprint is
tested by the agent on its own fault **plus a healthy negative plus a
cross-fault cell plus the reverse** (another blueprint on *this* fault). The
negatives and cross cells are the point.

**The headline for this section, verbatim from the notes:**

> **"The loop that got here is itself the result: blueprint → agent run →
> failure analysis → two targeted fixes → correct verdict."**

The transcript chain is the audit record (`.bponly → .bponly2 → .bponly3`).

### The scorecard — 24 verdict cells across five blueprints

| # | blueprint | result | how it got there |
|---|---|---|---|
| 1 | `svc_cpu_cap` | **0/1 → 3/3** | three agent-run iterations (below) |
| 2 | `noisy_neighbor` | **3/4 → 4/4** | one round; the miss was a discovery (below) |
| 3 | `slow_db` | **2/4 → 4/4** | one round, three fixes (below) |
| 4 | `svc_mem_cap` | **5/5 first try** | zero iterations needed |
| 5 | `svc_net` | **4/4** | tested on **unseen data from day one** |

**Across all of it: zero confident wrong answers.**

### Blueprint 1 — three iterations, and a token result

Same run, same model, three conditions:

| | full toolkit | blueprint-only, v1 | blueprint-only, v2 |
|---|---|---|---|
| verdict | cpu_throttling, right container, 0.20–0.24 cores | cpu_saturation, "host" | **cpu_throttling, right container, 0.25 cores** |
| correct? | yes | **NO** | **yes** |
| tool calls | 69 | 31 | 38 |
| tokens in | 1.41M | 0.50M | **0.49M** |
| wall | 560 s | 569 s | **375 s** |

> **The blueprint plus its own nine scripts matches the full-toolkit verdict at
> about one third of the input tokens and two thirds of the wall time.**

Three findings underneath that are more interesting than the number:

1. **First blueprint-guided run: correct verdict, blueprint tools never used.**
   **0 of 69** tool calls used the blueprint's scripts. The planner's subtasks
   mirrored the blueprint's *method*, but the workers executed it with generic
   tools and self-written pandas. *"Blueprint worked as knowledge, not as
   toolkit."* That is what motivated `--blueprint-only` mode.
2. **The A/B diagnosed three blueprint-rule failures, not model failures.** The
   sharpest: *"The blueprint assumes a cap hits ONE process; a cgroup cap hits a
   process TREE"* — two victims showed long waits, and the rule "many processes
   suffer → whole machine short of CPU" pushed the answer to `host`.
3. **A second miss gave a transferable lesson about tool output.**
   `victim_info.py` printed `cgroup_ns=0, ipc_ns=0, net_ns=0` for fields it
   could not read, and the model read that as "different namespaces → a separate
   container". Rule: **"A 0 that means 'unknown' must not look like a namespace
   value."**

And note the failure *mode* is tracked as a quality in its own right: *"not a
confident wrong answer (v1's 'host') but an honest 'unconfirmed' — the fixed
blueprint degrades gracefully."*

### Blueprint 2 — the miss that was a discovery

`noisy_neighbor` was chosen deliberately as blueprint 1's **nearest
look-alike**, so the two form a **discrimination pair**.

Round 1 scored 3/4, and the one miss is the find:

> **N equal busy threads on C cores each settle at a flat ~C/N of a core — fair
> sharing mimics a quota ceiling.**

The blueprint called a contention run a cap, because 92% flatness at 27 ms per
100 ms looks exactly like a quota. **The separator is the idle share:** a cap
leaves the CPU **96% idle** during the victim's waits; fair sharing leaves it
**1%**. Fixes went into *both* blueprints, and round 2 passed every cell.

### Blueprint 3 — `slow_db`, and a tool rewritten mid-build

A design discovery changed the instrument: **blocking-read durations measure
nothing on async runtimes.** Go and Node use non-blocking sockets plus epoll, so
`read()` returns instantly — *"every read took 0.0 ms while every request took
500 ms."* The tool was rewritten to measure the **request-to-answer gap**
(completed write → next completed read with data), which works for threaded and
async runtimes alike.

Round 1 (4 cells): 2 pass, 1 near-pass, 1 miss. Three fixes applied
(the CPU gate became the first mandatory action over the whole budget table; a
mirror rule to name the peer; an explicit instruction to commit to the label
when the evidence held). Round 2 on the fixed blueprint:

| cell | round 1 | round 2 (fixed) |
|---|---|---|
| blueprint on `slow_db_r1` | "other", 0.68 — found the right evidence but refused the label | **`db_latency` 0.92** — names the app-to-mysqld path, quotes 0.9 ms → 418.7 ms and the mysqld mirror 0.3 → 501.6 ms, and reasons "no CPU/disk strain on mysqld → path, not a struggling database" |
| blueprint on `svc_cpu_cap_r3` | `service_network` 0.78 — a false call | "other" 0.78 — **correctly refuses** the dependency diagnosis |

### Blueprint 4 — the first to pass with zero iterations

`svc_mem_cap`, **all 5 cells pass first try.** The discriminator is the event
*name*: `mm_vmscan_memcg_reclaim_*` means the container's own limit; direct
reclaim plus `kswapd` means the host is full. Measured: **9,224 memcg reclaims
by the victim in 32 s; baseline zero; host events zero.**

The decisive rule, and how it was built, is the best single example of
evidence-first authoring in the repo:

- the **kill-vs-finish gap** — a killed process exits *inside* its final
  reclaim (**0.02–0.37 ms** on 3 known kills) while a process that finishes
  under pressure exits **7.9–48.3 ms** after (5 known finishes). Threshold 1 ms,
  **20× margin**.
- **two earlier candidate rules were rejected by the data**: "died near
  reclaim" false-fired on normal soft-cap completion, and "parent died with it"
  failed because a killed child's wrapper also exits.

On the OOM cell the agent quoted the rule with the exact number: *"777 memcg
reclaims, exited 0.02 ms after its own last reclaim → hard-limit kill."*

Why it needed no iteration, per the notes: *"the evidence-first discipline plus
the lessons baked in from blueprints 1–2 (stop rules, honest hedges,
decisive-check-first) carried over."* **That is the library getting better as it
is used — which is the thesis.**

### Blueprint 5 — tested on unseen data from day one

No local run holds a network fault, so `svc_net`'s matrix ran on data the
blueprint had never seen. **4/4**, and two cells are notable:

- on the unseen positive: **`service_network`, right container, confidence
  0.94** — *"degraded path to/from MongoDB, retransmit both directions 1.4–1.9%
  vs 3/107,201 baseline, traffic fell 30–55×, delay inferred from collapse."* It
  replicated the whole evidence methodology on a run it never saw, **including
  the honest "delay is inferred" framing**.
- on the cross-fault cell it did not merely reject — **it routed**, naming
  `cpu_throttling` with the right container at 0.87, which is *better than the
  CPU blueprint's own earlier answer on that same run*.

Its measurement artifact is worth a slide too: the trace has no `tcp_*`
tracepoints, but `net_dev_queue` carries full TCP headers. A packet crossing
veth→bridge **fires the event once per device**, so naive counting reads ~50%
"retransmission" on every healthy flow. Fix: count each flow at **one**
observation point. After the fix, baseline is **4 of 90,107 segments = 0.0%**.
And the conclusion is not the obvious one: **"the 150 ms delay, not the 4% loss,
does the damage."**

### Blueprints route to each other — measured on unseen data

The strongest single result in this section. On an unseen 2×2 from the real
dataset (different app, different scale, different injection from the runs the
blueprints were iterated on), **each blueprint solved the *other's* fault**
while being over-cautious about its own:

| cell | verdict | outcome |
|---|---|---|
| CPU blueprint on the CPU fault | "other", right container, 0.82 — measured the starvation exactly but withheld the label | honest near-miss |
| **neighbour blueprint on the CPU fault** | **`cpu_throttling`, right container, 0.90** | **correct, via routing** |
| neighbour blueprint on the neighbour fault | "host/cpu_saturation", 0.76 — *found* the aggressor but its dominance rule refused it at 18% | honest near-miss |
| **CPU blueprint on the neighbour fault** | **`noisy_neighbor`, named the injected aggressor container, 0.76** | **correct, via routing** |

> **Both unseen runs were diagnosed correctly by the pair.** 2/4 exact, 2/4
> honest hedges, **zero confident-wrong.**

This is the clearest evidence that **the library, not the single blueprint, is
the artifact** — the look-alike tables point in both directions and the
routing-out rules turned out to be load-bearing.

It also produced a rule worth quoting, because it is what the real dataset
demanded and the local runs did not: the neighbour criterion is now **two-form**
— *heavy* (dominates the wait time, idle small) or *subtle* (the group is
**new**, absent in the baseline, its arrival coincides with the waits, even at
15–25% share). The rule's name is **"arrival beats share."**

### The pattern across every blueprint's first unseen round

> negatives clean · positives find the right evidence but **under-commit** ·
> cross-fault cells expose exactly one missing rule · **never a confident wrong
> answer**

"Never a confident wrong answer" is the behaviour you want from captured
expertise, and it is a strong slide.

**Catalogue state at the latest commit: five blueprints, every decision rule
measured before writing, 24 agent-verdict cells.** Held-out unseen pools remain
for later: `slow_db` r2–r5 + burst + subtle + 11 Train Ticket runs with
`no_metric_signature` (where the kernel blueprint is the **only** evidence), and
8 + 8 unseen `svc_mem_cap` runs.

**One known weakness, diagnosed but not fixed:** cross-fault routing fails when
the fault spans most of the trace, because both the agent's slices then sit
inside the fault window and the symptoms look "already present" versus its own
baseline. Say this if asked — it is a clean, specific limitation.

> These numbers (0.92, 0.88, 0.94, 0.98) are the **agent's own confidence** on a
> matrix cell, recorded in the progress notes and the transcripts — not a
> precision/recall score. Say "the agent committed to the right label at 0.92
> confidence", not "the blueprint scores 0.92".
>
> Where the evidence lives: `progress-notes/17-10-2026/decisions.md` and
> `Blueprint/agent/transcripts/v2/*.json` (e.g.
> `slow_db_aggressive_steady_r1.sdb1.json`,
> `svc_cpu_cap_aggressive_steady_r3.unseen.json`).

### 9.9 Kernel portability — a blueprint can silently fail on another kernel

Found 15 Oct 2026 while testing the `svc_cpu_cap` blueprint on the agentic runs.
This is a **1-fault / 1-baseline qualitative case study**, not a scored
evaluation.

`sched_budget.py` counted only `prev_state == 0` as CPU-wait. On the GCP VM's
kernel (7.0.0-1011-gcp) a **preempted-runnable** thread is reported as **256**
(`TASK_REPORT_MAX`), which the script dropped. So **every agent thread read ~0
wait** and the blueprint's Steps 2–3 flagged **no victim**. The README text said
to count 256 too — a doc/code mismatch.

| | waits ≥1 / ≥10 / ≥50 ms | max |
|---|---|---|
| fault run, as written | 2 / 0 / 0 — **no victim shown** | ~2 ms |
| fault run, fixed (count 256) | **126 / 126 / 126** — victim jumps out | **89 ms** |
| uncapped baseline, fixed | ~0 / 0 / 0 — correctly no victim | <1 ms |

The 89 ms max freeze ≈ the 100 ms quota period, and 126 freezes ≥50 ms is the
burst-and-freeze signature. Ground truth from `cpu.stat`: `nr_throttled = 208`,
`throttled_usec = 20.1 s` (≈97 ms per throttle).

The clean mechanism behind it:

- **time-slice contention** → `prev_state = 0`
- **CFS bandwidth throttle** → `prev_state = 256`

Two further honest findings from the same evaluation: Step 6's whole-run
averaging **breaks on a bursty workload** (the agent is ~84% idle waiting on the
LLM, so `swapper` dominates and the victim reads `run = 0.09`) — slicing to the
active window is mandatory. And `cpu.stat` is cheap ground truth the blueprint
excluded; it should be promoted to a Step-0 cross-check.

> The verdict in the file: *"The blueprint's **method is correct**, but **out of
> the box it fails on the agentic traces** for two reasons, both fixable."*
> Present it that way. It is a portability finding, not a win.

Source: `Blueprint/latency/1_svc_cpu_cap/EVALUATION-on-agentic-runs.md`,
`progress-notes/15-10-2026/decisions.md`.

### 9.10 Reproducibility is part of the claim

While validating a performance change, the same script produced a **different
output row order** on consecutive runs over the same trace. Values were always
correct; ordering followed the interpreter's per-process string hashing through
**23 un-tie-broken sorts**. **Two of those sorts feed a verdict by reading the
top row**, so a tie could in principle name a different service.

Fixed and verified under forced hash seeds.

Worth reporting because a blueprint claims to be a **re-runnable**
investigation. Reproducibility is therefore part of the claim, not a detail.

Source: `thesis/PROPOSAL.md` §5.5, `progress-notes/03-09-2026/decisions.md`.

### 9.11 Two credibility beats worth a slide each

**The measurement recovers the injected parameter.** On CPU-cap runs, read out
of `sched_switch` with **no knowledge of the recipe**: recipe cap 1.0 →
measured 0.988 and 0.997; recipe cap 2.0 → 1.978, 1.978, 2.002. **Within ~1% of
ground truth.** Source: `FINDINGS-phase1.md` F3.

**We diagnosed our own instrument.** `nagle_delayed_ack` fired
`host-disk-saturation` in **10 runs out of 10**. The arriving process was
**`lttng-consumerd` — our own trace collector**. Excluding it removed all 10
false diagnoses at zero recall cost.

> *"For one fault family, we were measuring the measurement."*

The same instrument shows up in the metrics: LTTng writes **~53 MB/s**
continuously on Sock Shop — **exactly the measured baseline** of
`node_disk_written_bytes_total`. *"Bounded metrics are blind to faults our
collection contends for."*

Source: `blueprints/docs/RESULTS-antipattern-ceiling.md`,
`DATASET-v2-INVENTORY.md`.

---

## 10. Honest limits and negative results

Naser's standing instruction: **a negative result is a result.** The thesis
should say where blueprints do not help, not claim they always do. There is a
lot here — pick two or three.

### 10.1 Two faults proven NOT diagnosable from kernel traces

After six and one measured attempts respectively: a **frozen service** and a
**silent queue backlog**. Both are defined by *absence* — the container stops
answering without losing packets or going quiet in the scheduler.

The decisive measurement for the frozen case: the **strongest freeze signature
in the data belongs to the slow datastore** (`mysqld`, 10 of 11 threads stopped
being scheduled). *"Absence of on-CPU time cannot distinguish 'frozen by the
cgroup freezer' from 'blocked on I/O'."*

For the queue case: *"'The queue went quiet' means 'the system slowed down', not
'the consumer is paused'."* The same shape appears in **seven of thirteen** Sock
Shop families.

**This matches the pre-registered predictions in `fault_catalog.md`** — and in
the queue case it *contradicts* them: the catalogue named kernel as the winning
modality, and we could not deliver it. **The pre-registration is not confirmed
there, and the file says so.**

Source: `FINDINGS-phase1.md` F11–F15, F19; `BLUEPRINT-BACKLOG.md`.

### 10.2 We cannot write many more blueprints — the data does not support them

The scope-honesty slide. From
`blueprints/docs/COVERAGE-which-blueprints-are-missing.md` (272 packs, 25
families, 45 signals):

> **"12 families have a blueprint. 12 do not — 101 runs."** But *"we cannot
> write 13 more blueprints. **The data does not support them.** Only two are
> worth attempting."*

**11 families are not buildable from kernel traces (86 runs).** Six of the
thirteen were collected on one application only — *"a collection gap, not an
analysis gap."*

> *"Naser asked for negative results, twice. This is one."*

And the reason some families separate on nothing is itself a finding: the
`code_*` families measure **28.6–79.9% retransmission in the BASELINE window**
against 0–5.6% everywhere else. *"Nothing separates these families because the
loudest thing in the data is the injection mechanism."*

One family **is** buildable and shows the argument for a blueprint over a
threshold inside a single fault: `dns_delay` needs **two gates** — EMFILE share
≥ 0.0175 (11× margin against a descriptor cap) *and* retransmission < 12% (to
remove the network family).

### 10.3 Anti-patterns vs real faults

Can RCA tell "something broke" from "the code is badly written"?

| | before | after |
|---|---|---|
| a blueprint fired and should not | **46 of 156 (29%)** | **19 of 156 (12%)** |
| a blueprint owns the run and got it right | 85 of 116 (73%) | **85 of 116 (73%)** |

**27 false diagnoses removed, none of the correct ones lost.**

The separating measurement: socket wait against each run's own baseline reads
**1.07–144×** for `slow_db` (22 runs) but **651–2462×** for the five code-defect
families (25 runs). A ceiling at the geometric midpoint, **306×**, keeps 22 of 22
owned runs and excludes 25 of 25 defect runs — **2.13× margin on both sides.**

Source: `blueprints/docs/RESULTS-antipattern-ceiling.md`.

### 10.4 The result that started the whole specificity programme

`FINDINGS-phase1.md` F2 — present this if you want the "we did not believe our
own good numbers" beat:

> **42% false-positive rate on the negative class, and every false fire is
> confident.** 5 false fires in 12 negatives; **none abstained**; all reported
> **0.80–0.85 confidence**.
>
> Worst case: `normal_none_burst_r1` — **a healthy system under a bursty
> workload — diagnosed as a noisy neighbour on the host at 0.80 confidence.**

And the structural reason the earlier "100% precision" number meant nothing,
from `RESEARCH-PLAN-phase1-kernel.md`:

> *"Every evidence pack we have is from one of the two families the blueprints
> are designed to fire on. **A false positive was structurally impossible in
> that test set.** The 100% precision number is therefore not a specificity
> measurement — it is a sensitivity measurement with no negative class."*

The stated standard that came out of it: *"**Success is not 'zero false
fires.'** It is knowing the false-fire rate and why."*

### 10.5 Transfer across applications is uneven

- Blueprints fire on confirmed faults **41/58 (71%) on Sock Shop** vs
  **17/58 (29%) on Train Ticket** (`RESULTS-v2-all-blueprints.md`).
- The rule engine's 14 "don't knows": **11 of 14 are Train Ticket.**
- *"Same fault, two architectures, two different signatures. **That is blueprint
  content, not a bug.**"* (F7)
- The apps are genuinely different: normal host CPU use **48% (SS) vs 82% (TT)**;
  ~16 vs 40+ services; different hardware (**12 vs 16 CPUs**).
- Three fault families **are not the same experiment on the two apps** — e.g.
  `svc_cpu_cap` on Train Ticket targets a service using **0.0033 cores against a
  0.2-core cap — 60× headroom**, so there is nothing to throttle.

### 10.6 Other recorded negatives (one-liners, pick what fits)

| Result | Number | File |
|---|---|---|
| Removing thresholds is worse | **12× the false fires** (3/826 → 38/826); recall 76% → 71% | `RESULTS-v2-threshold-free.md` |
| A 16/16 result **retracted** | `service-memory-cap`'s negative set excluded `anomaly_mem`, its closest look-alike | `RESULTS-v2-uncovered-faults.md` |
| One signal that must never ship | `softirq_x` points in **opposite directions** on the two apps | `RESULTS-v2-rederived.md` |
| A metric that is "what overfitting looks like" | `error_newcomer_per_s` band | `COVERAGE-...md` |
| Two metrics unusable as defined | `tail_ratio` produced 1735 / 18545 / 246522; `min reply ratio` reads 0.00 in every family | `FINDINGS-phase1.md` F13 |
| Kernel lock tracepoints do not exist on our kernel | **0** `lock_*` tracepoints; "not collectable without a custom kernel" — so the lock blueprint is about **user-level `futex`** locks | `LATENCY-CAUSES.md` |
| A lock blueprint must key on shape, never total | first run read **408 seconds of futex wait per second of wall clock**; `java` alone waited 6684 s over 22,036 calls ≈ 300 ms each — **thread pools parked, not contention** | F22 |
| A silent windowing bug | one run reported host utilisation of **−0.000** because its fault window **crossed midnight** (span computed as −86,340 s). Blast radius 1 run of 93, but silent — so all four windowing scripts were fixed. **And the first fix was wrong** | F8 |
| The author's own process failure, recorded | *"I made the mistake E1 exists to catch: I tested the network signal on 8 families, not 13."* The fix cost **1 more miss to remove 6 regressions** | F17 |
| A blueprint that had never been evaluated | *"`host-disk-saturation` has been in the decision engine's verdict table since it was built, and had never once been evaluated. It was counted as 'built' for a month."* | F23 |
| Silence, not mis-selection, is the bigger gap | of 76 runs where no blueprint fired, **56 are fault runs that got no answer at all.** *"Fixing selection would not have moved a single one of these 56 runs."* | `RESULTS-v2-all-blueprints.md` |
| Audit of the dataset | **59 of 303 runs are not okay. 244 are fine.** 32 injections did not take + 27 contaminated baselines, zero overlap. Honest gap: **31 runs have no analysis pack**, so their baselines were never checked and are counted as usable | `AUDIT-v2-full.md` |
| Thinnest margins in the library | `db-latency` **1.01×**; `service-cpu-throttle` **1.01×**. *"The top two have about 1% of room."* | `RESULTS-blueprint-cards.md` |
| External validation is not available for phase 1 | RCAEval, LEMMA-RCA, LO2, Loghub carry metrics/logs/spans — **not kernel traces** | `RESEARCH-PLAN-phase1-kernel.md` |
| Unrecoverable data loss | **103 of 134** Train Ticket runs have no client-side request CSV. *"The lost CSVs are not recoverable."* | `DATASET-v2-INVENTORY.md` |
| The trap that cost two days | between 16–18 Sept the working copy held **116** Sock Shop runs instead of 170 — ten whole families absent — **and nothing errored** | `DATASET-v2-INVENTORY.md` |

---

## 11. The agentic leg — OS noise on coding agents

The agent is not only the *consumer* of the library; it is also a **system under
observation**. That is what makes the framing bigger than root cause analysis.

**Keep this to ONE proof point on the scope slide.** It is a separate paper and
the thesis talk should not fork into it
(`progress-notes/15-10-2026/decisions.md`).

**The paper:** *"OS Noise for Agentic AI: A Kernel-Trace Study of How Container
Resource Limits Slow Down and Break AI Coding Agents"* — Yuvraj Sehgal, Sneh
Patel, Mahsa Panahandeh, Naser Ezzati-Jivan.
`Blueprint/research-paper/paper.tex`. Standalone artifact repo:
`C:/workplace/os-noise-for-agentic-ai` (local git only, Zenodo DOI pending).

**The claim:** an agent's own compute demand is small and fixed. When a sandbox
limits a resource the agent does not do less work — **it waits, or it dies.** On
an adequate box it is LLM-bound; past a configuration threshold the OS is the
bottleneck, not the model.

**Design:** one GCP VM (**4 vCPU / 16 GB**), LTTng kernel tracing only, no
metrics. Two production agents: **Claude Code** (node) and **Codex CLI** (Rust).
Each run wipes and regenerates a byte-identical task repo, puts the agent in a
cgroup, sets **one** limit, and records the full kernel trace plus the cgroup's
own counters as ground truth. **5 reps per condition**, shuffled order, medians.
Trace on-CPU validated against `cpu.stat` to **97–99%**. Hypotheses
pre-registered per problem. **260 runs in the four-problem campaign (130 Claude +
130 Codex).**

### The catalogue

| # | Problem | Knob | Mechanism | Headline |
|---|---|---|---|---|
| 1 | CPU cap | `cpu.max` | CFS throttle | **0.25 core → +75% wall.** Throttle ladder monotone: 0 → 0.3–0.5 → 4.4–6.3 → **13.7–19.8 s**. On-CPU flat across caps — compute is fixed, the agent just waits |
| 2 | threads vs cores | over-parallelism on 4 vCPUs | run-queue contention | **4× cores → +295% wall** (+91% at W=8). Runnable-wait 0 → 0.05 → 0.93 → 2.81 s. **The textbook law, exact**: measured wait fraction 0.497 / 0.747 vs predicted (W−C)/C = 0.500 / 0.750 |
| 3 | memory cap | `memory.high` / `memory.max` | reclaim + refault / OOM | **4.7× slower** (page cache) **or killed mid-task** (anonymous). Sharp binary OOM cliff **between 640M (3/3 killed) and 768M (3/3 fine)** |
| 4 | disk I/O cap | `io.max rbps` | block-layer throttle | **50 MB/s → 3.4× slower**; wall ∝ 1/rbps once the cap is below native disk (~205 MB/s). Throttling exact: 1 GB / 20.4 s = 50 MB/s |

**The headline cross-cutting number: ~84% of wall-clock time has an LLM request
in flight** on a healthy box (median over n=10, per-run range **80–91%**), while
local computation is only **~4.7 CPU-seconds** per run. Under a tight cap that
share falls to **53%** at a quarter core — the OS takes the wall clock the model
used to own.

**Why kernel tracing is needed, in one line** (great slide for the whole
thesis):

> `cpu.stat` tells you *that* the cgroup was throttled and for how long; the
> wall clock says the run got slower. Neither says *what* the agent waited on.
> **Counters measure that and how much; the trace measures what and where.**

### Three findings that land well

**The agent harness is well-behaved; the configuration is the danger.** Claude
Code **probes the core count** — exactly **18 `sched_getaffinity`/`sysinfo`
calls per run, independent of N** — and does **not** oversubscribe CPU. Its
sub-agent bursts are ~0.4 s each, uncontended, and **staggered, not stacked**
(~20 stalls vs 2550 in the forced-parallelism condition). So the contention risk
is real but needs explicit over-parallelism, not the default path. This answers
Naser's "do they check cores?" with **yes**.

**"A sandbox memory limit silently kills your tools mid-task."** Two regimes:
the OOM killer takes the **worker**, not the agent — the agent survives, detects
SIGKILL (exit 137), reports the correct reason, and completes its turn with a
failure report. But when the *agent itself* is in the kill path (128/96 MiB) it
thrashes for minutes, gets killed repeatedly (**6 OOM kills at 128 MiB**), and
dies with no clean report. **No graceful degradation.**

**It replicates on a second agent, and the one difference is instructive.** 130
Codex runs at 1:1 parity. Problems 2, 3A and 4 are identical to within noise
(e.g. threads W=16 phase 3.9 s vs 3.8 s; memory refault 1.0M vs 1.0M; disk
20.4 s vs 20.4 s). Both are **≥80% LLM-bound uncapped**, measured independently
through each agent's own API socket. The difference: the **OOM cliff moves with
the agent** — Claude (node, ~250 MB RSS) + a 512 MB workload ≈ 762 MB, so it
dies at 640 MB (3/3); Codex (Rust, much smaller) survives 640 MB (0/3). Same
mechanism, different threshold, because the cliff sits at *agent RSS +
workload*. **A leaner harness buys headroom.**

### The end-to-end check (answers "but does it matter on a real task?")

A real coding task (edit code, run tests), Claude, medians, n=3:

| limit | total time | success |
|---|---|---|
| unlimited | 21 s | 3/3 |
| CPU 0.25 core | 33 s (+75%) | ok |
| memory ≥192 MiB | 20–26 s | 3/3 — no effect |
| memory 128 MiB | **149 s** | **1/3** — 6 OOM kills |
| memory 96 MiB | **656 s** | **0/3** |
| disk 50 / 20 MB/s | 23–25 s | 3/3 — no effect |

> **"Only CPU bites a lightweight coding task."** The agent survives down to
> ≈192 MiB by reclaiming page cache, then falls off a cliff — and the cliff is
> the agent's **own footprint** (node ≈190 MiB), not a synthetic allocation.

**Takeaway for the scope slide:** across four independent resources, a mis-set
container limit adds **1.7×–4.7×** wall time or kills the agent's tools. Naser's
"even 5% would be a finding" bar is cleared by a wide margin.

Sources: `Blueprint/latency/OS-NOISE-FOR-AGENTIC-AI.md`,
`Blueprint/research-paper/{LLM-SHARE,CONSISTENCY,E2E}-RESULT.md`,
`agentic-runs/*/RESULTS.md`, `progress-notes/12-10-2026/` and `13-10-2026/`.

---

## 12. Numbers you must not use

Each of these has been mis-quoted at least once in this repo's history.

| Banned | Why |
|---|---|
| **"50% → 70–80%"** | appears in **no** result file. `RESULTS-withwithout.md` explicitly forbids it: *"That was said from memory in the 16 Sept meeting."* |
| the **pooled blueprint effect** across the 6-problem matrices (reads +0) without the per-problem split | an averaging artefact — ceiling and floor problems cancel the middle. The doc says *"Never report the pooled number."* |
| the `fault`-label column when comparing with/without rows | the blueprint text names the fault, so a `given` row can read the answer straight off it |
| `service-memory-cap` at **16/16** | **retracted 11 Sept** — the negative set excluded `anomaly_mem`, its closest look-alike |
| **"40/40 detected, 0 false alarms"** for the agentic CPU-cap evaluation | not in the evaluation file. It is an index claim in `Blueprint/README.md`; the "40" is a *runs collected* progress counter |
| any **`verified_by`** claim | *"Every blueprint still says `verified_by: PENDING`."* Nothing is human-verified yet |
| any verdict breakdown from `DATASET-v2-INVENTORY.md` that has to **sum** | four arithmetic inconsistencies (see §8) |
| any **narrative sentence** from `TRAIN-TICKET-RESULTS-22-09-2026.md` | stale copy-paste from the Sock Shop file; it even says "Train Ticket. Zero runs." The **tables** are fine |
| the with/without doc's **"`n_no_pick: 0` / every run picked something"** | the raw JSON records 30 runs with `skill: "none"`. The summary field is buggy |
| **"<1% variation"** for the OS-noise work | Mahsa's review proved it false — wall time varies **10–15% from LLM noise alone** |
| **"on-CPU matches `cpu.stat` to within 0.1–3%"** | false. Across 40 runs: median error **2.2%**, max **17.6%**, 17/40 over 3%. Already corrected in the paper |
| **"260 controlled runs"** as the whole OS-noise study | 260 = 130 Claude + 130 Codex for the four-problem campaign. The end-to-end work adds ~51 more (~311). Say "over 300" or scope it explicitly |
| anything from `Blueprint/research-paper/` presented as a **blueprint** result | different research track |

**One stale warning you can ignore.** `presentation-plan.md` says
`blueprints/problems/deadlock-lock-order/blueprint.json` has a trailing comma
and is invalid JSON. **Checked 19 Oct 2026 — all 16 `blueprint.json` files parse
cleanly.** Nothing to fix.

---

## 13. Research questions and status

From `thesis/PROPOSAL.md` §4. The abstract names four evaluation questions;
these eight are the full set behind them.

| RQ | Question | Status |
|---|---|---|
| RQ1 | Does an agent with a blueprint diagnose better than the same agent without one? | **measured once** — a tie (§9.1) |
| RQ2 | Does a blueprint transfer to a different incident, service, and application? | partially measured (§9.4, §10.5) |
| RQ3 | Does a blueprint beat a strong **deterministic** control, not just a naive agent? | **measured** (§9.4) |
| RQ4 | On faults no blueprint covers, does the library stay quiet or mislead? | **measured** (§10.1–10.4) |
| RQ5 | Does shipping **executable code** beat prose describing the same step? | **strong preliminary signal** (§9.3) |
| RQ6 | Can a blueprint's collection order cut the data needed without losing accuracy? | designed, not run (setup D) |
| RQ7 | Can a selector choose the right blueprint from **evidence alone**? | **measured — this is the bottleneck** (§9.1) |
| RQ8 | Can blueprints be **mined** from past investigations rather than hand-written? | future work |

**RQ5 and RQ7 are where this thesis can say something others cannot** — RQ5
because the harness is leak-audited and can measure run-to-run variance, RQ7
because the library is large enough for wrong selections to actually happen and
be counted.

**Why RQ3 exists at all, and why it matters for how you present RQ1.** On 21
August we measured that **a one-shot model call with a good deterministic
briefing ties the full tool-using agent** (78% / 52% both ways, at **27% of the
tokens**). So the control in every with/without experiment is that strong brief,
in **both** arms — not an unaided model. *"A blueprint has to earn its place
against that control."* This is what the abstract means by "deliberately
unkind", and it is the honest reason the headline result is a tie rather than a
win. Source: `blueprint-idea.md`.

### Scope, as set by the supervisor (3 September 2026)

- **Around ten classes of operational issue**, beginning with latency.
- **Telemetry in general** — metrics, logs, traces, kernel — beginning with
  kernel traces, because that is the layer existing corpora omit.
- **Microservice, monolithic, and agentic** systems, where an AI agent is both
  the consumer of the library *and* a subject under observation.
- **No industry partner named** in the thesis.
- Framing is **agentic software observability**, not "root cause analysis" —
  Naser's point was that RCA undersells the work.

Latency on kernel traces is the **starting point, not the boundary**. The design
must not assume one issue class, one telemetry type, or one system class.

### Why selection is the next piece of work

The measured bottleneck. Phase 2 replaces the flat library with a **parent
latency blueprint that routes to children**, so the agent narrows rather than
guessing from a flat list.

**But there is a confound to fix first** (`blueprints/docs/AGENT-DESIGN.md` —
this is a design, nothing in it is built):

> The symptom words are invented per blueprint — **24 words across 11
> blueprints, and 22 of the 24 are used by only one blueprint.** Matching on
> them would pick the right blueprint almost every time — not because selection
> works, but because **the word names the answer.** *"If we build on this, our
> selection score is meaningless."*

Fix: one shared vocabulary every blueprint draws from. Until then, **our earlier
selection numbers may be too kind.** Two other gaps the same doc names:
`cheap_precheck` is prose, not a runnable test (a person can run it, a program
cannot — 10 of 11 blueprints are affected), and `service-memory-cap` is
incomplete (no precheck, no `capabilities_required`).

The planned agent flow:

```
1 TRIAGE   is anything wrong at all?   -> if no, stop and say "healthy"
2 SURVEY   cheap, fixed measurements   -> a list of symptom words
3 RANK     score all blueprints        -> an ordered shortlist
4 CONFIRM  run the top one properly    -> verdict, or switch, or give up
5 REPORT   fault, service, evidence, confidence
```

**Triage does not exist yet.** Every test to date told the agent a fault
happened; it only had to say which one. *"A tool that finds a fault in a healthy
system is worse than no tool."*

The baseline a reviewer will ask about: **run all 11 blueprints and keep the
best.** If our agent matches that while running **1** blueprint instead of 11,
that is the result. The planned scale is ~83 Sock Shop + ~78 Train Ticket runs —
far more than September's 57 — with the **healthy runs kept in, because they are
the point**.

### Phases of proposed work

From `thesis/PROPOSAL.md` §6: latency cause taxonomy → **hierarchical selection
(the bottleneck)** → purpose-built micro-benchmarks → the stronger
with/without (neither arm gets pre-computed evidence) → transfer and external
validation → writing.

Two gaps may be answerable from **data already collected**: we record all
syscalls (so `futex` waits are present) and the IRQ families, and neither has
been fully analysed.

---

## 14. Contributions (the closing slide)

1. **The blueprint format and the method for producing one** — measure-first,
   validator-enforced, no discriminator admitted until measured against *all*
   fault families. **The method is the contribution, not any single blueprint.**
2. **StrataTrace** — the first public incident dataset time-aligning kernel
   traces with application traces, logs and metrics under labelled fault
   injection.
3. **An honest map of where captured expertise helps** — including that it is a
   tie overall, that it rescues faults a model cannot do unaided, and that every
   observed harm came from **misrouting**, not bad content.
4. **The rules-versus-prose result** — executable decisions transfer to an
   agent; the same knowledge as text does not. A direct design consequence for
   anyone building agent skill libraries.
5. **Reproducibility as a requirement** for executable diagnostic artifacts,
   with a concrete failure mode and fix.

---

## 15. Likely questions, with answers

1. **"How is this different from a runbook?"** A runbook is prose for a human. A
   blueprint is executable (steps bind to real commands), its claims are
   measured against every fault family, and it must say when it does not apply.
   The validator rejects anything that is just prose. And we can now say by how
   much it matters: retransmission alone gets 44 of 272 runs wrong; the whole
   rule gets 268 of 272 right.
2. **"Isn't this just retrieval / prompt engineering?"** We tested that. The
   same knowledge as markdown gets roughly half the accuracy of the executable
   form. We also tested giving the model more data: **+61% tokens for zero
   accuracy gain.** The artifact under study is the **investigation**, not the
   prompt.
3. **"If the deterministic rules score 93%, why have an agent?"** Rules only
   cover faults someone already solved, and abstain elsewhere. The agent handles
   the open set, adapts when evidence does not fit, and explains. The thesis
   measures the **division of labour**, not one side.
4. **"Two applications — will this generalize?"** That is a research question,
   not an assumption. We have already *measured* that it transfers unevenly —
   71% on one app, 29% on the other — and that the rules which transfer are the
   ones keyed to a physical bound. Transfer is RQ2, plus purpose-built
   micro-benchmarks to remove the two-app objection.
5. **"Who writes the blueprints? Does this scale?"** The *method* is the
   contribution. Mining blueprints from past investigations is named future work
   (RQ8).
6. **"What if selection never gets good enough?"** Then that is the finding. The
   tie is reportable, and we already know the failure is routing, not content.
   The hierarchy is the designed fix; abstention is measured.
7. **"Why kernel traces first?"** The layer every public corpus omits, and the
   hardest case — no service names, no request ids. If a blueprint helps there it
   carries real method, not a restatement of a log line. We have the measured
   proof: on one fault family the kernel confirmed 8/8 where metrics could
   confirm only 4/8.
8. **"How do you know the agent isn't cheating?"** Ground truth is unreachable
   by construction, the sandbox never receives a run path, names are masked,
   skills are leak-scanned, nothing carries between runs, and every transcript
   is audited. Checked with 19 adversarial escape attempts.
9. **"Which ten issue classes?"** Show the fault-family list (CPU cap,
   co-tenant, memory, disk, network, DNS, locks, deadlock, pools, outage, code
   defects…). Latency is the entry point. And be honest: **11 of the uncovered
   families are not buildable from kernel traces alone, and we measured that.**
10. **"Monolithic systems — where is the data?"** Honest answer: not collected
    yet. Micro-benchmarks and a held-out app are the plan, and the agentic leg
    already has 130 runs per agent.
11. **"What runs automatically today?"** Honest answer: the blueprints and the
    rule engine run; **selection is manual.** The knowledge objects are built and
    proven; the runtime that routes between them is the next phase.

---

## 16. Directory map — where everything is

Paths relative to the repo root `C:\workplace\microservice-trace-dataset`.

### Read in this order to understand the project

| # | Path | What |
|---|---|---|
| 1 | `CLAUDE.md` | the map: current state, hard-won technical facts, where things live |
| 2 | `blueprints/README.md` | **what a blueprint is** — the single best doc. Read it |
| 2b | `blueprint-idea.md` | **where the idea came from** — the 26 Aug 2026 meeting, verbatim. The best source for the introduction slides (§2b) |
| 3 | `blueprints/docs/blueprint-report.md` | plain-English account of **every design decision**. The one to read before presenting |
| 4 | `blueprints/docs/DATASET-v2-INVENTORY.md` | what the dataset actually contains, with caveats |
| 5 | `thesis/PROPOSAL.md` | problem, RQs, preliminary results, phases |
| 6 | `READING-ORDER.md` | which of the ~120 markdown files are current, and which to skip |
| 7 | `CAMPAIGN-ISSUES.md` | live list of data problems. **Read before trusting any run** |

### Thesis and presentation

| Path | What |
|---|---|
| `thesis/abstract.tex` | **canonical abstract + title** |
| `thesis/ABSTRACT.md` | mirrors the `.tex` and records *why* each sentence is worded that way, plus a 178-word variant and a table showing how the declarative tense stays honest |
| `thesis/abstract-merged.txt` | the submitted abstract (four paragraphs) |
| `thesis/PROPOSAL.md` | §5 = preliminary results, §6 = phases, Appendix A = evidence index |
| `thesis/msc-thesis-abstract-presentation/presentation-plan.md` | the 17-slide plan with timings and a 15-minute cut list |
| `thesis/msc-thesis-abstract-presentation/CONTEXT.md` | this file |

### The blueprint idea and the two generations

| Path | What |
|---|---|
| `blueprint-idea.md` | the 2026-08-26 meeting, in detail: the origin story, the six-step validation loop pre-registered, Mahsa's "put the exact code in the skill" finding, the eight RQs, and the honest note about the deterministic-brief control |
| **`blueprints/`** (lowercase) | **previous generation.** All published results come from here. Kept as reference |
| **`Blueprint/`** (capital) | **the active workspace** (since 16 Oct 2026). Self-contained — nothing inside depends on files outside it, so it can graduate to its own repo |

> Both directories exist side by side. Case-insensitive tooling can confuse
> them. `blueprints/README.md` is the concept doc; `Blueprint/README.md` is the
> active-workspace map.

### `blueprints/` — previous generation (where the numbers come from)

| Path | What |
|---|---|
| `blueprints/schema/blueprint.schema.json` | **the format**, field by field, with the descriptions that enforce the discipline |
| `blueprints/thresholds.json` | 33 measured thresholds, single source of truth, each with a `transfers` verdict |
| `blueprints/providers.json` | **the capability registry** — 22 capabilities → tools, plus the escalation policy |
| `blueprints/symptoms.json` | the symptom vocabulary |
| `blueprints/problems/<id>/` | one folder per problem: `blueprint.json`, generated `skill.md`, `scripts/`, `evidence/`, `results/` |
| `blueprints/problems/RESULTS-v2-all-blueprints.md` | 136 runs, 7 blueprints. **3 false fires in 826 opportunities**; the 8/8-vs-4/8 modality result |
| `blueprints/problems/RESULTS-v2-rederived.md` | same 136 runs, engine changed: recall **50% → 76%** |
| `blueprints/problems/RESULTS-v2-uncovered-faults.md` | all 303 runs, 27 families, 45 signals. **Retracts** the 16/16 claim; finds `fork_storm` and `data_exfiltration` clean |
| `blueprints/problems/RESULTS-v2-threshold-free.md` | **negative result**: removing thresholds is 12× worse on false fires |
| `blueprints/problems/RESULTS-v2-blueprint1-cpu.md` | why `CONTENDED = 0.55` inverts on the second app |
| `blueprints/lib/` | ~100 scripts: the generator (`blueprint_to_skill.py`), the rule engine (`blueprint_decide.py`), measurement scripts (`measure_signature.py`, `net_loss_signature.py`, …), the harness (`q2_*.py`), the scorer (`q2_judge.py`), and the SLURM job files |
| `blueprints/skills-kernel-only/` | the 16 generated kernel-only skills — **what the agent actually reads** |
| `blueprints/skills-generated/` | the 11 four-modality skills |
| `blueprints/results/` | `withwithout.json` (the raw with/without rows), `ruler.json`, `verification_index.json`, `q2/` |
| `blueprints/REFERENCE-PACK-FOR-KERNEL-TRACE.md` | kernel-trace reference pack |

### `blueprints/docs/` — the results and design library

| Path | What |
|---|---|
| `blueprint-report.md` | every design decision + the v1→v5 revision history + the measured two-problem contrast |
| `SCORING-EXPLAINED.md` | **how every score is computed**, with a worked 60-cell example. The methodology doc |
| `RESULTS-withwithout.md` | the 57-incident tie and the failure analysis that reframed the thesis |
| `RESULTSv2.md` | the rule engine: 38/41 when it fires, 64/81 overall |
| `RESULTS-comparison.md` | **blueprint vs 5 alternatives**, 12 incidents, same scorer. The two negative controls |
| `RESULTS-blueprint-cards.md` | **"one number alone vs the whole rule"** — the best single table |
| `RESULTS-antipattern-ceiling.md` | anti-pattern vs real problem (29% → 12%) + the `lttng-consumerd` observer effect |
| `RESULTS-verification-filter.md` | scoring only against runs whose fault took: recall **73% → 90%** |
| `WHEN-A-BLUEPRINT-HURTS.md` | **the portability finding**. 600 runs. Underused |
| `SOCK-SHOP-RESULTS-22-09-2026.md` | the 6-problem matrix, 360 runs. **Trust this one** |
| `TRAIN-TICKET-RESULTS-22-09-2026.md` | same for Train Ticket. **Tables only — the prose is stale** |
| `Q2-FULL-6-problems.md`, `Q2-PILOT-noisy_neighbor.md`, `Q2-RERUN-with-process-tools.md` | the earlier matrices and the method corrections that came out of them |
| `AGENT-DESIGN.md` | the **selection** design + the symptom-word confound. **A plan, not results** |
| `EVAL-PLAN-effectiveness.md` | the A/B/C/D setups and pre-registered win conditions. **A plan** |
| `FINDINGS-phase1.md` | 65 KB running log, **newest first**, F1–F23. The measurement spine |
| `RESEARCH-PLAN-phase1-kernel.md` | the protocol `FINDINGS-phase1.md` logs against, and the "no negative class" admission |
| `COVERAGE-which-blueprints-are-missing.md` | **we cannot write 13 more blueprints — the data does not support them** |
| `LATENCY-CAUSES.md` | 11 causes of latency over our own runs, and which kernel traces can see |
| `BLUEPRINT-BACKLOG.md` | which anomalies to write next, ordered by measurement |
| `FAULT-CATEGORIES-V2.md` | how the fault set went from 5 issue types to ~10 |
| `CODE-BUGS-V2.md` | injecting real code defects, not just infrastructure faults |
| `AUDIT-v2-full.md`, `RECOLLECT-list.md` | every run checked; what needs re-collecting vs re-scoring |
| `COLLECTION-V2-SPEC.md`, `COLLECTION-PLAN.md` | the one-shot collection spec. Its rule: *we do not get a second run* |
| **`charts-ss/`, `charts-tt/`** | **reusable figures**: `1-blueprint-effect.png`, `2-every-run.png`, `3-window-raw.png`, `4-room-to-improve.png`, `5-cost-raw.png` — one set per app |
| **`presentations/presentation1/`** | **the old deck**: `slides.html`, `ciena-slides.html`, `ciena-slides-notes.md`. The notes are the best plain-English explanation of a blueprint in the repo |

### `Blueprint/` — the active workspace

| Path | What |
|---|---|
| `Blueprint/README.md` | workspace map and direction. **Two stale claims**: the "40/40" eval figure and the `latency/2–4_*` label |
| `Blueprint/000-what-is-telemetry/` … `005-how-to-use-lttng/` | **six short teaching notes**: telemetry, tracing, what to trace, application traces, system traces, LTTng. **Use these for the background slides** |
| `Blueprint/latency/1_svc_cpu_cap/README_v1.md` | the **template** blueprint (CPU cap). Parts 1–6 + two appendices |
| `Blueprint/latency/1_svc_cpu_cap/EVALUATION-on-agentic-runs.md` | the kernel-portability case study (§9.9). **Not a scored evaluation** |
| `../../agentic-runs/1_svc_cpu_cap/agentic-os-noise/` | the OS-noise study: collection, analysis, runs, `RESULTS.md` |
| `Blueprint/latency/2_noisy_neighbor/`, `3_slow_db/`, `4_svc_mem_cap/`, `5_svc_net/` | the other four blueprints, same shape. Each has `README_v1.md` + `tools/` |
| `Blueprint/latency/OS-NOISE-FOR-AGENTIC-AI.md` | **the four-problem agentic catalogue** — the doc to show Naser |
| `Blueprint/agent/` | the generation-2 agent: `agent_v2.py`, `utils.py`, `ctf_tool.py`, `codetool.py`, `leakguard.py`, `blueprints.py`, `skillreg.py`, `config.py`. `AGENT-V2-ARCHITECTURE.md` explains the loop and the documented scratchpad failure |
| `Blueprint/agent/bp_work/` | per-run scratch for `blueprint_tool` — the trace slices the blueprint's own scripts cut |
| `Blueprint/agent/ctf-index/` | the local count index: `<run>.tsv.gz` (counts) + `<run>.lines.gz` (line sample) |
| `Blueprint/agent/transcripts/v2/` | **full-fidelity audit logs** — every prompt, raw response and tool result, paired `.json` + `.console.log` per run. `bponly*` marks blueprint-only runs |
| `Blueprint/research-paper/` | the OS-noise paper: `paper.tex`, `figures/`, `make_data.py` / `make_figures.py` (every cell recomputed from run data), `E2E-RESULT.md`, `LLM-SHARE-RESULT.md`, `CONSISTENCY-RESULT.md` |

> `paper.tex` currently embeds **only `fig_method`**, although
> `figures/` holds `fig_cpu`, `fig_threads`, `fig_memory`, `fig_io`,
> `fig_llmshare`, `fig_consistency` too. The README's claim that the four
> problem figures are embedded is stale. All of them are available as `.png`
> for slides.

### The agent harness (generation 1) and the agentic runs

| Path | What |
|---|---|
| `agentic-rca/` | the full generation-1 harness: `agent.py`, `agent_v2.py`, `ctf_tool.py`, `codetool.py`, `leakguard.py`, `degrade.py`, `evaluate.py`, `run_digest.py`, `inspect_run.py`, `audit_leakage.py`, plus 13 `RESULTS-*.md` |
| `agentic-rca/AGENT-V2-ARCHITECTURE.md` | the agent architecture |
| `agentic-rca/RESULTS-nonllm-baselines.md`, `RESULTS-stat-baseline.md` | the non-LLM baselines |
| `agentic-runs/2_threads_vs_cores/` | OS-noise problem 2: `PLAN.md`, `runs/` (Part A, 20 runs), `runs_partB/` (6 sub-agent runs), `analysis/`, `RESULTS.md` |
| `agentic-runs/3_memory_cap/`, `4_io_cap/` | problems 3 and 4, same shape |
| `agentic-runs/provenance/` | everything swept off the VM before any future deletion: `vm_env.txt`, all 9 campaign logs, all 6 run manifests. VM run counts verified equal to local. *"Nothing research-relevant left only on the VM now"* — the explicit lesson from the v1 data loss |
| `agentic-runs/provenance/collection_as_run/` | **the collection scripts exactly as they ran on the VM**, CRLF-stripped — preserved as a run artifact, not as source. Its README lists six "do not rediscover" gotchas, including the best bug in the set: `echo $BASHPID \| tee` wrote the *pipe-subshell* pid, so the agent never entered the cgroup — caught only because the `cpu.stat` delta was zero |

> **OS-noise problem #1 is NOT in `agentic-runs/`.** It lives at
> `../../agentic-runs/1_svc_cpu_cap/agentic-os-noise/`. The `Blueprint/latency/`
> numbering was later reused for *blueprints*, so problems #2–#4 were moved out
> to `agentic-runs/`. Some docs still carry stale `del-this/` links to the old
> location.
| `results-download/deadlock/DIGEST.md`, `results-download/conn_pool_exhaustion/DIGEST.md` | **the 30/30 and 27/30 matrices.** These are not in `blueprints/docs/` — easy to miss |

### Dataset, collection and research plans

| Path | What |
|---|---|
| `fault_catalog.md` | **pre-registered** per-fault modality predictions. Cannot be edited in place — changes go through its §7 amendment log |
| `understanding-dataset.md` | first-time guide, walked through one fault family |
| `DATASET_GUIDE.md` | longer from-scratch guide |
| `temp.md` | the **per-family run-count table** (SS vs TT). Uncommitted — move it somewhere stable |
| `microservice-lttng-data-collection-scripts/` | all collection tooling: `collect_trace.sh`, the 7 compose overlays, `faults/`, `audit_alignment.py`, `load_generator.py`, `vm_bootstrap.sh`, `run_gate.sh`, `TROUBLESHOOTING.md` |
| `train-ticket-collection-scripts/` | the Train Ticket port, `PORT-PLAN.md` |
| `transfer/` | staging/derivation/transfer scripts, `pull_from_vm.sh`, `env.sh`, `README.md` |
| `msr-research.md` | **v2 framing** — the per-task modality-ablation study. The MSR paper still targets this |
| `research-agentic-rca.md` | **v3 framing** — agentic RCA under telemetry degradation. Supersedes `msr-research.md`'s framing |
| `non-llm-baseline.md` | the non-LLM baseline we compare against (RCAEval + multi-source BARO) |
| `paper/` | the FSE 2027 draft: `fse-draft.md`, `main.tex`, `sections/` |
| `CLUSTER-LAYOUT.md` | where everything lives on Trillium. Read before cluster jobs |
| `future.md` | parked work, each entry says why it waits |
| `progress-notes/` | **the live decision log**, one folder per day, day-first dates. Records *why*, not *what*. Read the latest day first |
| `progress-notes/next-steps.md` | last updated 17 Sept — the October state is in the dated folders (`12-10`, `13-10`, `15-10`, `17-10`) |

### Skip these

`archive/` (the LMAT/JSS stack, archived 2026-08-08), `DOCS/` (JSS-era, paths
point at an old workspace), `stratatrace-v1/` (byte-identical duplicates of the
root `DATASET_GUIDE.md` and `fault_catalog.md`), `todolist.md`, `new_design.md`,
`archive/progress-snapshots/`.

### The framing lineage (so you do not mix generations)

```
msr-research.md            v2  modality ablation (MSR 2027 dataset paper)
       │
       ▼
research-agentic-rca.md    v3  agentic RCA under telemetry degradation
       │
       ▼
blueprint-idea.md          v4  the blueprint (2026-08-26 meeting)
       │
       ▼
thesis/PROPOSAL.md             agentic software observability  <-- the thesis
```

---

## 17. Open items and cautions for whoever builds the deck

**Before building:**

1. Confirm the exact **date**, the **audience** (committee or department
   seminar?), whether the 20 minutes **includes Q&A**, and the **slide format**
   (PowerPoint / HTML / LaTeX Beamer).
2. Pick **one title** and use it everywhere — `abstract.tex` is canonical.

**Content cautions:**

- The slide plan was written **14 Oct**. It does not include §9.8 (the
  agent-feedback loop, 17 Oct), §9.9 (kernel portability), §9.4's two negative
  controls, or §10.2 (the "we cannot write 13 more" scope honesty). All are
  strong. Consider folding §9.8 into the evidence act and §10.2 into the scope
  slide.
- Be explicit on any slide about **which generation** a number comes from:
  `blueprints/` (previous, all published numbers) or `Blueprint/` (active, the
  October matrices).
- `AGENT-DESIGN.md` and `EVAL-PLAN-effectiveness.md` are **plans, not results**.
  They say so at the top. Do not present their tables as measurements.
- `temp.md` is uncommitted. If you cite the per-family table, move it somewhere
  stable first.
- **There are two scorers with two vocabularies, and mixing them will produce a
  slide nobody can source.** `agentic-rca/runs.py` scores
  `service_hit` / `fault_hit` / `both` (the Top-1 campaign scorer).
  `blueprints/lib/q2_judge.py` + `q2_run_one.py` score WHERE (six-way) / WHEN
  (IoU + onset + gated earliness) / WHAT (concept coverage) / HOW (trajectory).
  **Every recent number comes from the second.** The first was replaced because
  it was *"marking vocabulary, not analysis"* — an agent that said "a foreign
  process is eating CPU while the services keep working" understood the incident
  perfectly and scored zero for not using the exact label.

**Docs that are stale — do not read these for current state:**

| Doc | What is wrong |
|---|---|
| `progress-notes/next-steps.md` | dated **17 September**. Still about Train Ticket collection. Read `progress-notes/16-10-2026/` and `17-10-2026/` for state |
| `CLAUDE.md` | still names `agentic-rca/` as "the primary track". That is one generation behind — `Blueprint/` is the active workspace |
| `Blueprint/README.md` | the "40/40, 0 false alarms" eval figure (not substantiated — §12) and the `latency/2–4_*` label (the dirs are 2 noisy_neighbor, 3 slow_db, 4 svc_mem_cap, 5 svc_net; and blueprint 1 ships ten scripts, not eight) |
| `agentic-rca/AGENT-V2-ARCHITECTURE.md` | says `MAX_WORKER_STEPS = 12`; the code says **18** |
| `Blueprint/latency/OS-NOISE-FOR-AGENTIC-AI.md` | `del-this/` links to the old problem #2–#4 locations |
| `presentation-plan.md` | the stale deadlock-JSON warning (resolved — §12) and "~24 families" (it is **27**) |

**Reusable assets:** `blueprints/docs/charts-ss/` and `charts-tt/` (5 figures
each), `blueprints/docs/presentations/presentation1/` (old deck + Ciena notes),
`Blueprint/research-paper/figures/` (7 figures as `.pdf` + `.png`, including
`fig_method`).

**What is genuinely open, if asked "what's next":**

1. **Unseen-data sweeps** on the held-out pools — 8 + 8 `svc_mem_cap` runs, and
   `slow_db` r2–r5 + burst + subtle + the 11 Train Ticket `no_metric_signature`
   runs where the kernel blueprint is the only evidence.
2. **Hierarchical selection** — the measured bottleneck, and the one known
   routing weakness (a fault spanning most of the trace, §9.8).
3. **Triage** — the agent has never been asked whether a trace is healthy.
4. **The output spec** — `explanation.txt` and `recommended_action.txt` are
   declared by blueprints and written by nothing. This was named as a gap in the
   original August meeting and is still the one unfilled item from that list.
5. **Two questions from the origin meeting still genuinely unanswered:** what
   counts as "similar but not identical" for a transfer test (the unseen-pool
   discipline gropes toward it without a pre-registered ladder), and how the
   autonomy gap should be scored.

**The three things the committee needs to hear, in this order:**

1. **This is not unstarted work.** The dataset, the agent, the blueprints, and
   the first experiments already exist. Every number traces to a file.
2. **The evaluation is honest.** A strong deterministic control, negative results
   kept, a tie reported as a tie, and our own plumbing bugs published alongside
   the results.
3. **The remaining work is targeted.** We measured the bottleneck — blueprint
   selection — and the proposed work attacks exactly that.
