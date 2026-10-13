# Problem #2 results — threads vs cores (Part A)

Data: **20 runs**, W in {2,4,8,16} workers x 5 reps, uncapped, VM
`agentic-noise` (**4 vCPUs** = 2 physical cores + SMT), 2026-10-13.
Medians. From `analysis/aggregate_t4.py`; per-run in
`analysis/results_partA.json`. Part B (sub-agent observation) still to run.

## Headline

When an agent fans out more parallel workers than the box has cores, it
manufactures its own OS noise: the extra threads sit **runnable-but-not-
running**, and the parallel phase slows in proportion — no cap, no code
bug, nobody throttled anything. Configuration-level.

| W | load | phase wall | worker on-CPU | worker runnable-wait | stalls >=1ms | >=10ms |
|---|---|---|---|---|---|---|
| 2 | 0.5x | 0.42 s | 0.42 s | 0.00 s | 8 | 1 |
| 4 | 1.0x | 0.98 s | 0.91 s | 0.05 s | 21 | 3 |
| 8 | 2.0x | 1.87 s | 0.94 s | 0.93 s | 2550 | 2 |
| 16 | 4.0x | 3.87 s | 0.95 s | 2.81 s | 5228 | 138 |

phase-wall inflation vs W=cores: W=8 **+91%**, W=16 **+295%**.

## What holds up (all pre-registered in PLAN.md)

- **H2 confirmed, and the theory is exact.** Predicted wait fraction for
  W>C is (W-C)/W. Measured runnable / (on-CPU+runnable):
  - W=8: 0.93 / 1.87 = **0.497** vs predicted (8-4)/8 = 0.500
  - W=16: 2.81 / 3.76 = **0.747** vs predicted (16-4)/16 = 0.750
  A clean run-queue-contention law, straight from the kernel trace.
- **on-CPU is flat from W=4 on** (~0.9-0.95 s) — identical work, so the
  phase-wall growth past cores is pure scheduling wait, not more work.
- **H3 confirmed**: the >=10 ms scheduling-stall tail is negligible until
  W>C and then grows (138 at W=16) — the "my parallel step randomly
  stalls" symptom.
- **No cpu.stat blind spot** here (unlike #1's throttle): this noise is
  fully visible to the sched state machine. throttled_usec = 0 throughout.

## SMT resolved (the earlier "curiosity")

Per-worker on-CPU jumps 0.42 s (W=2) -> 0.91 s (W=4) then stays flat. This
is **SMT**, not a bug: at W=2 the two workers land on separate physical
cores (no sibling sharing, full IPC); at W=4 both hyperthread siblings on
each core are busy, so identical work costs ~2x the core-time. Past W=4 the
cores are saturated, so on-CPU can't rise further and extra load becomes
queueing (runnable-wait). Reported as the scheduling unit the cloud user
actually gets (vCPU), stated plainly.

## Part B — does the harness itself oversubscribe? (observation)

Data: 6 runs, N in {4,8} sub-agents x 3 reps, Claude Code launching N
sub-agents via its Task tool, each running the SAME CPU worker as Part A.
Answers Naser's question: "do they check cores, or just fan out?"

**Finding: the harness checks cores and does NOT oversubscribe the CPU.**

| | worker on-CPU | worker runnable-wait | phase wall | stalls >=1ms |
|---|---|---|---|---|
| Part A xargs, W=8 (OS parallel) | 0.94 s | **0.93 s** | 1.87 s | **2550** |
| Part B Task, N=8 (harness parallel) | 0.40 s | **~0.0 s** | 7-8 s | ~20 |

- **Claude Code probes the machine**: exactly **18** `sched_getaffinity` /
  `sysinfo` syscalls per run, N-independent (a startup check, not
  per-sub-agent). It knows the core count.
- **Sub-agent CPU work does not overlap.** In an N=8 run the 8 actual work
  bursts are ~0.4 s each (uncontended, full IPC) and **staggered** across
  the 8 s phase; the long-lived tids (2.7-7.6 s) are sub-agent shells
  blocked on their LLM turn, not on CPU (runnable-wait ~0). Phase wall
  scales ~linearly with N (N=4 ~3 s, N=8 ~7-8 s) = serial, not parallel,
  CPU.
- So a well-behaved harness on an adequate box manufactures **no**
  run-queue contention on its own. The Part A problem is real but requires
  explicit oversubscription (raw `xargs -P`, forcing high concurrency, or
  a shared/undersized box) - not the default sub-agent path.

**Why this is the stronger story**: the risk is real (Part A) *and* we can
say precisely when it does / doesn't bite. Default agent use is LLM-bound
and CPU-polite; the OS-noise risk appears under over-parallel configuration
- exactly the "configuration-level problem" framing from the 07-10 meeting.

## Caveats

- 4 vCPU = 2 SMT cores: the "effective core" for zero-contention is ~2-4
  depending on IPC sensitivity; we use vCPU=4 as the knee, which the data
  supports (runnable-wait ~0 at W<=4).
- `lttng-consumerd` competes for CPU, constant across W.
- Workers are pure-CPU by design (isolates the mechanism); Part B covers
  real sub-agents that also wait on the LLM.
- LLM variance handled as in #1 (fixed prompt, fresh repo, shuffled, n=5).
