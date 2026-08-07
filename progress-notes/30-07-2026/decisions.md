# 30-07-2026 — Agent-first collection-aware MVP (branch `agentic-tracing`)

Building the demo MVP for the new research direction (agent-first, collection-aware
observability). Engine + 4 skills working end-to-end on the StrataTrace dataset.
All work is READ-ONLY on `~/traces`; decompressed kernel copies live in `~/mvp_work/`,
live captures in `~/mvp_captures/`. Safety snapshot: `stratatrace-dataset-safe-20260729`.

## Key method decisions (with the *why*)

1. **Wait-attribution is framed as a RULE-OUT, not "blocked-on-X %".**
   Go's runtime (catalogue = the `app` binary) uses a netpoller: a goroutine waiting on
   a slow DB response is NOT parked in a blocking `read()` syscall — its OS thread parks
   in `epoll_pwait`/`futex` (scheduler idle-park). So per-thread syscall-blocking does
   *not* show "blocked reading the DB socket"; it shows off-CPU I/O-readiness wait.
   The decisive, defensible claim is therefore the rule-out: **on-CPU ≈ 0.7%, disk ≈ 0%
   → not compute-bound, not disk-bound → the latency is off-CPU external-I/O wait.**
   Buckets: `on_cpu` / `runnable_wait` (CPU starvation) / `disk_wait` / `off_cpu_io_wait`.
   Validated on slow_db: 0.7 / 0.1 / 0.0 / 99.2 → `external_io_or_dependency_wait`. Correct.

2. **Thread identity is by TGID (container main PID), not comm.**
   catalogue, payment, and user ALL run `/app` (comm `app`), so comm-matching conflates
   them. Fix: identify a container's threads by TGID = the container's main PID from
   `docker top` (stable, unique), learned per-thread from the per-event `pid` context.
   Comm remains the fallback for aggressors (stress-ng) that have no docker-top snapshot.
   This dropped slow_db's catalogue thread set from 29 (comm) → 14 (precise TGID).

3. **The verdict is DETERMINISTIC (rule-scored over structured evidence); the LLM only
   narrates.** The system must never hallucinate a root cause. `rca.py` scores hypotheses
   from the evidence bundle; an optional `claude`-CLI narration writes prose over the same
   evidence but cannot change which hypothesis wins. Demo-safe and honest.

4. **Collection-aware payoff = scoped bytes read vs an undirected kernel-deep pass.**
   For slow_db the skill's scope touched ~420 MB (catalogue+DB scoped kernel lines + the
   window's catalogue/front-end spans + logs), vs ~13.3 GB an undirected kernel-deep tool
   would ingest for the same run (full decompressed kernel + all spans/logs) → ~30× less.
   Honest denominator = processing cost, not on-disk gz bundle (3.3 GB).

5. **Four faults wired, each with a DIFFERENT decisive modality** (proves the system
   genuinely decides *what to collect*, differently each time):
   - slow_db → **kernel + traces** (wait-attribution rule-out; DB engine healthy).
   - noisy_neighbor → **kernel-only** (names the stress-ng aggressor; catalogue p95 stays
     ~5 ms → invisible to metrics/traces — the sharpest "why kernel" proof).
   - dependency_outage → **traces + kernel** (payment emits 0 spans + ~0 CPU = frozen;
     orders hang at the 5.01 s client timeout → dead edge localized).
   - error_storm → **logs + metrics** (catalogue 5xx 0→229/s, log reset signatures,
     fail-fast spans; no kernel needed).

6. **Live mode (`live_capture.py`) reuses the tested `faults/` recipes + `load_generator`,
   NOT `collect_trace.sh`** (which hardcodes `~/traces` output). Writes to `~/mvp_captures/`,
   creates an LTTng session enabling ONLY the skill's declared events (collection-awareness,
   live), injects under load, captures a short window, restores in `finally`. Replay is the
   default; live is opt-in (`--live`) with replay as the fallback.

