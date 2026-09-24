# Ciena meeting — running order and talking points
**24 September 2026. Audience: mostly engineers.**

For an engineering room: lead with the method and the bugs, not the wins. They have seen agent
demos. They have not seen someone measure honestly and show the failures.

---

## Running order (~35 min + questions)

### 1 · The question (2 min)
> "Observability costs money to collect and keep. We are trying to measure which telemetry you
> actually need to diagnose which failures."

Four modalities, labelled faults, two applications. Give the agent a subset, measure what it
still gets. Today's subset: kernel traces only.

**Say once, early:** the agent is not told an incident happened, when, or where. That is what
makes the numbers mean anything.

### 2 · The headline, and its trap (4 min)
Host-wide faults 40–55 of 60. Per-service faults 0–3 of 60 in five of six cells, with a slow
datastore at 24. Same direction on both applications.

> "Our first reading was that kernel traces cannot localise a fault to a service. That reading
> was wrong, and the rest of this is how we found out."

Do **not** dwell on the good numbers. The room will ask about the zeros — let them.

### 3 · The four bugs (10 min) — *the centrepiece*
This is the part engineers will remember and the part that transfers to their own work.

| bug | what it did |
|---|---|
| reply cap sliced JSON mid-number | 3,827 unparseable results; container list reached the model 4.7% of the time |
| raw lines cut at 400 chars | TCP header starts at ~660; every sequence number invisible |
| `read_csv(comment="#")` | JVM names threads `GC Thread#7` → 23M events silently dropped, Java apps only |
| scorer credited any container id | would have scored "rank and pick lowest" correct whether or not it worked |

**The line to land:**
> "Three of these produced no error, no warning, and no failed run. They produced plausible
> worse numbers. Before you conclude what a model can or cannot do, check what it actually
> received and what it was allowed to say."

**Expect pushback: "how did you find them?"** Answer: by making two tools answer the same
question and comparing. A smoke test proves a tool returns; only a cross-check proves the answer
is right. 20 checks across 5 runs and both applications.

### 4 · The signal was there (3 min)
Six of six incidents: the injected container's traffic collapses to 9–18% of its own baseline
while the median container holds at 63–129%. In data the agent already had.

### 5 · Live demo (10 min)
```
python demo/app.py          # http://127.0.0.1:8765
```
Full walkthrough with wording is in **`demo/speaker-notes.md`** — five tabs, and the agent runs
for real rather than replaying.

Short version if time is tight: **Discriminator** tab, drag the chart, then switch the Signal
dropdown so they see the same container separate on one measurement and not another. Then
**Agent → Run the agent for real** and pause on a code step.

**Then immediately:** "That is one run. Across 30 runs it gets the container right 10 times with
the playbook, once without." Say it before anyone asks.

### 6 · What a measured playbook buys (4 min)
`svc_net` 0/30 → **10/30** with, 1/30 without. `svc_cpu_cap` 0/30 → **6/30** with, 1/30 without.

Say "moved off zero", never "solved".

### 7 · The three results we would rather not have (5 min)
- A playbook whose deciding check needs a quantity the tools cannot compute makes the agent
  **abstain** — even with the signal visible.
- Ranking by "what degraded most" finds **victims, not culprits**. The throttled container falls
  to 40% while the median falls to 18%, because a stalled service slows everything.
- **One of our own injections never engaged** — CPU cap fifty times above what the service uses.
  The agent now correctly says "no fault" 43 of 60 times, and our metric scores that as failure.

> "We are showing you a broken fault of our own and a metric that punishes the agent for being
> right. Both are getting fixed before the campaign."

This is what buys credibility with engineers. Do not skip it to save time.

### 8 · Ask them for something (3 min)
- Do these fault families match what you actually see?
- Which modalities are expensive for you to collect and keep?
- Would you validate the catalogue against your incidents, or share anonymised traces?

---

## Questions to expect

**"Is it just pattern-matching the fault names?"**
No — it never sees them. It gets an opaque incident alias, and fault-revealing container names
are pseudonymised in every tool result. Ground truth is readable only by the scorer.

**"How do you know the container it named is the right one?"**
Fair, and it was broken until yesterday. We resolve a container to a kernel namespace by
matching CPU time from cgroup snapshots against the trace, and the scorer **refuses** when the
match is ambiguous — recorded as `unverified`, not as a pass.

**"33% isn't very good."**
Agreed. The claim is not that it is good, it is that it is not zero and we know why. The
comparison that matters is 33% against 3% on the same data with the same model.

**"Would this work on our systems?"**
Unknown, and worth finding out. The two applications differ — the same fault has opposite
signatures on each. That is a result, and it is also the reason we want your incident data.

**"Which model?"** The published runs used `gpt-5.4-mini` via Azure; the demo runs `gpt-5.4`. The harness is provider-agnostic. Nothing here
depends on a specific model, and we can re-run an ablation on another.

**"What does it cost to run?"** ~345k tokens and ~3.5 minutes per incident. A 720-run campaign
is about 7 hours wall clock.

---

## Do not say

- "Solved" / "works" / "production-ready" — none of that is true yet.
- Quoting per-service numbers without n. Several are n=30; the earlier ones were n=6.
- Presenting Train Ticket's CPU cap as a result. It is a known-bad injection — say so first.

## Have open in another tab
- The results page (link below) for anything they want to see in detail.
- `progress-notes/23-09-2026/decisions.md` if someone wants the raw reasoning.
