# Meeting Notes — 29 July 2026 (Organized)

**Attendees:** Naser Ezzati-Jivan (supervisor), Sneh Patel, Mahsa Panahandeh, Yuvraj Sehgal
**Format:** Two back-to-back calls on the same day:
1. **Team call** (~1:42–2:42 PM, all four present) — source: `sneh-and-mine-together.txt` lines 1–431
2. **1:1 follow-up** (~2:10–2:22 PM your time / marked 5:10–5:22 PM UTC, Naser + Yuvraj only) — source: `my-part.txt`, identical content also at `sneh-and-mine-together.txt` lines 437–509

Official minutes (sent by Naser after the call) are folded in below where they add
precision: `meeting-notes.txt`.

> **Note on transcript quality:** this is an AI-generated transcript and it does contain
> recognizable errors. I've flagged the ones I noticed rather than silently correcting
> them — verify anything marked ⚠️ before you act on it.
> - "**bubble trace**" / "**bible test**" / "**bubble taste**" → almost certainly
>   **Babeltrace** (the tool is named explicitly and described correctly — command-line
>   LTTng trace analyzer, C, Babeltrace2 — so the *concept* is solid even though the name
>   kept getting mangled).
> - "**Siena**" / "**Sienna**" → a client/partner company name; given the telecom context
>   (Ericsson meetings), this may be **Ciena** (a real telecom equipment vendor) rather
>   than "Siena." Worth confirming with Naser.
> - "**Ciena**" → referenced as another team/partner doing similar Trace Compass +
>   AI work with polished graphical output; likely an organization name, not spelled
>   out clearly enough to confirm.
> - "**Google's soft shop**" → Sock Shop is the **Weaveworks** demo app, not Google's;
>   likely a misattribution in the moment, not a transcription artifact.
> - Your fault-run count: transcript says "**in total we have 4036 are fault runs... and
>   four are like normal runs**" — garbled. Possibly "40 total, 36 fault runs, 4 normal,"
>   which doesn't quite match the actual dataset (34 fault + 6 normal = 40, per
>   `progress-notes/28-07-2026/campaign-complete.md`). Likely just an imprecise verbal
>   recollection in the moment rather than a real discrepancy — the file numbers are the
>   source of truth.
> - Two *different* statements about what kernel data to skip: this transcript has you
>   saying "professor specifically mentioned that we do not need to collect **IO**
>   related" traces; a separate note from your own project history records "**exclude
>   memory events** for sure." These may both be real (two separate pieces of advice
>   at different times) or one may be an ASR mix-up of "I/O" vs "memory" — worth
>   double-checking which is currently accurate for your curated kernel profile.

---

## 1. Why this pivot happened

Sneh presented his week's work: a chatbot-style client that connects an LLM to Trace
Compass via **TMLL** (Trace Compass's new MCP-based analysis layer) and **MCP**, able to
answer "why is this thread slow" using the Control Flow view. Naser's reaction, at
length: **connecting a chatbot to an existing tool is not a research contribution** —
it's a couple hours of engineering, and the same access is possible by pointing ChatGPT
at the MCP directly, without touching Trace Compass at all.

While digging into what TMLL actually offers, Naser found its GitHub README already
lists: create trace experiment, list outputs, fetch data, **run anomaly detection**,
**detect memory leaks**, **detect change points**, **analyze correlation**, **detect
idle resources** — and that the TMLL team has already **published a paper** on this
(a top-venue publication, not yet named in the transcript). Verdict: **"we are not ready
for Friday [demo] — they have already done this."** This is the pivot point for the
whole meeting.

**Where the real gap is**, per Naser: TMLL's anomaly views are basic (CPU/disk/network
usage only) — it does **not** cover critical path analysis, cross-view reasoning, or
complex/compound anomaly detection. That gap is the opportunity.

Mahsa's framing (useful heuristic going forward): the way to find a genuine
contribution isn't to learn/use the tool — it's to **stress-test it with complex,
unexpected scenarios** and see exactly where it breaks or falls short. That gap is the
paper.

---

## 2. The shared vision to emerge: "agent-first" observability

A few ideas the group converged on that apply to both Sneh's and your track:

