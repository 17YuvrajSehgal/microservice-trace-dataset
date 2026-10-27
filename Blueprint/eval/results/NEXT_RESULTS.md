# Next blueprints to build — gap analysis against DATASET-v2-INVENTORY.md

We have **5 blueprints** (`svc_cpu_cap`, `svc_mem_cap`, `noisy_neighbor`, `slow_db`, `svc_net`).
v2 collected **~24 fault families**. The eval is **kernel-trace only** (no metrics, no logs), so the
real question is: which *uncovered* families have a **kernel signature** and real data?
Every classification below cites the inventory's own measured evidence, not assumptions.

## Strong candidates to build (kernel-visible, confirmed, distinct mechanism)

| family | apps | kernel signature | why it's worth it |
|---|---|---|---|
| **fd_exhaustion** | SS+TT 5/5 | process exits / restart-loop (front-end restarts 9×), EMFILE | confirmed after target fix (issue 22); clean distinct mechanism |
| **conn_pool_exhaustion** | SS+TT 5/5 | threads blocked waiting for a free connection (futex/socket wait) | distinct from slow_db (pool starvation, not a slow peer) |
| **lock_contention** | SS+TT 5/5 | user-level **futex** waits | new in v2; SS re-collected to 5/5 |
| **deadlock** | SS+TT 5/5 | two threads each blocked on the other's futex, no progress | new in v2; 5/5 |
| **priority_inversion** | SS+TT 5/5 | low-prio holder blocks high-prio waiter (sched + futex) | new in v2 |
| **fork_storm** | SS+TT 5/5 | `sched_process_fork` burst | very clean kernel signal |
| **dependency_outage** | SS+TT 5/5 | connection refused / resets / retry storms | distinct from slow_db (down, not slow) |
| **nagle_delayed_ack** | SS+TT 5/5 | ~40 ms TCP delayed-ack stalls | a precise net-latency variant |
| **data_exfiltration** | SS+TT 5/5 | anomalous egress bytes / flows | security angle, kernel-visible |

## Check kernel-visibility before building (likely fine, but verify first — evidence-first)

- **anomaly_disk** (block_rq I/O stress) — new disk modality; but TT's own tracing already writes
  176/206 MB/s, so the fault is small there.
- **anomaly_cpu / anomaly_net** — probably **already covered** by noisy_neighbor / svc_net (same
  mechanisms); may not need their own blueprint.
- **queue_backlog** (SS only), **dns_delay** (SS only), **resource_abuse** — single-app or unclear
  mechanism; confirm what the trace actually shows.
- **code_event_loop_block, code_serial_awaits** (Node, SS only) — the inventory *measured* these as
  visible (event-loop stall: injection rate falls and recovers); the other 3 code defects are **Go
  and invisible**.

## Do NOT build (inventory's own evidence says no kernel/metric signature)

- **error_storm** — "the evidence is in the **logs**" (462 link failures); nothing in metrics *or* a
  clean kernel signal. Skip for a kernel-trace eval.
- **anomaly_mem** — same **memcg-tracepoint gap** that makes svc_mem_cap not evaluable on
  microservice. Skip until a re-collection with memory tracepoints.
- **code_n_plus_one / code_unbounded_cache / code_lock_across_io** — Go, concurrency absorbs them;
  measured invisible.

## Honest take on "must"

**None are strictly required** — the 5 we have tell a complete "resource & latency contention"
story. But to make v2's *breadth* count in the paper, the highest-value, lowest-risk additions are
the **7 distinct kernel-visible mechanisms** that are confirmed in **both** apps:
`fd_exhaustion`, `conn_pool_exhaustion`, `lock_contention`, `deadlock`, `priority_inversion`,
`fork_storm`, `dependency_outage`. Each is a genuinely different failure the current 5 cannot catch.

Per the evidence-first rule, do **not** write any of them from knowledge. Next step: a quick
**kernel-visibility probe** on one confirmed run of each candidate (does the signature actually show
in the trace?), then build only the ones that prove out.
