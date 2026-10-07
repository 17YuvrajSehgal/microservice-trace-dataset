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

## Sessions: runs + chats persist (demo)
- One JSON file per session under demo/data/sessions/ (gitignored, ~1 MB each): the run's
  transcript + verdict, and the chat's message thread + events. A finished run auto-saves;
  every answered question folds back into the file.
- Resume = the stored thread verbatim (agent_v2.Chat restore=snapshot). The thread IS the
  context, so nothing is re-derived; sessions are isolated by construction - one file, one
  thread, no cross-session reads. Claude-style continuation without context explosion.
- Boot logic: page refresh reattaches to an in-flight run, else restores the newest session
  (steps, charts, conversation).
- Verified across a server kill: 102 run steps + chat + chart restored; asked "in the chart
  you drew earlier, what was the peak?" - the resumed agent re-ran the computation (the model
  never sees PLOT numbers) and answered 7.255 cores at 08:15:38, measured not remembered.

## Session sidebar + the blank-chart bug
- The restored chart drew blank after refresh because the boot restore runs while the Agent
  tab is display:none - a hidden canvas has zero clientWidth, so the chart painted into
  nothing. Fix: drawPlot remembers every spec (PLOTSPEC) and skips zero-width canvases;
  redrawPlots() fires on tab open and window resize. The chat text was never affected.
- Sessions moved from a dropdown to a left sidebar on the Agent tab (Claude-style): newest
  first, active highlighted, question count per session. Two explicit starts: "Run the agent
  (new session)" and "New chat on this run" - the latter forks the stored run into a new
  session with an empty chat, because the run costs minutes and a chat is free.

## Connect code: one-point RCA + code analysis (demo chat)
- New agentic-rca/coderepo.py: jailed read-only access to a user-connected directory. Three
  tools (code_tree/code_grep/code_read) mirroring Claude Code's core trio. Jail = realpath
  must stay under root (symlinks cannot escape); denylist = ground_truth*/verification*/.env/
  keys unreadable even if the connected dir contains run data (upholds the "nothing the agent
  can reach may read ground_truth" rule); caps = grep-before-read context discipline.
- Chat gains code tools only when a repo is connected; prompt tells it to grep first, read the
  region, keep trace evidence primary, and quote file:line. code_root is stored in the session
  file, so the connection survives refresh/restart and a fork inherits it.
- Tested live on the real catalogue Go fork (C:\workplace\catalogue): asked where the sock-list
  SQL is built - it grepped, read service.go, and quoted service.go:55 (the SELECT), 101-103
  (per-row tag split), 109 (pagination AFTER the query). Every cited line verified exact in the
  file. Found a real issue: pagination applied post-query, so large listings fetch-and-discard.
- Bug fixed en route: the demo loaded .env only inside the live-run path, so a server that went
  straight to chat fell back to provider=claude (AttributeError: Anthropic has no .chat). Now
  loaded once at startup.

## UI redesign (demo)
- Decision: full visual overhaul in the EXISTING stack (custom CSS design system, no build
  step), not a React/Vue rewrite. Rationale: the demo's value is "one command, works offline,
  nothing to install", and all logic (polling, charts, chat, sessions, code-connect) is wired
  and tested; a framework rewrite risks that the day before the Ciena talk for visual gains CSS
  already delivers. Offered the React path if they want it later.
- New design system: soft shadows, 12px radii, pill nav tabs, logo monogram, rounded stat/
  table/step/chat cards, refined indigo accent, focus rings, custom scrollbars, sticky blurred
  header. Kept EVERY class/id hook the JS and the two canvas renderers depend on; only the
  token VALUES and component styling changed, plus a few added tokens (shadows, radius).
- Added a light/dark toggle (◐) that remembers the choice in localStorage and otherwise
  follows the OS; it redraws the canvases (which read CSS vars) on switch.
- Verified: all six tabs in both themes, zero console errors; chat charts still render and
  repaint after a theme toggle (sampled canvas pixels).

## Product pass (demo -> product)
- Removed the Results tab (nav + panel + loadResults/resultsTable/tone/sc/scw JS). It was a
  paper/slide artifact; the /api/results endpoint is left in place (unused, harmless).
- Removed the "55/60 found the right component" header stat and the explanatory demo
  sub-headline; replaced with a product tagline. Agent intro rewritten to product tone
  (dropped "the study calls" / agent_v2.diagnose framing).
- Native folder picker: /api/code/browse opens the OS directory dialog via a tkinter
  subprocess on the server (server == user's machine, so it returns a real absolute path).
  UI now has Browse… / Connect / Disconnect(✕) with a green connected state, instead of
  paste-only. Subprocess keeps Tk off the request thread.
