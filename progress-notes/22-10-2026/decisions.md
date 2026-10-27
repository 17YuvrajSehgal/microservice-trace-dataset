# 22-10-2026

## Matched-blueprint evaluation harness, in Blueprint/eval
- User wants everything we use to reside in Blueprint/. Built a self-contained eval that drives
  Blueprint/agent + Blueprint/latency and scores detection - no dependency on agentic-rca or
  blueprints/lib (the old q2 harness scored the OLD agent's ranked_candidates, which agent_v2
  does not produce, so a verbatim copy would have been half-dead).
- Blueprint/eval/: eval_matrix.py (driver, parallel, resumable, scoreboard, budget cap),
  eval_one.py (diagnose+score one run), score.py (detection scorer for BOTH ground-truth shapes
  - microservice fault.target_service/scope, and agentic cpu_max/mem_limit caps incl. control
  vs fault), datasets.py (problem->blueprint, discover runs with an index), nsmap.py (copied).
- "detected": microservice = right fault AND right component (name or pid_ns->container via
  nsmap); agentic = right fault type (cap is on the whole cgroup, no victim service); control =
  agent says normal.
- PROVEN end to end on svc_cpu_cap_aggressive_steady_r1 (real ground truth): verdict "java in
  pid_ns 4026532538 / cpu_throttling", scored detected=True, where=container, window IoU 0.975.
  Cost $0.21 (1.98M in + 25k out at research defaults). The same Sock Shop trace that gave
  "unknown/other" before now lands correctly - the accumulated fixes (WSL babeltrace, date
  self-heal, sched_budget 256 fix) paid off.

## Launch readiness for the full 250-run matched eval
- Harness: READY.
- Blocker: each run needs its index (<run_id>.tsv.gz) co-located (by run_id) with its
  ground-truth dir. Today only the svc_cpu_cap sample lines up locally.
  - Microservice 80 runs: traces on Trillium -> build index-v2 there and run eval on Trillium
    (or pull indexes).
  - Agentic 170 runs: kernel traces are Zenodo-only (2.6 GB) -> download + build indexes with
    run_ids matching the meta/ dirs (NOT the demo's ext_* ids).
- Cost confirmed by the real run: ~$0.21/run research-default -> ~$52 for 250; ~half with the
  demo step cap. Fund $60 (matched) / $200 (full specificity matrix).

## "How it works" page in the demo (for the Ciena walkthrough)
- Added a first tab (now the default landing page) that explains the system before anyone sees
  it run: the pipeline (raw trace -> index -> agent+blueprint -> verdict), why the index exists
  (babeltrace2 cannot seek: 1 s at depth 3 s costs 9.6 s, at 213 s costs 133 s -> decode once),
  what the index holds (100 ms buckets; pid_ns = container identity; value_sum because a count
  is not a quantity - the guilty workload ranked 8th by count, 1st by CPU time), the 10 tools,
  what a blueprint is (a folder: method text + its own scripts, both injected), the agent's four
  stages with their real limits (4 subtasks / 18 turns / 2 rounds / synthesiser has no tools),
  the four stopping conditions, and the 7-step narrowing workflow.
- Ends with a real verdict + evidence, and the honest scoreboard (mem 25/44, cpu 4/29, controls
  10/11) with the caveat that the low CPU number is most likely "cap set but did not bite".
- Every number on the page was verified against the code/results, not written from memory.
- Trace is no longer the default tab; verified its chart still paints on switch (the existing
  tab-switch redraw handles the zero-width-canvas case). No console errors, light and dark.

## "How it works" moved out of the demo into its own deck
- The explanation now lives in presentation/how-it-works.html (15 slides, standalone, offline)
  so it can be presented one idea at a time, then hand off to the live demo.
- Removed the demo's "How it works" tab, its panel and its now-dead CSS; Trace is the default
  tab again. Verified: five tabs, Trace chart paints on load, no console errors on any tab.

## Blueprints tab: render the markdown properly
- The viewer showed raw markdown in a monospace block, so the blueprints' 1,838 table lines,
  124 code fences and 64 headings were unreadable - the worst case for the tab that is supposed
  to prove a blueprint is a real engineering document.
- Wrote a small markdown renderer in the demo (no library, no network - it stays offline):
  headings, GFM pipe tables with alignment, fenced code, bullet/numbered lists, blockquotes,
  rules, bold, inline code. Code spans are pulled out behind a control-char placeholder before
  styling, so a plain number in prose can never be mistaken for one.
- Viewer is now a document pane: title from the H1, chips for the blueprint name, size and each
  of its tools/ scripts, a section outline built from the H2s (click to jump, active highlighted),
  and a Raw toggle - because "these are the exact files handed to the agent" should be checkable.
- Verified on svc_cpu_cap: 9 tables, 21 headings, 18 code blocks rendered, no raw markdown
  leaking, outline jump works, Raw toggles, switching blueprints works. No console errors,
  light and dark.

## Full pre-run analysis (user asked: analyze before running), and what it changed
Analyzed 4 full transcripts (3 cpu post-CRLF-fix + 1 memory). Findings -> fixes:

ARCHITECTURE (workers/tokens)
- Fan-out works (4 workers fire) but cost is skewed: the "inspect mechanisms" worker burns
  21-59% of input alone; the reviewer's round-2 worker cost 19-51% for 2-5 findings (on one run
  it cost MORE than all of round 1). Kept the architecture; bounded cost via ABL_WORKER_STEPS=12
  + ABL_THREAD_BUDGET=90000 in the eval launcher (demo-measured safe).
