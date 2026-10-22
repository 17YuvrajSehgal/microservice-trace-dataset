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
