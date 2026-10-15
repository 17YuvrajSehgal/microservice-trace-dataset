# Evaluating the svc_cpu_cap blueprint on agentic runs

Does `README_v1.md` (the kernel-trace RCA method for CPU-cap faults) correctly
diagnose a CPU cap on our **agentic** runs? Our Claude/Codex runs under
`cpu.max` *are* svc_cpu_cap faults, but on a very different application: an
AI agent that is bursty and LLM-bound, not a steady Sock Shop service.

Scope: CPU-cap runs only (`agentic-os-noise/runs/t3_implement_*`). Fault =
`t3_implement_cap25_r1` (0.25 core); baseline = `t3_implement_nocap_r1`
(uncapped). The slicing scripts need babeltrace2 (not local); the analytical
core (`sched_budget.py`) runs directly on our decoded `trace.txt.gz` dumps.

## Verdict

The blueprint's **method is correct**, but **out of the box it fails on the
agentic traces** for two reasons, both fixable:

1. **A kernel-portability bug silently zeroes the signal.** The blueprint's
   `sched_budget.py` counts a thread as "waiting for CPU" only when
   `prev_state == 0`. On this VM's kernel (7.0.0-gcp) a thread preempted
   while still runnable is reported as `prev_state == 256`
   (`TASK_REPORT_MAX`, the preempt flag), which the script buckets as
   "other" and ignores. Result: every agent thread shows **~0 wait**, so
   Steps 2--3 never flag a victim. (The README text even says "0 and 256 =
   wants CPU," but the code only handles 0 --- a doc/code mismatch.)
2. **It ignores `cpu.stat`.** The blueprint's "Not used" list excludes the
   rest of `meta/`, but `cpu.stat` holds the direct ground truth:
   `nr_throttled = 208`, `throttled_usec = 20.1 s` for this run. For a CFS
   bandwidth cap that single counter confirms the fault immediately.

After a **one-line fix** (count `prev_state` 256 as preempt-wait), the
blueprint works and pinpoints the victim.

## Evidence

`sched_budget.py` on the fault run, top process, before vs after the fix:

| | victim shown? | ≥1 / ≥10 / ≥50 ms waits | max wait |
|---|---|---|---|
| as written (count only state 0) | no --- agent threads ~0 wait | 2 / 0 / 0 | ~2 ms |
| fixed (count 256) | **yes** --- `python3` test runner | **126 / 126 / 126** | **89 ms** |
| baseline (uncapped), fixed | no (correct) | ~0 / 0 / 0 | <1 ms |

The 89 ms max freeze ${\approx}$ the 100 ms quota period, and the 126 freezes
of ${\ge}50$ ms are exactly the **burst-and-freeze** rhythm the blueprint's
Step 4 looks for. `cpu.stat` independently gives `throttled_usec = 20.1 s`
over 208 throttle events (${\approx}97$ ms each ${\approx}$ the period).

## Per-step assessment

| step | on agentic runs |
|---|---|
| 1. What was recorded | Works, but the meta differs: no `runinfo_start.txt` / `docker top`. Use `meta/root.pid` + `ground_truth.json` to find the victim PID instead. |
| 2--3. Victim via `sched_budget` wait | **Fails as written** (preempt coded 256, ignored). **Fixed:** victim (`python3`) jumps out with 126 long waits; baseline shows none. |
| 4. Burst-and-freeze rhythm | Present: freezes up to 89 ms ${\approx}$ the quota period. Detectable. |
| 5. Rule out lookalikes | Holds: victim `D${\approx}$0` (not disk), `S` low during bursts (not lock/net). |
| 6. Estimate limit (`run ${\approx}$ quota`) | **Fails on the whole-run average** (victim `run${=}0.09$, diluted by idle): the agent is ${\approx}84\%$ idle waiting on the LLM, so `swapper` dominates. Must slice to the active burst, where `run` approaches the cap. |
| 7. RCA statement | Template fine. |

## Why agentic workloads break the assumptions

- **Bursty + LLM-bound.** Sock Shop was under continuous load, so the throttled
  victim was always runnable and the whole-run average read near the quota.
  The agent is idle ${\approx}84\%$ of the run (blocked on the model), so
  whole-run averages are diluted and **slicing to active windows is
  mandatory**, not optional.
- **CFS throttle is only partly a per-thread "wait."** When the quota is
  exhausted the kernel dequeues the whole cgroup; the preempt-coded freezes
  (state 256) recover ${\approx}$ half the 20 s as visible per-thread wait ---
  enough to diagnose --- but `cpu.stat` is the only exact total.
- **Kernel-version drift.** The state-code assumption (preempt == 0) was fine
  on the dataset's older kernel; it breaks on 7.0.0. (Our own
  `analyze_run.py` shares this and is why its trace `runnable_wait`
  under-counted throttle --- we worked around it by trusting `cpu.stat`.)

## Recommendations for a v2 blueprint

1. **Fix the state decode** in `sched_budget.py`: treat `prev_state & 0x100`
   (256) as preempted-while-runnable (wait), and `& 0xFF` for the base
   sleep state. Print the codes seen (it already does) and map generically.
2. **Add a `cpu.stat` cross-check** as Step 0: `nr_throttled > 0` and
   `throttled_usec` is a one-line, direct confirmation of a CFS cap --- cheap
   and kernel-independent. Promote `meta/cpu.stat` from "not used" to a
   primary signal.
3. **Auto-pick the active window** for bursty agents: compute the budget over
   the slice(s) where the victim's `run > 0`, not the whole run, so Step 6's
   `run ${\approx}$ quota` estimate works.
4. Keep Steps 4--7 --- the burst-and-freeze rhythm and the RCA template
   transfer unchanged.

## Bottom line

The blueprint **does** capture svc_cpu_cap on agentic runs --- the throttle
signature (long periodic CPU freezes ${\approx}$ the quota period) is clearly
present --- but only after a one-line kernel-portability fix and, ideally, a
`cpu.stat` cross-check. The agentic workload is a good stress test: it
exposed a silent state-code bug and the whole-run-averaging assumption that a
steady-load dataset never would.
