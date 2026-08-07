---
name: db-slowness-rca
description: Diagnose database slowness on an instrumented microservice system. Use when a user reports the database or DB-backed requests are slow. This skill decides what kernel/trace/log/metric data to collect, then runs a kernel-deep wait-attribution root-cause analysis.
triggers: ["database is slow", "db latency", "slow queries"]
version: 0.1.0
---

# Database Slowness RCA

**When to use.** The user says their database (or a DB-backed service) is slow, and
wants the root cause — not just a dashboard.

**What makes this skill different.** It is *collection-aware*: before touching any data,
it emits a machine-readable **requirements spec** (`skill.json`) declaring exactly the
kernel events, syscalls, OTel spans, logs, and metrics needed — and the `lttng` command
that scopes capture to just those. It collects only that, then reasons kernel-deep.

**How the agent should run it.**
1. Call `phase1_requirements("db-slowness-rca", <problem>)` and show the user the scoped
   collection plan (the differentiator — surface it, don't hide it).
2. Call `run_skill("db-slowness-rca")`. The engine (live scoped capture, or replay over a
   collected run) performs **per-thread wait attribution** from the kernel trace:
   classifying each service thread's time into on-CPU / runnable-wait /
   blocked-on-socket(DB fd) / blocked-on-disk / blocked-on-futex, correlates with the
   catalogue latency change-point, and reasons over the three hypotheses
   (DB-connection-path latency vs disk I/O vs service CPU).
3. Present the output-contract result: root cause, evidence, what was **ruled out**,
   decisive modality, confidence, recommended fix, and data-touched vs the everything-bundle.

**Expected finding on the reference `slow_db` fault.** Latency lives in the DB connection
path: the catalogue service's threads spend the dominant share of request time blocked in
`recvfrom()` on the DB socket; on-CPU and disk I/O are negligible → root cause is the DB
connection/proxy path, not catalogue CPU or DB disk.
