# Observability Blueprints — what we built, and why

A plain-English account of every decision, for presenting the work.
Branch: `blueprints`. Written 2026-08-27.

---

## 1. The idea in one paragraph

Every time an engineer diagnoses a problem, they do the same three things: decide what data
to collect, decide what analysis to run, and produce an answer. Today all of that is thrown
away when the ticket closes. The knowledge stays in one person's head.

A **blueprint** writes that whole experience down in a form that can be **re-executed** —
by a person or by an agent. Blueprints accumulate into a library. When a similar problem
appears again, the library already has the prescription.

The thing we are selling is not the agent. It is that **trace analysis accumulates** instead
of starting from zero every time.

---

## 2. What a blueprint actually contains

Not just "what was wrong". A blueprint records the whole loop:

| Part | What it says |
|---|---|
| **When it applies** | the symptoms that make this blueprint the right one — and when *not* to use it |
| **What to collect** | the exact events needed. Not "kernel data" — actual tracepoint names |
| **What to run** | the analysis steps, each one a capability that resolves to a real command |
| **How to decide** | what makes the verdict true, and when to prefer a different explanation |
| **What to produce** | the JSON, the chart, the explanation, and the recommended action |
| **When to stop** | when to conclude, when to switch blueprints, what to say if the evidence is not enough |
| **What does NOT work** | signals we tested and found useless, so nobody wastes time on them again |

The key difference from our old agent "skills": those were prose. A blueprint carries
**runnable commands, exact event names, and an output specification.**

---

## 3. Why these two problems

We built two, and chose them to be **opposites**:

1. **CPU contention** — another workload on the same machine steals CPU. Services are not
   busy; they are waiting for a turn on the processor.
2. **Datastore wait** — a database answers slowly. It is not busy either; it is blocked
   waiting for something else.

Both look identical from the outside: things are slow, nothing is obviously broken. If our
method can tell these two apart, that is a real demonstration. If it cannot, the method is
not worth much.

They are marked `mutually_exclusive_with` each other — both can never be right for the same
incident.

---

## 4. Two rules we work under

**Rule 1 — measure first, then write.** Nothing goes into a blueprint until it has been
measured on our own data. Not one signal, not one threshold. Even when we are sure.

**Rule 2 — one folder per problem.** Because there will be hundreds of these:

```
blueprints/problems/<problem-name>/
├── blueprint.json     the knowledge
├── skill.md           GENERATED from it — never edited by hand
├── scripts/           the analysis code for this problem
├── evidence/          the measurements proving every claim
└── results/           per-run outputs
```

The skill is generated from the blueprint, so the two can never drift apart.

---

## 5. The story: how the blueprints changed five times

This is the most important part to present, because **the process caught our own mistakes**.

### v1 — written from knowledge (wrong)

The first draft was written from what we already believed, taken from the old skills. It
said things like *"during CPU contention, services show a raised runnable-wait share."*

That sounded obviously right. It was not checked.

### v2 — measurement contradicted it

We measured the wait data across **93 runs / 310 records**. Three claims died:

| We had written | What the data showed |
|---|---|
| "services show raised runnable-wait" | runnable-wait **never exceeds 4%** in *any* fault, and was **1.6%** on the CPU-contention run itself |
| "the culprit's wait breakdown identifies it" | for host-level faults there is **no culprit record at all** — 5 whole fault families |
| "the datastore shows dominant external I/O wait" | true — and **98–99% for every fault type**. It identifies nothing |

All three would have been on a slide.

The reason they failed: the derived data reports **shares of time**, and idle waiting swamps
everything. Every service is mostly idle, so every service looks the same.

Retracted claims were **kept**, not deleted — with the measurement that killed them — and
they now appear in the skill so the agent is warned off them too.

### v3 — switched to the raw trace, and the signal appeared

Instead of the derived summaries, we read the **original LTTng trace** with Babeltrace2.

This changed everything, because the raw trace gives **per-event latencies** rather than
shares:

