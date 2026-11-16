# 16 Nov 2026 - decisions

## Logs join the Blueprint agent, by porting INQUEST's log layer (not the whole agent)

**Decision.** `Blueprint/agent/logtool.py` is a port of INQUEST's `agent/logs.py`
(`C:\workplace\JiraAndLogs\industry-c7` @ b161ae8). The INQUEST agent itself was not merged.

**Why not the whole agent.** INQUEST ranks the files a fix changed, from Jira text with pasted
logs. Our agent names fault type, service and window from runtime data. Its paper also has no
with/without-logs test, and its results are flat across report types (stack trace 66.5, logs
only 66.6, prose 70.8), so "logs help" is not something we can borrow as a claim.

**What was kept as measured there.** Template masking; "earliest error ranks first"; generic
timeout/retry lines halved; matching a log line to the source statement by its constant text.

**What changed for runtime logs.**
- Docker timestamps give every template a first-seen time and per-10 s counts. A template that
  first appears more than 60 s after the container's first line is flagged `new`.
- OTel span-relay lines (`LoggingSpanExporter`, `[scopeInfo:`) are counted and skipped. On the
  sample run they are 321,836 of carts' lines; only 30 are application logs.
- go-kit `caller=file.go:N` is matched to source by file and line, before any text search.
- Node `console.log` and single-quoted strings are indexed (INQUEST knew Java/C++ only).
- Source lines over 500 chars are skipped: a minified bundle hung the string regex for minutes.

**Off by default.** `ABL_LOGS=1` (or `diagnose(logs=True)`) adds log_overview / log_events /
log_search. `ABL_CODE_ROOT=<dir>` adds code_tree/grep/read + log_to_code. With both unset the
worker toolset is identical to before, so every measured kernel-only condition is unchanged.
The transcript meta records `kernel_only: False` when logs are on.

**Prompt rule (why).** Logs say when a symptom began and who complained; the kernel says why.
The service that logs "timeout" is usually the victim. This is INQUEST's "printed vs fixed
file" finding, restated for services.

**Checked without an LLM.** Self-check passes. On `svc_cpu_cap_aggressive_steady_r1`: index of
250 MB of logs in 7.5 s; `log_events` shows the orders/front-end timeout errors starting
15:20:01 as `new`; `log_to_code` resolves catalogue `caller=logging.go:56` and two front-end
console lines to the right file and line.

**Known weak points.**
- The generic mask is aggressive (`Order <v> <v> <v>`); two templates per JSON line in front-end.
- A baseline error present from the start (406 payment declined, 1,449 lines) still takes the
  "first error" bonus. The `new` flag and the prompt compensate; a pre/post-window diff would
  be better.
- `function_at` is "nearest function header above", no parser.

**Not ported, and why.** `lc_trace`, `turn_budget`, `trim_history`: agent_v2 already has a
transcript, step caps and thread trimming. Incident memory (`lc_store`): 303 runs is a small
memory and its `recall_incidents` tool has the firewall off by default in the lc/wf arms
(`tools.py:210`) - fix that in INQUEST first.

## Next
1. Pilot arm (c) kernel+logs+code on 2-3 `code_*` runs (needs the bug-injected service source
   on Trillium as the code root), report tokens, then decide on the full 25.
2. Scorer: function-level Acc@K against the anchors in `faults/code-defects/inject_defects.py`.

## First agent test of blueprints 11-16 on the OpenAI API (gpt-6-luna), and what it changed

**Setup.** Clusters had no GPU time, so the matched arm ran on the OpenAI API: 21 cells, Sock
Shop data only (partner traces never go to an API; `one_cell.sh` refuses those paths).
10.0 M input tokens, 118 K output. Results on Trillium `bp_eval/openai/`.

**Result.** 13 fork_storm, 15 dependency_outage, 16 anomaly_disk: 3/3 fault runs and a clean
normal run each. 14 deadlock: 3/3, but a false alarm on a normal run and the wrong window.
12 fd_exhaustion: 3/3 fault. 11 priority_inversion r1: said normal (2.0 M tokens, 48 min).

**Blueprint 14, two fixes (tool-only re-check: 5/5 fire, 15/15 other faults quiet, 5/5 normal
quiet at the anchor AND at trace start).**
- False alarm: the agent cut its slice at trace start, where the `docker` CLI starts and parks
  9-12 Go runtime threads in one burst (10/0/0 per third). This happens at the start of all 5
  normal runs, so the old tool was wrong there 5/5; the 11-11 validation never cut that slice.
  New rule: the new hung threads must be born in 2+ bursts (births > 1 s apart). I first planned
  "exclude host-namespace daemons"; rejected, because a deadlock in a host process is real and
  the burst shape is what the data actually separates. Cost: a one-time deadlock gets a NOTE.
- Window: the verdict line now prints `first hung at`, and Step 5 says to use it. Before, the
  agent reported the slice it read (IoU 0.01).

**Scorer, three bugs (all scorer side; no agent re-run needed).**
- Normal runs have no `ground_truth.json`; they fell into the fault path and every correct
  "normal" scored as a miss. Now a control: correct = said normal.
- `nsmap.container_cpu` used last-minus-first of the cgroup counter. front-end crash-loops under
  fd_exhaustion (restart count 43 -> 54), the counter resets, the container vanished from the
  map. Now sums the steps and treats a drop as a restart.
- Even then CPU matching picked the wrong namespace for front-end. Added a second check: the
  busiest process name in the agent's namespace must run in the target container only
  (`meta/top_*.txt`). `node` runs only in front-end, so fd r3 now scores `container`.
  r4 and r5 name the same `node` namespace but have no index (the login-node build hit the CPU
  limit), so the scorer cannot confirm them yet.
- Also noticed: for host-scope families (13, 14, 16, 11) `where_ok` is true by rule; the scorer
  does not check the container the agent named. "3/3 location" there is from reading verdicts.

**Blueprint 11 is not reliable on the priority_inversion runs (tool only, 30 s slices, r1-r3).**
- Verdicts: r1 LOCK CONTENTION, r2 and r3 PRIORITY INVERSION at 32% and 45% runnable share
  (bar 30%). All three are on the Python interpreter lock (GIL), not the application lock.
- Before the injection the tool says LOCK CONTENTION on 3/3 runs: the load generator's
  python3 (153 threads on its own GIL). So the contention branch fires on normal traffic.
- Why the textbook picture never shows: the recipe is CPython. The nice 19 holder spins under
  the application lock but needs the GIL to spin; the six nice 0 threads keep the GIL. So the
  holder is asleep in futex on a second lock, not runnable. The kernel shows a chain: waiter
  (nice -5) -> application lock -> holder (nice 19) -> GIL -> middle threads (nice 0).
- What is stable on 3/3 and absent before the injection: the nice -5 thread waits 445-730 ms
  on the application lock, released by the nice 19 thread that slept 92-97% of that wait.
- So the agent's "normal" on r1 followed the blueprint correctly; the blueprint rule is wrong
  for this recipe. Not fixed yet (needs a rule for the chained case + a GIL/base-rate guard).
