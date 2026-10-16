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