- **Layered architecture:**
  - **Layer 1** — access existing views/data (mostly already solved by TMLL/MCP)
  - **Layer 2** — intelligent analysis on top: root cause analysis, cross-view
    reasoning, critical path analysis, complex anomaly detection
  - **Layer 3** — agent-driven workflows: automatic view selection, automated
    navigation, interactive visualization (agent can zoom/highlight/load views on
    request)
- **Central indexing / RAG layer.** Trace Compass has an internal "**State System**"
  (its indexing database that every view queries). Naser's proposal: build an
  equivalent **central RAG / GraphRAG index** that all analyses can query, instead of
  each view/analysis reading raw trace data independently — this scales much better
  and is itself a candidate architectural contribution.
- **"Skills" as the core interface** (this is the concept your 1:1 call goes deep on
  — see §4). Instead of one monolithic tool, package reusable **skills**, each of
  which defines the full pipeline for one type of problem: what data to collect, how
  to analyze it, what to output.
- **Agent-first design philosophy**: assume the end user interacts through an AI
  agent, not a UI. Design APIs, MCP interfaces, and skills around that assumption from
  the start, not as an afterthought.
- **Business/strategic framing** (stated directly by Naser): getting the architecture
  right makes it easier for the partner org to **patent** this work, and Naser wants
  the team's authorship clearly recognized — "we want to make sure people associate
  this to us."

---

## 3. Sneh's track (context only — not your task, but shapes the shared architecture)

- **Status:** built a TMLL↔Trace Compass client; can explain simple slowdowns via the
  Control Flow view; working on critical path next.
- **Naser's assessment:** the client itself isn't the contribution — the bridging code
  Sneh wrote to get TMLL proper access to Trace Compass views *is* real work, and should
  be cleaned up and **submitted as pull requests** to the TMLL/Trace Compass repos (one
  clean module per view), to build community recognition.
- **Assigned:** read the TMLL paper and architecture in full; finish all Trace Compass
  labs (esp. critical path, complex analysis); build connector modules for every major
  TC view; investigate GraphRAG/central-indexing/cross-view-reasoning improvements;
  send Naser an architecture diagram (**Chat Client → MCP → TMLL → Trace Compass →
  custom modules**, contributions clearly marked) the same night; only demo Friday if
  there's genuine novelty beyond "a client."
- **Relevance to you:** Naser explicitly said your two tracks are complementary and
  should stay loosely coupled — Sneh stays on the graphical/Trace Compass side in
  Java; you go faster/scalable on the command-line/Babeltrace side; your outputs "can
  be imported by Sneh" later, and the skill/workflow concept (§4) is meant to apply to
  both.

---

## 4. Your track — full detail

### 4.1 Recap: what you reported on the dataset (team call)

- Sock Shop-based dataset essentially complete: kernel traces (LTTng), OpenTelemetry
  traces, logs, and metrics, across **12 fault types**, ~150 GB (this matches the
  actual ~164 GB collected — see `progress-notes/28-07-2026/campaign-complete.md`).
- LTTng collection is **curated**, not full capture — a specific subset of event
  families was selected on your professor's instruction (see the ⚠️ IO-vs-memory note
  above).
- Current faults are mostly **not** single-service — most bring down "the whole
  thing" rather than isolating one service.
- **Ask from Naser:** categorize/tag faults by **blast radius** — some scenarios
  affecting exactly 1 service, some 2–3 (based on shared dependency/resource), and so
  on. He does *not* want exhaustive combinatorics (2, 3, 4, 5 services...) — just a few
  representative steps. **Share the fault table with him for review.**
  - *Note:* this maps directly onto the two-axis (host-wide vs service-targeted) fault
    catalog design already built in `fault_catalog.md` — likely largely satisfiable by
    documenting/extending what already exists rather than starting fresh.
- **Research direction discussed** (for the existing StrataTrace/MSR work, separate
  from the new agentic pivot): an empirical, ablation-style observability study —
  map the four modalities (traces, logs, kernel traces, metrics) to downstream tasks
  (anomaly detection, RCA, comprehension) and measure which modality(ies) are most
  useful per task, including whether reduced modality subsets retain accuracy. Possibly
  add a second benchmark dataset beyond Sock Shop later. **This is unchanged from your
  existing plan in `msr-research.md` and `fault_catalog.md`.**

