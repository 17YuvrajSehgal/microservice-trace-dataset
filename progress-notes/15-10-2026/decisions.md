# 15-10-2026 — decisions

## M.Sc. abstract presentation (20 min) planned

Work lives in `../../thesis/msc-thesis-abstract-presentation/` (kept separate from the
research tracks on purpose). Plan: `presentation-plan.md`.

Decisions and why:

- **Structure follows the abstract's four paragraphs** (problem → blueprint →
  evidence → plan), because the audience has the abstract in hand and the
  talk should expand it, not re-order it.
- **Lead the evidence act with the honest tie** (56% vs 51%, 57 incidents)
  and only then the headline wins (deadlock 30/30 vs 3/30). Why: the tie plus
  its failure analysis ("routing, not content") is what makes the proposed
  work look targeted instead of hopeful.
- **The OS-noise paper appears only as one proof point** on the scope slide
  (agent as system-under-observation, 84% model-wait, 260 runs). It is a
  separate paper; the thesis talk should not fork into it.
- **A "numbers not to use" list is part of the plan** — the banned
  "50%→70–80%", the pooled +0 artifact, the disproven "<1% variation".
  Why: these have already been mis-quoted once each in this repo's history.

## Evaluated the svc_cpu_cap blueprint on agentic CPU-cap runs

Branch `test-svc-cpu-cap-blueprint-on-agentic-runs`. Ran `README_v1.md`'s
method on an agentic cap run (`t3_implement_cap25_r1`, 0.25 core) vs its
uncapped baseline, via the blueprint's own `tools/sched_budget.py` on our
decoded `trace.txt.gz`. Write-up: `1_svc_cpu_cap/EVALUATION-on-agentic-runs.md`.

Findings and why they matter:

- **Method is correct but fails out-of-the-box on the agentic kernel.**
  `sched_budget.py` only counts `prev_state==0` as CPU-wait; on this VM's
  kernel (7.0.0-gcp) a preempted-runnable thread is reported as `256`
  (`TASK_REPORT_MAX`), which the script drops. So every agent thread read
  ~0 wait and Steps 2--3 flagged no victim. The README *text* says count
  256 too — a doc/code mismatch, kernel-portability bug.
- **One-line fix** (count 256 as preempt-wait) makes the victim jump out:
  `python3` test runner, 126 waits ≥50 ms, max 89 ms ≈ the 100 ms quota
  period = the burst-and-freeze signature. Uncapped baseline: ~0.
- **Our own `analyze_run.py` shares the same `prev_state==0` assumption** —
  this is (part of) why its trace `runnable_wait` under-counted throttle and
  we leaned on `cpu.stat`. Worth a look if we ever trust the trace wait number.
- **cpu.stat is the cheap ground truth the blueprint excludes**:
  `nr_throttled=208, throttled_usec=20.1 s`. Recommend promoting it to a
  Step-0 cross-check.
- **Bursty/LLM-bound workload breaks whole-run averaging** (agent ~84% idle,
  `swapper` dominates) — Step 6's `run≈quota` needs slicing to active windows.

