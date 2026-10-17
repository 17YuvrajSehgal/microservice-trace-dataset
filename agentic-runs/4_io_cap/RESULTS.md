# Problem #4 results — disk I/O bandwidth cap

Data: **20 runs**, io.max rbps in {unlimited, 200M, 100M, 50M} x 5 reps,
VM `agentic-noise` (4 vCPU, pd-balanced boot disk ~205 MB/s native),
2026-10-13. From `analysis/aggregate_io.py`. Category: configuration-level
(`io.max` on a container). Recoverable dose-response.

## Headline

A container disk-bandwidth limit throttles an agent's file reads
proportionally: phase wall ~ bytes / rbps, once the cap is below the
disk's native speed. Same workload, up to 3.4x slower purely from the cap.

| io.max rbps | n | phase wall | effective rate |
|---|---|---|---|
| unlimited | 5 | 5.98 s | ~205 MB/s (native) |
| 200 MB/s | 5 | 5.98 s | ~205 MB/s |
| 100 MB/s | 5 | 10.1 s | ~100 MB/s |
| 50 MB/s | 5 | 20.4 s | ~50 MB/s |

phase inflation vs unlimited: 100 MB/s = **1.7x**, 50 MB/s = **3.4x**.

## What holds up (pre-registered in PLAN.md)

- **H2 confirmed, throttle is exact.** The worker's own clock reads 1 GB in
  20.4 s at the 50 MB/s cap (= 50.3 MB/s) and 10.1 s at 100 MB/s. phase
  wall scales as 1/rbps.
- **Same work every cell**: `io.stat rbytes` ~= 1.22 GB in all cells (1 GB
  file + readahead/metadata), so the wall growth is pure throttling, not
  more I/O.
- Reproducible across 5 reps.

## The one honest wrinkle

The **200 MB/s cap has no effect** (5.98 s, same as unlimited) because the
VM's disk only does ~205 MB/s natively - a cap above the real device speed
cannot bite. The effect appears only once rbps < native bandwidth. State
the disk's native speed; on slower storage the knee moves up, on faster
storage (local SSD, ~GB/s) you would need a lower cap to see it.

## Caveats

- Caches dropped before each run so the whole read hits the device
  (reused #3's drop_caches path); single-pass read avoids cache-hit
  confounds.
- io.max throttles device I/O only; page-cache hits are free. A real agent
  benefits from cache on warm files, so this is the cold-read worst case.
- The `io` cgroup controller had to be delegated (`+io` to root
  subtree_control) - it is not on by default on this VM (cpu/memory/pids
  are). The collector now does this automatically.
- LLM variance handled as before (fixed prompt, fresh repo, shuffle, n=5).
