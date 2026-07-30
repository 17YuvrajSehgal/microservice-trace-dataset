# StrataTrace — Agent-First, Collection-Aware Observability
### Demo summary

**For:** Naser Ezzati-Jivan · **From:** Yuvraj Sehgal · 30 Jul 2026
Pairs with the 3-slide deck (`ciena-pitch.html`). Built bottom-up on the existing 40-run
StrataTrace dataset (kernel traces + OTel traces + logs + metrics, ground-truth labelled).

---

## What we built — the "skill" architecture, working end-to-end

A working prototype of the **skill** design from our 1:1. A skill is a self-contained,
reusable diagnostic *contract* per class of problem, packaging exactly the four components
you specified:

| Component | In our implementation |
|---|---|
| **Requirements** | `skill.json` — machine-readable (JSON): the LTTng events, syscalls, target services, OTel/log/metric scope, **and the exact `lttng` capture command** |
| **Workflow** | collect → attribute (kernel wait-analysis) → correlate → reason → output |
| **Output** | fixed contract — root cause · ruled-out · decisive modality · confidence · fix · data-saved — rendered as an HTML verdict dashboard |
| **Code** | the engine backing each stage, packaged with the skill |

**Two-phase execution**, exactly as discussed:
- **Phase 1 — Requirements.** Given *"my database is slow,"* the skill emits the collection
  spec (*what* to collect) — surfaced to the user **before any data is touched**.
- **Phase 2 — Execution.** Collect only that, run the analysis chain, produce the verdict.

The **skill dictates collection scope** — the differentiator you stressed. It decides *what*
to collect from the problem statement, rather than "collect everything into a zip." We
quantify the payoff: a scoped run reads **up to 32× less data** than an undirected
kernel-deep pass.

Access is **agent-first**: an MCP server exposes the skills as tools
(`discover_skills` → `phase1_requirements` → `run_skill`); the agent drives the whole loop
from the plain-language problem. A deterministic CLI mirrors it as a fallback.

---

## Backend: Babeltrace2, kernel-deep

Analysis runs over **Babeltrace2** (C, CLI, scales to GB/TB) — its input→analysis→output
graph is the kernel engine. The novel analytical core is **per-thread wait-attribution**:
we split each service thread's time into *on-CPU / runnable-wait / disk / off-CPU-I/O*,
which lets us **rule causes out**, not just flag an anomaly.

For *"my database is slow"*: the `catalogue` service spends **99% off-CPU on I/O-readiness
wait, ~0% on CPU, ~0% on disk**, and the database engine is idle → root cause is the DB
**connection path**, not compute or disk. That is the mechanism-level answer TMLL's basic
CPU/disk/network anomaly views cannot give — and it lands the gap you identified.

---

## What we experimented with — results

We ran the skills against the collected dataset **blind to ground truth** (used only to
score afterwards), across four fault classes. It was **correct on all four — each with a
*different* decisive modality**, which is the whole thesis: the system genuinely decides
what to collect, differently per problem.

| Problem | Decisive modality | Data ↓ | Correct vs ground truth |
|---|---|---|---|
| "my database is slow" | kernel + traces | ~32× | ✓ |
| "everything's a bit slow" | **kernel-only** | ~13× | ✓ |
| "orders are failing" | traces + kernel | ~28× | ✓ |
| "tons of 500 errors" | logs + metrics | ~2× | ✓ |

Three findings worth noting:
- **Kernel depth is necessary.** In the noisy-neighbor case the service metrics and traces
  stay flat (p95 ≈ 5 ms) — *only* the kernel names the co-located culprit process.
- **Works live, not just on replay.** We also inject a fault on the running Sock Shop stack,
  capture **only the declared events** (scoped LTTng), and reach the same verdict on fresh
  data — demonstrating live collection-awareness end-to-end.
- **No hallucinated root cause.** The verdict is deterministic (rule-scored over the
  structured evidence); the LLM only writes the narrative.

---

## Scope, reuse, and extensibility

- **Bottom-up, this dataset first** (per your scope guidance): the demo `slow_db` scenario
  maps directly onto our existing, calibrated `slow_db` fault; the curated kernel-event
  profile is one real instance of a skill's requirements block.
- **Extensible by design:** the MCP server is backed by a growing library of skills — **5
  shipped**, and new diagnostics (adaptive-tracing, memory-leak, GC-pauses,
  network-partition, …) can be added **without changing the engine or the dataset**.

## Open item (next)
Your §4.2 gating question — Babeltrace2 parsing **non-LTTng** data. Today we read
logs/OTel/metrics through dedicated readers alongside the Babeltrace2 kernel graph;
unifying non-LTTng formats via a Babeltrace2 *source plugin* is the next step, and would
make Babeltrace2 the single backend for all four modalities.

---

*Code + full architecture on branch `agentic-tracing` under `agent-first-mvp/`
(architecture doc: `DOCS/agent-first-architecture.md`). Everything is read-only on the
164 GB dataset — nothing was modified.*
