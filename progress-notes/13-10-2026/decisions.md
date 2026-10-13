# 13-10-2026

- Designed problem #3 (memory cap): `Blueprint/latency/3_memory_cap/PLAN.md`.
  Configuration-level, memory analog of #1's CPU cap. Mechanism = reclaim +
  refault I/O (vmscan_*/block_* already in profile), ground truth from
  cgroup memory.events/memory.stat/memory.peak (the cpu.stat analog).
  Key design call: the agent (node) is itself memory-heavy (~0.5-1GB RSS),
  so a cgroup memory limit squeezes the agent too - embraced as the
  realistic container framing, with caps sized relative to a measured
  baseline B (profiling run first). Two regimes: Part A recoverable
  (memory.high, file-backed page-cache pressure -> refault slowdown,
  dose-response, 20 runs) because GCP VMs have no swap so anon pressure
  OOMs instead of stalling; Part B the OOM cliff (memory.max lowered toward
  B until a process is killed -> task-failure threshold, ~12 runs).
  H1-H4 pre-stated. ~35 runs. Rig changes: MEM_LIMIT arg in collector +
  memory.events/stat snapshots, t6_memtouch task, analyzer reclaim-stall +
  block-read metrics, run_campaign_t6.
- Built + validated the problem #3 rig. collect_agent_run.sh: 5th arg
  MEM_LIMIT (high:<N> / max:<N>), snapshots memory.events/stat/peak, drops
  page cache before memory runs. tasks/t6_memtouch.sh (ttmem worker reads a
  1GB file 5x). analyzer: memory block (reclaim_stall from
  mm_vmscan_*reclaim_begin/end, block I/O, memory.stat/events deltas, peak).
  run_campaign_t6.sh (Part A high dose-response / Part B max cliff).
  Regression-checked: #1/#2 runs analyze unchanged.
- Three real bugs caught by smoke tests before the campaign (good):
  (1) dd creates big.dat cache in ROOT cgroup -> reader hit it free, cap
  never bit. Fix: drop_caches before memory runs so the reader faults the
  file in-cgroup. (2) wildcard `vmscan_*` matches NOTHING - kernel names
  them `mm_vmscan_*` (same for compaction/migrate); reclaim was never
  recorded. NB: the main rig's collect_trace.sh has the same wrong wildcard
  - its memory tracepoints likely never recorded either. (3) uncapped cell
  must also drop caches -> use high:max (unlimited soft cap) not empty.
- Validated contrast (1GB file, 5 passes): high:max -> peak 1.38GB,
  refault 0, phase ~5s; high:1152M -> peak 1.21GB, workingset_refault 1.05M,
  pgscan 1.1M, memory.events[high]=8830, phase 30s (6x slower). oom_kill=0
  (recoverable). Insight: reclaim CPU stall is tiny (0.16s) - the cost is
  REFAULT I/O (29k block completions), not reclaim itself. Headline =
  phase_wall + refault + events[high].
- Rig ready for the ~35-run campaign (Part A 20 + Part B OOM cliff). VM
  stopped.
- Ran problem #3: 44 runs total, all downloaded to 3_memory_cap/runs/
  (runs_t6 + runs_t7, full CTF+dumps+meta), VM stopped. RESULTS.md written.
  - Part A (memory.high, 20): clean recoverable dose-response. Fits
    (high>=1536M vs 1.38G working set) -> 0 refault, phase 6.5s; doesn't
    fit (<=1152M) -> 1.05M refault, phase 30s (4.7x). <0.1% reproducible.
    Mechanism: reclaim CPU stall tiny (0.16s); cost is refault disk I/O.
  - Part B file (memory.max, 12): NO OOM at any level, even 768M. Finding:
    clean file cache is always reclaimable, so a hard cap reclaims (same
    refault cost) rather than killing. Design flaw caught - OOM needs
    ANON memory.
  - Part B cliff (memory.max + 512MB anon, t7, 12): sharp binary OOM cliff
    between 640M (3/3 OOM+fail) and 768M (3/3 ok) = agent+workload ~762MB.
    Nuance: OOM killer kills the WORKER not node, so agent_exit=0 but
    task_check=1 - agent survives and reports the failed task. "Sandbox
    memory limit silently kills your tools mid-task."
  - Built tasks/t7_memhog.sh (anon allocator) to get the real cliff after
    the file-workload Part B couldn't OOM. aggregate_mem.py covers all 3.