| | Derived summary | Raw trace |
|---|---|---|
| CPU contention | runnable share **1.6%** — invisible | runqueue delay **7.12×** — obvious |
| Datastore | external-wait share 99.4% — same as everything | one syscall **36.8×** — unmistakable |

It is also the easier story to tell: *the agent reads the real kernel trace, not a
simplified copy of it.*

### v4 — the blueprint must not name tools

Reading Naser's architecture notes changed the structure. His rule: **a blueprint never
names a tool.** It states a requirement; the system picks the tool at run time.

Our v3 hard-coded `babeltrace2` and script paths. That made it a script wrapper, not
portable knowledge — and a customer with their own tools could not use it.

So now:

```
needs: kernel.scheduler.runqueue_delay          ← the blueprint (portable)
        ↓ providers.json decides
run [babeltrace2-cli]: python3 .../runqueue_delay.py ...   ← this environment only
```

This also **resolved a conflict between our two supervisors**:

- Mahsa: the exact function must reach the model or accuracy drops.
- Naser: the blueprint must not name tools.

Both are satisfied: the blueprint stays abstract, and binding produces the exact command
*before* the agent sees it.

We also added, from the same document: problem taxonomy (a blueprint covers a *class* of
problems, not one incident), applicability conditions, stopping conditions, and adaptation
rules for when evidence does not fit.

### v5 — policies, cost, and choosing between tools

The full version of Naser's notes had much more. Added:

- **Overhead budget and approval rules.** Collection is not free. Cheap analysis is
  automatic; expensive tracing needs approval.
- **Cheapest-first escalation.** Use data you already have, then cheap collection, and only
  then expensive tracing. Never start at the top.
- **Provider cost metadata**, so the system can *choose*: eBPF at 2% overhead first,
  escalate to full tracing at 4% only if the cheap answer is not enough.
- **Selection metadata** — the goals, symptoms and environments a blueprint fits, so a
  selector can rank candidates.
- **A confidence floor.** Below 0.7, do not report a diagnosis: name the missing evidence
  and ask for one specific thing.
- **A recommended action**, not just a diagnosis.

---

## 6. What we actually measured

All from the raw kernel trace, on two labelled runs. Each fault is the other's control.

| Signal | CPU contention | Datastore wait |
|---|---|---|
| **Runqueue delay** (busiest service, p95) | **7.12×** (48,886 samples) | 0.97× |
| Runqueue delay, median across processes | **1.78×** | **0.84×** |
| Runqueue delay of the database | — | 1.09× |
| **Database `poll` wait** (p95) | **1.12×** (45,337 samples) | **36.83×** (17,245 samples) |
| Largest inflation of any syscall | 3.95× | 36.83× |
| **Trace convergence** | **none** (1.7×) | **717.7×** |

Read the two middle rows together. **The same measurement, on the same component, gives
1.12× in one case and 36.8× in the other.** That is what makes the two blueprints genuinely
separable rather than just differently worded.

### Supporting evidence for CPU contention

- The guilty container used **2.00 CPU cores** during the incident against **0.00** before.
- It has **no place in the call graph** — nothing calls it, it calls nothing.
- Host CPU went 5.31 → 7.96 cores (×1.5): busier, but **not exhausted**. That is contention,
  not saturation.

### The scripts route themselves

Running the datastore verdict script on both runs, unchanged:

**On the datastore fault → YES**
> mysqld blocked in poll for 36.83× its baseline. Runqueue delay stayed flat (max 1.59×), so
> it is not short of CPU. Slow call edges converge on catalogue.
> **NOTE: traces name catalogue but the kernel shows mysqld is the one blocked — catalogue is
> a victim, and mysqld emits no spans.**

**On the CPU fault → NO, plus a redirect**
> No socket-waiting syscall inflated by 5× or more (largest was 3.95×). Runqueue delay
> inflated up to 7.12× — the processes are short of CPU. **Use the CPU-contention blueprint.**

