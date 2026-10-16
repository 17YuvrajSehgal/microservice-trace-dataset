# 16-10-2026 — decisions

(The first half of today's work — Blueprint/ workspace, agent copy + trim,
blueprint tool wiring, OpenRouter check — is logged at the end of
`../15-10-2026/decisions.md` under "(16-10)" headers; this file continues
from there.)

## First blueprint-guided agent run: correct verdict, blueprint tools unused

`agent_v2` + svc_cpu_cap blueprint on `t3_implement_cap25_r1`
(gpt-6-luna via OpenRouter, 560 s, 1.41M in / 25.5k out tokens):

- **Verdict correct and precise**: `python3 in pid_ns 4026531836`,
  `cpu_throttling`, "~25 ms per 100 ms = 0.20–0.24 cores" (true cap 0.25),
  window = the python3 phase, confidence 0.68 with honest caveats.
- To make the index tools work locally, built the ctf count index FROM the
  decoded trace.txt.gz (byte-compatible with build_ctf_index.py; 0.7 s,
  157 KB) -> `Blueprint/agent/ctf-index/`. Also fixed ctf_timespan to
  auto-discover the trace layout (trace/kernel vs kernel/kernel).
- **Headline workflow finding: 0 of 69 tool calls used blueprint_tool.**
  run_python 28, ctf_timeline 23, ctf_lines 6, timespan 5, proclife 4,
  query_ctf 3. The planner's subtasks mirrored the blueprint's METHOD, but
  workers executed it with generic tools + self-written pandas. Blueprint
  worked as knowledge, not as toolkit. The reviewer even flagged the gap
  sched_budget.py would have filled (runnable-wait comparison).
- Full step-by-step logs for the user's analysis:
  `Blueprint/agent/transcripts/v2/t3_implement_cap25_r1.json` (+console.log).

## Blueprint-only mode added (user ask: test the blueprint toolkit alone)

`diagnose(..., blueprint_only=True)` / `--blueprint-only`: toolset becomes
[blueprint_tool, note_finding] — no index tools, no run_python. Design:

- **Own prompt head** (_BP_HEAD/_BP_WORKER/_BP_SYNTH): the stock prompts
  describe seven tools and DEMAND run_python subtasks; v2's history shows
  the model believes the prompt over the schema, so advertising tools that
  are not offered would poison the test.
- **Planner skipped** (fixed single subtask, no API call): a blueprint is a
  sequential procedure; parallel subtasks would each need the previous
  step's output. One investigator walks the steps in order.
- Index tools stay in the codebase untouched — this is a per-run mode, so
  flipping back is just dropping the flag. The comparison (same run, same
  model): full-toolkit transcript vs `.bponly.json` transcript.

Launched on the same run -> `transcripts/v2/t3_implement_cap25_r1.bponly.*`.

## A/B result: blueprint tools WORK, blueprint-only is NOT sufficient

Same run, same model, side by side:

| | full toolkit | blueprint-only |
|---|---|---|
| verdict | cpu_throttling, python3 in pid_ns, 0.20-0.24 cores | cpu_saturation, "host", cap "unconfirmed" |
| correct? | YES (true: 0.25-core cgroup cap) | NO (right evidence, wrong attribution) |
| confidence | 0.68 | 0.57 |
| tool calls | 69 (0 blueprint) | 31 (ALL blueprint: budget 9, slice 7, rhythm 5, idx 5, wake 4, victim 1; 0 errors) |
| tokens | 1.41M in / 25.5k out | 0.50M in / 16.7k out |
| wall | 560 s | 569 s |

The toolkit itself executed flawlessly (31/31 calls clean, incl. the NTFS
colon fix). The miss is in the BLUEPRINT'S DECISION RULES on this workload:

1. **Two victims = "host overload" misfire.** The cap covers the agent's
   whole cgroup, so TWO processes (8192 python3 + 8126) showed long waits;
   the blueprint's Step-4 rule "many processes suffer -> whole machine short
   of CPU" pushed the agent to `host`. The blueprint assumes a cap hits ONE
   process; a cgroup cap hits a process TREE.
