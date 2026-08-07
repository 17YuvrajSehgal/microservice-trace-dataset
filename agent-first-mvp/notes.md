# Speaker notes — Ciena presentation

How to use this: each slide has **the one message**, a **"Say this"** script (short, plain
words — paraphrase, don't read), what to **point to**, and likely **questions**. Whole deck
is ~6–8 minutes; leave room for questions. There's a 60-second version and a glossary at the
end.

**The single idea to land:** *Instead of recording everything and hoping the answer is in
there, you tell it the problem in plain English — it decides exactly what to record, records
only that, and reads it deeply to find the true cause. Less data, precise answer, and you can
trust it.*

---

## Before slide 1 — 15-second opener
> "I'll show you a different way to do root-cause analysis. Today's monitoring tools collect
> as much as they can and then let you search it. We flip that around: you describe the
> problem in plain language, and the system decides *what* to collect — and then goes much
> deeper than a normal dashboard, at a fraction of the data. Four slides."

---

## Slide 1 — The idea

**One message:** The agent decides *what to collect* from the problem itself — then goes
kernel-deep on only that.

**Say this:**
> "Deep observability has a scale problem. If you want to debug all the way down to the
> operating system, you'd have to record terabytes constantly, everywhere — nobody can afford
> that. So today's tools only show you what happened to be collected, and the deep detail
> usually isn't there when you need it.
>
> We change the order. You say the problem in plain English — *'my database is slow'* — and
> the system turns that into a **scoped collection plan**: exactly what to capture, on which
> services, for a short window. It captures only that, then goes kernel-deep on it. You get a
> precise root cause, **up to 32× less data**, and an answer you can trust — because it's
> rule-based, not the AI guessing."

**Point to:** the left-to-right flow (Problem → Skill → Collection spec → Kernel-deep →
Verdict) and the three chips at the bottom (kernel-deep · 32× less data · deterministic).

**If asked:**
- *"What does kernel-deep mean?"* → The operating-system level — where you can see exactly
  what each process was waiting on (CPU, disk, or network). Normal tools stop at "the service
  is slow"; we can say *why*.
- *"Why less data?"* → Because we only capture what this specific problem needs, briefly, on
  the relevant services — not everything, always, everywhere.

---

## Slide 2 — How it works (the architecture)

**One message:** A plain-English problem runs a two-step loop — **first decide what to
collect, then collect and analyze** — and the library of problem-types keeps growing.

**Say this — walk the top strip left to right:**
> "End to end: the problem comes in. An AI agent picks the right **skill** — think of a skill
> as a diagnostic playbook for one class of problem. It reaches our tools through **MCP**, a
> standard connector for AI agents. **Phase 1**: the skill writes the **collection spec** —
> the exact list of what to capture. *That's* the new part: the system decides what to
> collect, instead of 'collect everything into a zip.'"

**Then the dashed cloud:**
> "And it's built to grow. The skills are a **library** — five are built today; we can add
> more — adaptive tracing, memory leaks, and so on — **without touching the engine or the
> data**. Your own existing diagnostic pipelines could become skills here too."

**Then Phase 2 — walk the five boxes:**
> "Phase 2 is the actual investigation.
> ① **Collect** only what the spec asked for — mostly kernel here, plus traces, logs,
> metrics.
> ② The key step — **split each thread's time** at the OS level: was it *computing*, *waiting
> on disk*, or *waiting on the network*? For the slow database, the service spent **99% of
> its time waiting on the network** — almost nothing on CPU or disk — and the database itself
> was idle and healthy. So the database isn't the problem; the **connection to it** is.
> ③ **Cross-check** — the traces, metrics, and logs all agree.
> ④ **Rule out** — not CPU, not disk — which lands us on the connection path.
> ⑤ **Verdict**, with a confidence score and a recommended fix."

**Punchline (green bar at the bottom):**
> "Every step is scored by rules over the evidence. The AI writes the explanation in English,
> but it never invents the cause — that's what makes the answer trustworthy."

**Point to:** box ② (the purple "99% off-CPU" bar) — that's the whole insight in one picture.

**If asked:**
- *"Is this on recorded data or live?"* → Both. It runs on stored traces, or it can capture
  live on a running system.
- *"What if the skill picks wrong?"* → It rules causes out from evidence and reports a
  confidence; if the evidence is thin, confidence drops rather than bluffing.
- *"Which AI model?"* → The agent uses Claude, but the *verdict* is deterministic rules — the
  model is swappable and never the source of truth.

---

## Slide 3 — Results (the proof)

**One message:** Tested blind on four very different faults — all four correct, and a
*different* type of data was decisive each time. That's proof it genuinely picks the right
thing to look at.

**Say this:**
> "We didn't just design it — we tested it, blind, on four real faults, with the answer hidden
> from the system. It got **all four right**. And here's what matters: a **different type of
> data** cracked each case.
> - *'Database is slow'* → kernel + traces.
> - *'Everything's a bit slow'* → **kernel only** — a noisy neighbor was stealing CPU, and the
>   normal dashboards showed nothing wrong; only the OS-level view named it.
> - *'Orders failing'* → traces — a service was frozen.
> - *'500 errors'* → logs.
>
> Same system, four problems, four different answers — all correct, at up to **32× less
> data**. That's the evidence it really decides what to look at, per problem."

**Point to:** the second card ("everything's a bit slow" — *invisible to metrics/traces*) —
it's the most convincing one for a scale-conscious audience.

**If asked:**
- *"How do you know they're correct?"* → We injected known faults, hid the ground truth from
  the system, ran it, then compared — 4 out of 4.
- *"Why is 'less data' different per case?"* → Logs-and-metrics problems need little; the
  kernel-deep ones save the most (up to 32×) because kernel data is the expensive kind.

---

## Slide 4 — What it means (findings + the wedge)

**One message:** Four takeaways, and why this is open space no one else occupies.

**Say this:**
> "Four takeaways.
> One — **a different data type wins each time**, so a fixed pipeline can't cover every case;
> you have to *choose*, and that's what this does.
> Two — **kernel depth is necessary**: in the noisy-neighbor case the service dashboards
> looked completely normal; only the OS-level view found the culprit.
> Three — it **works live**, on a running system, not just on stored data.
> Four — **no hallucinated answers**: it's rule-scored evidence; the AI only narrates.
>
> And the bottom line — the wedge: **no existing tool decides what to collect from the
> problem statement.** Not Datadog, not Dynatrace, and not the research systems — and none of
> them go kernel-deep. That's the gap we're building in."

**The ask / close:**
> "For Ciena this is **precise root cause at a fraction of the data and cost**, driven by
> plain language, and **extensible to your own problem types**. We'd love to look at your
> hardest recurring issues and see which ones could become skills."

---

## Likely Ciena questions (keep answers short + honest)

- **"Does kernel tracing add overhead / is it safe in production?"** → We capture a *curated*
  set of kernel events for a *short, scoped window* — not everything, always. That's the
  point of the collection spec; it keeps overhead and data volume low. LTTng is a mature,
  production-grade tracer.
- **"Can it run on-prem / our stack?"** → Yes — it's plain tooling (LTTng + Babeltrace2 +
  standard signals). Nothing is tied to a cloud; the dataset here is our test bench (Sock
  Shop), your services would be the target.
