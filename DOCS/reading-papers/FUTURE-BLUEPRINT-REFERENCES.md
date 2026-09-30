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
| **Chen, Shang, Jiang, Hassan, Nasser & Flora, ICSE 2014** — *Detecting Performance Anti-patterns for Applications Developed using Object-Relational Mapping* [V] | The canonical paper on this exact anti-pattern, which they call **one-by-one processing** (a special case of *Empty Semi Trucks*). **228 instances in one 206 KLOC open-source e-commerce system**, an ESLint-grade well-known mistake, fixed by batching (`@BatchSize`) |
| **Yang et al., ICSE 2018** *(already held)* | ORM misuse is one of their three root-cause categories for real DB performance bugs. Also gives the **mirrored** mistake: over-eager loading, **few round-trips but huge payloads** |
| **Database Access Bugs in Java, arXiv 2024** | A recent empirical characterisation of the bug class |

**Citation corrected 30 Sept 2026.** This section previously said Chen reports N+1 costing *"more
than an order of magnitude"*. **It does not.** The order-of-magnitude figure in that paper (130 s
to 2 s, -98%) is for the **excessive data** anti-pattern in Pet Clinic — a *different* pattern.
Chen's own micro-benchmark for **one-by-one processing** is **1.68 s to 1.39 s, a 17%
improvement**, and across Broadleaf's test suites it was **statistically significant in only 5 of
10**, ranging from **+8% (worse) to -32%**. The commercial system did see **-69%**.

**So the effect size is not reliably large, and the reason matters to us.** Chen et al. state it:
*"when the response time of a program is small, adding batches will not give much improvement...
not all anti-patterns are worth fixing."* What decides is **schema cardinality and baseline
latency** — one-to-many relationships hurt, one-to-one barely register. **Our injected
`code_n_plus_one` needs calibrating hard enough to be visible**, the same problem
`noisy_neighbor` has.

**The discriminator to look for:** query *count* rises while per-query latency does not. **Chen's
weak numbers are an argument for our modality, not against the fault** — their whole measurement
is wall-clock response time, which is exactly what hides a small effect. We count round trips, and
a count survives noise that a duration does not. That is a hypothesis to test on our runs before
it enters a blueprint.

---

## `code_event_loop_block` — the service stalls entirely, including requests that never touch the slow path

| Source | Why |
|---|---|
| **Davis, Williamson & Lee, USENIX Security 2018** — *A Sense of Time for JavaScript and Node.js* [V] | Names the failure mode: **Event Handler Poisoning**. A single long-running callback poisons the event loop, so a single-threaded runtime has nothing left to run anything on. **403 of 1,132 reported npm vulnerabilities (35%) are usable as an EHP vector** — 121 poison the Event Loop, 115 of those by ReDoS. On baseline Node.js both their CPU-bound and I/O-bound attacks produce **complete DoS, zero throughput** |
| **Node.js docs** — *Don't Block the Event Loop* | The practitioner statement of the same thing |

The earlier EUROSEC 2017 paper by the same authors (10.1145/3065913.3065916) is the original
statement of EHP but is **paywalled**; the 2018 paper covers the same ground and is open.

**Why this matters for the blueprint:** the recipe's note says it *"resembles a CPU quota from
the outside"*. So the blueprint must separate it from `svc_cpu_cap`. EHP gives the mechanism
for why: under a quota, threads stop *because they are throttled*; under EHP, one thread is
*busy* and everything else is starved of a runtime to execute on.

**Stated as a test on signals we already have:**

| | `code_event_loop_block` (EHP) | `svc_cpu_cap` (CFS throttling) |
|---|---|---|
| Is a thread running? | **yes — one thread on-CPU the whole time** | **no** |
| What is the CPU doing? | **busy** | **idle**, `next_comm=swapper`, `prev_state=0` |
| Pattern in time | **one continuous block** | **periodic**, on the 100 ms `cfs_period_us` boundary |

Gelle et al. 2021 §4.3 publish the raw `sched_switch` line for the throttled side of that table,
so only the EHP side needs measuring on our runs.

**One thing to check in the recipe.** Davis et al. split the runtime into **one Event Loop** and a
**Worker Pool of 4 by default**. Poisoning the loop is total and instant; poisoning the pool is
**gradual and needs several workers stuck at once**. Which one our injection actually hits decides
whether the signature is one blocked thread or four degrading ones — and we have not asked.

