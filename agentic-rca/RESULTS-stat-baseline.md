# Results — statistical baseline degradation sweep (RCA method #1)

**No-API reference results.** 93 labeled incidents (43 Train Ticket + 50 Sock Shop) × 15 degradation
conditions = **1,395 evaluations**, statistical/heuristic baseline (`baseline_stat.py`) over the four
tools. Sweep job 2074051 (Trillium, 53 min). Regenerate: `sbatch agentic-rca/sweep_stat.sbatch` then
`python agentic-rca/analyze.py "agentic-rca/results/sweep/*.json"`. Metric = Top-1 **both-hit**
(root-cause service AND fault type correct).

## RQ1 — robustness to degradation (both-hit %)

| axis | full | | | | |
|---|---|---|---|---|---|
| **trace** (100→5%) | 38 | 37 | 38 | 35 | **34** |
| **metric** (5→60 s) | 38 | 37 | 37 | 39 | |
| **log** (ALL→ERROR) | 38 | 38 | 38 | | |
| **kernel** (all→none) | 38 | 38 | 38 | 38 | |

**Finding:** the statistical baseline is **strikingly robust** to every degradation axis — it leans on
coarse, robust signals (the injected stress container, CPU throttling) that survive thinning. Split by
fault: **kernel-decisive faults stay flat at 54%** across *all* axes including full kernel removal (the
baseline never exploits kernel); **other-modality faults fall 9%→0%** as traces vanish (they need traces).

## RQ3 — kernel as safety net (per family, both-hit %)

| family | full | kNone | drop-K | expected |
|---|---|---|---|---|
| anomaly_cpu | 83 | 83 | 83 | kernel |
| anomaly_disk | 100 | 100 | 100 | kernel |
| anomaly_mem | 60 | 60 | 60 | kernel |
| noisy_neighbor | 100 | 100 | 100 | kernel |
| svc_cpu_cap | 50 | 50 | 50 | kernel |
| dependency_outage | 50 | 50 | 50 | traces |
| **slow_db** | **0** | **0** | **0** | kernel |
| **queue_backlog** | **0** | **0** | **0** | kernel |
| error_storm | 0 | 0 | 0 | logs |
| svc_mem_cap | 0 | 0 | 0 | logs |
| anomaly_net / svc_net | 0 | 0 | 0 | traces |

**Findings:**
1. **Removing kernel changes nothing** (full = kNone = drop-K for *every* family) — the statistical
   baseline is kernel-blind by construction.
2. It **completely fails the kernel-decisive blind-spot faults** `slow_db` and `queue_backlog` (0%),
   and the log/trace faults `error_storm`, `svc_mem_cap`, `*_net` (0%).
3. It **succeeds on the metrics-visible faults** via the injected stress container / throttle signals
   (cpu/disk/mem/noisy/cap 50–100%).

This is exactly the reference the study needs: it establishes the **ceiling of a metrics/logs/traces
statistical method** and pins the **gap the kernel-aware LLM agent must close** (RQ3 "kernel as safety
net") — recover `slow_db`/`queue_backlog`/`error_storm` and show real degradation sensitivity the
baseline lacks. Overall both-hit: **38%** (TT 44%, SS 32%).

*Caveat:* SS runs use kernel L1+L3 only (L2 not derivable on Trillium — CTF2; see progress-notes
08-08); TT uses L1+L2+L3. Doesn't affect the statistical baseline (kernel-blind), but matters when the
kernel-aware agent runs.
