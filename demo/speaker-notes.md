# Speaker notes — the StrataTrace demo

Five tabs, roughly 20 minutes. Everything in **quotes** is something you can say close to
verbatim; everything else is background so you can answer questions.

**Before you start**, run the app and leave it on the **Host CPU saturation** trace:

```
python demo/app.py          # http://127.0.0.1:8765
```

One framing sentence before you touch anything:

> "We collected labelled faults from two microservice applications with four kinds of telemetry
> running at once. Then we take telemetry *away* and measure what an automated agent can still
> work out. Today you're seeing the hardest subset — kernel traces only. No metrics, no logs,
> no distributed traces."

---

## 1 · TRACE — what the data actually is

### What to say

> "This is one recording. Four minutes of a live microservice application, and every single
> thing the kernel did during it."

Read the four numbers off the screen rather than memorising them — they differ per trace
(CPU: 3.0M rows, 440 event types, 22 containers; network: 4.1M rows, 373 event types, 21).

Point at the line **"The raw trace for this run is 15 GB."**

> "The raw trace is fifteen gigabytes for four minutes. You cannot hand that to a language
> model, and you cannot grep it either — the decoder can't seek, so reading one second from the
> middle costs the same as reading the whole file."

Then the key idea:

> "So we do one full pass, once, and build an **index**: for every 100-millisecond bucket, for
> every combination of event type, process and container, how many times it happened and — where
> it means something — how much. That's 37 megabytes instead of 15 gigabytes, and it's what the
> agent's tools actually read."

### Show the event chart

Pick `sched_switch` from the dropdown, then try one or two others.

> "Pick any event and you see its rate across the whole recording. You can already see something
> happen here" — *(on the CPU trace the collapse and recovery are visible)* — "and I want to be
> clear: the agent is not told any of this. Not that an incident happened, not when, not where."

### Show the container table

> "Every kernel event carries the namespaces of the task that produced it. One of those,
> `pid_ns`, is one number per container. That matters more than it sounds, because the kernel
> records no service names at all. This host runs several Java services and the kernel calls
> every one of them `java`. The namespace is the only thing that tells them apart."

### Background — if they ask

**Why 100 ms buckets?** Fine enough to locate a fault to within a fraction of a second, coarse
enough that the index stays small. It does mean sub-100 ms effects — like the delay between a
thread becoming ready and actually running — can't be recovered from the index; those need the
raw lines.

**What's in the index, exactly?** Six columns: bucket, event, process name, container, count,
and a summed value. The last one exists because **a count is not a quantity.** For CPU we sum
`sched_stat_runtime`'s nanoseconds; for network, bytes; for disk, sectors. Counting how often
the scheduler accounted for a container is not the same as how much CPU it got — a throttled
container gets accounted just as often while receiving far less.

**Does the index hide anything?** Yes, and we say so. It holds counts, not individual events.
The agent has a separate tool for raw event lines, which carry every field — TCP sequence
numbers, scheduling priorities, disk sectors. That's slower, and it's a deliberate choice the
agent makes.

**Is the index tuned per fault?** No. It's built before anyone asks a question of it, and
identically for every run. It contains no notion of a baseline, an incident window, a fault,
or a culprit.

---

## 2 · DISCRIMINATOR — the deciding check, run live

This is the tab to spend time on. It is the only place the audience can *watch* the method work
instead of being told about it.

### What to say

> "A blueprint is our word for a diagnostic procedure. Every blueprint has one check that
> decides — we call it the discriminator. This tab runs that check, live, on a window you pick."

Read the line at the top — it changes with the trace:

- CPU trace: *attribute CPU time per container and look for a workload consuming it that was not there before*
- Network trace: *sum network events per container over a quiet window and a suspect window, divide, and rank lowest first*

### Do this

**Drag across the middle of the chart.** The check runs.

On the **CPU** trace you get:

> **A container appeared.** `4026533601` (stress-ng-cpu) has essentially no baseline and
> 5,750,918,837 CPU ns/s in the suspect window.

On the **network** trace:

> **One container separates.** `4026532538` falls to **0.109×** its own baseline against a
> median of **0.325×** — a separation of **3×**.

**Then switch the Signal dropdown.** This is the moment.

> "Same window, same containers, different measurement. On the network trace, that container
> separates on network events and does *not* separate on CPU or scheduling. That's the whole
> distinction: one container's network path is impaired, and the machine is not busy. If I
> could only show you one thing today, it would be this."

### The honest part — say it, don't skip it

Point at the grey line under the verdict:

> "Notice it reports both ends — the biggest faller and the biggest riser. That's not a UI
> nicety, it's something we got wrong and had to fix.
>
> The obvious statistic is 'rank by what degraded most'. We measured it: for a throttled
> container, that puts the actual culprit at **number fifteen out of eighteen**. It falls to
> about 40% of its baseline while the median container falls to 18% — because when one service
> stalls, the whole application slows, and everything else loses *more* than the faulty
> component does.
>
> Ranking by the biggest drop finds victims."

