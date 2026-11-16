# Results: event_loop_block on our labelled runs (2026-11-16)

Tool: `tools/loop_block.py`. Data: Sock Shop v2 (StrataTrace), Trillium `data/stratatrace-v2/sockshop/`.
Slices: 5 s, events `sched_switch|syscall_entry_`; baseline 45 s before the injection, fault 50 s
into it. Normal runs have no injection: the anchor is 90 s after the trace start. Run on the login
node with `work/bp17/validate_one.sh` (no LLM).

| check | result |
|---|---|
| fires on `code_event_loop_block` (5 runs) | **5 / 5** |
| fires on `code_serial_awaits` (5 runs) | **5 / 5** |
| stays quiet on normal runs (10) | **10 / 10** quiet |
| stays quiet on CPU lookalikes: `svc_cpu_cap` (8), `noisy_neighbor` (8), `anomaly_cpu` (5) | **21 / 21** quiet |
| stays quiet on `resource_abuse` (3), `lock_contention` (3) | **6 / 6** quiet |
| stays quiet on the code defects with no runtime effect: `lock_across_io` (3), `n_plus_one` (3 + 1 proof run), `unbounded_cache` (3) | **10 / 10** quiet |

57 runs: 10 verdicts, all on the two families; 0 false alarms.

## The 10 verdicts

| run | thread | time in long runs | long runs in 5 s | median ms | longest ms | baseline | system calls /s | CPU |
|---|---|---|---|---|---|---|---|---|
| code_event_loop_block_r1 | node tid 518505 pid 518505 (ns 4026532620) | 95% | 44 | 107 | 128 | 0.0% | 6755 -> 243 (28x) | 95% -> 98% |
| code_event_loop_block_r2 | node tid 550831 pid 550831 (ns 4026532620) | 95% | 45 | 107 | 124 | 0.0% | 6553 -> 322 (20x) | 93% -> 99% |
| code_event_loop_block_r3 | node tid 583167 pid 583167 (ns 4026532620) | 94% | 44 | 107 | 123 | 0.0% | 6784 -> 322 (21x) | 96% -> 98% |
| code_event_loop_block_r4 | node tid 615378 pid 615378 (ns 4026532620) | 95% | 45 | 108 | 138 | 0.0% | 6760 -> 359 (19x) | 94% -> 99% |
| code_event_loop_block_r5 | node tid 647700 pid 647700 (ns 4026532620) | 96% | 44 | 107 | 159 | 0.0% | 6617 -> 258 (26x) | 96% -> 99% |
| code_serial_awaits_r1 | node tid 679773 pid 679773 (ns 4026532624) | 72% | 111 | 33 | 41 | 0.0% | 6690 -> 1070 (6x) | 94% -> 99% |
| code_serial_awaits_r2 | node tid 712233 pid 712233 (ns 4026532624) | 70% | 109 | 32 | 40 | 0.0% | 6624 -> 1242 (5x) | 95% -> 99% |
| code_serial_awaits_r3 | node tid 744821 pid 744821 (ns 4026532624) | 74% | 115 | 33 | 41 | 0.0% | 7171 -> 998 (7x) | 96% -> 99% |
| code_serial_awaits_r4 | node tid 777682 pid 777682 (ns 4026532624) | 71% | 110 | 34 | 40 | 0.0% | 6437 -> 1078 (6x) | 96% -> 99% |
| code_serial_awaits_r5 | node tid 810198 pid 810198 (ns 4026532624) | 73% | 113 | 33 | 41 | 0.0% | 6826 -> 1023 (7x) | 95% -> 99% |

The two families separate on the median run: 107-108 ms (one 120,000-round PBKDF2 per request)
against 32-34 ms (a 40 ms busy wait per request; why the median reads below 40 was not
investigated). The tool's SHAPE
line splits at 60 ms. That line is fitted to these two defects only.

## What the quiet runs look like

| family | highest thread, share of slice in long runs | what it was |
|---|---|---|
| normal (10) | 0-3% | `java`, `python3` (the load generator), `prometheus` |
| svc_cpu_cap (8) | 0-6% | a MongoDB `conn` thread |
| noisy_neighbor (8) | 49-51% | `stress-ng-cpu`, a NEW process: NOTE, no verdict |
| anomaly_cpu (5) | 32-41% | `stress-ng-cpu`, a NEW process: NOTE or under the bar |
| resource_abuse, lock_contention (6) | 0-1% | - |
| code defects with no runtime effect (10) | 0-2% | - |

`prometheus` shows one 20 ms run in many slices (a scrape). It is why LONG_MS is not lower.

## How the bar was set (what failed first)
All 57 were right on the first run. One bar was then loosened: the system-call drop was >= 5x,
and `code_serial_awaits` falls only 5-7x, so r2 passed with no margin. It is now >= 3x. No quiet
run depends on that bar: each fails earlier, on "under 40% in long runs" or "not in the baseline"
(stress-ng). The 57 runs were not re-run after the change; it can only add verdicts, and the
quiet runs cannot reach it.

## Not tested
- A blocked thread in a multi-threaded service (Go, Java). No labelled run has one.
- The agent. This is the tool alone; no LLM run has used this blueprint yet.
