# Analysis — agentic OS-noise

`analyze_run.py <run_dir> ...` — reads each run's `trace.txt.gz` +
`meta/` and prints a JSON time budget. Needs only Python 3 (no babeltrace).

## What it reports

- **subtree_cpu_seconds** — CPU state-seconds summed over the whole agent
  process subtree (built from `root.pid` via `sched_process_fork`):
  - `on_cpu` — compute the agent actually demanded.
  - `runnable_wait` — woken but not running = **CPU noise** (contention +
    throttle). The quantity that should grow as the cap tightens.
- **main_thread_wall_s** — the claude main thread's wall-time budget,
  summing to ~`wall_s` (the agent's-eye view, free of the parallel-threads
  inflation that makes a subtree-wide "blocked" sum exceed wall). Off-CPU
  time is bucketed by the syscall the thread blocked in:
  `wait_eventloop` (epoll — idle + LLM wait), `wait_lock` (futex),
  `wait_io`, `wait_child`, `wait_sleep`, `wait_other`.
- **validation** — `on_cpu` vs cgroup `cpu.stat usage_usec`, and
  `runnable_wait` vs `throttled_usec`. If these diverge the parse is wrong.

## Known limitations (do not forget)

1. **LLM-wait is not yet separated from idle.** Both land in
   `wait_eventloop` (the node event loop's epoll). Splitting them needs
   mapping the API socket fd (from connect/socket syscalls) — future work.
2. **runnable_wait under-counts CFS throttle.** On the 1-core run it read
   0.03s vs cpu.stat's 0.45s throttled: a throttled cgroup is dequeued in a
   way the simple sched_switch/wakeup state machine misses. Use `cpu.stat
   throttled_s` as the ground-truth throttle figure; treat trace
   `runnable_wait` as scheduling-latency only until this is refined.
