# Decisions — 03-08-2026 (branch `agentic-tracing`)

Built L2 + L3 derivers, then **validated the whole kernel ladder + loader on real VM data**.
Key outcomes and decisions:

## 1. Loader SDK — fully validated on the real run layout
`load_run()` against `anomaly_mem_aggressive_steady_r1`:
- spans **2.64 M** rows (OTLP `resourceSpans` unwrapped → per-span: service, trace/span id,
  dur_ms, attrs; front-end 1.9M, carts 646K, max dur 1232 ms)
- metrics **248 K** rows / **427** distinct metrics · logs **1.01 M** rows / 10 containers ·
  load **95 K** rows · ground_truth + verification.
- **Two layout fixes (validated):** metrics/load are **siblings** of the run
  (`$HOME/<run_id>_metrics`, `$HOME/<run_id>_load.csv`), not inside it → added `_sibling_dir`
  resolver + `load()`. spans.jsonl is OTLP-nested → added `_flatten_otlp`.

## 2. L1 performance — the bt2-python reader was unusable; switched to a fast CLI reader
- **Finding:** the bt2 **python** message iterator does ~20 K events/s — on the anomaly_mem
  trace (**333 M events!** — memory-pressure sched/syscall/writeback storm) it ran 65 min and
  only reached 80 M, and its unbounded latency-sample lists RAM-pressured the VM (SSH dropped).
- **Fix:** `--reader cli` (now default) — `babeltrace2` subprocess (C decode) + minimal
  **str** parsing (no per-line regex/objects). Measured **~15×**: 333 M events in **26 min**
  vs ~4 h projected for bt2. Also capped latency samples per bucket (`_LAT_SAMPLE_CAP=20 K`)
  so percentiles stay accurate without unbounded memory. bt2 reader kept as `--reader bt2`
  cross-check. **Lesson: never full-read these traces via bt2-python; use the CLI reader.**

## 3. Full ladder validated end-to-end (L1 → L3)
- **L1** KPIs all populate correctly: reclaim 3.98 M, writeback 5.87 M, block 716 K, net
  8.1 M, syscall families io 18.7 M / futex 14 M / poll 10.6 M / … The **peak-reclaim service
  is `kswapd0` at windows 83–94 s** — exactly the injection window and exactly the right
  kernel actor for F3. The F3 signature is captured.
- **L3** produced 26,967 templated digests that read correctly (*"io syscalls 7.9×;
  writeback 5.3×; block p95 latency NEW"*); 6,572 mention reclaim.

## 4. Open refinement (now concrete): service attribution
L1/L3 key `service` on raw **procname**, which yields **229 "services"** including kernel
threads (`kswapd0`, `N_scheduler`, `udev-worker`) mixed with app threads — too noisy for
per-microservice study tables. **Next:** map procname → microservice (reuse L2's
`SERVICE_COMM`, aggregate kernel/system threads), or use the pid→cgroup snapshot in `meta/`
for exact per-container attribution. Offline-doable; validate on the saved L1.

## State
- Ladder built + validated; `kernel_l1.parquet` + `kernel_l3.jsonl` saved into the anomaly_mem
  run dir. **L2 not yet run on real data** (next). Loader validated. VM STOPPED (~3 h session).
- Deriving all 55 runs is a multi-hour batch even at CLI speed (this run alone = 26 min at
  333 M events; most runs are far smaller) — run it unattended.
