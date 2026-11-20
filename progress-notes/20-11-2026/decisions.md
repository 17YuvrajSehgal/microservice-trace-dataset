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

## 4. Blueprints 24 and 15 in the new form; the format after three blueprints

Converted `24_code_unbounded_cache` (3 steps) and `15_dependency_outage` (4 steps). Three
things were added to the format and the harness because these two needed them:

- **`line:` on an outcome.** The start of the tool's verdict line that stands for this
  outcome. The harness finds it in the step's tool output by text match, compares it with
  the outcome the agent chose, asks for a reason when they differ (logged as
  `against_tool_verdict`), and copies the line into the evidence itself.
- **`handoff:` on an outcome.** The folder of the blueprint that takes the case next; the
  harness starts it with the facts already found. Written for 24 -> 15 ("memory grows with
  new threads"). Not seen in a run yet.
- **`vars:`** named event lists (`$MEMSYS`, `$SEV`), expanded in tool arguments.

One source: `bp_render.py` writes `BLUEPRINT.md` from the yaml (header, background, tools,
steps with an outcome table, measured and limits). `README_v1.md` stays for now because
`agent_v2.py` and RCA Studio read it; it goes when all blueprints are converted.

Runs (gpt-6-luna; tools on the laptop through WSL, or on the Trillium login node):

| blueprint | run | tool verdict line | agent's outcome | verdict | truth |
|---|---|---|---|---|---|
| 15 | `dependency_outage_aggressive_steady_r1` | SERVICE FROZEN, then FROZEN AT 11:16:29.156 | frozen, frozen_at | confirmed: `app`, pid_ns 4026532822 | `payment` paused at 11:16:29 |
| 24 | `code_unbounded_cache_aggressive_steady_r1` | MEMORY ONLY GROWS: `node`, 421 MB in 30 s | leak | confirmed (see below) | front-end, 05:19:40 to 05:21:43 |
| 15 | `svc_cpu_cap_aggressive_steady_r1` | NO SILENT SERVICE (quietest kept 7%) | none | rejected | a CPU cap |
| 24 | `svc_cpu_cap_aggressive_steady_r1` | NO STEADY MEMORY GROWTH | no_growth | rejected (see below) | a CPU cap |

Cost per run: 8 to 12 model calls, 18k to 29k tokens in, 1.4k to 1.7k out, 2 to 6 minutes.
The short blueprints cost about a fifth of blueprint 1 (111k tokens in).

Harness bug found: both blueprint 24 runs came out "inconclusive" although the agent chose
the right outcome. The agent had also filled `next_step` with the place that outcome goes
to anyway, and the harness counted that as a jump and did not apply the verdict. Fixed
(naming the outcome's own destination is not a jump; in the self-check). The verdicts in
the table for 24 are the rule applied to the saved ledger; for the labelled run the report
was written again and reads "confirmed". Neither run was repeated in full.

Agent behaviour seen: in every one of the four runs the agent's outcome agreed with the
tool's verdict line. On the labelled leak run it lost four calls on wrong arguments
(`extract_slice.sh` without the trace folder) before the right call.

Still one run per case. Not yet seen: an agent that goes against a verdict line, a
hand-off, a trace where the suggested slice time is wrong.

## 5. Blueprints 12 to 23 in the new form (11 more; 14 of 25 now)

Converted 12, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23 with three helper agents, under a
checker written first (`Blueprint/agent/bp_check.py`): step links, scripts exist, every
`line:` is really printed by a tool, every number in the text is in the README, the results
file or a tool. All 13 files of 12 to 24 pass with no warnings. `BLUEPRINT.md` is generated
for each.

Changes I made to the helpers' files: blueprint 14's last step no longer rejects a deadlock
because of a contention verdict about another process (the README is silent on that case;
now "unconfirmed", and only for the same process); blueprint 17's optional host check can
no longer reject.

Stale or missing things in the old READMEs that the conversion exposed (not fixed in the
READMEs): 12 lists a message the tool no longer prints, its status says four runs are
unchecked although RESULTS.md has 10 of 10, and it cuts 90 s but passes 60 to the tool;
16, 19, 20 give no rule for the slice time.

Agent runs, one labelled Sock Shop run each (gpt-6-luna, tools on the Trillium login node):

| blueprint | first try | after the fix below |
|---|---|---|
| 12, 14, 17, 18, 19, 20, 21 | confirmed, right process | |
| 13 `fork_storm` | rejected: slice 1 s after the fault ended | confirmed |
| 16 `anomaly_disk` | rejected: slice 20 s after the fault ended | confirmed |
| 22 `error_storm` | rejected: slice 14 s after the fault ended | confirmed |
| 23 `code_n_plus_one` | rejected: fault and baseline slices both inside the fault | rejected again |

Cost: 6 to 17 model calls, 13k to 60k tokens in per run.

**Finding: choosing the time is the weak step, not reading the tool.** In every run the
agent's outcome agreed with the tool's verdict line. The four failures came from the slice
time. For these faults the rate table shows no window, the agent guessed a late time, and
one "no" was taken as a rejection. The tool-only sweeps could not show this: they took the
time from the label.

Decisions:

1. General rule in the agent's instructions: the rate table is a hint; with no clear window
   take several times; the check decides.
2. The harness sends a rejecting outcome that rests on at most one measured slice back
   once. The agent then either confirms that the window was clear or cuts slices spread
   over the trace. Why a challenge and not a forced scan: on a trace with a clear window a
   scan is waste, and whether the window was clear is a judgment.
3. The harness takes all verdict lines of a step as a set (a tool can print one per server
   or per process); the agent chooses among them. Inside one line the longest match wins.
4. Both rules are in METHOD.md, section 3, as rules of use for every blueprint.

Open: blueprint 23 needs a rule for a baseline outside the fault at steady load. In this
run the only such stretch is after 03:17:00, and nothing tells the agent that. It stays
the weak blueprint.

Not done: 1 to 11 (older template, some tools without a verdict line), a rerun of the seven
that passed under the final harness, any run on Train Ticket, any second model.
