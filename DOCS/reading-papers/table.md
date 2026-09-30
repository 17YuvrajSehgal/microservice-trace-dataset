# Key findings from the reference papers

One row per paper. **"What it actually says"** is the finding worth citing; **"What it means
for us"** is what changes in our work because of it.

Read the **Citation problems** section first — four of these papers are currently cited in a
way the paper does not support.

Status: **15 of 41 papers summarised.** All three 50+ page documents are done. Full summaries live in
`sources/<slug>/paper.md`. The remaining 29 are listed at the bottom.

---

## Citation problems found so far

These are not summary issues. They are places where a blueprint says something the cited paper
does not support.

| # | Where | Problem | Fix |
|---|---|---|---|
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

---

## Mechanism sources — why the signal exists

| Paper | What it actually says | What it means for us |
|---|---|---|
| **Ugedal & Kumar 2022** <br> *Unnecessary Throttling, SBAC-PAD* | CFS throttles processes **that have not used their quota**, because negative runtime from one period is repaid from the next. Same workload, same quota ratio: **0% throttled periods unlimited → 6.8% at 100 ms → 49% at 10 ms**. Throttling is **per logical CPU** | The citation for blueprint 10's most counter-intuitive claim. Also fixes our wording: not all threads stop together. Note we infer throttling from scheduler behaviour — `nr_throttled` lives in `cpu.stat`, which we do not collect |
| **Sha, Rajkumar & Lehoczky 1990** <br> *Priority Inheritance, IEEE TC* | Defines priority inversion. Assumes **strict priorities**, uniprocessor, binary semaphores. Priority ceiling bounds blocking to one critical section **and prevents deadlock** | **Our fault is not this.** Under CFS `nice` is a weight, so the holder still runs, just less. Call ours "weighted lock-holder starvation". Linux applies inheritance only to PI futexes / RT — which is *why* our fault is observable at all |
| **Turner, Rao & Rao 2010** <br> *CPU bandwidth control for CFS, OLS* <br> *(pp. 245-254 of the proceedings)* | The **design paper** for the mechanism. Hybrid global/local quota pools, slices, per-`cfs_rq` throttling. **Their §6.3 names the slack-time bug**: over-commit bounded by `num_cpus × batch_slice`, fix proposed as generation counters | **The 2010 authors predicted the bug Ugedal measured in 2022** — and Ugedal's "slush fund" is essentially their proposed fix, twelve years later. Also confirms: throttling is per run-queue, tasks are never throttled (only groups), limits are hierarchical with **no feasibility check** |

---

## Empirical sources — does it happen in the wild?

| Paper | What it actually says | What it means for us |
|---|---|---|
| **Dai et al. 2018** <br> *Timeout Problems, IC2E* | 156 bugs, 11 cloud systems. **47% misused timeout value, 31% missing timeout** (≈81% together). Impact: **40% system unavailability**. And: **60% produce no error message, 12% produce a misleading one** | **The 60%/12% is the strongest argument in the pack for the kernel modality** — measured on real organic bugs, not injected faults. Belongs in the introduction, not buried in blueprint 3. DynamoDB 2015 (5 h outage) is our retry-storm example |
| **Lu et al. 2008** <br> *Learning from Mistakes, ASPLOS* | 105 bugs. **97% of deadlocks: two threads, at most two resources.** **22% are one thread re-acquiring what it holds.** 73% of non-deadlock bugs fixed **without** touching locks | Supports blueprint 4's framing that real deadlocks are small. **But no runtime data at all** — our signature is our own measurement. All four apps are **C/C++**; Sock Shop is Java/Go |
| **Yang et al. 2020** <br> *DNS Query Failures, ATC* | 3 B queries. **13.5% fail.** A records 6.9%, **AAAA 64.2%** — but ~60% of domains simply have no AAAA record, and Happy Eyeballs makes that normal | Blueprint 11 cites the 13.5% correctly. **Nothing else transfers** — public Internet, not containers, and it measures **failure** while our fault injects **delay**. Their blind spot (queries with no response) is exactly our signal |

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

## Still to do — 26 papers

**Method / DORSAL:** `gelle-2021-combining-tracing`, `ezzati-2020-depgraph`,
`gassais-2020-host-ids`, `kohyarnejadfard-2022-anomaly` *(the JCC article — the thesis
Chapter 6 summary already covers it; needs only a short pointer file)*

**Mechanism:** `lozi-2016-wasted-cores`, `zhang-2013-cpi2`, `lo-2016-heracles`,
`weiner-2022-tmo`, `mogul-2001-nagle`

**Empirical:** `tu-2019-go-concurrency`, `yang-2018-db-perf-bugs`,
`ghanavati-2020-resource-leaks`, `gunawi-2016-cloud-outages`, `jin-2012-performance-bugs`,
`zhou-2018-train-ticket`, `waseem-2021-issues-five-microservices`,
`waseem-2023-issues-causes-solutions`, `arzani-2016-netpoirot`, `replicawatcher-2024`

**Related work (LLM agents / TSGs):** `autotsg-2022`, `stepfly-2026`, `rcacopilot-2024`,
`roy-2024-llm-agents-rca`, `xpert-2023`, `aiopslab-2025`, `beyond-fault-localization`,
`self-evolving-rca-harness`, `mining-root-cause-knowledge-2022`, `siriushelper`

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
