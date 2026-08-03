# stratatrace — loader SDK + kernel representation ladder

The release-facing Python package for the StrataTrace four-modality incident dataset. Two
jobs: (1) **derive** the kernel representation ladder (L1–L3) from raw CTF, and (2) **load**
any run's modalities into time-aligned dataframes with one call.

## Install (dev)
```
cd stratatrace && pip install -e .     # needs pandas + pyarrow for Parquet
# bt2 (babeltrace2 python bindings) is required only for deriving/reading L0 — VM-only.
```

## Load a run
```python
from stratatrace import load_run, list_runs

run = load_run("~/traces/anomaly_mem/anomaly_mem_aggressive_steady_r1")
run.ground_truth      # {fault: {name, scope, intensity, injection_start_utc, ...}}
run.spans()           # DataFrame — distributed traces (OTLP spans)
run.logs()            # DataFrame — per-container logs
run.metrics()         # DataFrame — Prometheus series (long form)
run.kernel_l1()       # DataFrame — L1 kernel KPIs (per service, 1s window)

for fam, run_id, rd in list_runs("~/traces"):
    ...
```

## Kernel representation ladder (msr-research.md §4)
| Level | What | Status |
|---|---|---|
| **L0** | raw CTF (LTTng, gzipped channels) | shipped by collection |
| **L1** | kernel KPIs per (service, 1s window) → Parquet | **`derive_kernel_l1.py`** — **VM-validated** (all KPIs populate; F3 reclaim signature via kswapd0). Use the fast `--reader cli` (default). |
| **L2** | per-service wait attribution (on-CPU / runnable-wait / blocked-disk/net/futex) → JSONL | **`derive_kernel_l2.py`** — productionized from the MVP engine; offline-tested; **real-data VM validation pending** |
| **L3** | templated NL kernel digest per (service, window) → JSONL | **`derive_kernel_l3.py`** — **VM-validated** end-to-end on real L1 |

> **Performance:** the kernel traces are huge (a memory-pressure run = **333 M events**). Use
> the default `--reader cli` (babeltrace2 subprocess, ~15× the bt2-python bindings). Even so,
> deriving is minutes-to-tens-of-minutes per big run — run the batch unattended.

Derive all three for a run (on the VM):
```
python3 stratatrace/derive_kernel_l1.py <run_dir>     # -> kernel_l1.parquet
python3 stratatrace/derive_kernel_l3.py <run_dir>     # -> kernel_l3.jsonl  (needs L1)
python3 stratatrace/derive_kernel_l2.py <run_dir>     # -> kernel_l2.jsonl  (needs babeltrace2)
```
L2 v1 is per-(service, injection-window); per-*request* attribution (join spans × tids) is the
documented refinement.

### Derive L1 for a run (on the VM)
```
python3 stratatrace/derive_kernel_l1.py ~/traces/<fault>/<run_id> --out <run_dir>/kernel_l1.parquet
```
L1 decompresses the gzipped CTF channels into a temp dir (bt2 can't read `.gz`), reads once,
and writes a small Parquet. Columns: `run_id, service, window_start_s`, syscall family counts,
syscall + block latency percentiles, sched/block/net/reclaim/writeback/pagefault rates.

## Known refinements (tracked)
- **Service attribution (next priority)** — L1/L3 key `service` by raw `procname`, which on a
  real run yields **229 "services"** including kernel threads (`kswapd0`, `N_scheduler`,
  `udev-worker`) mixed with app threads — too noisy for per-microservice tables. Map procname
  → microservice (reuse L2's `SERVICE_COMM`; bucket kernel/system threads), or use the
  pid→cgroup snapshot in `meta/` for exact per-container attribution. Schema already carries
  the `service` column so this is a drop-in. (The raw-procname output is still correct and
  useful — e.g. it correctly attributes the F3 reclaim to `kswapd0`.)
- **Block latency pairing** — v1 pairs block issue→complete on `nr_sector` (coarse); refine to
  `(dev, sector)` once validated on the VM.
- **Loader paths** — metrics dir / spans filename resolvers try known candidates; pin once
  validated against the real run layout.
