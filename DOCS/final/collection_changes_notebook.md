# Collection script changes — engineering notebook

Short log of changes made to the data-collection scripts on 2026-06-12, why they
were made, and the measurements that justified them.

## 1. Lossless kernel tracing under stress (`collect_trace.sh`)

### Problem
The kernel session enabled events with `lttng enable-event -k --all '*'` without
first creating a channel. LTTng then auto-creates a **default channel with tiny
per-CPU ring buffers (~1 MB/CPU)**. Under heavy load the trace consumer cannot
drain fast enough, the buffers fill, and events are dropped. A 40 s disk-stress
sample dropped **47,375,876 events**.

### Fix
Create an explicit channel with large buffers *before* enabling events, and
attach the events/context to it:

```bash
sudo lttng enable-channel -k channel0 \
    --subbuf-size="${KERNEL_SUBBUF_SIZE:-8M}" \
    --num-subbuf="${KERNEL_NUM_SUBBUF:-32}"          # 256 MB/CPU
sudo lttng enable-event  -k --all '*' --channel channel0
sudo lttng add-context   --kernel --channel channel0 --type=pid --type=tid --type=procname
```

- The channel is named `channel0`, preserving the documented `channel0_*` CTF
  per-CPU stream file naming.
- Buffer geometry is overridable via `KERNEL_SUBBUF_SIZE` / `KERNEL_NUM_SUBBUF`.
- `256 MB/CPU × N_CPU` of RAM is reserved at session start (~4 GB on a 16-vCPU host).

### Measurements (30 s samples, 200 users, 16 vCPU)

| Buffer geometry | normal | disk-stress | mem-stress |
|---|---|---|---|
| default (~1 MB/CPU) | — | 47M dropped | — |
| 16 MB × 8  (128 MB/CPU) | 3.3M dropped | 11.2M dropped | 0 |
| **8 MB × 32 (256 MB/CPU)** | **0** | **0** | **0** |

Key takeaway: the **number of sub-buffers matters more than their size**. More
sub-buffers gives the starved consumer more free slots to rotate into, so very
few events are dropped. Disk-stress is the worst case because the trace consumer
competes with `stress-ng` for the same disk bandwidth it needs to flush CTF.

## 2. Sample (small-subset) collection scripts

Added short-duration wrappers so a small, representative subset can be collected
quickly (see `sample.md`):

- `sample_normal.sh` — load only, no fault injection (new).
- `sample_disk_stress.sh` — `stress-ng --hdd` (already existed).
- `sample_mem_stress.sh` — `stress-ng --vm`, **moderated** for a sample
  (`VM_WORKERS=12`, `VM_BYTES=50%`) so memory stress does not OOM the host while
  the ~4 GB of LTTng ring buffers are also resident (new).

All three default to `RUN_ID=sample`, `DURATION=30`, 200 users, and reuse the
fixed `collect_trace.sh` above, so every sample bundle is fully lossless.

## 3. How to run

```bash
# Each writes ~/traces/<scenario>/sample and ~/experiments/<scenario>/sample
PROMETHEUS=http://localhost:9090 FRONTEND_HOST=http://localhost:80 \
  ./sample_normal.sh sample 30
# ...likewise sample_disk_stress.sh / sample_mem_stress.sh (run sequentially —
# they share the host LTTng kernel session).
```
