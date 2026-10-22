# OS noise for agentic AI

How much of an AI coding agent's slowness is the LLM, and how much is the
**machine configuration** underneath it? People blame the model. We show,
with kernel traces, that container resource limits add large, measurable
delay - and sometimes kill the agent's tools outright.

This is the shared framing for a four-problem catalogue. Each problem has
its own folder with a PLAN, collection scripts, raw runs, and a RESULTS
writeup. This file is the story that ties them together (for the
"OS noise for agentic AI" paper, per the 07-10-2026 meeting).

## The claim

An agent's own compute demand is small and fixed. When a sandbox limits a
resource, the agent doesn't do less work - it **waits**, or it **dies**.
Default agent use on an adequate box is LLM-bound; past a configuration
threshold, the OS is the bottleneck, not the model.

## Method (common to all four)

- One GCP VM, 4 vCPU / 16 GB, LTTng kernel tracing only (no metrics).
- Agent: Claude Code headless (`claude -p`) on fixed coding tasks.
- Each run: wipe + regenerate a byte-identical task repo, put the agent in
  a cgroup, set one resource limit, record the full kernel trace + the
  cgroup's own counters (the ground truth) + wall-clock anchors.
- 5 reps per condition, shuffled order, medians - to absorb LLM
  nondeterminism. Every result is validated against the kernel's own
  accounting (e.g. trace on-CPU vs `cpu.stat`, to 97-99%).
- Evidence-first: hypotheses pre-registered in each PLAN, then tested.

## The catalogue

All four are **configuration-level** (a container limit set too low) - not
a code bug, not a kernel bug. Each is a different resource and a different
kernel mechanism.

| # | problem | knob | mechanism | headline |
|---|---|---|---|---|
| 1 | CPU cap | `cpu.max` | CFS throttle | 0.25 core -> +75% wall; compute stays fixed, agent waits |
| 2 | threads vs cores | over-parallelism | run-queue contention | 4x cores -> +295% wall; (W-C)/W wait law, exact |
| 3 | memory cap | `memory.high` / `memory.max` | reclaim + refault / OOM | 4.7x slower (cache) **or** killed mid-task (anon) |
| 4 | disk I/O cap | `io.max` | block-layer throttle | 50 MB/s -> 3.4x slower; wall ~ 1/rbps |

Details and tables: `../../agentic-runs/1_svc_cpu_cap/agentic-os-noise/RESULTS.md`,
`del-this/2_threads_vs_cores/RESULTS.md`, `del-this/3_memory_cap/RESULTS.md`,
`del-this/4_io_cap/RESULTS.md`.

## What each one adds to the story

- **#1 CPU cap** - the base case. The agent demands ~4-5 CPU-seconds no
  matter the cap; tightening the cap converts that compute into throttle
  wait. LLM-bound at 1 core, OS-bound at 0.25 core. Establishes the regime
  framing.
- **#2 threads vs cores** - self-inflicted noise. Over-parallel workers on
  too few cores wait in the run-queue; the wait fraction matches textbook
  (W-C)/W to two decimals. **Part B** then checks the real harness: Claude
  Code *probes the core count* (18 `sched_getaffinity`/`sysinfo` calls) and
  does **not** oversubscribe - its sub-agents are LLM-bound, staggered, not
  stacked. So the risk is real but needs explicit over-parallelism, not the
  default path. (Honest, and stronger for it.)
- **#3 memory cap** - two failure modes in one. File/cache pressure is
  **recoverable** (reclaim + refault I/O, ~5x slower); anonymous pressure
  with no swap is a **sharp OOM cliff** - below a threshold the kernel kills
  the worker and the task fails, though the agent survives and reports it.
  Also a sub-finding: a hard cap never OOMs a cache-only workload (clean
  cache is always reclaimable).
- **#4 disk I/O cap** - the fourth resource. Read bandwidth throttles
  linearly (wall ~ bytes/rbps) once the cap drops below native disk speed.
  Completes the quartet: CPU, scheduling, memory, disk.

## Takeaways for the paper

1. **It is not just the LLM.** Across four independent resources, a
   mis-set container limit adds 1.7x-4.7x wall time, or kills the agent's
   tools. Naser's "even 5% would be a finding" bar is cleared by a wide
   margin at realistic sandbox sizes.
2. **Regime, not blanket claim.** Agents are LLM-bound on an adequate box;
   the OS becomes first-order only past a per-resource configuration
   threshold. We locate each threshold.
3. **Two shapes of harm.** Bandwidth limits (CPU, disk, soft memory) cause
   recoverable *slowdown*; hard limits on unreclaimable resources
   (anonymous memory) cause *failure*. Over-parallelism is self-inflicted
   slowdown.
4. **Well-behaved harnesses help themselves.** Claude Code checks cores and
   avoids CPU oversubscription - so the danger is in the *configuration a
   user/platform imposes*, which is exactly the thing nobody profiles.
5. **All kernel-visible.** Every effect is both in the LTTng trace and in
   the cgroup's own counters, cross-validated - a reusable method for a
   fault catalogue, not one-off anecdotes.

## Open / parked

- LLM-wait vs idle is not separated within the "event-loop wait" bucket
  (needs API-socket fd attribution; the epoll return isn't decoded on this
  kernel). The headline results do not depend on it.
- No-swap VM: anon memory OOMs rather than swapping. A swap-enabled variant
  is parked (a different configuration).
- Possible 5th entries if needed: process/thread cap (`pids.max` -> fork
  EAGAIN), FD limit (`EMFILE`), DNS/network config. Parked unless the
  package needs more.
- Pending: read Naser's 3 OS-noise papers (CPU-noise one first) and match
  this writeup's shape to the model paper.
