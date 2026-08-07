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

## 4. Service attribution — IMPLEMENTED (`service_map.py`)
The raw-procname key gave **229 "services"** (kernel threads `kswapd0`/`N_scheduler` mixed with
app threads). Added a two-tier resolver: (1) exact **TGID→service** from the run's
`meta/top_<container>_*` docker-top snapshots — the container main PID is the TGID shared by all
its threads and equals the event `pid`, so it splits same-comm services (carts/orders/shipping
are all comm "java") — the identity L2 uses; (2) a procname classifier fallback (kernel
threads→`kernel`, `traefik`→edge-router, `stress-ng`→aggressor, else `system:<comm>`). L1 now
parses the event `pid` in both readers and keys `service` via `classify()`. **Offline-tested**
(TGID split java→carts/orders, kernel bucketing, snapshot parse, CLI pid parse). **VM re-derive
pending** to refresh parquets + confirm 229→~15 clean services. L3 needs no change (consumes
L1's service column).

## State
- Ladder built + validated; `kernel_l1.parquet` + `kernel_l3.jsonl` saved into the anomaly_mem
  run dir. **L2 not yet run on real data** (next). Loader validated. VM STOPPED (~3 h session).
- Deriving all 55 runs is a multi-hour batch even at CLI speed (this run alone = 26 min at
  333 M events; most runs are far smaller) — run it unattended.

---

## 5. Service-attribution fix (shell-wrapper bug) + L2 real-data validation
Re-deriving L1 with the new mapping surfaced a bug, then validated the fix:
- **Bug:** Sock Shop's java services use a **shell-wrapper entrypoint** (`java.sh` = container
  PID 1) that *forks* the real `java` process under a **different TGID**. `main_pid`/`build_
  tgid_service` keyed only on PID 1 (the shell) → the service's threads (carrying the java
  child TGID) went unmapped: **carts L2 = 0 threads**, and L1 lumped all JVMs as `system:java`
  (Go/Node services worked — they *are* PID 1).
- **Fix:** `container_pids()` now returns **all** of a container's PIDs (shell + java child);
  L1 `classify` + L2 `attribute` match any. Go services unaffected. Validated on the real
  slow_db meta: map went 13→**22 entries**, `626364 (java child) → carts`, and all 13 real
  microservices resolve (incl. carts/orders/shipping/queue-master).
- **L2 validated end-to-end (svc_net, netem on carts):** `carts` **0 → 241 threads**,
  **99.9% off-CPU I/O wait → `external_io_or_dependency_wait`** — exactly the "why slow" answer
  (carts blocked on network). catalogue 14 tids / 99.6%, front-end 9 tids / 96.3%. **The whole
  ladder (L1/L2/L3) + loader is now validated on real data.**
- **Ops notes:** all traces are 100–300 M events (no "small" run — slow_db burst = 266 M);
  L1 re-derive is ~27 min/trace. Heavy SSH commands (kill/pull/launch of big procs)
  intermittently 128'd under derive load — run launches as minimal standalone commands, pull
  separately. The `system:*` buckets (dockerd, containerd, lttng, host tools) are correctly
  non-services; optionally collapse to one `system` bucket for the study.
- **Pending:** batch **re-derive L1** across all runs with the fix (unattended, ~hours) to
  refresh the parquets — the fix is code-validated, only the stored artifacts are stale.