---

## `code_serial_awaits` — total time scales with item count, not with per-call latency

| Source | Why |
|---|---|
| **Turcotte, Shah, Aldrich & Tip, ICSE 2022** — *DrAsync: Identifying and Visualizing Anti-Patterns in Asynchronous JavaScript*. DOI 10.1145/3510003.3510097 [V] | Detects `loopOverArrayWithAwait` — awaiting inside a loop instead of once over `Promise.all`. **That is our fault, named.** 293 static instances across 20 popular repositories, and an ESLint rule exists for it |

This was the hardest of the five to find a source for, and DrAsync is the only paper located
that names the pattern specifically. The recipe already states the open question honestly:
*"whether that is visible in kernel data is exactly the question."*

**Read after the full paper (30 Sept 2026): DrAsync is weak evidence that the fault *matters*, and
it says so itself.** Their two good numbers — **16.4%** (`appcenter-cli/cpDir`) and **36.1%**
(`vuepress/apply`) — are hand-picked favourable fragments, measured on the fragment alone. When
they refactored **every executed instance** in eleventy and vuepress, removing ~1.1K and ~1.2K
runtime promises, they measured **no meaningful change in test-suite run time, twice**. Their
explanation:

> *"Even if thousands of redundant promises are eliminated, it is possible that the application
> was waiting on another operation which takes longer than the sum total of the lifetimes of the
> eliminated promises."*

**That failure is a wall-clock failure, and it is the best argument in the `code_*` set for our
modality.** Serial awaits and `Promise.all` issue the **same number** of round trips. The
difference is **overlap**: the serial version never has two requests in flight, so every `sendto`
follows the previous `recvfrom`. That is readable straight off socket-event timestamps and is
invisible to every method in their paper.

**It also separates this fault from `code_n_plus_one`**, which otherwise looks similar: N+1 issues
*too many* round trips, serial awaits issues *the right number with zero concurrency*.

**Two cautions.** DrAsync only calls the loop a defect *"where the iterations of the loop are
independent"* — if our injection serialises awaits that had to be ordered anyway, we injected
nothing. And their biggest effect came from a **7.8 GB directory copy**; effect size scales with
per-iteration latency, and Sock Shop's front-end awaits are short local HTTP calls. Same
calibration risk as `code_n_plus_one`.

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
| **Karn, Kudva, Huang, Suneja & Elfadel, IEEE TPDS 32(3):674-691, 2021** — *Cryptomining Detection in Container Clouds Using System Calls and Explainable Machine Learning*. DOI 10.1109/TPDS.2020.3029088 [V] | The closest published work to this fault: cryptomining, in **containers**, detected from **system calls**. Its argument is our coverage sweep's problem stated by someone else: **CPU share is a good first-order metric but false-alarms on legitimately busy workloads**, so they move to a second-order one - *which* syscalls, not how much CPU. 8 miners vs 8 deliberately CPU-heavy benign workloads; **decision tree 97.1%**, beating an LSTM by 18 points at 1/500 the training time. Of 100 syscalls the miners use, only **12 are unique to them and 88 are shared**. **Previously cited here as "Suneja et al., IPDS 2020" - wrong first author, wrong venue, wrong year. Corrected 30 Sept 2026.** |
| **Gassais et al., 2020** *(already held)* | LTTng host IDS; lists resource abuse and exfiltration as threats |

**Not obtained:** Tahir et al., *Mining on Someone Else's Dime* (RAID 2017), which introduced
MineGuard and used micro-architectural CPU signatures. Only a ResearchGate record was found.

**A caution for the blueprint.** The coverage sweep found `resource_abuse` separable *per
application only*, and noted it *"runs a hidden CPU loop, so it is probably not separable from
`noisy_neighbor` at all"*. Karn's system-call angle is a different axis from CPU share, which
is why it is worth having — but the sweep's verdict stands until measured.

**And there is a reason it may not rescue the fault.** Their miners are real binaries doing real
work — pool network I/O, file writes, timers — which is where the 12 distinctive syscalls come
from. If our `resource_abuse` recipe is a bare spin loop, it may make **no** distinctive syscalls,
and then this paper's method does not apply to our fault. Check the recipe before citing it as
support. Also note their own data: **Hadoop and Cassandra, both benign, emitted more syscalls per
minute than 4 of the 5 named miners** — so volume is not the signal.

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
