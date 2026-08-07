# Fault blast-radius categorization (for review)

**For:** Naser Ezzati-Jivan · **From:** Yuvraj Sehgal · 30 Jul 2026

Per the §4.1 ask from the 29-Jul meeting — *categorize the faults by how many services
each affects, a few representative tiers (not exhaustive combinatorics).* This is derived
from the fault recipes (`EXPECTED_BLAST_RADIUS`/`TARGET_SERVICE` in
`microservice-lttng-data-collection-scripts/faults/*.sh`) and each run's
`ground_truth.json`; it does **not** edit the frozen pre-registration in `fault_catalog.md`.

Two things to separate:
- **Injection scope** — *where the fault is applied* (host, or one service).
- **Blast radius** — *which services actually show symptoms* (the thing you asked to tier).

Headline: the service-targeted faults are **bounded** (2–3 services), i.e. they localize —
this directly answers the "most faults bring down the whole thing" concern. Only the two
host-resource faults are host-wide by construction.

---

## Blast-radius tiers (collected v1 = 8 fault families)

### Tier H — host-wide (all ~13 services)
| Fault | Family | Injected at | Blast radius | Propagation | Decisive modality |
|---|---|---|---|---|---|
| `anomaly_cpu` (F1) | host resource | host (stress-ng, 24 workers) | **all services** slow together | shared CPU exhaustion | kernel |
| `noisy_neighbor` (F11) | infrastructure | host (co-located stress-ng container, cgroup-capped) | **all services, mildly** — KPIs stay in normal variance by design | shared-core contention | **kernel-only** (blind spot) |

### Tier 3 — three services (a dependency chain / path)
| Fault | Family | Injected at | Blast radius | Propagation | Target trace visibility | Decisive modality |
|---|---|---|---|---|---|---|
| `slow_db` (F5) | application | **catalogue-db** | catalogue-db → catalogue → front-end | latency on the DB connection path | **blind spot** (no DB client span) | kernel |
| `dependency_outage` (F9) | dependency | **payment** (docker pause) | payment → orders → front-end | caller hangs on the frozen dependency | covered | traces |
| `queue_backlog` (F10) | dependency | **queue-master** (docker pause) | queue-master → rabbitmq → shipping | async pipeline stalls — **silent** (request path completes normally) | **blind spot** (async boundary) | kernel |

### Tier 2 — two services (target + immediate upstream)
| Fault | Family | Injected at | Blast radius | Propagation | Target trace visibility | Decisive modality |
|---|---|---|---|---|---|---|
| `error_storm` (F6) | application | **catalogue** (proxy reset) | catalogue → front-end | 5xx storm surfaces upstream | covered | logs |
| `svc_cpu_cap` (F7) | service resource | **carts** (docker `--cpus`) | carts → front-end | CFS throttling; upstream sees slow carts | covered | kernel |
| `svc_mem_cap` (F8) | service resource | **carts** (docker `-m`) | carts → front-end | GC pressure / OOM on the capped cgroup | covered | logs |

> **Reading the tiers:** every service fault is injected at exactly **one** service; the
> blast radius grows only along real request/dependency edges. `slow_db` and `queue_backlog`
> are 3-in-path but their *injection target* is a deliberate telemetry **blind spot** — which
> is exactly why the kernel modality is decisive for them.

---

## Dataset facts to confirm (three items surfaced by the meeting notes)

**1. Collected v1 = 8 fault families / 40 runs / 164 GB.** 34 fault runs (31 confirmed +
3 borderline) + 6 normal. Of the **12 designed** faults in `fault_catalog.md` (F1–F12),
four are *designed-but-deferred* to keep the campaign at ~40 runs: **F2 host-disk,
F3 host-mem, F4 host-net, F12 per-container-netem.** (The meeting's "12 fault types" was the
catalog design count; the collected set is 8.) Each collected family: aggressive/steady ×3,
plus subtle (`noisy_neighbor`, `slow_db`, `svc_cpu_cap`) and burst (`slow_db`, `error_storm`)
workload variants.

**2. Curated kernel profile — settles the "don't collect IO" question (the ⚠️ in the
notes).** Every run captures the *same* curated LTTng profile (`collect_trace.sh`):
> **all syscalls (entry+exit)** + tracepoint families `sched_* block_* net_* netif_* napi_*
> skb_* sock_* tcp_* udp_* irq_* softirq_*`.

So **IO is fully collected** (block-layer tracepoints `block_rq_*` + filesystem read/write at
the syscall boundary). What is **excluded** is the **memory-management tracepoints**
(`kmem_* / pgfault / reclaim / kswapd`), available only via the `KERNEL_EVENTS=all` escape
hatch. → the transcript's *"professor said don't collect IO"* is almost certainly an ASR slip
for *"memory."* **Please confirm** memory-tracepoint exclusion is the intended profile.

- **Implication to flag:** the F3/F8 kernel predictions in `fault_catalog.md` assume a
  reclaim/pgfault kernel signature — those exact tracepoints are **not** in the curated
  profile, so for `svc_mem_cap` (F8) the kernel evidence is limited to syscalls/sched/block
  (logs carry T2/T3 anyway, as predicted). If we want the memory-tracepoint kernel signal in
  the study, re-run F8 (and add F3) with `KERNEL_EVENTS=all` — otherwise amend the F3/F8
  kernel cards via the `fault_catalog.md` §7 log.

**3. Blast radius is bounded for service faults (2–3 services)** — validates the two-axis
(scope × layer) catalog and gives the representative tiers you asked for, without exhaustive
combinatorics.

---

*Source of truth for counts/verdicts: `progress-notes/28-07-2026/campaign-complete.md` and
each run's `verification.json`. Blast radius: `faults/*.sh` `EXPECTED_BLAST_RADIUS` +
`ground_truth.json`.*
