# 21-10-2026

## Demo: load ANY kernel trace from disk
- New feature: a "Load trace…" button (header) opens a native folder dialog, finds the CTF
  inside the chosen directory, builds the index, registers it as a run, and switches to it.
- find_ctf() locates the CTF at depth 0/1/2 (<dir>, <dir>/kernel, <dir>/kernel/kernel,
  <dir>/trace/kernel) by looking for metadata + channel0_*. Handles the agentic-runs layout
  (trace/kernel) and the Sock Shop layout (kernel/kernel).
- The decode runs in WSL (babeltrace2 is WSL-only here) via demo/_build_index.py, paths passed
  as bash positional args ($0..$3) - NOT interpolated into a -c string. The inline-code version
  failed with quoting errors; the helper-script + argv version is robust. build() is called with
  ctf_subdir='' so it decodes the CTF dir directly wherever it sits.
- External runs register dynamically: RUNS[rid]={blueprint:None, gt:None, external:True}; a
  junction makes <run_dir>/kernel/kernel point at the CTF so load_run and raw-decode fallbacks
  work. load_state guards gt=None; _live_worker runs with skill_given=False when there is no
  blueprint, so the agent still investigates a trace with no known fault.
- Verified end to end on agentic-runs/2_threads_vs_cores/runs/t4_w2_r2/trace: index built in
  <4 s (12k rows, 308 events, 2 containers, 7.2 s), appeared in the dropdown, became current,
  live agent ready, Trace chart + Verdict render, no console errors.
- Note: loading a new trace needs WSL (for babeltrace2). Pre-built runs do not.

## Bug: Discriminator showed the previous trace after a Load
- Loading a trace calls boot() directly, but boot() did not reset the discriminator's SEL
  window or its computed #dtab/#sum. So after loading, the suspect window kept the old trace's
  times (15:19:49) and the Discriminator tab showed the PREVIOUS trace's table (Sock Shop
  containers) because `if(!#dtab.innerHTML) runCheck()` skipped recompute on a non-empty table.
  The chart was correct (uses fresh SERIES), which made the mismatch obvious.
- Fix: reset all per-trace UI state at the TOP of boot() (SEL, #dtab, #sum, #i0/#i1, steps,
  verdict), so every entry - initial load, dropdown switch, and Load-trace - starts clean. The
  dropdown handler's own reset is now redundant but harmless.
- Verified: after loading a trace the window matches the new timeline and the discriminator
  rows are the new trace's namespaces.

## Operator picks the blueprint before an agent run
- Until the agent selects its own blueprint, the user chooses one explicitly. Added a
  "Blueprint for this run" dropdown in the Agent panel (populated from /api/blueprints, 16 +
  a "none - investigate with no blueprint" option), defaulting to the run's configured
  blueprint if it has one.
- live_start(blueprint) carries the choice: a name forces that skill, '' runs with none, None
  keeps the run's default. _live_worker honours it; the START card already shows the blueprint,
  so the user confirms which one was used.
- Verified: ran svc_cpu_cap (default service-cpu-throttle) but picked deadlock-lock-order in
  the dropdown; the START card showed blueprint=deadlock-lock-order, proving the override.

## Wrong-trace trap: loaded traces now persist + the Agent panel names its trace
- A memory_cap verdict looked wrong (window 02:48, "no reclaim seen") - it had actually run on
  the THREADS trace (ext_t4_w2_r2 @ 02:48), not the memory trace (ext_t6a_high_768_r1 @ 04:31).
  The memory trace's 9,311 mm_vmscan_memcg_reclaim events were never touched.
- Root cause: external (loaded) traces were registered in the in-memory RUNS only, so a server
  restart dropped them from the dropdown even though the index files persisted. The memory trace
  vanished and the run landed on the threads trace.
- Fix 1: discover_external_runs() at startup re-registers every demo/data/ext_*.tsv.gz, so a
  loaded trace survives restarts.
- Fix 2: the Agent panel shows "Trace: <run_id>" above the blueprint picker, and the running
  note names the run id, so you cannot run on the wrong trace without seeing it.
- Cleaned a stray ext_trace (bad run-id from an early load, duplicate of t4_w2_r2).
- Confirms the earlier analysis: service-memory-cap is the wrong lens for these agentic memory
  runs (it keys on IRQ/disk proxy, not mm_vmscan reclaim). A real memory blueprint would key on
  mm_vmscan_memcg_reclaim_begin/end, which these runs DO carry.

## Demo switched to the Blueprint/ agent + blueprints
- The demo was on the old agentic-rca agent and blueprints/skills-kernel-only. Repointed to
  Blueprint/agent/agent_v2.py and Blueprint/latency/*/README_v1.md, where each blueprint carries
  its own tools/ scripts wired in via blueprint_tool. diagnose(run_dir, blueprint=<md>,
  index_root=DATA) and Chat(run_dir, blueprint=<md>, ...) - both take a run_dir PATH now (no
  load_run) and a blueprint markdown path.
- Module-collision guard (import_agent): both trees define agent_v2/ctf_tool/codetool/config.
  The Verdict scorer imports the OLD agent_v2; import_agent() drops any non-Blueprint copy from
  sys.modules so the Blueprint/agent ones always win, regardless of order.
- Blueprint library tab + picker now read Blueprint/latency: 5 blueprints (svc_cpu_cap 10 tools,
  noisy_neighbor 10, slow_db 13, svc_mem_cap 11, svc_net 11). RUNS svc_cpu_cap blueprint ->
  "svc_cpu_cap".
- Verified: full live run to completion (335 s) with the new agent; START shows the new
  blueprint; worker toolset = 7 fixed + blueprint_tool; Chat constructs with blueprint_tool.
- HONEST CAVEAT (two findings):
  1. On this Windows demo box there is NO babeltrace2, so the blueprint's raw-slice tools
     (extract_slice.sh -> sched_budget/cpu_ceiling) cannot decode; the demo run dirs have no
     trace.txt.gz dump either. The agent therefore falls back to the fixed index tools (which
     read the same tsv.gz index). blueprint_only mode would FAIL here for the same reason, so
     the demo stays in full mode.
  2. The new svc_cpu_cap blueprint was authored/tuned for the AGENTIC runs, not Sock Shop. On
     the Sock Shop svc_cpu_cap trace the new agent returned "unknown/other" (vs the old setup's
     clean carts/cpu_cap). These blueprints belong with the agentic traces they were built for,
     on a machine with babeltrace. Natural demo pairing: an agentic trace + its matching
     blueprint.
