# Key findings from the reference papers

One row per paper. **"What it actually says"** is the finding worth citing; **"What it means
for us"** is what changes in our work because of it.

Read the **Citation problems** section first — four of these papers are currently cited in a
way the paper does not support.

Status: **33 of 50 papers summarised** (28 by me, 5 by you). All three 50+ page documents from
the reference pack are done. Full summaries live in `sources/<slug>/paper.md`. The remaining 17
are listed at the bottom.

---

## Citation problems — all found, all fixed (30 Sept 2026)

Eight corrections, made after reading each paper in full. Every one was a case of citing a
paper for something it does not say.

**All eight were confined to `blueprints/REFERENCE-PACK-FOR-KERNEL-TRACE.md`.** The
`blueprint.json` files and the generated `skill.md` files were clean — three of the affected
blueprints have an empty `evidence_from_literature`, and `service-cpu-throttle`'s actual
discriminator says "broad, simultaneous loss of CPU time across many unrelated processes",
which is about the process population and is correct. **So no blueprint changed, no skill
changed, and no completed run is affected.**

| # | Where | What it said | What the paper says |
|---|---|---|---|
| 1 | Cross-cutting §1, Giraldeau | the backbone method for our discriminators | needs `sched_ttwu` (kprobe — the stock `sched_wakeup` loses the wake-up **source**) and socket-level netfilter events. **We collect neither.** Cite the principle, not the implementation |
| 2 | Blueprint 4, Rezazadeh | "Supports: lock waits reconstructed from traces" | the paper's contribution is that kernel-only tracing **cannot see** user-space locks. Cite it for the **limit** |
| 3 | Blueprint 4, DepGraph | "a cycle in it = deadlock" | **the paper never mentions deadlock or cycle detection.** Its use cases are lock, CPU and disk contention. The cycle argument is ours |
| 4 | Blueprint 6, Rezazadeh | "lock contention can be seen in kernel traces" | in **multi-level** traces. The kernel level alone is the thing the paper says is insufficient |
| 5 | Blueprint 6, Franke | futex rate is a contention signal | **measured on C/C++.** That is *why* the JVM case is an exception, not a contradiction. The paper also names busy-waiting as invisible from the kernel |
| 6 | Blueprint 7, CPI² | "the same logic as 'who preempted me' in `sched_switch`" | CPI² **correlates statistically** because cache interference cannot be attributed directly. `sched_switch` names the culprit outright — **ours is stronger, not equivalent**. CPI² also targets cache/memory-bus, not CPU time |
| 7 | Blueprint 8, Rezazadeh | "lock-holder and waiter analysis from traces" | only with user-space `lock_req`/`lock_acq` tracepoints, which split *waiting for* from *holding*. We cannot make that split |
| 8 | Blueprint 10 | "**all** its threads stop at the same time" | throttling is per `cfs_rq` — **per logical CPU per cgroup**. One pool stopping does not stop the others, and a task is never throttled, only its group |

### Two that were already right

Blueprint 1's Lozi row correctly says **Refines** — cores can be idle while threads wait, so
per-CPU idle time is a needed rule-out. And blueprint 6's framing paragraph already said the
JVM observation is ours to prove, backed by a chain of citations. Both left alone.

---|---|---|---|
| 1 | Blueprints **4, 6, 8** cite Rezazadeh 2020 | Cited as "lock waits can be reconstructed from traces". The paper's actual contribution is that **kernel-only tracing cannot see user-space locks** — hence their `LD_PRELOAD` pthreads tracepoints, which we do not have | Cite it for the **limitation**, not the capability |
| 2 | Blueprint **10** | Says "**all** its threads stop at the same time". Ugedal 2022 shows throttling is enforced **per logical CPU**; one pool being throttled does not throttle the others | Reword to "threads on a throttled CPU stop together, while CPUs are idle" |
| 3 | Blueprint **6** | The futex-means-contention rule comes from Franke 2002, which benchmarks **C/C++ only**. Our JVM finding is the exception, not a contradiction | Cite Franke for the general rule, our measurement for the JVM exception. Already framed correctly in the reference pack |
| 4 | Cross-cutting §1 | We cite Giraldeau 2016 as the method backbone, but our event set lacks `sched_ttwu` (kprobe) and socket-level netfilter events | **We cannot claim we implemented active-path analysis.** Cite the principle only |

---

## Method sources — how to diagnose from traces