- Every worker re-ran the same orientation (ctf_timespan x4-5/run) and slice tools got guessed
  dates. FIX: diagnose() computes ctf_timespan once and injects it into every worker prompt
  (trace metadata, not fault info - fair).
- blueprint_tool usage was 8/2/0 calls across three runs - worker whim, because the PLANNER
  never sees the blueprint and its subtasks are generic. FIX: when a blueprint with tools is
  given, n_plan deterministically dedicates one worker to "execute the blueprint procedure
  start-to-finish incl. its deciding check"; other subtasks keep their breadth.

GROUND TRUTH (scoring fairness, pro-agent direction too)
- cpu.stat deltas prove EVERY capped run throttled (cap100: 12-29 episodes, cap50: 57-106,
  cap25: 134-219; nocap: 0). So misses are real misses; denominator stands.

TOOLS
- ctf_timespan had LOST its index-first guard (old "no CTF" error returned on agentic layout);
  re-applied. Verified: timespan + timeline read the index.
- extract_slice date self-heal upgraded: it fixed malformed dates but passed through
  valid-but-WRONG ones (agent guessed 2026-01-01 -> empty slice read as "no data"). Now always
  resolves the trace's own date and overrides a mismatch with a note.

BLUEPRINT ROBUSTNESS
- cpu blueprint's Step-5 gate ("waits jump -> Step 6") misses MILD caps: cap100 runs throttle
  only 12-29 times so the wait table barely moves; on t2_cap100_r1 the agent ran sched_budget
  and stopped before cpu_ceiling (the deciding check). Added an explicit mild-cap path: small
  waits + a candidate => run cpu_ceiling anyway (one call) before reporting "no victim".

BLUEPRINT FAIRNESS (leaks removed - previous numbers were inflated)
- 4_svc_mem_cap Appendix named `ttmem` (the eval victim), the exact 768M cap and exact counts
  (9,224) - the demo verdict had matched these verbatim. Anonymized to the noisy_neighbor
  Appendix-B style (rough magnitudes, no names); intro example 768M -> 512M.
- 3_slow_db worked example named "catalogue + MySQL, 500ms" = the Sock Shop answer. Renamed to
  "a service + its SQL database, several hundred ms"; numbers kept for scale.
- 5_svc_net dropped "a Java service" (narrows carts/ts-basic); magnitudes kept.
- noisy_neighbor was already clean (its Appendix B is the model the others now follow).

## 2026-10-27: svc_mem_cap is NOT evaluable on the microservice dataset (trace lacks the signal)
Switched to by-hand, evidence-based judging (JUDGING.md) at the user's request - score.py's
keyword grading mis-scored both ways and risks falsified numbers in a paper. First finding:

The Sock Shop / Train Ticket v2 LTTng profile has **425 event types: 377 syscall, 14 sched, 13
block, 10 net, 5 irq, 3 skb, 1 power - ZERO memory events** (no mm_vmscan / memcg_reclaim / oom /
kswapd). The agentic profile HAD mm_vmscan_memcg_reclaim_begin/end, which is why agentic
svc_mem_cap scored 44/44 bite-aligned. The microservice svc_mem_cap blueprint detects a cap by
its memcg-reclaim burst - a signal physically absent from these traces.

=> svc_mem_cap microservice 0/7 (SS), 0/6 (TT) is a DATA-COLLECTION GAP, not an agent or
blueprint miss. The agent behaved correctly: it ran the slices, found no reclaim, and DECLINED to
assert a memory cap ("not confirmed... observed workload interruption rather than a proven
resource fault"). That is the integrity-correct verdict given the trace.

Action: svc_mem_cap is EXCLUDED from the microservice detection scoreboard (marked "not
evaluable - trace lacks memcg tracepoints"), not counted as a miss. Re-collecting Sock Shop/TT
with the memory tracepoints enabled is future work. The other four families use events that ARE
present (cpu/noisy=sched, slow_db=syscall read/write, svc_net=net/skb), so they remain evaluable.
