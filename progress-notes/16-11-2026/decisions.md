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

## Blueprint 11 fix: chained inversion rule + per-waiter contention bar (tool only)

**Rule 1, chained inversion (checked first).** Two or more hand-off waits of >= 100 ms where the
releaser has a worse priority than the waiter, slept >= 50% of the wait, and for >= 50% of the
wait was itself in futex waits on other addresses released by threads with a better priority
than its own. Verdict text starts `PRIORITY INVERSION (chained)`.
**Why this and not a lower bar on the old rule:** the old rule reads "holder runnable but not
running". In a CPython program the holder is never runnable, it is asleep on the interpreter
lock. Lowering 30% would only make the marginal GIL verdict fire more often, also on healthy
programs. The chain is the real mechanism and the numbers are far from any bar (94-100%).

**Rule 2, contention bar per waiter.** "Held waits >= 5% of the slice" was a sum over waiters;
now it is the average per waiter. The sum let the 153-thread load generator through.

**Measured, 17 slices of 30 s, no API.**
| slices | result |
|---|---|
| priority_inversion r1-r3, inside | 3/3 PRIORITY INVERSION (chained): 730 / 514 / 451 ms, holder blocked 100 / 100 / 94%, 67-81 such waits, 43-45% of the slice |
| priority_inversion r1-r3, before | 3/3 NO LOCK PROBLEM (was 3/3 LOCK CONTENTION) |
| lock_contention r1-r3, inside | 3/3 LOCK CONTENTION, same numbers as before |
| lock_contention r1-r3, before | 3/3 NO LOCK PROBLEM |
| normal r1-r5 | 5/5 NO LOCK PROBLEM |

**Open.** (1) Not re-run on the five partner traces (they live on Nibi); their threads use many
priorities, so the chained rule must be checked there before the partner matrix is trusted
again. `futex_wait.py` is one file copied into 0, 8, 9, 10, 14 and select_d; all copies were
updated together. (2) The agent has not run the new blueprint 11 or 14 yet (API credits).
(3) fd r4/r5 still need their index (SLURM job).

## Pilot: kernel + logs + code, no blueprint, gpt-6-luna (2 cells, 1.56M tokens in / 17K out)

| run | verdict | truth | log calls | code calls | tokens in |
|---|---|---|---|---|---|
| code_lock_across_io r1 | normal | catalogue, lock held across the query | 0 | 0 | 364K |
| code_event_loop_block r1 | fd_exhaustion on edge-router | front-end, blocked event loop | 15 | 0 | 1.20M |

Both wrong. What it taught:
- **The planner does not know the new tools exist.** Its prompt is unchanged, so no subtask sends
  a worker to the logs or the code. On the lock run nobody opened a log. Same lesson as the
  blueprint tool (called 8, 2, 0 times until one worker was dedicated to it).
- **The agent blamed the service that complained.** edge-router logged EMFILE because front-end
  stopped answering; the prompt rule "the logger is usually the victim" was not enough.
- **Code tools were never called**, so log-to-code is untested with an LLM.
- **Lock run: the logs hold no new error at all.** The signal there is go-kit's `took=` latency,
  which templates mask.

Decisions:
- `new` is measured from the run's first log line, not the container's (edge-router's 458
  warnings were hidden because its first line ever was the first warning).
- The build tree cannot be the code root: it names every defect behind its gate.
  `Blueprint/eval/make_code_root.py` writes a single-bug tree instead.
- Next, before any more API spend: (1) a dedicated logs+code worker in the plan, as for
  blueprints; (2) `log_latency` from `took=`; (3) a code_* blueprint or at least vocabulary
  entries - today no fault label fits these families, so "right" is not even expressible.

Testbed limits: 5 defects in 2 functions (score needs function + mechanism); source for 2 of ~8
services only. Bonsai on the laptop loaded all layers on CPU again (6-11 tok/s): wiring smoke
only, it did call log_events / log_to_code / code_grep.

## Rerun after the three fixes (2 cells, 1.93M tokens in / 17K out; pilot total 3.5M in)

Changes: a dedicated logs(+code) worker in the plan; `log_latency` (go-kit `took=`); five
code-defect labels + `culprit_code` + scorer (`code`: function / file / miss).

| run | verdict | log calls | code calls | window IoU | tokens in |
|---|---|---|---|---|---|
| code_lock_across_io r1 | normal (0.88) | 9 | 3 | - | 903K |
| code_event_loop_block r1 | other, host-wide collapse (0.72) | 11 | 7 | 0.96 (was 0.57) | 1.03M |

- The tools are used now. On the event-loop run the agent timed the onset from the logs and
  wrote that edge-router's EMFILE came 55 s later, "a downstream symptom" - the earlier wrong
  verdict is gone. It still did not find front-end.
- **code_lock_across_io was the wrong run to pilot on.** Its verification says
  `no_metric_signature`, and the inventory already says three of the five code families
  (lock_across_io, n_plus_one, unbounded_cache) change nothing measurable: catalogue List p50
  is 0.93 ms before, during and after. "normal" is the right reading of the runtime evidence.
  Only `code_event_loop_block` and `code_serial_awaits` (10 runs) are a real testbed.
- Why front-end was missed: no check looks for "one thread of one container on a CPU without a
  break while its syscalls stop". That is a blueprint, not a prompt. And the code worker runs
  in parallel with the kernel workers, so it reads code before anyone knows which service to
  suspect; code reading belongs after localisation (the reviewer's second round).

Decision: no more API cells on code_* until (1) an event_loop_block blueprint is validated
tool-only on the 10 real runs + normals, as blueprints 13-16 were, and (2) the code step runs
after the suspect service is known.

Laptop: Bonsai cannot be tested right now - Windows lists only the Intel GPU (nvidia-smi fails,
llama.cpp "no CUDA-capable device"), so every layer loads on CPU whatever the context size.