| Paper | What it actually says | What it means for us |
|---|---|---|
| **Giraldeau & Dagenais 2016** <br> *Wait Analysis, IEEE TPDS* | Blocking changes control flow; the **wake-up event names the cause of the wait**. Follow it backwards recursively, across threads and machines. O(n). Overhead **18.3% worst case, 5.1% typical, ~200 ns/event**. Busy-wait is **invisible** | The method backbone for blueprints 1, 2, 7, 9. **But it needs `sched_ttwu` via kprobe and socket-level netfilter events — we have neither.** Cite the principle, not the implementation. Their overhead numbers are our reference points |
| **Rezazadeh et al. 2020** <br> *Multi-Level Lock Contention, ISSRE-W* | Giraldeau's kernel-only method **cannot see spinlocks or Apache's filelock**. Fix: `LD_PRELOAD` pthreads tracepoints splitting `lock_req` / `lock_acq` / `unlock`. Overhead **<0.7% user-space, ~7% with a minimal kernel set** | **Argues against kernel-only lock analysis.** We see *that* a thread entered futex, not *how long it waited for what*. Cite for the limitation |
| **Nemati et al. 2022** <br> *Critical Path through Virtualized Envs, IEEE TCC* <br> *(file on disk is the 173-page thesis)* | Recovers guest process states and wait reasons from **host hypervisor tracing only**, at any nesting depth. The **injected virtual interrupt vector names the wait** (disk/task/net/timer). **Overhead ~0.3% vs 3.65-6.13%** for in-VM tracing | Supports "diagnose from the host without touching the guest" — our pid-namespace attribution. **But needs `kvm_*` hypervisor events we don't have.** Their virtualisation machinery solves a problem we don't have: containers share one kernel, so `pid_ns` is already in our events |
| **Kohyarnejadfard 2022** <br> *Anomaly Detection thesis + JCC article* | A span is a sentence; an LSTM trained on **normal traces only** predicts the next event **and its arguments**. **F-score 0.9759** over 4,028 classes. Argues collective > point anomalies, and LTTng > OpenTracing | **The closest published work to ours in data source** — LTTng, microservices, same lab. Different in goal: it decides *whether* a span is anomalous and hands a human a highlighted region. **We localise.** That gap is our contribution. Their F-score is next-key prediction, **not** a fault-detection rate |
| **Franke et al. 2002** <br> *Fuss, Futexes and Furwocks, OLS* | An **uncontended lock never enters the kernel**. Futex syscalls happen only under contention. Busy-waiting is a legitimate design and is invisible from the kernel | The basis of blueprint 4's "FUTEX_WAIT with no FUTEX_WAKE" and blueprint 6's premise. **C/C++ only** — the JVM exception is ours to prove |
| **Gelle, Ezzati-Jivan & Dagenais 2021** <br> *Combining Distributed and Kernel Tracing, Electronics* | Patch the **Jaeger client** to emit an LTTng-UST event per span; LTTng's shared kernel/user clock does the joining for free. Overhead **<4-5% on HotROD**, **18-30% on Cassandra** (short requests pay more). Their §4.3 injects a **1% cpu cgroup cap** and reads out `sched_switch prev_state=0, next_comm=swapper` with **100 ms** periodicity | **The strongest external confirmation in the pack.** Their §4.3 is our blueprint 10, measured independently in 2021 - preempted but not replaced, CPU idle, 100 ms period. Now cited there. They do not name the 100 ms as `cfs_period_us`; we can. Also the right paper to position against: they had request context and still needed a human to read the views |
| **Ezzati-Jivan et al. 2020** <br> *DepGraph, SCAM* | A **waiting-dependency graph**: who is blocked on whom, built from kernel traces. Fills the gap Giraldeau's critical path leaves - **which thread holds the resource you are waiting on**. Use cases are lock, CPU and disk contention | Blueprint 4 cited it for "a cycle in it = deadlock". **The paper never mentions deadlock or cycle detection** - that argument is ours. Corrected. Cite it for the dependency graph, not for the cycle test |
| **Kohyarnejadfard et al. 2022** <br> *JCC article* | The journal version of Chapter 6 of the thesis | Pointer file only - the thesis summary covers it |

---

## Mechanism sources — why the signal exists

