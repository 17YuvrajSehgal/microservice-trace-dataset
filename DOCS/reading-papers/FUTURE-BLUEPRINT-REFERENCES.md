# References for the blueprints we have not written yet

Ten fault families have a recipe and collected data but **no blueprint**. This is the evidence
gathered for them in advance, so a blueprint can be written from sources that are already on
disk rather than hunted for afterwards.

Everything is in `blueprint-references/future-blueprints/`, and each source carries
`for_family` (written for this gap) or `also_for` (already held, and it serves this gap too)
in `tools/manifest.yaml`.

---

## What is missing

16 blueprints exist. These families have a recipe and runs but nothing written:

| family | what the recipe does | reference state |
|---|---|---|
| `code_n_plus_one` | one extra query per returned row | **new** |
| `code_serial_awaits` | work done one at a time that was meant to be parallel | **new** |
| `code_event_loop_block` | synchronous CPU work inside a request handler | **new** |
| `code_lock_across_io` | a mutex held across a database round trip | covered by existing |
| `code_unbounded_cache` | a cache that is never evicted | covered by existing |
| `resource_abuse` | mining-shaped CPU plus periodic short connections | **new** |
| `queue_backlog` | the sole consumer of a queue is paused | **thin** |
| `anomaly_mem` | host-wide memory pressure | **new** + existing |
| `error_storm` | every DB connection reset through Toxiproxy | covered by existing |
| `nagle_delayed_ack` | Nagle against delayed ACK | already complete |

**The five `code_*` families had no references anywhere in the reference pack.** They are the
real gap and most of what follows is for them.

---

## `code_n_plus_one` — looks like a slow datastore that is perfectly healthy

The recipe's own note: *"One is the database's fault and one is the caller's, and the evidence
a caller sees is nearly identical."* That is the discrimination problem the blueprint has to
solve, against `slow_db`.

| Source | Why |
|---|---|
| **Chen et al., ICSE 2014** — *Detecting Performance Anti-patterns for Applications Developed using Object-Relational Mapping* | The canonical paper on this exact anti-pattern. Reports that N+1 costs **more than an order of magnitude** over the equivalent single query |
| **Yang et al., ICSE 2018** *(already held)* | ORM misuse is one of their three root-cause categories for real DB performance bugs |
| **Database Access Bugs in Java, arXiv 2024** | A recent empirical characterisation of the bug class |

**The discriminator to look for:** query *count* rises while per-query latency does not. Chen's
order-of-magnitude figure is the reason that gap should be large enough to see.

---

## `code_event_loop_block` — the service stalls entirely, including requests that never touch the slow path

| Source | Why |
|---|---|
| **Davis, Williamson & Lee, USENIX Security 2018** — *A Sense of Time for JavaScript and Node.js* | Names the failure mode: **Event Handler Poisoning**. A single long-running callback poisons the event loop, so a single-threaded runtime has nothing left to run anything on |
| **Node.js docs** — *Don't Block the Event Loop* | The practitioner statement of the same thing |

The earlier EUROSEC 2017 paper by the same authors (10.1145/3065913.3065916) is the original
statement of EHP but is **paywalled**; the 2018 paper covers the same ground and is open.

**Why this matters for the blueprint:** the recipe's note says it *"resembles a CPU quota from
the outside"*. So the blueprint must separate it from `svc_cpu_cap`. EHP gives the mechanism
for why: under a quota, threads stop *because they are throttled*; under EHP, one thread is
*busy* and everything else is starved of a runtime to execute on.

---

## `code_serial_awaits` — total time scales with item count, not with per-call latency

| Source | Why |
|---|---|
| **DrAsync, ICSE 2022** — *Identifying and Visualizing Anti-Patterns in Asynchronous JavaScript* | Detects `loopOverArrayWithAwait` — awaiting inside a loop instead of once over `Promise.all`. **That is our fault, named** |

This was the hardest of the five to find a source for, and DrAsync is the only paper located
that names the pattern specifically. The recipe already states the open question honestly:
*"whether that is visible in kernel data is exactly the question."*

---

## `code_lock_across_io` — the honest counterpart to synthetic lock contention

Covered by sources already held, now also in this folder:

| Source | Why |
|---|---|
| **Lu et al., ASPLOS 2008** | Real-world concurrency bug shapes |
| **Jin et al., PLDI 2012** | Real-world performance bugs |
| **Rezazadeh et al., ISSRE-W 2020** | And the honest limit — kernel-only tracing may not separate contention from a coding mistake |

The recipe already anticipates the outcome: *"If a blueprint cannot separate them, the honest
verdict is 'threads are serialised on a lock, and kernel data cannot tell you whether that is
contention or a coding mistake', which is a useful limit rather than a failure."* Rezazadeh is
the citation for exactly that limit.

---

