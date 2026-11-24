# How a blueprint is built and used (the method)

Status: **draft for discussion, 20-11-2026.** Sections 1 to 3 describe what we already did
for blueprints 12 to 24, written down as fixed rules. Section 4 says where the existing
blueprints do not meet these rules yet. Section 5 lists what is still missing before we can
claim the method in a paper. The pass bars in Step 4 and Step 5 are proposals, not yet agreed.
The rule in Step 7 (the agent check changes the text only, never the tool) is also new: it
was not checked against how blueprint 1 was built.

## 1. What a blueprint is

A blueprint is a tested method that confirms or rejects **one** root cause from a kernel
trace. It has six parts, and all six are required.

| Part | What it holds | Where it lives |
|---|---|---|
| Root cause | One sentence: what is wrong, in which kind of process | header table of `README_v1.md` |
| Mechanism | How this fault changes what the kernel does, and which events record it | Part 1 |
| Signal | The measured quantity, and its value with the fault, without it, and for the look-alike faults | Part 1 table |
| Decision rule | A tool that reads a trace slice and prints one `VERDICT:` line. Every bar in the rule is a named constant | `tools/` |
| Procedure | The fixed steps a person or an agent follows (Section 3) | Part 3 |
| Evidence and limits | Found and false-alarm counts on all labelled runs, the history of the rule, and what the blueprint cannot see | Part 4 and `RESULTS.md` |

The text is the last thing made. Each number in it comes from a tool output saved in a sweep.

## 2. How a blueprint is built (seven steps)

Each step has an output that is kept, and a rule for going on.

**Step 1. State the fault and the mechanism.** Before reading any trace, write down what the
fault does to the system and which kernel events should record it. Source: how the kernel
works (scheduler, memory, block layer, TCP), not the trace.
Output: the mechanism paragraph and the list of events.
Go on if: the events are in the trace profile. If not, the family goes to "Not built yet" in
`FAMILIES.md` with the reason.

**Step 2. Contrast.** In ONE labelled run, cut a slice inside the fault window and a slice
before it, at the same load. Measure the quantity from Step 1 in both.
Output: fault value and baseline value.
Go on if: the two differ clearly. If they do not, stop and record the measurement
(`code_lock_across_io` stopped here).

**Step 3. Decision rule.** Write the tool. It prints a table and one `VERDICT:` line. The
verdict names the process (comm, pid, pid namespace) and the numbers. Bars are constants at
the top of the file.
Output: the tool.

**Step 4. Own-family check.** Run the tool, unchanged, on every run of the family.
Output: one line per run in `RESULTS.md`.
Pass bar (proposal): every run is found, or each miss is explained by the run itself (for
example a crash loop in 2 of 5 `dns_delay` runs).

**Step 5. Cross-family sweep.** Run the same tool on every other labelled run of both
applications, including the `normal` runs.
Output: the false-alarm count and the list of runs that fired.
Every false alarm is read and put in one of two classes:

- **The rule is too loose.** Find the quantity that separates the two cases, add it to the
  rule, and run Steps 4 and 5 again. Each added rule gets a row in the rule history: the
  rule, runs found, false alarms (example: `24_code_unbounded_cache/RESULTS.md`).
- **The other fault really produces this signal.** The rule stays. The blueprint names the
  look-alike and the check that tells them apart, or says that the trace cannot tell them
  apart (`dependency_outage` and `queue_backlog`).

Pass bar (proposal): 0 false alarms, or every false alarm is in the second class and written
in the blueprint.

**Step 6. Write the text** in the fixed template: header table, "When to use this", honest
status, Part 1 background, Part 2 tools, Part 3 procedure with a verdict table, Part 4
measured and limits.

**Step 7. Agent check.** An LLM agent that has only the blueprint and its tools runs it on
labelled runs. A wrong answer is traced to a step of the text. The text changes; the tool and
its bars do not change at this step.
Output: an evaluation file with the agent's answers per run.

Rules that hold for all steps:

- A rule changes only because of a run that is named in the rule history.
- A blueprint never claims more than its sweeps show. Settings not collected and runtimes
  not tested are listed in Part 4.
- Tools are deterministic. The same slice gives the same verdict line.

## 3. How a blueprint is used (four steps)

Every blueprint's Part 3 follows the same order.

1. **Orient.** Read the trace index: date, span, health, data written per interval. Pick the
   suspect time.