### Background — if they ask

**Where did the thresholds come from?** Measurement, on our own labelled runs, before anything
was written down. For the network check: six of six incidents across both applications, the
injected container collapses to 9–18% of its own baseline while the median container holds at
63–129%. Separation 3.8× to 9.9×.

**How do you pick which kernel events matter for a problem?** Also by measurement, and the
blueprint records the reasoning. For host CPU saturation it's two events, `sched_switch` and
`sched_waking`, and the file says why:

> `sched_switch` alone carries everything the decision needs: it names the thread starting to
> run on each CPU and when, so the gap between consecutive switches on a CPU is the previous
> thread's on-CPU time. `sched_waking` is collected only to compute runqueue delay as
> corroboration; the verdict does not depend on it.

That second sentence is the useful discipline — it distinguishes what *decides* from what
merely *agrees*.

**Why does that matter commercially?** Because collection has a cost. This recording carries
over 400 distinct event types and the decision rests on two of them. You do not need the rest
running in production.

---

## 3 · BLUEPRINTS — the work behind the method

**This is the most important tab.** The agent is interchangeable; the blueprints are the
research.

### Open the tagged one and say

> "A blueprint is a diagnostic procedure for one class of fault. These are not prompts we wrote
> and liked the sound of. Every claim in here was measured on our own labelled data first, and
> a validator refuses to build the file if it wasn't."

### Walk the sections in this order

**Front matter** — scroll to the top.

```
name: host-cpu-saturation
version: 3
authored_by: measured from the CPU-cluster sweep, 17 labelled runs across four families
covers: anomaly_cpu
mutually_exclusive_with: cpu-contention-co-tenant, service-cpu-throttle, healthy-baseline
```

> "It records how many runs it was derived from, and which other blueprints it is mutually
> exclusive with. That last field is doing real work — it's a claim that these faults can be
> told apart, and the discriminators below have to back it up."

**When this applies / Do NOT use this when**

> "Entry conditions, and just as important, exit conditions. A blueprint that never says 'this
> isn't me' will be applied to everything."

**Problem signature → "Telling it apart from its look-alikes"** — *this is the core.*

Read one discriminator out loud:

> **host CPU utilisation, computed as busy on-CPU time over available CPU time from sched_switch**
> — this problem: utilisation reaches the ceiling, 0.99 or above. Not this problem: utilisation
> rises but keeps real headroom (co-tenant contention), stays flat (healthy), or *falls* below
> baseline (a cgroup cap).

Then show the evidence behind it:

> "And behind that line in the source file sits the measurement:
>
> *MEASURED on 17 labelled runs from four families. Host saturation 0.991–0.998 (n=3);
> co-tenant 0.619–0.681 (n=5); no-fault 0.462–0.531 (n=5); cgroup cap 0.114–0.365 (n=4).*
>
> Four populations, no overlap. That's why the threshold is where it is. The validator will not
> build this blueprint if that field is missing or doesn't point at a measurement."

**What to look at first** — the minimal event set, with the reasoning quoted above.

**Investigation blueprint** — the numbered steps.

> "Each step names a *capability*, not a command — 'attribute CPU on-CPU time per container',
> not 'run this script'. That's deliberate: a capability can be satisfied differently on
> different infrastructure, so the blueprint is portable. The mapping to what's actually
> runnable here is resolved separately, and a step whose capability has no implementation makes
> the whole blueprint fail to build."

**"Signals that do NOT work for this problem"** — scroll to the bottom. **Do not skip this.**

> "This section is a list of things we tried that didn't work, and it's in every blueprint.
>
> For example: high runqueue delay — how long ready threads waited for a CPU. It's the intuitive
> signal for CPU saturation. We measured it and it's *not usable*: it rises under every
> CPU-family fault and under ordinary load bursts too. So it's recorded as corroboration and
> never as the deciding signal.
>
> The reason this section exists is that without it, the next person re-derives the same dead
> end. A negative result you measured is worth keeping."

**"How this looks on different systems"**

> "The same fault does not look the same everywhere. We have two applications, and for the
> network fault they behave *oppositely* — on a short call chain 7 to 12 interfaces retransmit;
> on a wide fan-out system the same fault reached 0 to 1. The blueprint says so rather than
> pretending one number is universal."

### The one-sentence summary

> "A prompt tells a model what to think. A blueprint tells it what was measured, what the cut-off
> is, what it's confused with, and what has already been ruled out — and refuses to exist if any
> of that is unsupported."

---

## 4 · AGENT — watch it work

### Set up honestly, then press the button

> "This is the same function our study calls. Same blueprint, same tools, same data. It takes
> two to four minutes, and I'm going to run it now rather than show you a recording."

Press **Run the agent for real.** While it runs, narrate:

**Investigation starts** — point at the stamp.

> "Timestamped, so you can see this is happening now. The agent gets the trace and seven
> read-only tools and is told nothing else."

**It splits the work**

