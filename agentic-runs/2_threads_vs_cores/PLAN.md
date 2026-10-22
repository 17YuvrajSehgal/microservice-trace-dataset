# Problem #2: threads vs cores — experiment design

Date: 2026-10-12. Second entry in the "OS noise for agentic AI" catalogue
(07-10 meeting; the angle Naser pushed hardest). Reuses the rig from
`../1_svc_cpu_cap/agentic-os-noise/` (VM `agentic-noise`, collector,
analyzer). Category: **configuration-level** — over-parallelism on an
undersized box, no code bug, no kernel bug, no cpu.max cap.

## The question

Agent harnesses fan out sub-agents / parallel workers. Naser's claims to
test: (1) harnesses self-limit parallelism — "do they care, or do they
just have it?"; (2) when parallel work exceeds cores, agents create their
own OS noise: threads sit runnable-but-waiting, and the task slows down
even though no one capped anything.

## Mechanism (what the kernel trace will show)

Problem #1's noise was **CFS throttle** (quota). Problem #2's noise is
**run-queue contention**: with W runnable threads on C cores, each thread
waits in state runnable (our analyzer's `runnable_wait` / RDY) for
~(W-C)/W of the time. Unlike throttle, this wait is fully visible to the
sched_switch/wakeup state machine — no cpu.stat blind spot.

## Pre-stated hypotheses (evidence-first; write results against these)

- **H1 (observe)**: the harness limits concurrent sub-agents below what we
  request, and the trace shows whether it even checks the machine
  (`sched_getaffinity` / `sysinfo` / reads of /proc/cpuinfo by `claude` —
  all visible as syscalls we already record).
- **H2 (dose-response)**: with W <= C, subtree `runnable_wait` ~ 0; past
  W > C it grows with (W-C)/W, and the parallel phase's wall time grows
  ~ W/C while total on-CPU stays flat.
- **H3 (latency tail)**: scheduling delays >= 10 ms per wakeup appear only
  past W = C and grow with W (the "my tool call randomly stalls" symptom).
- **H4 (the story)**: a harness that fans out on a small/shared box
  manufactures the same symptom family as problem #1's cap — OS noise by
  configuration, not by the LLM.

## Part A — controlled dose-response (the numbers)

Keep the measured phase deterministic, like problem #1 kept the task fixed.

- **Workload**: task repo `t4_parallel` — `worker.py` (pure CPU, fixed
  work: ~3 s on an idle core, e.g. prime counting) + `run_all.sh` that
  launches **W** workers with `xargs -P W`. The agent is still the driver:
  prompt = "run ./run_all.sh, then report the slowest worker's time from
  results.csv". The fan-out happens inside the agent's tool call; the
  measured phase is deterministic.
- **Grid**: W in {2, 4, 8, 16} on the 4-vCPU VM (load factor 0.5, 1, 2,
  4x) × 5 reps = **20 runs**. No cpu.max (that's problem #1's knob).
- **Metrics per run** (analyzer extensions, same trace profile):
  - `phase_wall`: first worker fork → last worker exit (from
    sched_process_fork/exit; ignores LLM-wait before/after).
  - subtree `on_cpu` (should stay ~flat ≈ W × 3 s... total work scales
    with W, so compare **per-worker** on_cpu: flat) and `runnable_wait`
    (the noise; should explode past W=4).
  - wakeup→run latency histogram per worker (counts ≥1 ms / ≥10 ms /
    ≥50 ms — same buckets as `sched_budget.py`).
  - sanity: per-worker on_cpu identical across W (same work), so any
    phase_wall growth is scheduling, not workload.

## Part B — agentic observation (the harness behavior)

- Prompt Claude Code to spawn **N parallel sub-agents** (its Task tool):
  "analyze these N files simultaneously, one parallel task each", N in
  {4, 8}, 3 reps each = **6 runs**.
- From the trace: max concurrent runnable/running tids in the agent
  subtree over time (100 ms sampling) vs requested N; fork timeline
  (batched or all-at-once?); and H1's "does it check cores" syscalls.
- This answers Naser's question directly from kernel evidence, and shows
  what a real harness does — whatever the answer is, it's a finding
  (self-limiting = good citizenship to report; not = the risk is real).

## Stretch (only if A+B are clean)

One combined cell: W=8 **plus** 0.5-core cap, 3 reps — links problems #1
and #2 (sandboxed agent that also fans out = compounding noise).

## Honest confounds, stated up front

- n2-standard-4 = 4 vCPUs = 2 physical cores with SMT. Contention between
  hyperthread siblings starts before W>4. We treat the vCPU as the
  scheduling unit (that is what cloud users get); say so in the writeup.
- `lttng-consumerd` competes for CPU at high W. It is constant across
  conditions; note it, don't pretend it's zero.
- LLM nondeterminism: same mitigations as #1 — fixed prompt, fresh repo
  per run, shuffled order, medians of 5.
- Workers are pure-CPU and identical by design; real sub-agents also wait
  on the LLM. Part B covers the realistic mix; Part A isolates the
  mechanism. Both are needed, neither alone is the claim.

## Rig changes needed (small)

1. `collect_agent_run.sh`: accept an optional 4th arg (variant, e.g. W)
   exported as `TASK_ARG` to the task script and recorded in
   ground_truth.json.
2. New task `tasks/t4_parallel.sh`: generates worker.py, run_all.sh
   (reads W from TASK_ARG), prompt, .check (all W results present).
3. `analyze_run.py` extensions: phase_wall (worker fork→exit window),
   per-tid wakeup-latency buckets, max-concurrency timeline.
4. `run_campaign.sh`: iterate W values for t4 (or a small t4 driver).

## Run budget

20 (Part A) + 6 (Part B) + optional 6 (stretch) ≈ **26-32 runs**, one VM
evening. Analysis is local, same as #1.
