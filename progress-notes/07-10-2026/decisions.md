# 07-10-2026

## Demo switched to OpenRouter
- `.env` now `RCA_PROVIDER=openrouter`, model `openai/gpt-6-luna` (the professor's shared key).
- Verified with one real diagnose run through the demo: 161 s, 46 tool calls, correct verdict
  (stress-ng-cpu, right container).
- `live_ready()` now knows openrouter's key variable (both spellings).

## Ask-the-agent chat (demo + agent_v2.Chat)
- Why a single tool loop, not the plan/work/review graph: a question IS one worker's worth of
  work; the graph exists to decompose an investigation. Chat reuses `_call`/`_exec_tool`/
  `_trim_thread`, so caps, auditing and the sandbox are identical to a run.
- Seeded with the finished run's verdict + findings + raw computed output, so "why did you say
  X" answers instantly; fresh questions trigger real tool calls.
- Guard disabled in chat (`leakguard.Guard(enabled=False)`): the verdict shown to the human is
  already unmasked, so chat must speak real names or questions would not match.
- `tools=[]` is rejected by some providers; `_call` now omits the key when empty.
- Tested live: a question the run never computed made it call ctf_timespan then query_ctf, and
  it correctly refused the un-covered part of the window (trace starts 73 s before the fault).

## Chat upgrades: charts, visible status, harder questions
- Charts WITHOUT image files: the sandbox forbids writes by design, so the agent prints one
  `PLOT {json}` line from run_python and the demo renders it on a canvas. codetool hoists the
  line into `result.plot` whole (OUT_CAP would cut a 600-point series) and replaces it in
  stdout with "[chart rendered to the operator]" so the model does not re-read 600 numbers.
- Prompt now says: if the asked-for quantity is not in the trace, chart the nearest thing that
  IS recorded and say exactly what the chart shows. Tested: "latency graph" now produces a
  scheduler-rate chart with a one-sentence caveat, instead of a refusal.
- MAX_CHAT_STEPS 10 -> 14 for multi-tool questions.
- Chat status line: thinking / acting on the model's reply / ran X, with elapsed seconds -
  users could not tell whether anything was running.
- run_python calls now render as code steps in chat (steps_from leaves them to the end-of-run
  code_snippets event, which chat never emits).