That last line is worth showing. The blueprint **refuses to answer and points at the right
one instead** of forcing a verdict.

---

## 7. A bonus finding

The datastore verdict discovered our blind-spot argument by itself:

> "traces name catalogue but the kernel shows mysqld is the one blocked"

The fault was injected on the database. The call graph blames the *service in front of it*,
because the database emits no request traces. Traces get you one hop away from the truth;
only the kernel closes the gap.

We did not write that in. The tool reported it. It is recorded in the blueprint as a known
limitation rather than hidden.

---

## 8. How the pieces fit

```
Historical problems  →  problem taxonomy  →  BLUEPRINT (portable knowledge)
                                                  │
                                    declares capabilities, not tools
                                                  │
                                            providers.json
                                       (binds to whatever exists here)
                                                  │
                                          exact commands
                                                  │
                                    agent / engineer executes
                                                  │
                                     evidence → analysis → verdict
                                                  │
                                    enough?  →  diagnosis + action
                                    not enough?  →  ask for ONE more thing
```

The blueprint is the durable part. Tools underneath can be swapped without touching it.

---

## 9. What is built, and what is not

**Built and working:**
- The blueprint format, with a validator that enforces the rules
- Two blueprints, fully measured, with all evidence stored
- Five analysis scripts reading the raw kernel trace
- The generator that turns a blueprint into an agent-facing skill
- The measurement tools that must run *before* any claim is written
- A capability→tool registry with cost metadata

**Not built — be clear about this:**
- **The runtime.** Naser's architecture has an intent normaliser, a blueprint selector, a
  policy engine, a binder, an execution planner and an adaptive planner. Our blueprints
  *declare* everything that runtime would need, but nothing consumes it yet. Selection is
  manual today, which the meeting explicitly accepted for now.
- The with/without-blueprint experiment (the headline number Naser wants).
- Mining blueprints automatically from past tickets.

Honest framing for tomorrow: **the knowledge objects are built and proven. The machine that
runs them automatically is the next phase.**

---

## 10. What we are not claiming

- **One run per fault.** The differences are huge (7× vs 1×, 37× vs 1.1×), but repeats
  across intensities and the second application are still owed.
- **Two problems, not five.** Naser asked for about five eventually.
- **Process-name attribution** works on this application but is ambiguous on the Java-heavy
  one, where every service is called `java`.
- The confidence floor of 0.7 is a **policy choice**, not a measured threshold.

---

## 11. Likely questions, and honest answers

**"Is this just a runbook?"**
No. A runbook is prose for a human. A blueprint carries exact event names, runnable steps,
an output specification, machine-checkable stopping conditions, and a record of what does
*not* work. It is written to be executed without a human.

**"Why not just let the AI figure it out?"**
Two reasons. Without written-down knowledge the agent reinvents the procedure every time —
Naser's own experience with AI tools. And we measured that a good deterministic evidence
summary already matches a tool-using agent, so structure is what helps, not more autonomy.

**"How do you know your signals are real?"**
Every claim cites a measurement file, and the validator rejects a claim without one. We can
show three claims from our own first draft that the measurement killed.

**"What if we use different tools?"**
The blueprint names capabilities, never tools. Point the registry at your collector and the
blueprint is unchanged. Trace Compass is already listed as an unbound alternative.

**"How much overhead does this add?"**
Each provider declares its estimated overhead and the blueprint carries a budget. The rule
is cheapest-first: existing data, then light collection, then deep tracing only if needed.

**"How is this different from published RCA work?"**
Published work reports accuracy for one pipeline. Here the deliverable is a **reusable
artifact**, and the measurement is whether it works again on the *next* problem. The
blueprint also feeds back into what gets collected, which RCA papers do not do.

---

## 12. The one-sentence version

> We turn a solved investigation into a portable, executable document that says what to
> collect, what to run, how to decide and when to stop — proven against our own labelled
> data, and written so the tools underneath can be replaced without rewriting the knowledge.
