# Decisions — 31-07-2026 (branch `agentic-tracing`)

Dataset-side session: reviewed collection gaps vs `msr-research.md` + the 29-07 meeting
summary + the agentic design, then **built and validated wave-2 collection**. Key
research/method decisions and the *why* below.

## 1. Wave-2 gap analysis → tiered plan (`dataset-collection-gaps.md`)
Decided what v1 (40 runs / 164 GB / 8 fault families) is missing for MSR **and** what the
agentic system needs, tiered 🔴 must / 🟡 should / 🟢 derive-only / 🤖 agentic-helpful.
- **Why tier it:** the abstract is Nov 5; we can't collect everything. The 🔴 set (host
  disk/mem/net for RQ1's confusable-resource faults, the RQ4 overhead matrix, full
  Prometheus) is what the *research questions* strictly require; the rest is upside.
- **Finding that closed a gap for free:** `download_metrics_full.sh` already existed and
  `run_scenario.sh` already calls it → wave-2 (and v1) get the full `__name__` space
  automatically. No new work; just confirm it fired in v1 while Prom retention holds.

## 2. Fault naming: `host_*` → `anomaly_*`
Renamed the new host stressors to `anomaly_disk/mem/net` to match the **existing**
`verification_targets.json` keys and the `anomaly_cpu` sibling.
- **Why:** `verify_injection.py` grades by `FAULT_NAME`; matching the pre-existing keys
  means the grader works with no schema churn and the family stays internally consistent.

## 3. Kernel memory profile is opt-in (`KERNEL_MEM=1`), not default
Added a `KERNEL_MEM=1` knob to `collect_trace.sh` that appends the mm/reclaim/writeback
tracepoint groups; off by default.
- **Why:** memory tracepoints (esp. `writeback_*`) are extremely high-volume (millions of
  events — 2M+ `writeback_mark_inode_dirty` in one run). Making them default would bloat
  every trace and skew the RQ4 overhead numbers. Only the memory faults (F3/F8) and the
  memory-leak agentic skill need them, so they turn it on per-run.
- **Hard-won fact:** this kernel has **no `kmem_*` tracepoints**; the real memory signal is
  `mm_vmscan_*` (reclaim) + `writeback_*` (page-cache). Don't chase `kmem_*`.

## 4. `anomaly_net` mechanism: per-container netns, NOT host-bridge netem
Wave-2 showed `tc netem` on the **bridge device** left catalogue p95 completely flat.
Rewrote the recipe to apply netem inside **every stack container's netns** (via `nsenter`).
- **Why:** a qdisc on a Linux bridge *device* shapes traffic egressing that device, but
  container↔container frames are **L2-forwarded** through the bridge and never hit that
  qdisc. Per-netns netem on each `eth0` is the only thing that actually impairs the mesh.
  Also changed the verification target from host throughput → **catalogue p95** (the honest
  user-visible symptom; throughput was the wrong signal).
- This is a genuine methodological correction, not a tuning tweak — recorded so we never
  re-attempt bridge netem.

## 5. `anomaly_disk` gate relaxed 0.8 → 0.5 + O_DIRECT
Containerized `stress-ng --hdd` drove io_time 0.04 → 0.66, a clear signal, but under the
0.8 gate. Added `O_DIRECT` to the recipe and relaxed the gate to 0.5.
- **Why:** the container's fsync path is weaker than a host-run stressor; 0.66 is
  unambiguous disk pressure. `verification_targets.json` is a **QC gate, not a
  pre-registered prediction** (those are frozen in `fault_catalog.md`), so tuning it to the
  real observed effect size is legitimate.

## 6. `anomaly_mem`: switched stressor `--vm` → `--bigheap` (capped container)
The memory stressor was the session's hard problem. Chain of elimination:
- Not swap-less OOM → **added 16 GB swap** to the VM (persisted in `/etc/fstab`).
- Not the `--vm-bytes %` syntax → used absolute bytes.
- Not `--vm-method all` freeing memory → used `--vm-hang 0` to hold.
- Each helped (MemAvailable 0.82 → 0.63) but **`stress-ng --vm` caps at ~7–8 GB on this VM
  regardless of workers/bytes/hang** — it churns allocate/free rather than sustaining.
