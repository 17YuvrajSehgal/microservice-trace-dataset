# Sample dataset (small lossless subset)

A small, quick-to-collect subset of the SockShop trace dataset, intended for
pipeline testing, demos, and sanity checks without moving the full ~148 GB
collection. Generated on 2026-06-12.

## What it contains

Three scenarios, one run each (`run_id = sample`), 30 s of measured load at
200 concurrent users:

| Scenario | Fault injection | Trace bundle | Spans | Discarded events |
|---|---|---|---|---|
| `normal` | none | ~2.8 GB | ~28k | 0 |
| `anomaly_disk` | `stress-ng --hdd 300 --hdd-bytes 4G --hdd-opts direct,fsync` | ~3.1 GB | ~28k | 0 |
| `anomaly_mem` | `stress-ng --vm 12 --vm-bytes 50% --vm-method all --vm-keep --page-in` | ~2.6 GB | ~23k | 0 |

Every bundle is **fully lossless** (zero discarded kernel events) thanks to the
ring-buffer fix in `collect_trace.sh` (see `collection_changes_notebook.md`).
Each is comfortably under a ~4–5 GB budget.

## Layout

Same structure as the full dataset, one `sample` run per scenario:

```
~/traces/<scenario>/sample/
├── kernel/kernel/         # CTF, 16 per-CPU streams channel0_0 .. channel0_15
│   ├── metadata
│   ├── index/
│   └── channel0_0 ... channel0_15
├── ust/ust/uid/1001/64-bit/   # CTF, OTel span events (lttng_python)
└── meta/                  # docker/proc snapshots: *_start, *_end, *_tick_<UTC>

~/experiments/<scenario>/sample/
├── load_results.csv       # per-request load-generator results
├── metrics/*.json         # 33 Prometheus series (VM + per-service QPS/latency/errors)
└── run.log
```

Notes vs. the full published dataset:
- Collected on a 16-vCPU host, so there are **16** per-CPU kernel streams
  (`channel0_0 .. channel0_15`) rather than 12.
- UST uid is `1001` (collecting user), not `1002`.
- Kernel context (`pid`, `tid`, `procname`) and syscall entry/exit pairs are
  present, identical in shape to the full dataset.

## How it was generated

```bash
PROMETHEUS=http://localhost:9090 FRONTEND_HOST=http://localhost:80 \
  ./sample_normal.sh       sample 30
PROMETHEUS=http://localhost:9090 FRONTEND_HOST=http://localhost:80 \
  ./sample_disk_stress.sh  sample 30
PROMETHEUS=http://localhost:9090 FRONTEND_HOST=http://localhost:80 \
  ./sample_mem_stress.sh   sample 30
```

Trace growth is ~110 MB/s of kernel CTF; scale `DURATION` to stay within a size
budget. Delete `~/traces/<scenario>/sample` before re-running so old CTF streams
are not mixed with new ones.

## Reading it

```bash
babeltrace2 ~/traces/anomaly_disk/sample/kernel/kernel | head
babeltrace2 ~/traces/anomaly_disk/sample/ust/ust/uid/1001/64-bit | grep otel.spans | head
```
