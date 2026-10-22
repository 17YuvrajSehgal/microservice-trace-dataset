# 17-10-2026 — decisions

## slow_db 4-cell matrix, round 1: 2 pass, 1 near-pass, 1 miss

| cell | expected | got |
|---|---|---|
| sdb-bp on slow_db_r1 | db_latency ~500ms | "other" 0.68 — evidence COMPLETE (pool 0.46-0.56s on ten fds, answers flowing, mysqld mirror) but refused the label: "cannot map fds to remote endpoints" |
| sdb-bp on normal | rejection | normal 0.88 — PASS; long-pollers correctly ignored vs baseline |
| sdb-bp on svc_cpu_cap_r3 | reject -> CPU | service_network 0.78 — MISS: census winner was mongod (whose CPU it checked); java's 790 waits >=50ms never looked at. Root cause of the miss: the CPU check was the LAST bullet, scoped to "gap victims" |
| cap-bp on slow_db_r1 | reject | normal 0.98 — PASS (no CPU waits -> stop rule; honest scope note) |

Pattern repeats across all three blueprints' first unseen rounds: negatives
clean, positives find the right evidence but under-commit, cross cells
expose one missing rule. Never a confident wrong answer.

Three fixes applied (commit aee3198):
1. Step 3: the CPU GATE is now the first mandatory action, over the WHOLE
   budget table — everything talking to a CPU-starved process shows
   inflated gaps, so gaps on a starved machine mislead.
2. Step 6a mirror rule: a process whose own gaps mirror the victim's
   (mysqld 500ms vs pool 503-543) + the wake hint IS the peer; name it.
3. Step 10: commit to db_latency / the dependency when Steps 4-6 held;
   "other" is for evidence that did not hold.

Re-run of cells 1+3 launched against the fixed blueprint (.sdb2/.sdb2x).

## Re-run with fixed blueprint: positive flips to a textbook pass

| cell | round 1 | round 2 (fixed) |
|---|---|---|
| sdb-bp on slow_db_r1 | "other" 0.68 | **db_latency 0.92: "app-to-mysqld connection path (peer observed as mysqld pid 19881)"; quotes 0.9ms->418.7ms and the mysqld mirror 0.3->501.6ms; "no CPU/disk strain on mysqld -> path, not a struggling database"** |
| sdb-bp on svc_cpu_cap_r3 | service_network 0.78 (false call) | "other" 0.78 — correctly REFUSES the dependency diagnosis ("not established; gap jump based on one answer; other gaps fell"), saw java's waits. Did not route to the cap blueprint (its slices both sat inside the 2-min fault window, so the waits looked "already present" vs its baseline) |

All three fixes visible in behavior: sock_lag 18 calls with the census-first
flow; the mirror rule named mysqld as the peer; the label committed.

FINAL blueprint-3 matrix: positive PASS (0.92, matches ground truth
exactly), normal PASS, cap-cross PASS-as-rejection (no false dependency
call; routing to cap-bp still imperfect when the fault spans most of the
trace), cap-bp-on-slowdb PASS. Zero confident wrong answers across all 6
runs of the matrix.

Catalogue state: THREE blueprints (svc_cpu_cap, noisy_neighbor, slow_db),
each agent-tested on its own fault + negatives + cross-fault cells, each
improved through measured failure analysis. Held-out unseen pool for
later: slow_db r2-r5 + burst + subtle + 11 TT runs (no_metric_signature -
the kernel blueprint is the only evidence there).
