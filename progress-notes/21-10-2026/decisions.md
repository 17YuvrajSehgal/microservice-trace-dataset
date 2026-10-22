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

## Blueprint tools run via WSL (babeltrace usable on Windows)
- blueprints.py Runner now executes the blueprint's own scripts through WSL when on Windows
  without native babeltrace2 (use_wsl). Paths ($TRACE/$WORK/$DUMP) are translated to /mnt/c/...
  (incl. the NTFS junction to the CTF). Native on Linux, WSL on Windows, python fallback if
  neither - one blueprint, any environment. (Also fixed: a function-local `import shlex` in the
  remote branch shadowed the module import -> UnboundLocalError in the WSL branch.)
- Verified directly on the demo svc_cpu_cap run: idx_summary (12 CPUs, date), extract_slice.sh
  (516,743-event slice via real babeltrace), sched_budget.py (java/carts: run 0.20s wait 7.58s,
  743 waits >=50ms - the CPU-cap signature).
- Live agent now DOES call blueprint_tool (it never did in full mode before). But it skipped the
  blueprint's Step 2 (idx_summary, which reports the date) and passed date '2026-??-??' to
  extract_slice -> exit 1. ctf_timespan gives only HH:MM:SS, so without idx_summary the agent
  can't know the day. This is blueprint-following/tuning (user will tune): the blueprint must
  force "get the date first", or the tools should resolve the day from the trace. Verdict on the
  Sock Shop trace is still weak for this reason, but the cause is now clean and fixable, not the
  environment.

## Bug: ctf tools failed on a loaded trace ("no CTF" / 0 events) - three root causes
Symptom: running the agent on ext_t6a_high_768_r1 gave ctf_timespan "no CTF at ...kernel/kernel"
and ctf_timeline "total events 0", though the index had 49,975 rows and ctf_proclife worked.
1. The new ctf_timespan/ctf_lines bailed on a missing CTF dir BEFORE reading the index. Made
   them index-first: error only when there is neither CTF nor index/sample (ctf_timeline and
   ctf_proclife were already index-first). The raw-decode helpers (_timeline_from_trace,
   _query_from_trace) still require the CTF - correct, they only run when there is no index.
2. The live run used the OLD agentic-rca ctf_tool (which decodes) via module caching - the
   scorer imports it. Hardened import_agent to drop EVERY cached sibling whose __file__ is not
   under Blueprint/agent, not just agent_v2.
3. The CTF junction (demo/data/run/ext_*/kernel) was lost after a restart - discover_external_runs
   re-registered the run but never rebuilt the junction, and we had not stored the source. Now
   _register_external writes run/<rid>/source.txt (the junction target) and _ensure_ctf_link
   rebuilds the junction; discover_external_runs rebuilds it from source.txt on startup.
Verified: import_agent loads Blueprint/agent/ctf_tool; timespan 48.0s no error; timeline
sched_switch matched 76,757; CTF reachable. (Recreated ext_t6a's junction + source.txt by hand
since it predated the sidecar.)

## Quick wins (user chose these before any bigger track)
1. ctf_lines raw-decode now uses WSL babeltrace on Windows. Added _bt_argv() in ctf_tool.py:
   on Windows without native babeltrace2 it routes `wsl -e babeltrace2 --clock-gmt <mnt-path>`;
   native everywhere else. All 3 decode sites use it. Verified: ctf_lines returned real
   mm_vmscan reclaim lines from the memory trace (was 4x "cannot run bt21.sh" before).
2. extract_slice.sh self-heals a missing/placeholder date. The agent sometimes calls it before
   idx_summary and passed `2026-??-??`; the script now resolves the day from the trace (same
   source idx_summary uses) when the date is not YYYY-MM-DD. Patched all 5 blueprint copies.
   Verified: bad date -> resolved 2026-10-13, cut 40,311 lines. (Tool robustness, not a
   method/prose change - the blueprint-text tuning remains the user's.)
3. Token cost: last run was 1.45M INPUT tokens, 1.05M in a single worker re-sending its thread
   (18 steps, 150k budget, + the 24k-char blueprint body in every system prompt). The demo now
   sets ABL_WORKER_STEPS=12 and ABL_THREAD_BUDGET=90000 via os.environ.setdefault at app import,
   so demo runs are ~half the cost while the agent's research defaults (18/150k) are untouched.