2. **Bursty victim breaks the rhythm check.** rhythm.py scores 0.29-0.40
   (threshold 0.5): the agent workload idles between LLM calls, so the
   quota beat is weak in wall-clock buckets — exactly the whole-run-
   averaging gap flagged in EVALUATION-on-agentic-runs.md.
3. **No baseline window** (the cap spans the whole trace) — Step 4 wants a
   normal stretch; the agent correctly noted it had none and lost
   confidence.

What the full-toolkit run had that decided it: run_python over
sched_stat_runtime (the index value_sum) computed the 25 ms/100 ms runtime
CEILING — the quantitative quota signature the blueprint only
approximates via `run` + rhythm.

DECISION: keep the index tools (the ceiling computation is the decisive
discriminator). Blueprint v2 should gain (a) a group-the-victims rule
(same cgroup/parent -> one capped group, not host overload) and (b) a
per-period on-CPU ceiling script (the blueprint's own Step-6 "Proposed"
item — this A/B is the evidence it is needed).

## Both blueprint fixes implemented (evidence-first)

(b) **cpu_ceiling.py** — ninth blueprint tool: the victim's on-CPU ms per
period from sched_switch; a flat ceiling below the period = the quota.
VALIDATED before writing the text, on runs with known limits:
- cap25: median/p90 25.0 ms, max 25.1, 82% flat -> 0.25 cores (true 0.25)
- cap50: 50.1 ms, 87% flat -> 0.50 cores (true 0.5)
- nocap: pegs at the full 100 ms -> correctly reads "no cap" (and the tool
  says a full-period ceiling on one thread cannot be told from a 1-core
  cap — honest ambiguity, stated in its output and in the blueprint).

(a) **Group-the-victims rule** in the text: §1.3 cap row ("one container =
possibly SEVERAL processes; a cgroup limit covers the tree"), overload row
(requires sufferers in DIFFERENT containers + no idle CPUs), and Step 4's
"many processes suffer" bullet now routes through victim_info namespaces +
wake_graph parentage: same container -> ONE victim group, continue.

Blueprint text integration: Step 6 retitled "...then measure the ceiling";
"no beat" no longer stops (bursty victims show weak beats — exactly what
sank the bp-only run) but falls through to 6b; Step 8 estimates from the
ceiling and warns that whole-slice run averages dilute for bursty victims;
Part 5 limits updated (rhythm thresholds one-case, ceiling three-run
validated); counts 8->9 everywhere. agent blueprint_tool picks the new
script up automatically (dynamic dir listing - verified).

## Re-run with blueprint v2: the bp-only arm now gets it RIGHT

Three arms, same run (t3_implement_cap25_r1), same model:

| | full toolkit | bp-only, blueprint v1 | bp-only, blueprint v2 |
|---|---|---|---|
| verdict | cpu_throttling, python3 pid_ns, 0.20-0.24 cores | cpu_saturation "host" | **cpu_throttling, python3 PID 8192 in pid_ns, 0.25 cores** |
| correct | yes | NO | **yes** |
| confidence | 0.68 | 0.57 | 0.58 |
| tool calls | 69 | 31 | 38 (1 error) |
| tokens in/out | 1.41M / 25.5k | 0.50M / 16.7k | **0.49M / 13.0k** |
| wall | 560 s | 569 s | **375 s** |

The agent ran cpu_ceiling.py 4x and quoted it verbatim in the verdict
("25.0 ms per 100 ms, 79% flat -> ~0.25-core cap"); the grouping rule kept
PID 8126's parallel waits from flipping it to "host". Honest hedging
remains ("suggestive, not confirmed: no cgroup throttle counters in a
kernel trace") - correct epistemics for kernel-only evidence.

HEADLINE: the blueprint + its own nine scripts now matches the full
index-toolkit verdict at ~1/3 the input tokens and 2/3 the wall time. And
the loop that got here is itself the result: blueprint -> agent run ->
failure analysis -> two targeted fixes -> correct verdict. Transcripts:
.json (full), .bponly.json (v1, wrong), .bponly2.json (v2, right).
