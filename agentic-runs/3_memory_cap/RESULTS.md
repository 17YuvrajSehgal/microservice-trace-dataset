# Problem #3 results — memory cap

Data: **44 runs**, VM `agentic-noise` (4 vCPU, 16 GB, no swap),
2026-10-13. From `analysis/aggregate_mem.py`. Three parts. Category:
**configuration-level** (a container memory limit set too low).

## Headline

A container memory limit hurts an agent in two distinct ways, and which one
depends on whether the pressed memory is reclaimable:

- **recoverable** (file/cache pressure): the agent survives but slows ~5x
  as evicted pages are re-read from disk (refault I/O).
- **catastrophic** (anonymous pressure, no swap): a sharp OOM cliff — below
  a threshold the kernel kills the tool mid-task and the task fails.

## Part A — recoverable slowdown (memory.high), 20 runs

Workload: read a 1 GB file 5x. Agent + file working set ~= 1.38 GB.

| memory.high | n | phase wall | refault pages | events[high] |
|---|---|---|---|---|
| max (unltd) | 5 | 6.5 s | 0 | 0 |
| 1536M (> 1.38G) | 5 | 6.5 s | 0 | 0 |
| 1152M (< 1.38G) | 5 | **30.4 s** | 1,049,673 | 8,505 |
| 768M | 5 | **30.4 s** | 1,049,884 | 9,296 |

- Clean threshold at the working-set size: fits -> 0 refaults, fast;
  doesn't fit -> ~1.05 M refaults and a **4.7x** slower phase. Reproducible
  to <0.1% across 5 reps.
- Mechanism note: the reclaim *CPU* stall is tiny (~0.16 s) - the cost is
  the refault disk I/O (the agent re-reads ~4 GB over the 5 passes), not
  reclaim itself. `memory.high` throttles the cgroup (8-9k `high` events)
  but never kills - recoverable, as designed.

## Part B (file workload, memory.max), 12 runs — a finding in itself

| memory.max | n | oom_kills | refault | outcome |
|---|---|---|---|---|
| 2G | 3 | 0 | 0 | fits, fast |
| 1280M | 3 | 0 | 1.05 M | reclaim, survives |
| 1024M | 3 | 0 | 1.05 M | reclaim, survives |
| 768M | 3 | 0 | 1.05 M | reclaim, survives |

**A hard `memory.max` does not OOM a cache-heavy workload** - clean file
cache is always reclaimable, so the kernel reclaims (same refault cost as
Part A) instead of killing, even at a tight hard cap. The OOM cliff needs
*unreclaimable* (anonymous) memory -> Part B cliff.

## Part B cliff — the OOM threshold (memory.max + anon), 12 runs

Workload: allocate + touch 512 MB anonymous. Agent (~250 MB) + 512 MB
~= 762 MB.

| memory.max | n | oom_kills | task failed | verdict |
|---|---|---|---|---|
| 1024M | 3 | 0 | 0 | ok |
| 896M | 3 | 0 | 0 | ok |
| 768M | 3 | 0 | 0 | ok |
| 640M | 3 | **3** | **3** | **OOM** |

- **Sharp, binary, reproducible cliff between 640M and 768M** (= the
  agent+workload footprint). 3/3 pass above, 3/3 fail below. This is H3
  (step function, not gradual).
- Nuance: the OOM killer kills the **worker** (biggest anon consumer), not
  node - so `agent_exit = 0` but `task_check = 1`: the agent **survives and
  reports the failure**. "Your sandbox memory limit silently kills your
  tools mid-task" - a configuration failure mode, not a crash of the agent.

## Hypotheses (pre-registered in PLAN.md)

- H1 (fits -> no refault): confirmed (high:max / 1536M -> 0).
- H2 (dose-response): confirmed, though the refault metric saturates once
  the file no longer fits (file is re-read in full every pass); phase-wall
  carries the cost.
- H3 (sharp OOM cliff): confirmed, 640M vs 768M, 3/3 each side.
- H4 (does the agent adapt?): it does not pre-empt, but it **survives** the
  worker's OOM and reports the failed task rather than dying.

## Caveats

- **No swap** (GCP default): so anon pressure = OOM, file pressure =
  recoverable. Both regimes shown; a swap-enabled variant is parked.
- Agent RSS varies run to run (LLM path), so the cliff is a narrow band,
  not a single byte - we bound it (640-768M) rather than claim a point.
- Disk speed (pd-balanced) sets the refault cost; a slower disk = bigger
  Part A effect, so our numbers are conservative.
- The `vmscan_*` -> `mm_vmscan_*` event-name fix (see 13-10 notes) was
  needed for reclaim to appear in the trace at all.