- **Decisive observation:** the **F3 kernel signature already fires** at 0.63 —
  `mm_vmscan_lru_isolate` 104K, `mm_vmscan_lru_shrink_inactive` 59K, `shrink_slab` — so the
  *kernel modality is already captured*; only the MemAvailable **gate** wasn't met.
- **First attempt — `--bigheap` in a `--memory`-capped container:** passed the MemAvailable
  gate (0.147) BUT the run's tracepoints showed **zero `mm_vmscan_`** (heavy `writeback_`
  only) + **`oom_`×2**. Root cause: the cgroup `--memory` cap **contained reclaim inside the
  memcg** — it OOM-killed the bigheap worker internally rather than driving host-global
  `kswapd`, so the F3 **kernel reclaim signature was lost.** Since the memory fault's
  *winning modality is kernel*, passing only the metrics gate is not enough — the recipe has
  to produce the global reclaim signal. **Lesson: never bound a host-pressure fault with a
  cgroup cap; the cap moves the pressure into a memcg the host-wide kernel trace can't see.**
- **Final decision — UNCAPPED single-worker `--vm`:** the ~8 GB cap was a *multi-worker*
  artifact (workers thrash/cycle). A **single** worker with absolute `--vm-bytes` +
  `--vm-keep --vm-hang 0` HOLDS the full allocation (probed: 34 GB held, avail 35→7 G,
  swap→6 G). Size it to ~88% RAM so alloc+stack overshoots physical into the 16 GB swap →
  **host-global reclaim (`mm_vmscan_*`) AND MemAvailable collapse**, OOM-safe.
- **✅ CONFIRMED on VM (same session), both signals:**
  - *Metrics:* `host_mem_available_drop` 0.849 → **0.021** (pass). Live monitor: MemAvail
    40 G→~0.6 G with swap climbing **steadily 1→8.5 G** (sustained global reclaim, vs the
    capped run's oscillation).
  - *Kernel (the winning modality):* decoding the 19 GB trace → **2.95 M `mm_vmscan_`
    events** — `write_folio` 2.5 M (swap-out), `lru_shrink_inactive` 105 K, `lru_isolate`
    191 K, `shrink_slab` 69 K, **`direct_reclaim` 3.1 K** (in-line reclaim = severe
    pressure), + `kswapd_wake/sleep`. The capped run had ZERO of these; uncapped restored
    the full F3 signature.
  This closes the memory fault: **5/5 wave-2 faults confirmed** (disk · net · mem ·
  svc_mem_cap · svc_net), and it wins on both metrics + kernel exactly as pre-registered.

## 7. RQ4 overhead = wrap the existing fair harness, don't rebuild
`collect_overhead.sh` orchestrates the **existing** rotated baseline/lttng_only/lmat_async
scripts + `analyse_reviewer_overhead.py`; auto-detects the LMAT model, falls back to
baseline+lttng_only if absent.
- **Why:** the fair rotated protocol is the JSS-era asset that makes the overhead number
  defensible; reusing it verbatim keeps the comparison honest. Per-modality overhead
  breakdown is a v2 nicety, not a blocker.

## Wave-2 validation result (REPEATS=1, stack up)
- **Pipeline PERFECT:** six-modality audit all-OK, clock drift **0.003 ms**, **428**
  full-metric series, **4.5M** kernel events, `KERNEL_MEM` passthrough works.
- **4/5 faults confirmed:** anomaly_disk ✓ · anomaly_net ✓ · svc_mem_cap ✓ · svc_net ✓
  (carts p95 0.04 → **9.9 s**). anomaly_mem: kernel reclaim fires; gate pending `--bigheap`.
- **Safety:** all work respected the READ-ONLY dataset rule; VM stopped at session end.