2. **Slice.** Cut 10 to 30 s at that time with the events the blueprint names. Cut a
   baseline slice if the rule compares.
3. **Decide.** Run the decisive tool. Read the `VERDICT:` line against the verdict table. If
   the blueprint names a look-alike, run its check.
4. **Report.** Fault type, the process on the verdict line, and the verdict line word for
   word as evidence. State what the trace cannot tell (for example which line of code).

Two rules hold for every blueprint. Both come from agent runs on labelled traces
(20-11-2026), where the slice time was not taken from the label:

- **The rate table is a hint, not a test.** It shows the volume of trace data. Many faults
  do not change it (4 of 11 in the first agent runs). No clear window is not a reason to
  stop.
- **A "no" holds only for the slice it was measured on.** Three of those four runs cut the
  slice 1 to 20 s after the fault had ended, read "nothing here", and rejected a fault that
  was in the trace. A rejection needs slices spread over the trace, unless the window was
  clear. Our tool-only sweeps never met this, because they took the time from the label.

- **Find the time with the fault's own check** (24-11-2026). The harness has a scan: it
  cuts slices end to end over the whole trace, runs the step's check on each, and returns
  the verdict per time. A check that needs a baseline is run against the first and the last
  slice of the trace, which the agent does not choose. Two things were learned from it:
  a signal can come in bursts (`error_storm`: about every 30 s, so slices with gaps between
  them missed it), and a baseline chosen by hand was inside the fault in two runs.

### How the agent harness applies this (`Blueprint/agent/bp_graph.py`)

A blueprint is also a structured file, `blueprint.yaml`, and `BLUEPRINT.md` is generated
from it (`bp_render.py`), so the text and the steps the agent runs have one source.
`bp_check.py` checks a file: step links, scripts, that every verdict line in the file is
printed by a tool, and that every number in the text is in the README, the results file or
a tool.

The harness gives the agent one step at a time, with the step's guidance and a short case
file. It does not paste the blueprint into the prompt. The split:

| The harness (code) | The agent (model) |
|---|---|
| one step at a time; only that step's tool output is in context | which commands, arguments and slices |
| reads the tool's verdict lines by text match and copies the chosen one into the evidence | which outcome fits; `other` when none does |
| asks for a reason when the outcome goes against the verdict lines | may go against them, with a reason |
| sends a rejection that rests on one slice back once | whether the time was certain or more slices are needed |
| the verdict is a rule over the outcomes reached | may dispute the verdict in the report, with a reason |
| logs every leave from the guidance | may jump, skip a step or stop early |

## 4. Where the existing blueprints stand (scan of 20-11-2026)

| Blueprints | State |
|---|---|
| 12 to 24 (13 folders) | All six parts, template, verdict table, `RESULTS.md` |
| 6, 11 | Verdict table and sweeps done; 6 has no `RESULTS.md`, 11 has no "When to use this" |
| 2, 4 | Verdict line and `RESULTS.md`; older template (no "When to use this", no honest status) |
| 1, 3, 5, 7 | Oldest. The tools print tables but no `VERDICT:` line, no `RESULTS.md`. Blueprint 1 has an agent evaluation instead |
| 0, 8, 9, 10 | Calibrated on partner traces. Evidence is off git, so Steps 4 and 5 cannot be shown publicly |

A written rule history exists for 15 and 24 only. For the others the changes are in
`progress-notes/*/decisions.md` and in git, not in the folder.

## 5. What is missing before this is a claim

1. **Held-out testing.** Today the bars are set on the same runs that are reported. Needed:
   set the bars on part of the runs and report on the rest. Strongest form: set them on one
   application and test, unchanged, on the other. We have this for some blueprints (11, 12,
   13, 14 and 16 were checked on Train Ticket with tools unchanged) but it was not planned
   as a split.
2. **Agreed pass bars** for Steps 4 and 5, fixed before the next blueprint is built.
3. **Repeatability.** A second builder (a person, or another model) follows Section 2 for
   one family without seeing our tool. We compare the signal and the rule they reach.
4. **Ablation of the parts.** The agent with no blueprint, with tools only, with text only,
   and with the full blueprint, on the same runs.
5. **Refit** blueprints 1 to 7 to the template, and put a rule history in every folder.
6. **Step 7** has been done for few blueprints. Most are tool-only.