## Interfaces confirmed (reuse, don't rediscover)
- Fault recipe: `faults/<name>.sh inject <intensity>` / `cleanup`; writes ground truth via
  `gt_begin`/`gt_end` to `$FAULT_STATE_DIR` (~/fault-state).
- Load: `load_generator.py --host http://localhost:30001 --users N --duration S`.
- Scoped kernel: `sudo lttng enable-event -k --syscall <list> --channel channel0` +
  `add-context --kernel --type=pid --type=tid --type=procname`. CTF lands at
  `<out>/kernel/kernel/`.
- Spans: OTel collector appends to `microservice-lttng-data-collection-scripts/otlp-out/spans.jsonl`
  (OTLP JSON, SERVER kind=2); slice by byte offset for a run window.
- Metric change-point already computed per-run in `verification.json` (read it; don't re-query
  Prometheus). `catalogue` p95 job uses `http_request_duration_seconds`; Java svcs use
  `request_duration_seconds`; carts job label is singular `cart`.

## State
- MVP under `agent-first-mvp/`: 5 skills, engine (wait_attribution/modalities/rca/phase2),
  demo_cli, mcp_server (fastmcp installed on VM), dashboard (render + site), live_capture.
- Hero dashboard published as an Artifact for sharing.
- VM stack UP (19 containers), LTTng 2.15.1. `fastmcp` installed (`mcp` 2.0.0 pypi is a
  name-collision package — use `fastmcp`).
- Pending: finish 4-fault validation, generate site + pre-cache dashboards, live dry-run,
  demo runbook.

## Dataset review — closing Naser's open asks (later 30-07)

1. **Fault blast-radius table** (`fault_blast_radius.md`, repo root) — his §4.1 ask.
   Derived from `faults/*.sh` `EXPECTED_BLAST_RADIUS` + ground truth (NOT editing the frozen
   `fault_catalog.md`). Tiers: **host-wide** (anomaly_cpu, noisy_neighbor) · **3-in-path**
   (slow_db, dependency_outage, queue_backlog[silent/async]) · **2** (error_storm,
   svc_cpu_cap→carts, svc_mem_cap→carts). Point for Naser: service faults are *bounded*
   (2–3 svc) — answers his "faults bring down the whole thing" concern.

2. **Curated kernel profile — resolves the IO-vs-memory ⚠️.** `collect_trace.sh` curated
   profile = ALL syscalls + `sched_/block_/net_/netif_/napi_/skb_/sock_/tcp_/udp_/irq_/softirq_`.
   → **IO is IN** (block_rq_* + fs syscalls); **memory-management tracepoints are OUT**
   (kmem/pgfault/reclaim/kswapd; only via `KERNEL_EVENTS=all`). The transcript's "don't
   collect IO" is almost certainly an ASR slip for "memory." **Implication flagged in the
   doc:** F3/F8 kernel cards assume a reclaim/pgfault signature that the curated profile
   does not capture — for `svc_mem_cap` kernel evidence is syscalls/sched/block only (logs
   win T2/T3 anyway, as predicted). Confirm intent with Naser; amend F3/F8 via §7 log or
   re-run with `KERNEL_EVENTS=all` if the memory-tracepoint signal is wanted.

3. **Counts reconciled:** collected v1 = **8 fault families / 40 runs / 164 GB** (34 fault =
   31 confirmed + 3 borderline; 6 normal). Of 12 *designed* (F1–F12), F2/F3/F4/F12 are
   designed-but-deferred. Meeting's "12 fault types" = catalog design count, not collected.

4. **Babeltrace2 non-LTTng parsing** (§4.2 gating question) — spike in
   `microservice-lttng-data-collection-scripts/babeltrace-spike/`. Answer = **yes** (plugin
   graph). Built-in `source.text.dmesg` parses plain text (guaranteed proof); wrote
   `applog_source.py`, a bt2 **source component** for our Sock Shop Go-kit logs
   (`method/err/took_ns`). Parsing **verified offline** (selftest 4/4); bt2 wrapper pending
   VM validation (`run_spike.sh`). VM currently **TERMINATED** — did not start it (cost);
   the empirical run is one VM session away.
