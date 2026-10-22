# Problem #4: disk I/O bandwidth cap — experiment design

Date: 2026-10-13. Fourth catalogue entry. Completes the cgroup-limit
quartet: CPU (#1), scheduling/parallelism (#2), memory (#3), **disk I/O**
(#4). Category: configuration-level (`io.max` on a container). Recoverable
dose-response, like #1 - balances the package (#2/#3 lean on cliffs).

## Question

A sandboxed agent under a disk-bandwidth limit (`io.max rbps`): how much
does throttled disk I/O slow its file work?

## Mechanism

cgroup v2 `io.max` throttles block-device bandwidth for the cgroup. A
workload doing real device reads (cache dropped first) is rate-limited;
phase wall ~ bytes / rbps. Fully visible: `block_*` events + `io.stat`
ground truth (`rbytes`, `rios`). No OOM, no kill - pure slowdown.

## Workload

`t8_ioread`: read a 1 GB file ONCE (comm `ttio`). Caches dropped before the
run so the whole read hits the device and is throttled. Single pass keeps
it clean (no cache-hit confound).

## Part A — dose-response (io.max rbps)

- rbps levels: unlimited, 200M, 100M, 50M (bytes/s). 4 cells x 5 reps =
  **20 runs**. Shuffled, resumable (`~/runs_t8`).
- Predict phase wall ~ 1 GB / rbps: ~unlimited fast, 200M ~5 s, 100M ~10 s,
  50M ~20 s. Validate against `io.stat rbytes` and measured wall.

## Hypotheses

- H1: unlimited -> phase at native disk speed, minimal block latency.
- H2 (dose-response): phase wall scales ~ 1/rbps; `io.stat rbytes` ~ 1 GB
  every cell (same work), so wall growth is pure throttling.
- H3: block-request completion latency rises as rbps drops.

## Rig changes

1. collect_agent_run.sh: 6th arg `IO_LIMIT` = "rbps:<N>". Detect the
   backing block device MAJ:MIN for $HOME, write "MAJ:MIN rbps=N" to
   `io.max`. Trigger the existing drop_caches path for IO runs too.
   Snapshot `io.stat` before/after.
2. tasks/t8_ioread.sh (ttio worker, read 1 GB once).
3. analyze_run.py: surface io.stat delta (rbytes/rios) in the memory/io
   block (already have block I/O count + phase window on tt*).
4. run_campaign_t8.sh.

## Confounds

- io.max throttles device I/O only; page cache must be cold -> drop caches
  first (reuse #3's mechanism). Single-pass read avoids cache hits.
- Device detection must find the real backing disk (GCP boot disk, e.g.
  8:0) - smoke-test it.
- LLM variance handled as before (fixed prompt, fresh repo, shuffle, n=5).

## Budget

~3 smoke + 20 Part A = ~23 runs, one VM session.