| Paper | What it actually says | What it means for us |
|---|---|---|
| **Ugedal & Kumar 2022** <br> *Unnecessary Throttling, SBAC-PAD* | CFS throttles processes **that have not used their quota**, because negative runtime from one period is repaid from the next. Same workload, same quota ratio: **0% throttled periods unlimited → 6.8% at 100 ms → 49% at 10 ms**. Throttling is **per logical CPU** | The citation for blueprint 10's most counter-intuitive claim. Also fixes our wording: not all threads stop together. Note we infer throttling from scheduler behaviour — `nr_throttled` lives in `cpu.stat`, which we do not collect |
| **Sha, Rajkumar & Lehoczky 1990** <br> *Priority Inheritance, IEEE TC* | Defines priority inversion. Assumes **strict priorities**, uniprocessor, binary semaphores. Priority ceiling bounds blocking to one critical section **and prevents deadlock** | **Our fault is not this.** Under CFS `nice` is a weight, so the holder still runs, just less. Call ours "weighted lock-holder starvation". Linux applies inheritance only to PI futexes / RT — which is *why* our fault is observable at all |
| **Turner, Rao & Rao 2010** <br> *CPU bandwidth control for CFS, OLS* <br> *(pp. 245-254 of the proceedings)* | The **design paper** for the mechanism. Hybrid global/local quota pools, slices, per-`cfs_rq` throttling. **Their §6.3 names the slack-time bug**: over-commit bounded by `num_cpus × batch_slice`, fix proposed as generation counters | **The 2010 authors predicted the bug Ugedal measured in 2022** — and Ugedal's "slush fund" is essentially their proposed fix, twelve years later. Also confirms: throttling is per run-queue, tasks are never throttled (only groups), limits are hierarchical with **no feasibility check** |
| **Lozi et al. 2016** <br> *A Decade of Wasted Cores, EuroSys* | Linux breaks the one invariant a scheduler has: **cores sit idle for seconds while runnable threads wait**. Four bugs, same symptom. Cost **13-24% typical, 138x worst case**. They **crash nothing**, so ordinary testing never finds them | Blueprint 1's rule-out: long runnable-wait does **not** prove every CPU is busy, so check per-CPU idle time too. Also separates blueprints 1/7/10 cleanly by what the CPUs were doing. **Fixed in 3.17-4.3; our kernel is 7.0 and CFS became EEVDF in 6.6** - cite the principle, not the bugs |
| **Zhang et al. 2013** <br> *CPI², EuroSys* | Learns normal **CPI** by pooling across all tasks of a job (**GEV** fits best, right-skewed, flag at **2σ**), then correlates the victim's CPI against each suspect's CPU use to name the **antagonist**. Deployed to **all** Google shared clusters. Honest about one job where CPI simply does not correlate | Source of our **victim/antagonist** vocabulary. **Not the same logic as `sched_switch`** - CPI² correlates because cache interference cannot be attributed directly; we read the culprit outright, which makes our claim stronger. Corrected in the pack. Their "learn normal from the population, not the individual" is worth stealing |
| **Lo et al. 2016** <br> *Heracles, ACM TOCS* | Servers are **50-70% of TCO** at **10-50% utilisation**; Google websearch servers idle **30% over 24 h**. Coordinating **four** isolation mechanisms reaches **90% utilisation with no SLO violations**. **No single mechanism suffices** | A **motivation citation only** for blueprint 7 - "even small amounts of interference cause significant SLO violations" is used correctly. Everything else differs: it **prevents** interference with a real-time controller steering on application latency. Pair carefully with CPI²: one prevents, the other detects and throttles |

---

## Empirical sources — does it happen in the wild?

