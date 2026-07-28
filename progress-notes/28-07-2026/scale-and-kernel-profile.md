# Campaign scale + kernel event profile decided (28-07-2026)

## Scale: ~40 runs (was inflated to 150–200)
150–200 was a leftover from the abandoned OmniMicro benchmark ambition and is
infeasible/inappropriate for a focused dataset paper. Reframed: a dataset
paper needs *diverse, well-labeled* incidents, not thousands of runs — fault
diversity > repeats. Finalized matrix (msr-research.md §5):
- Normal: 3 repeats × {steady, burst} = 6
- 8 core faults × aggressive × 3 repeats × steady = 24
- 3 intensity-sensitive faults × subtle × 2 repeats = 6 (RQ5)
- 2 faults × burst × 2 repeats = 4 (RQ5)
- **≈ 40 runs total.**
Answers every RQ with variance where it matters; comparable to peer datasets
(OpenRCA 68 GB). Campaign wall-clock ≈ 1–2 days (was ~3 wks).

## Kernel profile: CURATED, memory excluded (advisor guidance)
Advisor: collect syscalls + filesystem + process + network + sched; **exclude
memory events for sure** (they are the expensive, high-volume class);
"continue with less expensive ones, see if more is required later."

Implemented in `collect_trace.sh` as `KERNEL_EVENTS=curated` (default):
- all syscalls (`--syscall --all`) — covers fs read/write/open, process
  fork/exec/exit, network socket/send/recv at the syscall boundary;
- tracepoint families: `sched_* block_* net_* netif_* napi_* skb_* sock_*
  tcp_* udp_* irq_* softirq_*` (best-effort per kernel);
- **EXCLUDED**: kmem_*/mm_*/page-fault/reclaim (memory), and timer_* (very
  high volume, not requested).
`KERNEL_EVENTS=all` retained for ~3 full-capture showcase runs (preserves the
"full kernel capture" claim).

**Why:** L1/L2 analysis (wait attribution) reads syscalls + sched, so the
curated set covers the analysis; memory faults' kernel signal is intentionally
limited (verified via metrics limit-drop anyway) and revisitable per advisor.
**Effect:** ~2–3 GB/run vs ~8 GB → ~40 runs ≈ ~100 GB raw, fits the 200 GB
disk, **no GCS streaming needed**. Tiers: Lite ~20–30 GB (L1–L3 + app
modalities, Zenodo DOI); Full ~100 GB (+ raw curated CTF), shippable whole.

**Validation note:** the curated enable-event list is syntax-checked but not
yet run on the VM — the first Phase-2 run confirms which wildcards match this
kernel and the actual per-run size. (Some families may match nothing and are
best-effort `|| true`.)
