# Campaign results — agentic OS-noise (CPU cap)

Data: **40 runs**, 2 tasks x 4 caps x **5 reps**, VM `agentic-noise`
(4-core n2-standard-4), 2026-10-12/13. Medians per cell. Numbers from
`analysis/aggregate.py`; per-run detail in `analysis/results/campaign.json`.

## Headline

An agent's compute demand is **fixed** (~4-5 CPU-s regardless of cap).
Tightening the CPU cap does not reduce the work — it converts compute into
**waiting** (CFS throttle), and past a threshold the sandbox config, not
the LLM, is the bottleneck.

| task | cap | wall_s | on_cpu_s | throttled_s | wall vs uncapped |
|---|---|---|---|---|---|
| t2 fix | uncapped | 23.4 | 4.4 | 0.0 | — |
| t2 fix | 1 core | 24.4 | 3.7 | 0.3 | +4% |
| t2 fix | 0.5 core | 22.4 | 3.7 | 4.4 | -4% (see note) |
| t2 fix | 0.25 core | 28.9 | 3.9 | 13.7 | **+24%** |
| t3 impl | uncapped | 18.7 | 5.2 | 0.0 | — |
| t3 impl | 1 core | 18.7 | 5.0 | 0.5 | +0% |
| t3 impl | 0.5 core | 23.7 | 5.2 | 6.3 | **+27%** |
| t3 impl | 0.25 core | 32.7 | 5.3 | 19.8 | **+75%** |

## What the n=5 data establishes

- **The throttle ladder is rock solid** and monotone in both tasks:
  ~0 → 0.3-0.5 → 4.4-6.3 → 13.7-19.8 s. It is cgroup ground truth
  (`cpu.stat`), not inference.
- **on-CPU stays flat across caps** per task — the cap adds wait, not work.
- **t3 gives the clean dose-response curve**: 0% → +27% → +75% wall
  inflation. This is the figure for the paper.
- **Regime result**: uncapped/1-core agents are LLM-bound (~90%+ of
  main-thread time in the event loop); at 0.5 core and below the OS share
  becomes first-order (throttle = 19-60% of wall equivalents).

## Honest notes

- **t2 at mild caps**: wall inflation stays within LLM-latency noise even
  at n=5 (the -4% cell) — t2's event-loop wait (~20-22 s) varies more
  between runs than the ~4 s the cap adds. For t2, report throttle share
  (ground truth), not wall inflation, at <=0.5 core. t3 shows wall
  inflation cleanly because its local-compute share is higher.
- **Outlier**: `t3_implement_nocap_r5` traced 271 MB (agent took a long
  path; still solved). Median absorbs it; kept in the data.
- "eventloop wait" still mixes true LLM-wait with idle (see
  `analysis/README.md`); the headline does not depend on that split.
- One transient LTTng error ("Failed to format string") killed the first
  top-up campaign mid-run; the partial run was deleted and re-collected.
  All 40 final runs verified agent_exit=0, task_check=0, no tampering.
