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