### 4.2 New assignment: Babeltrace-based agent-first architecture

This is the headline new work item, introduced by Naser once the TMLL/Trace Compass
plan got redirected.

**Why Babeltrace, not Trace Compass:** Trace Compass (Java, GUI-first) is described as
too slow for large or long traces ("cannot use it for longer than ~10 seconds of
trace"). **Babeltrace(2)** is a C, command-line LTTng trace analyzer that scales to
gigabytes/terabytes, and — importantly — its architecture already mirrors OpenTelemetry:
**input → analysis → output**, fully plugin-based (write your own parser/analyzer/
output plugin for basically anything).

**Your concrete tasks (in order):**

1. **Verify Babeltrace2 can parse non-LTTng data**, not just kernel/LTTng traces —
   specifically regular application logs, and reportedly a non-standard partner format
   ("Tireball"⚠️ — likely mis-transcribed) that Trace Compass doesn't support. This is
   the gating question: if Babeltrace can ingest logs too, it becomes the one unified
   backend for everything you're collecting (kernel traces + OTel traces + logs +
   metrics).
2. **Design (don't over-build yet) an architecture**: Babeltrace's input/analysis/
   output pipeline + a new **MCP layer** on top, exposing two simple APIs to start:
   - raw data access
   - a basic query API ("what is this event", "what happened here")
   No complex analysis needed yet — Naser was explicit that the *architecture* matters
   more than the analysis sophistication for tomorrow.
3. **Prototype a minimal MCP-on-Babeltrace demo** if feasible before the next meeting —
   framed as "Babeltrace MCP," parallel to what Sneh is building for TMLL, but scoped
   to be much simpler for now.
4. **Prepare an architecture diagram** for the next meeting, in the same spirit as
   Sneh's: input sources → Babeltrace → MCP → outputs, contributions clearly marked.

**Later-phase ideas mentioned (not immediate tasks, just noted):**
- Reconnect this pipeline to your **prior JIRA/log-similarity work** — auto-file a
  JIRA ticket when the analysis detects a real anomaly.
- **Adaptive-tracing feedback loop**: the analysis stage could tell the collection
  stage "I need more of this specific log/event" — ties back to your earlier LMAT/
  adaptive-tracing line of work.
- Ciena's existing log-analysis pipeline (referred to as "Sherlock" in the transcript)
  could plug into your new architecture as one more analysis module.

### 4.3 The "skill" architecture — deep dive (this is your 1:1 call, `my-part.txt`)

This is the design Naser wants you to formalize and present. Read this section closely
— it's the part he's asking you to turn into an actual architecture diagram tonight.

**Core idea:** replace ad-hoc analysis scripts with a reusable, packaged **"skill"**
(Naser floated "use case" as an alternative name — pick whichever reads better) per
class of problem. A skill is a complete, self-contained package that defines:

| Component | What it specifies |
|---|---|
| **Requirements** | What data is needed to solve this class of problem: which trace/log/event formats, which specific LTTng events (e.g. `cpu.*`, `process.*`, `file.*`), which metrics. Machine-readable — Naser suggested **JSON**. |
| **Workflow / chain** | The processing pipeline: data collection → (optional) synchronization/correlation → preprocessing → mining/analysis (RCA, anomaly detection, etc.) → output generation. |
| **Output format** | Not one-size-fits-all — some analyses need a graphical view, some need tabular numbers (confusion matrix, accuracy), some need a text explanation. The skill dictates which. |
| **Code** | The actual implementation backing each stage — packaged together with the skill, not separate. |

**The critical point Naser repeated multiple times:** a skill dictates the *entire*
pipeline, **including data collection** — not just analysis on data that already
exists. It decides *what* to collect, *how* to save it, and *where*, based on the
problem, not the other way around. This is explicitly positioned as more sophisticated
than what the partner org (Ciena⚠️) currently does — his characterization of their
approach is "collect everything into a zip file" with no upstream decision layer
choosing what's actually needed.

**Two-phase execution model:**
- **Phase 1 — Requirements.** Given a stated problem ("my database is slow", "my CPU
  is always at 100%"), determine and emit the data/event requirements needed to
  diagnose it (JSON spec of needed LTTng events, metrics, log formats).
- **Phase 2 — Execution.** Using that spec: collect the data, run the analysis chain,
  generate the output.

**Search/retrieval:** keep it simple for now — a basic matching function over whatever
data is already available. **RAG-based retrieval is explicitly deferred** to a later
phase, once this core approach is validated.

**Scope discipline (explicit decision, not a side comment):** Naser was clear —
**do not try to build a generalized system that works for every customer/dataset.**
LTTng is open source, so *any* AI agent can install and use it, but that doesn't mean
you should design for arbitrary portability now. Take a strict **bottom-up approach**:
design specifically for this dataset/Ciena needs first; only in a later phase
consider merging or generalizing skills across use cases.

**Your proposed demo scope (agreed with Naser on the call):** a single skill, focused
on a database-slowness root-cause scenario:

> User/agent prompt: *"My database is really slow — find the root cause."*
> The skill's requirements spec directs the agent to pull the specific logs/traces it
> needs (not everything); the agent then investigates and reports.

Naser confirmed this is the right shape, and reiterated the demo must visibly show the
skill *dictating collection scope*, not just running analysis on already-collected
data — that's the differentiator to land in tomorrow's meeting/demo.

---

## 5. Action items for you (Yuvraj), consolidated

**Due tonight / before tomorrow's meeting:**
- [ ] Design the skill-based architecture (requirements → workflow → output packaging,
      per §4.3) and share it with Naser.
- [ ] Sketch the Babeltrace architecture diagram (input → analysis → output, + MCP
      layer, contributions marked) per §4.2.
- [ ] Prepare 2–3 slides for tomorrow: (1) agent-first design philosophy, (2) the
      skill/use-case architecture including data collection + analysis + output as one
      package, with **two example use cases** — one locks-related, one LTTng-trace-
      based (§4.2/§4.3 combined — these may end up being the same artifact).
- [ ] If time allows: a minimal working demo — verify Babeltrace2 can parse non-LTTng
      logs, and/or a bare-bones MCP-on-Babeltrace prototype.
- [ ] Talk to Naser tonight/before the meeting if you want to align before presenting
      (he offered explicitly).

**Ongoing / near-term:**
- [ ] Categorize existing faults by number of affected services (§4.1) and share the
      table with Naser.
- [ ] Continue toward the modality-ablation study already planned in `msr-research.md`
      (unchanged by this meeting — this is separate, parallel work).

**Do NOT do (explicitly deprioritized this meeting):**
- Code-generation / multi-agent-fixes-code framework — Naser said Ciena is no longer
  interested in this direction; can be dropped.
- Do not demo "just a chatbot connected to MCP" on Friday — confirmed dead end.

---

## 6. How this connects to the existing StrataTrace work

You flagged wanting to reuse the dataset — concretely, it's already positioned to help:

- The **40-run dataset** (kernel traces, OTel traces, logs, metrics, ground truth,
  verification verdicts) is a ready-made test corpus for both the Babeltrace-parsing
  question (§4.2 step 1 — try Babeltrace against your actual LTTng + log files) and the
  demo skill (§4.3 — the "database slow" scenario maps directly onto your existing
  `slow_db` fault, which is already collected, calibrated, and confirmed).
- The **two-axis fault catalog** (`fault_catalog.md`) already encodes host-wide vs.
  service-targeted scope — likely covers most of the "categorize by affected service
  count" ask in §4.1 with light extension rather than new work.
- The **curated kernel event profile** decision (already implemented in
  `collect_trace.sh`) is directly relevant to the Babeltrace requirements-spec format
  Naser described in §4.3 (JSON listing needed LTTng events like `cpu.*`/`process.*`) —
  you've effectively already built one instance of what a "skill requirements" block
  would look like.
- The **existing MSR modality-ablation research plan is unaffected** — this meeting
  adds a second, parallel track (agent-first skill architecture / Babeltrace) rather
  than replacing the dataset/study work.