| Paper | What it actually says | What it means for us |
|---|---|---|
| **Dai et al. 2018** <br> *Timeout Problems, IC2E* | 156 bugs, 11 cloud systems. **47% misused timeout value, 31% missing timeout** (≈81% together). Impact: **40% system unavailability**. And: **60% produce no error message, 12% produce a misleading one** | **The 60%/12% is the strongest argument in the pack for the kernel modality** — measured on real organic bugs, not injected faults. Belongs in the introduction, not buried in blueprint 3. DynamoDB 2015 (5 h outage) is our retry-storm example |
| **Lu et al. 2008** <br> *Learning from Mistakes, ASPLOS* | 105 bugs. **97% of deadlocks: two threads, at most two resources.** **22% are one thread re-acquiring what it holds.** 73% of non-deadlock bugs fixed **without** touching locks | Supports blueprint 4's framing that real deadlocks are small. **But no runtime data at all** — our signature is our own measurement. All four apps are **C/C++**; Sock Shop is Java/Go |
| **Yang et al. 2020** <br> *DNS Query Failures, ATC* | 3 B queries. **13.5% fail.** A records 6.9%, **AAAA 64.2%** — but ~60% of domains simply have no AAAA record, and Happy Eyeballs makes that normal | Blueprint 11 cites the 13.5% correctly. **Nothing else transfers** — public Internet, not containers, and it measures **failure** while our fault injects **delay**. Their blind spot (queries with no response) is exactly our signal |
| **Tu et al. 2019** <br> *Real-World Concurrency Bugs in Go, ASPLOS* | 171 bugs, 6 large Go apps. Counter-intuitive headline: **more blocking bugs come from message passing than from shared memory**. Go's own lightweight primitives are the new bug source | The **Go half** of blueprint 4's pairing with Lu 2008 - and Sock Shop has Go services. Changes what a deadlock looks like in a kernel trace: a channel block is not a futex |
| **Yang et al. 2018** <br> *How not to structure your DB-backed web apps, ICSE* | 12 Rails apps, ~200 issues, **9 ORM anti-patterns**. **11 of 12 apps have pages over 2 s** under a modest workload; server time is **>80% of load time for half the slow pages**. 64 manual fixes gave **median 2x, up to 39x**, **78% under 5 lines** - about **6x** total degradation | Blueprint 9's "it happens in the wild" source; the citation is accurate. The gift is the **vocabulary**: N+1 (**many tiny round-trips**) and missing-index (**one long one**) are **opposite kernel-trace signatures** we could separate by counting syscalls. **Our injected `slow_query` is one shape out of nine** - do not imply we cover the family. Rails only; of our two apps only Train Ticket is an ORM app |
| **Ghanavati et al. 2020** <br> *Memory and Resource Leak Defects, EMSE* | 491 issues, 15 Java projects. **76% manifest on error-free paths.** Top causes: forgot to close **30%**, bad exception handling **20%**, collection mismanagement **19%**. **Only 1 of 491 was found by a static analyser**; **63% only showed up at runtime**, via heap dumps and `lsof`. Fixes are small: **54% touch one file**, median churn **<20 lines** | Cited by blueprints 3 and 12, both correctly. The **1-in-491** number is the one we were not using and should be - it is a direct argument for runtime evidence. Also names our limitation: real leaks accumulate slowly on hot paths, and **the thread that hits the limit is not the one that leaked**. Two causes have different shapes we could test - steady growth vs bursts on error paths. **Java only** |
| **Gunawi et al. 2016** <br> *Why Does the Cloud Stop Computing?, SoCC* | 597 outages, 32 services, 1,247 news and post-mortem reports, 2009-2015. **355 of 597 (59%) have an UNKNOWN root cause.** Among the known: **UPGRADE 16%, NETWORK 15%, BUGS 15%**. NETWORK caused **52 outages across 21 services** | Blueprint 2's prevalence source. **Keep the qualifier**: 15% is of outages with a *known* cause; of all 597 it is 8.7%. The better citation is the **59% unknown** - it sits beside Dai's 60% and Ghanavati's 1-in-491 as the third independent measurement that **the evidence is not in the record**. No telemetry, so never cite it for a signature |
| **Arzani et al. 2016** <br> *NetPoirot, SIGCOMM* | **Blame allocation** - client, network or server - from a **client-side TCP agent only**, no application knowledge. Up to **96% for some failure types**. Key insight: **non-network failures still change how TCP behaves** (slow reader → zero-window probing; router drops → duplicate ACKs; client CPU load → less data sent) | Blueprint 2's closest academic match, and the citation is right. Their **blame-allocation framing is our WHERE axis stated by someone else**, with a production story behind it. Their three TCP signals are a checklist: **we have none of the flag-level ones** and infer loss from timing gaps. Their **10.55% per-machine partition error** is independent support for our v1 region-confound worry |

---

## Dataset and benchmark neighbours

| Paper | What it actually says | What it means for us |
|---|---|---|
| **Pham et al. 2025** <br> *RCAEval, WWW Companion* | 735 failure cases, 3 systems (**incl. Sock Shop and Train Ticket**), 11 fault types, metrics + logs + traces, 15 baselines. Best Avg@5 ≈ 0.80. **DISK 1.00 vs DELAY 0.47** | Our nearest dataset neighbour. **It has no kernel traces** — that is the gap we fill, in the most complete public benchmark available. Their network-fault weakness is the number to compare against. **Scores are not comparable** — different task, different inputs |

---

## Related work — the blueprint idea itself

