# Problem #3: memory cap — experiment design

Date: 2026-10-13. Third entry in the "OS noise for agentic AI" catalogue.
Reuses the rig from `../1_svc_cpu_cap/agentic-os-noise/`. Category:
**configuration-level** — a container `memory.high`/`memory.max` set too
low. No code bug, no kernel bug. The memory analog of problem #1's CPU cap.

## The question

Sandboxed agents run under a container memory limit. When the agent plus
its workload press against that limit, what does the kernel do, and how
much latency (or outright failure) does it add? Two regimes:

- **recoverable** (soft limit, `memory.high`): the kernel reclaims and
  throttles the cgroup; the agent slows but survives.
- **catastrophic** (hard limit, `memory.max`): reclaim can't keep up and
  the kernel OOM-kills a process — the agent or its tool dies mid-task.

## Mechanism (what the kernel trace + cgroup counters show)

- Problem #1's noise was CFS throttle; #2's was run-queue wait. #3's is
  **reclaim + refault I/O**: pages get evicted to stay under the cap, then
  re-read from disk on next touch.
- Trace signature (profile already has it — `vmscan_* block_* writeback_*`):
  - `mm_vmscan_*reclaim_begin/end` — direct/memcg reclaim episodes per task
    (sum = reclaim stall time, the memory analog of runnable_wait).
  - `block_rq_issue/complete` reads during the workload phase = refault I/O.
- Ground truth (the `cpu.stat` analog, snapshot before/after):
  - `memory.events`: `high` (times throttled), `max`, `oom`, `oom_kill`.
  - `memory.stat`: `pgscan`, `pgsteal`, `workingset_refault`, `pgmajfault`.
  - `memory.peak`: peak usage (sizes the caps).

## Key design choice: the agent is memory-heavy

node/claude RSS is ~0.5-1 GB, so a cgroup memory limit hits the agent too,
not just the workload. We embrace the realistic container framing (the
sandbox squeezes everything) and **size caps relative to the agent's
measured baseline**:

- **Profiling run first**: uncapped, read `memory.peak` for a plain t2/t3
  run -> call it B (expect ~0.6-1.2 GB). All caps below are B + headroom.

## Workload: file-backed page-cache pressure (recoverable, no swap needed)

GCP VMs have no swap, so **anonymous** pressure = instant OOM, not stall.
File-backed page cache is the clean recoverable signal: evicting clean
cache is cheap, the cost is the re-read on next access.

- Task `t6_memtouch`: creates a file of size F (e.g. 1 GB) and a worker
  (comm `ttmem`) that reads it sequentially **K times**. Agent prompt: "run
  ./touch_all.sh and report total bytes read."
  - cap >= B + F: file stays cached, passes 2..K are free -> fast.
  - cap < B + F: each pass evicts the previous -> every pass re-reads from
    disk -> slow, high `workingset_refault`, block-read I/O.

## Part A — recoverable dose-response (memory.high)

- `memory.high` levels relative to baseline B and file F:
  roomy (B + 1.5F), snug (B + 0.5F), tight (B + 0.1F), plus uncapped. 4 cells.
- 5 reps each = **20 runs**. Shuffled, resumable (own `~/runs_t6`).
- Metrics per run: workload-phase wall, subtree reclaim-stall time,
  block-read bytes, vs ground-truth `workingset_refault` / `pgscan` /
  `memory.events[high]`. Headline: wall inflation + refault count vs cap.

## Part B — the OOM cliff (memory.max)

- Lower `memory.max` toward B until a process is OOM-killed. Levels:
  1.5B, 1.1B, 0.9B, 0.7B (0.9B and below should kill). 3 reps = **~12 runs**,
  but stop early per level once the cliff is located.
- Outcome is a **failure curve**, not latency: at each level record
  `memory.events[oom_kill]`, agent_exit, task_check (did the task fail?),
  and which process died (from `sched_process_exit` / the OOM in dmesg-like
  `oom` counter). The finding: "below ~X MB the agent is killed mid-task" —
  a configuration that silently breaks agents.

## Pre-stated hypotheses (evidence-first)

- **H1**: with cap >= B + F, repeated reads stay cached — near-zero refault,
  flat wall across K.
- **H2 (dose-response)**: as `memory.high` drops below B + F, workload-phase
  wall and `workingset_refault` rise together; reclaim-stall time grows.
- **H3 (cliff)**: below `memory.max` ~= B, `oom_kill` > 0 and the agent's
  task fails (agent_exit != 0 or task_check != 0) — a sharp threshold, not
  a gradual slowdown.
- **H4**: the agent does/does not adapt to memory pressure (does it retry,
  back off, or just die?) — observed from agent.log, like #2 Part B.

## Rig changes needed

1. `collect_agent_run.sh`: add a memory knob. Simplest — a 5th arg
   `MEM_LIMIT` written to `memory.high` or `memory.max` (prefix like
   `high:B+...` / `max:...`); snapshot `memory.events`, `memory.stat`,
   `memory.peak` before/after into meta. (CPU `cpu.max` stays as is; a run
   sets one or the other.)
2. New task `tasks/t6_memtouch.sh` (file + ttmem reader, K passes, F/K from
   TASK_ARG).
3. `analyze_run.py`: add reclaim-stall time (sum of mm_vmscan reclaim
   begin/end per subtree tid), block-read bytes in the workload phase, and
   surface the memory.events/stat deltas. phase window keys on `ttmem`.
4. `run_campaign_t6.sh` for the memory grid.

## Confounds, stated up front

- **No swap**: anon pressure OOMs rather than stalls; we use file cache for
  the recoverable part and say so. (Could add a swap file as a variant — a
  separate configuration, parked.)
- The agent's own RSS varies run to run (LLM path) -> baseline B is a
  distribution; size caps off its upper end and report B's spread.
- Disk speed sets the refault cost; pd-balanced is fast, so the effect is
  conservative (slower disk = bigger effect). State the disk type.
- LLM variance handled as before (fixed prompt, fresh repo, shuffle, n=5).

## Run budget

profiling (~3) + Part A (20) + Part B (~12) ~= **35 runs**, one VM session.
Analysis local, same as #1/#2.