- Added problem #4 (disk I/O cap, io.max rbps): PLAN + 20-run Part A,
  RESULTS.md. Chose io.max (not FD/DNS/pids) to complete the cgroup-limit
  quartet CPU/parallelism/memory/disk and give a 4th recoverable
  dose-response. Built: IO_LIMIT arg (6th) in collector w/ backing-device
  detection, io.stat snapshots, tasks/t8_ioread.sh (read 1GB once),
  analyzer io delta, run_campaign_t8. Result: phase wall ~ 1/rbps once cap
  < native disk (~205MB/s): 200M no effect, 100M 1.7x, 50M 3.4x; throttle
  exact (1GB/20.4s = 50MB/s). Caught: io controller NOT in root
  subtree_control by default (cpu/mem/pids are) -> collector now enables
  +io. Honest wrinkle: a cap above native disk speed can't bite.
- CATALOGUE COMPLETE: 4 entries (CPU cap, threads-vs-cores, memory cap,
  disk I/O cap), all configuration-level, all kernel+cgroup evidenced,
  pre-registered hypotheses confirmed. ~110 agent runs across the four.
  VM stopped.
- Wrote the shared catalogue document:
  `Blueprint/latency/OS-NOISE-FOR-AGENTIC-AI.md` - ties all four problems
  into the paper story (claim, common method, catalogue table, what each
  adds, 5 takeaways, open/parked). This is the doc to show Naser. Matches
  his 07-10 framing (configuration-level, kernel-only, package 3-4
  problems). Shape to be aligned with his model paper once it arrives.
- Swept ALL provenance off the VM to `Blueprint/latency/provenance/`
  before any future deletion: vm_env.txt (uname/lttng/lscpu/lsblk/free/
  swap/node/claude/cgroup-controllers), all 9 campaign logs, all 6 run
  manifests, and collection_as_run/ (the CRLF-stripped scripts as they ran
  on the VM). Verified VM run counts == local (runs40/t4-20/t5-6/t6-32/
  t7-12/t8-20); all 132 run bundles already local with CTF+dump+meta.
  Nothing research-relevant left only on the VM now. Note: VM kernel
  auto-updated 7.0.0-1011 -> -1014-gcp across stop/starts; per-run
  ground_truth.json records each run's own kernel, so it's traceable.
  VM stopped. Safe to delete the VM whenever (nothing unique remains).
- Committed + pushed the catalogue to origin/blueprints (commit edc53dd),
  lean: raw CTF (4.2GB) AND decoded dumps (962MB) gitignored -> Trillium;
  git keeps scripts/results/PLANs/meta+agent.log/provenance/docs (~800KB).
  Scoped commit to session work only; left pre-existing index oddities
  (rythm.py, extract_slice->07-10.txt rename) untracked for user.
- Wrote the draft paper: `Blueprint/research-paper/paper.tex` (+README).
  Self-contained twocolumn article, plain-pdflatex, standard packages only;
  env/structure balance verified (no TeX engine on the box to compile).
  Sections: method, 4 problems w/ result tables, discussion (5 takeaways),
  threats, conclusion. Numbers from the RESULTS files; 130 campaign runs.
  Pending: real citations + align to Naser's OS-noise papers.
- Upgraded the paper's tables + added figures. make_data.py recomputes
  every cell (median + min-max across reps) from the run data; make_figures.py
  renders 4 matplotlib figures (Okabe-Ito colorblind-safe) to PDF (paper) +
  PNG (preview), verified by eye. Rewrote all 4 result tables richer: P1
  both tasks w/ throttle-%-of-wall, P2 measured-vs-(W-C)/W wait, P3 split
  into memory.high dose-response + a dedicated OOM-cliff table, P4 effective
  MB/s. Figures: fig_cpu (wall + throttle, 2 tasks), fig_threads (phase +
  the (W-C)/W overlay - dots land on the line), fig_memory (bars + OOM-cliff
  scatter), fig_io (measured vs ideal 1/rbps vs disk floor). Added multirow/
  amstext, graphicspath, all figures \ref'd. Env balance 17/17, 5 tables,
  4 figures. Can't compile here (no TeX engine); builds on TeXLive/Overleaf.
