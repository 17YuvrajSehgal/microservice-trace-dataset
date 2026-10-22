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
