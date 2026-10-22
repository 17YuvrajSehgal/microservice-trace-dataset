# 11-10-2026

- Summarized the 07-10-2026 supervisor meeting into
  `meeting-notes/07-10-2026-summary.md`. Key decisions from that meeting
  (recorded there in full): frame the throttling work as "OS noise for
  agentic AI", recreate the CPU-cap fault under an agentic workload
  (Codex CLI in a container), categorize every problem as kernel vs
  configuration vs code, and kernel-traces-only for the blueprint analysis.
- Wrote the agentic OS-noise collection plan:
  `../../agentic-runs/1_svc_cpu_cap/agentic-os-noise/PLAN.md`. Key choices: no stress-ng —
  the cgroup `cpu.max` cap IS the condition (it's how agent sandboxes are
  configured); observe-first step to see if harnesses self-limit; paired
  cap grid (unlimited/1/0.5/0.25 core) with ~5 reps because LLM runs are
  nondeterministic; attribute wall time to LLM-wait vs compute vs
  runnable-but-throttled using sched events, validated against cgroup
  `cpu.stat`.
- Created VM `agentic-noise` (teleeporter, us-east1-d, n2-standard-4,
  Ubuntu 24.04, kernel 7.0.0-1011-gcp, ~$0.19/hr). LTTng 2.15.3 verified
  (smoke trace read back). Bare-VM cgroups instead of Docker — same
  `cpu.max` mechanism, simpler tracing; 1–2 Docker runs later as an
  equivalence check.
- Agent harness switched Codex → **Claude Code** (headless `claude -p`,
  paid account signed in on the VM as user `aylabsltd`). Reason: the
  shared OpenRouter key is over its $150 monthly budget until Nov 1
  (Codex+OpenRouter wiring itself worked via `wire_api = "responses"` and
  stays configured as plan B). Harness choice doesn't affect the
  measurement — we trace the local system, not the model.
- Pilot1 passed (uncapped, 7.6 s wall): agent fixed the seeded bug, trace
  8.5 MB with full process tree visible (claude 29k events + bash/git/
  python3/ps children), cgroup `cpu.stat` delta 1.97 s CPU. Pipeline
  (cgroup + LTTng + headless agent + anchors) is proven. Gotcha: cgroup-v2
  delegation blocks non-root `cgroup.procs` writes — move the PID with
  sudo. Runner: `pilot_run.sh` on the VM (also in session scratchpad).
- Built the real collection rig (mirrors
  `microservice-lttng-data-collection-scripts/` structure) in
  `../../agentic-runs/1_svc_cpu_cap/agentic-os-noise/collection/`:
  `vm_setup_agentic.sh`, `collect_agent_run.sh` (one run), `run_campaign.sh`
  (tasks×4 caps×N reps, shuffled, resumable, manifest.csv), `tasks/`
  (t1_toy, t2_medium with 3 seeded bugs + CPU-burning test suite), README.
  Kernel profile = same curated v2 families as collect_trace.sh (syscalls +
  sched/block/net/irq/power/vmscan/writeback/...), no UST (agent not
  OTel-instrumented). Per-run meta: ground_truth.json, cpu.stat before/after,
  clock_anchors.jsonl, root.pid, lttng_enabled.txt, task_check.txt.
- Validated: capping works. Found + fixed a bash bug (`echo $BASHPID | tee`
  wrote the pipe-subshell pid, so the agent never entered the cgroup — caught
  because cpu.stat delta was zero). After fix, 0.25-core run showed
  nr_throttled=124, throttled_usec=12.87s — premise confirmed. t2_medium
  wall ~20s uncapped, needs lengthening for stable numbers.
- Tuned the task set for trace quality. Rebuilt t2_medium (3 modules,
  4 varied bugs) and added t3_implement (write-from-spec, different agent
  behavior). Validated uncapped: both solve reliably; traces are highly
  diverse — ~280 distinct kernel event types, 132 distinct syscalls, 73-77
  distinct procnames, 220-270k events/run. Wall ~17-25s, CPU 12-18s (ample
  to throttle; 0.25-core gave 12.9s throttled earlier). Decided NOT to make
  tasks harder — diversity goal already met, and harder tasks risk timeouts
  / give-ups at tight caps that would confound the throttle signal.
- Added data-integrity guard: collector records `test_file_tampered` (git
  diff on protected test_*.py) + agent_diff.txt, so a run where the agent
  "passed" by editing the test can be discarded. Verified: clean run shows
  tampered=false and diff touching only source files. AGENT_TIMEOUT raised
  600->900s for tight caps.
- Wrote + ran the analysis (`analysis/analyze_run.py`, pure Python on the
  gzipped babeltrace dump). Builds the agent process subtree from root.pid
  via sched_process_fork, state-machines sched_switch/wakeup per tid,
  buckets off-CPU time by the blocking syscall. Two bugs found and fixed:
  event-name regex ignored the `(+delta)` field (matched nothing -> all
  zeros); epoll_pwait2 (node's event-loop syscall on this kernel) was
  unmapped. Validated: subtree on_cpu matches cgroup cpu.stat to 97-99.7%.
- First real result (t2_medium, uncapped vs 1-core): agent main thread is
  ~92% blocked in the event loop (LLM+idle), ~7-8% on-CPU; total subtree
  compute 3.7s. Both runs saved in runs/, output in analysis/results/.
  Two known limitations documented in analysis/README.md: (a) LLM-wait not
  yet split from idle (both in epoll bucket; needs socket-fd mapping);
  (b) trace runnable_wait under-counts CFS throttle (0.03 vs cpu.stat 0.45
  on 1-core) - use cpu.stat throttled_s as ground truth for now.
- Ran the first full campaign: 2 tasks (t2_medium, t3_implement) x 4 caps
  (nocap/cap100/cap50/cap25) x 3 reps = 24 runs. ALL 24 succeeded
  (agent_exit=0, task_check=0, test_file_tampered=false) incl. every
  0.25-core run - task calibration holds up at tight caps. Downloaded all
  to runs/ (trace + text dump + meta each, 144MB tarball). VM
  `agentic-noise` STOPPED (TERMINATED, disk persists) to stop billing.
  Restart: gcloud compute instances start agentic-noise --zone=us-east1-d.
  then decide whether to top up to 5 reps.
- Ran full analysis (analysis/aggregate.py -> RESULTS.md,
  results/campaign24.json). Clean finding: throttle rises monotonically
  with the cap (0 -> 0.4 -> 4-6 -> 14-20s), on-CPU is flat across caps
  (~4-5s, agent's compute demand is fixed), wall inflation at 0.25 core is
  +33% (t2) to +83% (t3). Mild caps (1/0.5 core) are noisy at n=3 because
  LLM/event-loop wait (~20s) variance swamps the few seconds the mild cap
  adds -> top up to 5 reps to stabilize those. 0.25-core effect already
  clear. Headline rests on throttle+on-CPU+wall (all validated), not on the
  unresolved LLM-vs-idle split.