- **"How hard is a new skill?"** → A skill is a small package: the requirements (what to
  collect, as JSON), the workflow, and the output format. Adding one doesn't touch the engine.
- **"Does it depend on a specific LLM?"** → The agent uses Claude to drive the loop and write
  the narrative, but the verdict is deterministic rules — the model is swappable.
- **"How does this relate to what we already do (e.g. Sherlock)?"** → Your existing pipelines
  can plug in as analysis steps / skills, rather than being replaced.
- **"Is this real or a mock-up?"** → Real and running — the results on slide 3 are from actual
  runs against injected faults, verified against hidden ground truth.

---

## If you only have 60 seconds
> "Monitoring today means recording everything and hoping the answer's in there — which is too
> expensive to do deeply. We flip it: describe the problem in plain English, the system
> decides exactly what to record, records only that, and reads it at the operating-system
> level to find the true cause. We tested it on four different faults — all correct, a
> different data type decisive each time, up to 32× less data — and the answer is rule-based,
> so you can trust it. No existing tool decides what to collect from the problem, and none go
> this deep."

---

## Plain-word glossary (swap these in if the room isn't deeply technical)

| Term on the slide | Say instead |
|---|---|
| kernel / kernel-deep | the operating-system level — what each process was actually waiting on |
| wait-attribution / "split each thread's time" | check whether it was *computing*, *waiting on disk*, or *waiting on the network* |
| modality | a *type* of data — dashboards (metrics), text (logs), request timelines (traces), OS detail (kernel) |
| decisive modality | which type of data actually cracked the case |
| skill | a diagnostic playbook for one kind of problem |
| collection spec | the shopping list of exactly what to capture |
| MCP | a standard "plug" that lets the AI agent use our tools |
| deterministic verdict | the answer comes from rules over hard evidence, not the AI guessing |
| span / trace | the timeline of one request as it moves across services |
| p95 latency | how slow the *slowest 5%* of requests are — a standard health number |
| blast radius | how many services a fault actually affects |
| off-CPU / I/O wait | the process isn't working — it's parked, waiting for something (usually the network or disk) |

---

*Deck: `ciena-pitch.html` (this folder). One-pager for the professor: `experiment.md`.
Fuller architecture: `../DOCS/agent-first-architecture.md`.*
