# StrataTrace — Results Ledger

Durable, paper-facing record of measured results (numbers to cite). Complements the
narrative in `progress-notes/` and the status in `progress-01-08-2026.md`. Last updated
2026-08-02.

---

## Dataset composition
- **v1:** 40 runs / 164 GB / 8 fault families, six modalities time-aligned (Phase-0 gate:
  clocks 0.001 ms drift, kernel 2.3 M events).
- **Wave-2 (2026-08-01):** **15 runs** across 5 new fault recipes × REPEATS=3, **all
  confirmed** end-to-end. Fills RQ1's "confusable resource faults" (F2/F3/F4), the
  memory-layer kernel signature (F3/F8), and service-localized netem (F12).
- Storage: kernel channels gzipped (~4 GB/run; raw ~19–23 GB for resource-stress +
  KERNEL_MEM). Verified analysis-ready (decode round-trips: 45.7 M / 46.2 M events).

## RQ1 — fault → winning modality (wave-2, all confirmed)
| Fault | Recipe | Winning modality | Signature |
|---|---|---|---|
| host disk (F2) | `anomaly_disk` ×3 | kernel | block-I/O io_time 0.04→0.66 |
| host net (F4) | `anomaly_net` ×3 | traces | per-netns netem → catalogue p95 up |
| host memory (F3) | `anomaly_mem` ×3 | kernel | **2.95 M `mm_vmscan_`** reclaim events |
| svc mem cap (F8) | `svc_mem_cap` ×3 | kernel+metrics | cgroup limit-drop |
| svc net (F12) | `svc_net` ×3 | traces | carts p95 0.04→**9.9 s** |

**anomaly_mem kernel signature (the F3 headline):** MemAvailable 0.85→0.02 + steady swap
1→8.5 GB, and **2.95 M `mm_vmscan_` events** — `write_folio` 2.5 M (swap-out),
`lru_shrink_inactive` 105 K, `lru_isolate` 191 K, `shrink_slab` 69 K, `direct_reclaim` 3.1 K,
kswapd cycling. (Kernel recipe fact: this kernel has **no `kmem_*`**; the memory signal is
`mm_vmscan_*` + `writeback_*`, captured via `KERNEL_MEM=1`.)

## RQ4 — collection overhead (the "rare asset")
Fair rotated protocol, 200 users, **warmed 4 repeats** (`collect_overhead.sh`):
| Metric | baseline | lttng_only (kernel tracing) | Overhead |
|---|---|---|---|
| Throughput (req/s) | 194.2 ± 0.5 | 193.3 ± 0.3 | **−0.5%** |
| P95 latency (ms) | 45.1 ± 2.0 | 50.7 ± 2.0 | **+12.6%** |
| P99 latency (ms) | 244.9 ± 16 | 259.5 ± 25 | **+6.0%** |
| Error rate | 2.53% | 2.54% | flat |

**Headline: kernel tracing costs ≈0.5% throughput + ~13% P95 latency at 200 users** —
modest and well-characterized. (Methodology note: warmup is required — a cold first run at
low repeats inflated baseline P95 std to ±31 ms and produced a spurious −27.6%; with a 30 s
warmup the std collapsed to ±2 ms and the real overhead resolved at ~2.8σ.)

## Agentic MVP (Track B) — decisive-modality attribution
4 faults, 4 different decisive modalities, all correct vs hidden ground truth (replay):
| Fault | Decisive modality | Separation |
|---|---|---|
| slow_db | kernel + traces | 31.8× |
| noisy_neighbor | kernel-only | 13.3× |
| dependency_outage | traces + kernel | 27.6× |
| error_storm | logs + metrics | 2.0× |
Plus a validated live-capture path (scoped LTTng + fault inject under real load → correct
live verdict).

## Environment / storage facts
- VM: GCP Ubuntu 24.04, LTTng 2.15, Babeltrace2, Docker 27+, 39 GB RAM + 16 GB swap
  (persisted `/etc/fstab`), us-east1-d. Currently STOPPED.
- All overhead/performance numbers are VM-only (never laptop/WSL).
- Overhead artifacts: `~/experiments/overhead_wave2_clean/` (cite) + `overhead_wave2/` (first
  pass, kept for the record).