| Paper | What it actually says | What it means for us |
|---|---|---|
| **An et al. 2024** <br> *Nissist* | Turns messy TSGs into nodes of **intent + action + linker**. Retrieves on *intent*, not document text. **Incidents with a TSG had 60% shorter TTM** across ~1,000 real incidents | The 60% figure is a better motivating citation than their own TTM numbers (5 incidents, no baseline). **`linker` — outcome → next intent — is worth stealing**; our "stop and switch" is prose, theirs is a field |
| **Unnikrishnan et al. 2026** <br> *FixItFlow* | Generates TSGs from incident history. **Top TSG complaints: missing information 32.24%, broken links 13.32%, incorrect instructions 11.21%** | **Cite only the statistic.** Its own table shows satisfaction 2.58/5, **NPS −100, 0% adoption**. Useful as a **negative result**: generate-from-history produces readable guides nobody uses — which strengthens the case for measure-first |
| **Bronson et al. 2021** <br> *Metastable Failures, HotOS* | *"It is common for an outage... to be initially blamed on the trigger, but the true root cause is the sustaining effect."* Vulnerable ≠ overloaded; many systems run there deliberately | The exact citation behind blueprint 5 reporting trigger and sustaining loop **separately**. **But our paused container is not metastable** by their own definition — it resolves when the trigger stops |

---

## Supervisor-recommended papers (`prof-recommendation`)

Five already had hand-written summaries; they are now in `sources/<slug>/paper.md` with
`meta.yaml`, marked `summary_by: user`.

| Source | Paper | Summary |
|---|---|---|
| `shahedi-2026-performance-archetypes` | Discovering Performance Archetypes, ASE 2026 | yours |
| `fu-2025-msofsanomaly` | MSoFSAnomaly, JSS 2025 | yours |
| `song-2024-asfc` | ASFC, FGCS 2024 — **uses Sock Shop** | yours |
| `wert-2015-dynamicspotter` | DynamicSpotter, ICPE 2015 | yours |
| `wert-2013-ppd` | Supporting Swift Reaction, ICSE 2013 | yours |

### The four long ones — two observations before summarising them

| Source | Pages | Note |
|---|---|---|
| `ghosh-tracing-patterns-thesis` | 147 | *System and Application Performance Analysis Patterns Using Software Tracing*. **The closest of the four to our work** — performance analysis *patterns* from software tracing is the same idea as a blueprint. Worth doing first |
| `wert-thesis-dissertation` | 329 | Wert's KIT doctoral dissertation |
| `wert-thesis-book` | 486 | **The same work**, published as Karlsruhe Series vol. 20. Summarise one, not both |
| `vostokov-crash-dump-encyclopedia` | 1200 | *Encyclopedia of Crash Dump Analysis Patterns, 2nd ed.* A commercial reference book, not a research result. The filename carries a libgen watermark |

Both Wert theses are the long form of `wert-2013-ppd` and `wert-2015-dynamicspotter`, which
already have summaries — so the marginal value of summarising a 486-page duplicate is low.

## Still to do — 17 papers

**Method / DORSAL:** `gassais-2020-host-ids`

**Mechanism:** `weiner-2022-tmo`, `mogul-2001-nagle`

**Empirical:** `jin-2012-performance-bugs`, `zhou-2018-train-ticket`,
`waseem-2021-issues-five-microservices`, `waseem-2023-issues-causes-solutions`,
`replicawatcher-2024`

**Related work (LLM agents / TSGs):** `autotsg-2022`, `stepfly-2026`, `rcacopilot-2024`,
`roy-2024-llm-agents-rca`, `xpert-2023`, `aiopslab-2025`, `beyond-fault-localization`,
`self-evolving-rca-harness`, `mining-root-cause-knowledge-2022`, `siriushelper`

Plus the `code_*` family references, which have no cached text yet:
`chen-2014-orm-antipatterns`, `drasync-2022`, `davis-2018-first-class-timeouts`,
`suneja-2020-cryptomining-containers`.

### Cannot be summarised

| Source | Why |
|---|---|
| `patent-11750692-conn-pool` | 21 pages of **scanned images**, no text layer. Needs OCR |
| `gunawi-2016-socc-root` | Duplicate of `gunawi-2016-cloud-outages` — one summary will serve both |

### The three 50+ page documents — now done

All three were handled by extracting only the relevant part rather than the whole volume:

| Source | Total | What was actually read |
|---|---|---|
| `turner-2010-cpu-bandwidth` | 272 pp | **pp. 245-254** — the paper itself, inside the OLS 2010 proceedings |
| `nemati-2022-critical-path` | 173 pp | abstract, contributions, and **Chapter 5**, which is the TCC article |
| `kohyarnejadfard-2022-thesis` | 140 pp | abstract, contributions, and **Chapter 6**, which is the JCC article |
