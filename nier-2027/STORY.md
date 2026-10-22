# The NIER story, in one page

Naser's standing ask (G4, 9 Sept): *what is the new idea, what did we measure,
why does it matter.* This is that page. Target: **ICSE 2027 NIER, 23 Oct 2026.**

## The new idea

Everyone building LLM agents worries about context **size** — window limits,
compaction, retrieval, lost-in-the-middle. We instrumented a real tool-using
agent against verifiable ground truth and found something else.

**The window was used to 6.6%. A third of all tool results were being destroyed
in transit.**

An agent's context is not a window. It is the **output of a pipeline**:
serialize → truncate → retain → transfer → persist. Every stage is a lossy
transform written by an engineer. None of them is reported in any agent
evaluation we know of.

> **Context is a pipeline, not a window. Its failure modes are engineering
> defects, and they masquerade as model or data limits.**

## What we measured

Our harness capped tool results at 6000 characters by slicing the JSON
**string**. Measured over 720 runs:

- **3,827 of 11,189** tool results were cut, and **every cut one was
  unparseable JSON** — chopped mid-number.
- `json.dumps` preserves key order, so a prefix slice does not *sample* a
  result. It **deletes late keys outright.** One field, `present_throughout`,
  reached the model in **4.7% of 742 calls**. Its sibling,
  `present_for_only_part_of_the_recording`, reached it **99.3%** of the time.

Then the part that makes this a paper and not a bug report. **Which list a
culprit lands in is decided by whether it started during the trace.** An
injected stress process spawns → early key → delivered. A throttled or
network-degraded container was already running → late key → deleted.

**The benchmark split exactly along that line, on both applications:
spawn-type faults 40–55/60, already-running faults 0–24/60.**

We read that as a finding about kernel traces. It was a finding about our
serializer. The largest prompt any model call ever saw was 23k tokens against a
400k window — **we were destroying evidence to save context that was 94%
empty.**

## Why it matters

Three reasons, in order.

1. **The confound is selective, not noisy.** It did not add variance to our
   scores. It **partitioned** them along a task-structural axis with no
   scientific meaning. A reviewer reading our old numbers would have drawn a
   conclusion about telemetry that was false.
2. **Every tool-using harness has this pipeline.** Serializing, truncating,
   trimming and handing off between phases are not optional. So this is a
   defect *class*, not our mistake.
3. **Agent benchmarks score what an agent said, not what it knew.** We can
   measure the gap. On one campaign, **234 of 554 workers ran out of steps with
   tool calls still pending, and 98 of those recorded nothing at all** — whole
   investigations that never reached the decision, because the only channel
   across the phase boundary was a voluntary call. In one case a worker
   computed the deciding number exactly (a rate falling 1242.8/s → 0/s) and the
   agent answered "normal."

## What we propose

An **attrition profile**: instrument the five boundaries and report, for every
piece of evidence the agent produced, whether it survived to the decision.
Headline metric: **evidence yield** = reached the decision ÷ produced.

Publish it next to your accuracy number. We argue it should be a reporting
requirement for agentic-SE evaluation.

## The claim we can defend

Not "bigger windows do not help." The sharper one:

> **Within one harness, with capacity held constant and 93% of the window
> unused, memory-pipeline engineering moved task accuracy from 0/60 to 40+/60
> on a whole fault class — and the direction of the effect depended on a
> property of the task, not of the model.**

And the remedy is structural, not bigger: a structured prior (one of our
blueprints) reached the same verdict as free exploration using **35% of the
input tokens**, and a one-shot deterministic brief tied a full tool-using agent
at **27%**.

## Why nobody notices

Because it does not show up in latency. Kernel traces of coding agents show
**~84% of wall-clock time is model wait**; local compute is ~4.7 CPU-seconds.
Context attrition costs correctness and money, and almost no time. It is
invisible to exactly the metric people watch.