> "A planner writes independent subtasks and four workers run them in parallel on their own tool
> threads. Notice the plan is specific — it says what counts as a real signal versus routine
> noise, because the commonest failure is chasing something ordinary."

**The tool calls** — this is what to point at.

> "Each call shows what it **asked** and what it **got back**. That second line matters: two
> calls to the same tool look identical until you see one returned 25 million events and the
> other returned 358 thousand. This is where you can see it reasoning rather than just acting."

**A code step** — pause here properly.

> "And here it writes its own analysis code and runs it. This is the piece that removes the
> ceiling. Our six fixed tools answer a fixed set of questions; anything they can't express, it
> computes itself — summed CPU time per container, a rate before against after, a field parsed
> out of a raw packet header.
>
> That runs in a sandbox with no filesystem and no network. It matters here more than usual,
> because the ground truth file sits *inside* the run directory — so the sandbox is never given
> a run directory at all, just a pre-loaded table. We test it with nineteen escape attempts
> every time we change it."

**Findings**

> "It records findings as it goes, each with the numbers behind it. Those are what survive to
> the final step — not the raw conversation."

**Verdict**

> "And it commits: what, where, when, and the evidence."

### If you're short on time

Press **Stop**. It cancels at the next model call, usually within fifteen seconds, and the
partial transcript stays on screen.

> "Stopping is real, not cosmetic — the partial transcript is written to disk exactly like a
> completed run, so it stays auditable."

### Background — if they ask

**Everything is recorded.** Every prompt, every raw API response, every tool result, every line
of code it wrote, and a hash of the system prompt. For a dataset paper that audit record is the
evidence.

**Is it memorising the fault names?** No. It's given an opaque incident alias, and container
names that would reveal the fault are pseudonymised in every tool result and restored only after
it answers. Ground truth is readable only by the scorer.

---

## 5 · VERDICT — and the honest numbers

### Show the answer, then reveal

> "Here's what it concluded. Now let's see what was actually injected."

Press **Reveal ground truth**.

On the CPU trace:

> "It named `stress-ng-cpu` in namespace 4026533601. The injection was a co-tenant CPU load
> generator. The window it derived was 08:14:06 to 08:16:06; the truth is 08:14:06 to 08:16:07 —
> one second out, an overlap score of 0.992."

> "And it's scored by the study's own scorer, not a demo copy. Same code that produced our
> published results."

### Then — immediately, before anyone asks

This is the most important thing you say all session.

> "That's one run, and it's our best case. Here's the whole picture.
>
> Across 720 scored runs on two applications: faults that affect the **whole host** — CPU,
> network, a noisy co-tenant — it finds the right component 40 to 55 times out of 60. Faults
> inside **one service**: five of the six land between 0 and 3 out of 60. The exception is a
> slow datastore on one application, at 24.
>
> Same split on two applications that share no code. That replication is the main result."

Then the turn:

> "We read that as 'kernel traces can't localise a per-service fault'. **We were wrong.** It was
> three layers of our own plumbing.
>
> A reply cap was truncating tool results mid-JSON — the list naming already-running containers
> reached the model in 4.7% of calls. The blueprint reasoned about network *interfaces*, and a
> kernel trace can't map an interface to a service. And the answer schema asked for 'a process
> name', so it kept answering `java`.
>
> The signal was always there — six of six incidents, three to ten times separation. After
> fixing all three, on the network fault: **10 of 30 with the blueprint, 1 of 30 without.**
> Not solved. But off zero, for a reason we measured first."

---

## Closing — what you want from them

> "Three things would help us most:
>
> **Do these fault families match what you actually see?** We injected what the literature
> describes. You have the incident history.
>
> **Which telemetry is expensive for you to collect and keep?** That decides which ablation we
> run next — the whole point is to tell you what you can stop collecting.
>
> **Would you validate the catalogue against your own incidents, or share anonymised traces?**
> The fastest way to make this useful is to aim it at real failures rather than injected ones."

---

## Quick reference

| if they ask | short answer |
|---|---|
| What model? | `gpt-5.4` via Azure. Provider-agnostic harness; nothing depends on a specific model. |
| Cost per incident? | About 3.5 minutes and 350k tokens. A 720-run campaign is roughly 7 hours. |
| How big is the dataset? | 303 runs, two applications, four modalities, about 778 GB. |
| Why kernel traces first? | Hardest case. If it works here, adding metrics and logs can only help — and we can then price each modality. |
| Is 33% good? | No. The claim is that it isn't zero and we know why. The comparison that matters is 33% against 3% on the same data. |
| Would it work on our systems? | Unknown — and the two applications we have already behave oppositely on one fault. That's a result, and it's why we want your data. |

### Do not say

- "Solved", "works", "production-ready".
- Any per-service number without its sample size.
- Anything about the Train Ticket CPU-cap result — that injection was miscalibrated (a 0.2-core
  cap on a service using 0.004 cores) and we're re-collecting it. If it comes up, say that
  first.
