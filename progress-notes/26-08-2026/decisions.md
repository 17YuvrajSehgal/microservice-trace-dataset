# Decisions — 2026-08-26

## New direction from the supervisor meeting: observability blueprints

Meeting transcript: `meeting-notes/meeting-notes-26-08-2026.txt` (Naser, Mahsa, Yuvraj, Sneh).
Write-up: `blueprint-idea.md` (root, next to `new_design.md`).

**Immediate ask, with a date.** Naser wants a **draft blueprint for one simple problem by
2026-08-27**, and — separately and explicitly — Yuvraj to **define the blueprint format itself**
("you need to come up with a structure, a format"). He will review it and say whether it is good
enough. Target of ~5 blueprints to show Ciena at the next meeting. Naser will send an existing
JSON blueprint draft he built with AI for a Ciena meeting; it is not tied to a real problem and he
expects it to be changed.

**The decision.** The unit of research output changes. Instead of "we ran a pipeline, here is the
accuracy", the output is a **reusable executable artifact** — an observability blueprint recording
the whole experience of solving one problem (problem, reproduction, exact data to collect,
processing steps with runnable code, output spec) — plus evidence an agent can re-execute it on a
*similar new* problem unaided. Term of art is **blueprint**, not "template" (Naser's preference).

**Why (the pitch, in his words: "this is the part we are selling to Ciena").** Everyone already
has a trace analysis pipeline; nothing accumulates. The tool teams solve kernel-level problems
worth a paper each but keep no history — "the history is in Mohammed's brain", and gets deleted
when disk runs out. Framing: *"we are training another expert like Mohammed"*, pooling what
Mohammed, Jason and Alex each know. Positioned against Jira: companies already keep Jira histories;
**a blueprint is an enriched Jira history** with enough detail that an AI agent can act on it.

**The mechanism, from Naser's own experience — worth remembering as the intuition.** AI reinvents
every time; he has the workflow but the tool ignores it. He made it document what was already done,
**verified the document himself**, and now starts each session with "read that document first" —
much better, faster, more accurate. When he forgets to point at it, the tool goes back to
downloading a 50 GB model and reinventing. Two consequences for us: the blueprint's value is
avoided reinvention, and **human verification of the blueprint is part of the loop**.

**Our architecture is accepted; the blueprint is the delta.** Naser walked the `new_design.md`
diagram and placed the Jira work inside it (per-issue Jira plus related-Jiras in the Investigation
Context Builder / Shared Investigation Context) — fits unchanged. *"The one thing missing from there
is the blueprint."* Our 12 skills are already most of a blueprint; what they lack is the executable
part — event lists, runnable commands, output spec, and a link to the `faults/` recipes we own but
never wired in.

**Sequencing (explicit).** *"We will turn it to skills later on, but for now we just need a
template."* Blueprint document first; do not start by refactoring `skillreg.py`.

**Headline experiment, stated by the supervisor.** *"Compare with and without those blueprints —
you should see a huge difference."* Yuvraj added the second axis: **time**, not just accuracy. We
already record tokens/calls/$ per incident, so that axis is free.

**Mahsa's finding, taken as a design rule (validated, not speculative).** Putting the **exact
function/code** in the skill — rather than describing when to run it — **raises accuracy and
lowers LLM non-determinism**; replicated across three industry domains. So `processing` steps in
the blueprint must carry a runnable command, not prose. Caveat she attached: approaches lifted from
papers must be **re-tested on our own data** before being trusted in our domain. This became RQ5,
and it is a good fit for us because our harness can measure run-to-run variance.

**Blueprints drive collection, not just analysis.** A blueprint answers "what data do we need?"
before data exists: *"for this problem we need 5 kernel events, 3 telemetry data."* That closes the
loop back to the input layer and gives us RQ6 — does a blueprint's collection order cut data volume
without losing accuracy — which only we can answer well, because of the kernel ladder.

**Scope is wider than RCA.** *"Your work now will be finding issues that you can detect. It can be
detection, root cause analysis, or other kinds of analysis."* Anomaly detection counts as a valid
first blueprint.

**Bar the blueprint must clear (ours, from 21-08).** The model-only control with a good
deterministic briefing already ties the 7-tool agent (78/52 both ways, 27% of tokens). "Blueprint
beats no-blueprint" is not enough — it must beat that briefing control (RQ3). Read positively, that
result also supports this direction: good up-front structure is what actually works, and a
blueprint is exactly that.

**New consumer: TMLL.** Naser framed blueprints as *injecting expertise into TMLL* so it stops
re-deriving "what is this trace, what is this event" per question. That makes the format a shared
interface with Sneh's work, not ours to design alone (open Q7).

**Selection: manual now, AI later.** *"Give one main and a couple of similar ones... we will do it
manually, but later AI will choose."* That is our S1-with-distractors condition, so the existing
evaluation design covers it. With Mahsa's caution (autonomous selection fails on hard problems; the
orchestrator prefers the complex RAG skill over the simple one), the selector stops being a bug we
owe a fix for and becomes a research question — consistent with our own negative S1/S2 result.

**Deferred deliberately:** Jira mining (no corpus; our 95 labeled incidents can stand in as
pseudo-tickets), mining blueprints from transcripts, MCP and Trace Compass faces.

**Open, needs Yuvraj's call:** MSR abstract Nov 5 / paper Nov 10 versus a blueprint draft due
tomorrow. The blueprint track must not consume the paper deadline. Also open: JSON (Naser's draft)
versus markdown-with-frontmatter (our skills) as the blueprint file format.

**Transcript note:** three versions of the recording were merged; coverage is now effectively
complete (0:00-35:00). The earlier version is the only source for 10:36-13:22.

## Reading corpus downloaded (2026-08-26)

`DOCS/reading-papers/` now holds **48 of 72** PDFs from `progress-notes/reading_tracker.csv`
(109 MB). The tracker gained two columns: `Downloaded` and `PDF File`; blank = not fetched.

Only legal open-access sources were used — arXiv, publisher OA pages, and OA copies indexed by
OpenAlex/Unpaywall/Semantic Scholar. No paywall bypassing, so the 24 blanks are almost all
ACM DL / IEEE Xplore items with no free copy findable by API (several *do* have author-hosted
copies that a manual search finds — Yuvraj is fetching those himself). One blank is not a paper
at all: the MCP specification is a website.

**Not yet gitignored** — 109 MB of publisher PDFs would bloat the repo permanently if committed.
Decide before the next commit.
