# Decisions, 20-11-2026

## 1. Blueprints need a written method (supervisor's concern)

Concern: a blueprint is a text written with an AI, with no stated way of how it was made
or how it is used. A reviewer will ask where it came from.

Decision: write the method down and hold the blueprints to it. Draft:
`Blueprint/latency/METHOD.md`.

- A blueprint has six required parts: root cause, mechanism, signal, decision rule (a tool
  with a verdict line), procedure, evidence and limits.
- Seven build steps, each with a kept output and a rule for going on. This is what we did
  for blueprints 12 to 24; it was never written as rules.
- Why this and not a new process: the steps are true to the record (sweeps, rule
  histories, decisions files), so the claim can be checked.

Known gaps, written in the draft: bars were set on the runs that are reported (no held-out
split), the pass bars were never fixed in advance, nobody else has repeated the steps,
blueprints 1 to 7 do not fit the template.

## 2. Blueprints must not be pasted into the prompt

Concern: the agent gets the whole README as text and is asked to follow it. `agent_v2.py`
records the result: the blueprint tool was called 8, 2 and 0 times on three runs.

Decision: a blueprint also has a structured file (`blueprint.yaml`) and a harness runs it
as a LangGraph graph (`Blueprint/agent/bp_graph.py`). Prototype on blueprint 1 only.

What the harness holds, and what the agent holds:

| Harness (code) | Agent (model) |
|---|---|
| one step at a time; only that step's tool output is in the context | which commands, which arguments, how many slices |
| a step ends with an outcome and its facts, or a reason | which outcome fits; `other` when none does |
| evidence lines are checked against real tool output | jump to another step, skip one, or stop early |
| every leave from the guidance is logged with the reason | the final statement |

Why not a fully fixed pipeline: the user wants the work to stay agentic. A blueprint is
guidance; on a trace that does not fit, the agent must be free to do something else. So
leaving the guidance is allowed and logged, never blocked. The log gives a number we could
not have before: how often the agent followed the blueprint, and where it left.

Why steps with separate contexts: only the summary, facts and evidence of a step go on.
This keeps the context small (matters for local models) and forces the agent to write down
what it found.

Not decided yet:

- A baseline with no model (run every decisive tool, take the verdicts) must be reported,
  or a reviewer will ask why a model is needed.
- Comparison to run: README in the prompt (today) against the graph, same runs.
- Blueprint 1 has no `VERDICT:` line in its tools, so the harness cannot read a verdict
  by code here; the agent reads the tables. Blueprints 12 to 24 can do better.

State: `bp_graph.py --selftest` passes (scripted model, no trace, no API). No run with a
real model yet. Nothing committed.

## 3. First runs of the graph agent (blueprint 1, sample trace, gpt-6-luna)

Trace: `svc_cpu_cap_aggressive_steady_r1` (cap of 0.2 cores on carts, a JVM, injected
15:19:46 to 15:21:46). The run name is hidden from the model.

| run | steps visited | result | model calls | tokens in / out |
|---|---|---|---|---|
| 1 | 5 of 7 | right victim and window; stopped before the idle-CPU check; "not confirmed" | 23 | 94k / 5.9k |
| 2 | 7 of 7 | all checks done (CPUs 85% idle, ceiling 28.5 ms per 100 ms); report still said "not confirmed" | 29 | 111k / 5.3k |
| 2, report written again | same ledger | CONFIRMED, java pid 52884 in a container, window 15:19:45 to 15:21:45, cap about 0.285 cores | 1 | 2.4k / 0.7k |

All evidence lines were found in real tool output (24 of 24 in both runs).

Two design errors found, both mine and not the model's:

1. **The budget message ended the investigation.** "Close it now, with what you have" was
   read as "stop". Fix: the brief names what the next step does, and says that closing a
   step moves on.
2. **The verdict was a second free decision.** The report writer saw every check passed and
   still refused to confirm, because the quota itself is not in the trace and because two
   calls with wrong arguments had printed nothing. Decision: the verdict is a rule of the
   blueprint over the outcomes the agent chose (`verdict:` on an outcome in the yaml). The
   report writer explains it and may disagree, with a reason, in a separate field.

Why (2) is the right split: the agent's judgment is used where it sees the data (which
outcome fits this step). The step from outcomes to verdict needs no judgment, so it should
not be open to drift.

Seen and left as is: the agent cuts the baseline and fault slices again in `compare_budget`
although the same slices exist (allowed, costs time). Calls with wrong arguments use up the
step budget.

Limits of this result: one trace, one model, one blueprint, and the fix for (2) was tested
by writing the report of run 2 again, not by a third full run.