## `code_unbounded_cache` — the only gradual fault in the matrix

| Source | Why |
|---|---|
| **Ghanavati et al., EMSE 2020** *(already held)* | Memory and resource leaks in Java; unbounded growth is a leak shape |
| **Jin et al., PLDI 2012** *(already held)* | Real-world performance bugs |

**Gap:** *Cachetor: Detecting Cacheable Data to Remove Bloat* (FSE 2013, 10.1145/2491411.2491416)
is the most on-point paper and has **no open-access copy**. Needs institutional access.

---

## `resource_abuse` — mining-shaped workload in a co-located container

| Source | Why |
|---|---|
| **Suneja et al., IPDS 2020** — *Cryptomining Detection in Container Clouds Using System Calls and Explainable Machine Learning* | The closest published work to this fault: cryptomining, in **containers**, detected from **system calls**. It also names our own problem — containers share a host kernel, which makes per-container attribution hard |
| **Gassais et al., 2020** *(already held)* | LTTng host IDS; lists resource abuse and exfiltration as threats |

**Not obtained:** Tahir et al., *Mining on Someone Else's Dime* (RAID 2017), which introduced
MineGuard and used micro-architectural CPU signatures. Only a ResearchGate record was found.

**A caution for the blueprint.** The coverage sweep found `resource_abuse` separable *per
application only*, and noted it *"runs a hidden CPU loop, so it is probably not separable from
`noisy_neighbor` at all"*. Suneja's system-call angle is a different axis from CPU share, which
is why it is worth having — but the sweep's verdict stands until measured.

---

## `queue_backlog` — thin, and honestly so

| Source | Why |
|---|---|
| **RabbitMQ docs — Consumers** | The mechanism: what a stalled consumer does to a queue |

**No academic study of message-queue backlog in microservices was found.** Bronson 2021 and
Huang 2022 cover the feedback-loop framing, and are already held. This is a genuine gap of the
same kind the reference pack already records for connection-pool exhaustion and fork storms —
worth stating openly rather than padding.

---

## `anomaly_mem` — host-wide pressure, as distinct from a per-container cap

| Source | Why |
|---|---|
| **Linux memory management concepts** | Host-level reclaim and page cache, distinct from the `memory.max` path |
| **Weiner et al., TMO, ASPLOS 2022** *(already held)* | PSI measures stalls per process and per container; memory pressure causes latency **before** any OOM |
| **Kernel PSI doc** *(already held)* | `memory.pressure` |

**The hard part is already known.** The coverage sweep found `anomaly_mem` **inseparable from
`svc_mem_cap`** on our data, and the cause of 15 of 19 remaining false fires. A blueprint here
needs a mechanism argument — host reclaim versus cgroup reclaim — not a threshold.

---

## `error_storm` — already covered by sources we hold

| Source | Why |
|---|---|
| **Bronson et al., HotOS 2021** | **§2.3 "Slow error handling" is literally this fault.** Error paths capture stack traces, do reverse DNS, write to disk, and ship to a logging service — so an error storm makes the shortage worse |
| **Dai et al., IC2E 2018** | Timeout handling and retry behaviour |
| **Gunawi et al., SoCC 2016** | Outage causes in the wild |

Bronson §2.3 is the strongest of these and is already summarised in
`sources/bronson-2021-metastable/paper.md`.

---

## `nagle_delayed_ack` — already complete

Mogul & Minshall (SIGCOMM CCR 2001), Cheshire, Brooker, RFC 896 and RFC 1122 are all in
`misc/`. No further work needed; the blueprint can be written from what is there.

---

## Summary of what is still missing

| Gap | Status |
|---|---|
| Cachetor (FSE 2013) for `code_unbounded_cache` | no open-access copy; needs institutional access |
| Tahir et al. RAID 2017 for `resource_abuse` | only a ResearchGate record found |
| Davis et al. EUROSEC 2017 for `code_event_loop_block` | paywalled; the 2018 USENIX paper covers it |
| Any academic study of **queue backlog in microservices** | none found — a real gap |
| Any academic study of **serial awaits** beyond DrAsync | none found |

---

## Before writing any of these blueprints, read this

`blueprints/docs/COVERAGE-which-blueprints-are-missing.md` measured all 25 families over 45
signals and concluded that **most of these are not buildable from the data we have**. Its
verdicts for the families above:

- `conn_pool_exhaustion` — *"nothing, across all 45 signals"*
- `deadlock` — *"nothing. Futex shape was the hypothesis and it does not hold"*

**Both of those now have blueprints scoring 27/30 and 30/30.** So the sweep's verdict is a
statement about *automatic single-signal separation*, not about whether a written method can
work. It is still the right document to read first — it says which signals were already tried
and failed, which saves repeating them — but "not buildable" there has been wrong twice.
