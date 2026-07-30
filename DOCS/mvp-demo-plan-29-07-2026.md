# MVP Demo Plan — Agent-First "Skill" Architecture (demo: tomorrow, 30-07-2026)

**Goal for tomorrow:** a *live, working* end-to-end demonstration of the core thesis
from the research report (`meeting-notes/compass_artifact_...md`): a packaged **skill**
that (Phase 1) compiles a plain-language problem statement into a **machine-readable
collection-requirements spec**, then (Phase 2) executes a scoped
collect→correlate→analyze→report pipeline over **all four modalities** (LTTng kernel
via Babeltrace2, OTel traces, logs, metrics) — and lands the headline:

> **Correct root cause, verified against ground truth, from ~tens of MB of scoped
> data instead of the 164 GB collect-everything bundle.**

This is the differentiator no incumbent has (Datadog/Dynatrace/TMLL/TAAF/HolmesGPT
all analyze pre-existing telemetry; none derive collection scope from the problem
statement). The demo must make that *visible*, not just claimed.

---

## 1. What we already have (why one night is enough)

| Asset | Where | Role in MVP |
|---|---|---|
| 3 calibrated `slow_db` incident runs — kernel CTF (curated events, gzipped) + native OTel spans + per-container logs + Prometheus metrics + `ground_truth.json` (exact injection window, fault params) + `verification.json` (confirmed) | VM `stratatrace-collector` (us-east1-d, stopped), `~/traces/slow_db/…`, metrics in `~/<run>_metrics/` | The recorded incident the skill runs against; ground truth = the accuracy claim |
| `error_storm` runs (rich DB-driver error logs) | same VM | Data for a 2nd, logs-only skill (stretch) |
| Proven Babeltrace2 text parsing: window trimming (`--begin/--end`), event regex, pid/tid↔container join via `meta/` | `microservice-lttng-data-collection-scripts/audit_alignment.py` | Reused as the kernel-analysis stage |
| Clock-anchor + span/log/metric window logic | `audit_alignment.py`, `verify_injection.py` | Reused for multi-modal correlation |
| Curated-kernel-event selection (JSON-able list of LTTng events per purpose) | `collect_trace.sh`, `faults/verification_targets.json` | Template for the skill's `requirements` block |
| Claude Code + MCP support | local | The **orchestrating agent** — no UI to build |
| Docker Desktop | local | Runs Babeltrace2 (userspace-only tool; no LTTng kernel modules needed) |

**Fault-signature correction (important for the demo narrative):** our `slow_db`
fault is a Toxiproxy **latency toxic on the catalogue→catalogue-db path** — not slow
disk. So the kernel evidence will be catalogue threads spending the incident window
**blocked in socket `read`/`recvfrom` syscalls waiting on DB responses**, while
catalogue-db itself stays quiet and no `block_rq`/fsync anomaly appears. That is the
*correct* answer (ground truth: `latency_ms: 500` toxic on proxy `catalogue-db`) and
a better story than the report's generic "fsync/block-device wait" example: kernel
wait-attribution distinguishes "DB path is slow" from "disk is slow" — exactly the
mechanism-level insight app telemetry can't give (traces have **no DB client spans**
here — deliberate blind spot; logs are **silent** because slow ≠ failing).