Note: `README_v1.md` now exists (earlier note said it didn't).

## Applied the 256-fix to both scripts; paper numbers unchanged

Fixed `sched_budget.py` (blueprint) and `analyze_run.py` (paper analyzer) to
count `prev_state & 0x100` (256) as runnable-wait. Then ran `make_data.py`
old vs new over all local run data (all 4 problems, 42+20+32+12+20 runs).

**Result: no paper numbers need updating.** Diff was two stall counts nudging
by a handful (W=2 ≥1ms 8→9; W=16 ≥1ms 5228→5234). `worker_runnable` (2.8),
`≥10ms` stalls (138), all of Problem 1/3/4 — identical.

Why, and it's a clean mechanism: the kernel codes the two kinds of
switch-out differently.
- **Time-slice contention** (Problem 2, W>C) → `prev_state=0` (5079/5101 of
  ttworker switches). Old code already counted these as RDY.
- **CFS bandwidth throttle** (Problem 1 cap) → `prev_state=256`
  (TASK_REPORT_MAX, 138/175 of the capped agent's python3 switches). Old
  code dropped these. The fix recovers them — but Problem 1's paper number
  is the `cpu.stat` throttle (20 s), not the trace wait, so nothing moves.

So the fix is correct and matters for the blueprint's RCA (throttle shows as
256), but is a no-op for the paper's aggregates.

## Full correctness pass over paper2.tex (verified against data)

Made four edits; verified the rest against make_data/cpu.stat.

Edits:
1. fig:method caption — `prev_state=0` → "0 or the preempt flag (256)". The
   figure IMAGE was already correct (shows "preempted -> waiting"), only the
   caption text was wrong.
2. Validation sentence — the claim "on-CPU matches cpu.stat to within 0.1-3%
   (3.26 vs 3.27)" is **false**. Measured across 40 P1 runs: median error
   2.2%, max 17.6%, 17/40 over 3% (trace under-counts on-CPU, worst on
   unthrottled runs with many short-lived helpers). Rewrote honestly.
3. Kernel string — `7.0.0-gcp` → `7.0.0-1011-gcp` (the real string in
   ground_truth.json).
4. tab:threads >=1ms cells — 8->9 (W=2), 5228->5234 (W=16) to match the
   fixed analyzer. Cosmetic; narrative ("tens to thousands", "138 at 4x")
   unchanged.

Verified correct, no change: all of tab:cpu (wall/on-CPU/throttle), tab:mem
(1.05M refaults, 8505 high ev, 4.7x), tab:cliff (640M 3/3 OOM), tab:io
(1.23GB, 205/122/60), tab:consistency (Claude throttle 19.8 & Codex 18.7 both
verified from cpu.stat), 84% LLM-share, sub-agent ~20 stalls/0.4s.

Flagged, NOT changed (user's call): abstract "260 controlled runs" = 130
Claude + 130 Codex (four-problem + sub-agent campaign). The end-to-end
section adds ~51 more real runs (e2e_cl 21 + e2e_cx 30), so 260 undercounts
the full study (~311). Either bump to "over 300" or scope it as "260 across
the four-problem campaign."

## Carved out a standalone artifact repo for the paper

New repo `C:/workplace/os-noise-for-agentic-ai` (name chosen by user from the
paper title). Local git only (commit 07905f0, 4709 files, ~11MB); NOT pushed.
Source left in place in the main repo.

Decisions and why:
- **Preserve the `latency/` + `research-paper/` layout** rather than
  restructure, because the analysis scripts hard-code relative paths
  (`parents[1]/latency`, `1_svc_cpu_cap/agentic-os-noise/runs`, etc.) - a
  flat/clean layout would mean rewriting + retesting every path. Copying the
  structure makes every script run unchanged.
- **Ship code + all per-run `meta/` + agent.log, exclude the ~6GB traces**
  (user's choice: "code + all run metadata"). meta holds the cgroup
  ground-truth counters, so every headline number is inspectable offline;
  only re-parsing the traces needs the Zenodo download. .gitignore blocks
  `**/trace/` and `**/*.txt.gz` so a Zenodo unpack can't be committed.
- Wrote README / REPRODUCE / DATA / CITATION.cff / LICENSE(MIT). DATA.md
  carries a Zenodo-DOI placeholder (release pending, user will do later).
- Dropped the stale `paper.tex` (kept paper2.tex) and the scratch
  `analysis_compare_output.txt`; fixed the one repo-escaping link (PLAN.md ->
  meeting-notes) and the research-paper README's `paper.tex` references.
- Left out the StrataTrace blueprint + EVALUATION (separate work) to keep the
  artifact focused on the OS-noise study.

## (16-10) Blueprint/ becomes the active workspace; agent copied in

User direction: the repo is getting big; `Blueprint/` is the latest line of
work, `blueprints/` (root) is the previous generation and stays as reference.
Next focus: new blueprints in `Blueprint/`, and making the agent use the new
blueprint tools (`Blueprint/latency/*/tools/`). When 100% ready, `Blueprint/`
graduates to its own repo for the paper.

Did (copy, not move — originals untouched):
- `agentic-rca/` -> `Blueprint/agent/` (28 py files + 12 skills + docs;
  excluded old campaign `results/`, git-ignored `dev-runs/`, `__pycache__`.
  734K).
- **Vendored `stratatrace/` INSIDE `Blueprint/agent/`** — this is the
  portability fix. Every agent entry point already does
  `sys.path.insert(0, HERE)`, so the vendored copy resolves with ZERO code
  changes; the `from stratatrace import load_run` imports no longer reach the
  repo root. All data paths were already env vars (RUNS_ROOT, CTF_INDEX_ROOT,
  BT2, RCA_SOURCE_ROOT; defaults = Trillium).
- Smoke-tested from the new location: config.py OK, skillreg loads 12 skills,
  vendored stratatrace imports, core + kernel-tool modules import.
- Verified no `../` escapes in any copied script (only absolute cluster
  paths, which are environment config, not repo coupling).
- Added `Blueprint/README.md` (workspace map + direction) and a provenance/
  portability header in `Blueprint/agent/README.md`.

Not done yet (next): wiring the agent's toolset to the eight blueprint tools —
that is the design task this copy sets up.

## (16-10) Trimmed Blueprint/agent to the agent's actual dependency closure

User: keep only what the agent uses; the 12 skills are old-generation (we
have exactly one blueprint now, svc_cpu_cap README_v1).

Method, not guesswork: computed the import graph over all 28 modules.
closure(agent_v2) = 13 modules (agent, agent_v2, coderepo, codetool, config,
context_builder, ctf_tool, leakguard, shared_context, skillreg, source_tool,
tools, transcript) + vendored stratatrace/.

Removed (still in agentic-rca/ at the repo root — nothing is lost):
- skills/ (12 old-blueprint skills). skillreg.py STAYS: agent.py imports it
  top-level, and it degrades cleanly to 0 skills (verified). It becomes the
  mount point for blueprint-backed skills.
- 15 out-of-closure modules: evaluate, degrade, runs, baseline_stat,
  rcaeval_adapter, analyze, audit_leakage, bundle_artifact,
  component_census, cost_report, inspect_run, peek_run, run_digest, and the
  2 test files (they test kept modules but drive the old campaign setup).
- 13 RESULTS-*.md + TRANSCRIPTS.md (old campaign records), campaign_driver /
  review_driver / 3 sweep sbatch (old campaign machinery).
- agent_v2 needs no runs.py: it takes the run dir as argv[1].

654K, 17 entries. Smoke-verified after the cut: all 13 modules import
(incl. the full agent_v2 LangGraph chain), skill registry loads 0 skills
without error. README rewritten to match the clean folder.

## (16-10) Second trim: agent.py consolidated into utils.py; stratatrace out

User: v2 shouldn't need stratatrace; fold agent.py's pieces into v2 or a
utils module. Verified first, then cut:

- **stratatrace was only used for `load_run(rd).run_dir`** — the real imports
  were in three `__main__` blocks, and v2's kernel-only path touches nothing
  but the run-directory string. So `diagnose(run_dir)` / `Chat(run_dir)` now
  take the path directly; vendored stratatrace/ deleted.
- **agent.py (v1) retired.** What v2 imported from it moved to a new
  `utils.py` with public names (prompts KO_HEAD/FAULT_VOCAB/KO_RULES byte-
  identical — v2 asserts on the wording; fit_result; api_call/checked/
  ProviderError; tool_defs now kernel-only-only with the "other" fault enum
  baked in; run_tool now takes run_dir). v1-only machinery (four-modality
  prompts+tools, loops, oneshot baseline, ranked mode, nudges) NOT copied.
- Also deleted as v1-only: tools.py (RunTools, the pandas modality layer),
  source_tool.py, context_builder.py, shared_context.py.
- Fixed a latent bug while there: Ctx never initialized `self.repo`, so a
  hallucinated code_* call in the graph path would AttributeError; now None.
- requirements.txt rewritten (adds langgraph/pandas/numpy, drops the stale
  stratatrace/mcp lines).

Now 12 files. Verified: tool_defs == the 7 kernel-only schemas, fit_result
trims to valid JSON, agent_v2 imports with wording asserts passing, graph
builds, new signatures diagnose(run_dir,...) / Chat(run_dir,...).

## (16-10) Blueprint tools wired into agent_v2 (blueprints.py)

`python agent_v2.py <run_dir> <blueprint.md>` now does both halves
automatically: inject the blueprint text as the given skill AND expose its
sibling tools/ as a `blueprint_tool` the model can call with the exact CLIs
the blueprint's steps show ($TRACE/$WORK/$DUMP placeholders expanded).

Design decisions:
- One generic `blueprint_tool(script, args)` rather than one schema per
  script: the blueprint text IS the usage documentation and is already in
  the prompt, so per-script schemas would duplicate it and drift.
- `blueprints.load()` wraps ANY blueprint markdown into a skillreg.Skill
  (name from the folder, e.g. 1_svc_cpu_cap -> svc_cpu_cap; signature from
  the "What it looks like" section) - no reformatting of README_v1 into
  skill frontmatter, no second copy to drift.
- extract_slice.sh needs bash+babeltrace2; on machines without them
  (Windows dev box) the runner falls back to a pure-Python cut of the run's
  decoded trace.txt.gz with the same output contract (sched events in
  window), so sched_budget/rhythm/victim_info/wake_graph run unchanged -
  the whole blueprint is executable locally TODAY.
- Chat gets the same blueprint= param; fixed its tool list being built from
  the module-global CTX (now appends its own ctx's blueprint def).

Verified end-to-end at the tool layer on t3_implement_cap25_r1 (no API):
load -> 8 scripts enumerated -> trace dir auto-found -> idx_summary (DAY
2026-10-12, start 03:17:25) -> fallback slice cut -> sched_budget shows the
victim (python3 pid 8192, 34 waits >=50ms, max 88ms ~ the quota period) ->
rhythm + victim_info run -> worker toolset includes blueprint_tool.

Also confirmed OpenRouter works despite $0.00 credits reading: the account
is BYOK (Naser's Azure/Google upstreams - hence the hard provider pinning),
so billing is upstream and invisible to our API key; a real gpt-6-luna
request through config.py succeeded. Budget visibility = Naser's dashboard.

**One non-number accuracy item:** `paper2.tex` fig:method caption (line ~160)
says "`prev_state`=0 means preempted" — that's the old, incomplete
description (misses 256 = preempt-throttle). Flagged, not yet edited (paper
prose the user is curating). Proposed: "0 or the preempt flag (256)".

Flagged while preparing (not fixed, not presentation work):

- `blueprints/problems/deadlock-lock-order/blueprint.json` uncommitted edit
  leaves a trailing comma → invalid JSON.
- The `README.md` → `README_v1.md` reference rename (3 docs) is half-done;
  no `README_v1.md` exists yet.
