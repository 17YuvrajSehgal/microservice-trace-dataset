# Reference Pack for Kernel-Trace RCA Blueprints (Sock Shop / Train Ticket, LTTng)

Every blueprint can be grounded in the literature, but not in one way: each needs a **mechanism source** (kernel docs or OS papers), an **empirical source** (bug or outage studies that mine issues or post-mortems), and a **method source** (a kernel-trace diagnosis paper, mostly from the DORSAL lab and Brendan Gregg). The strongest empirical sources are mining studies of bug trackers and post-mortems, not the fault injection papers.

## TL;DR

- **The priority blueprints are well supported.** The kernel docs explain the signals (CFS bandwidth control, pids controller, cgroup v2 memory.max, PSI, futex). Mining studies give "it happens in the wild" evidence: Lu et al. ASPLOS 2008 (concurrency), Dai et al. IC2E 2018 (timeouts), Ghanavati et al. EMSE 2020 (resource leaks), Yang et al. ICSE 2018 (DB performance bugs), Huang et al. OSDI 2022 (metastable failures / retry storms), Gunawi et al. SoCC 2016 (597 unplanned outages from 1,247 news and post-mortem reports at 32 services). The DORSAL papers (Giraldeau & Dagenais 2016, Nemati et al. 2022, Rezazadeh et al. 2020, Kohyarnejadfard et al. 2022) show that your data source (LTTng kernel traces with sched_switch and wakeups) is an accepted method.
- **Some sources refine or contradict your discriminators, and you should say so openly.** Examples: CFS throttling can happen while average CPU use is low (Dan Luu; Ugedal et al. 2022). JVM parking goes through pthread_cond and then futex, so a high futex share is normal on Java services. Nice values under CFS are weights, not strict priorities, so "priority inversion via nice" is weaker than the classic real-time definition (Sha et al. 1990). Bronson et al. warn that metastable outages are often wrongly blamed on the trigger.
- **Eleven citations were corrected on 30 Sept 2026, after the papers were read in full.** Most
  were a case of citing a paper for something it does not say; three were bibliographic errors. The corrections are in the tables
  below; in summary: Rezazadeh 2020 argues that kernel-only tracing **cannot** see user-space
  locks (it is a limit for us, not a capability); DepGraph **never mentions deadlock or cycle
  detection**; CPI2 correlates statistically because cache interference cannot be attributed
  directly, which makes `sched_switch` **stronger** than it, not equivalent; Giraldeau's method
  needs `sched_ttwu` and socket-level netfilter events that **we do not collect**; Franke's
  futex result is measured on **C/C++**, which is why the JVM case is an exception rather than a
  contradiction; and CFS throttling is enforced **per run-queue**, not across all of a
  container's threads. Full notes per paper in `DOCS/reading-papers/sources/<slug>/paper.md`.
  Three more were in `DOCS/reading-papers/FUTURE-BLUEPRINT-REFERENCES.md`: Chen 2014 does **not**
  report an order of magnitude for N+1 (that figure is a different anti-pattern, and one-by-one
  processing is -17%); "Suneja et al., IPDS 2020" is **Karn et al., IEEE TPDS 32(3), 2021**; and
  Zhou et al. is **TSE 2021**, not 2018.
  **None of these reached a blueprint or a generated skill** - they were confined to documents -
  so no run is affected.
- **The strongest single result for the kernel modality is in Zhou et al. 2021, and it is a
  failure.** They replicated 22 real industrial faults on TrainTicket and re-debugged each at
  three tooling levels, up to distributed trace visualisation. **Two could not be debugged at any
  level, and both are non-functional *environment* faults** - a JVM/Docker memory-limit conflict
  (our `service-memory-cap`) and fine-grained SSL offloading. Their conclusion: *"most fault cases
  **except those caused by environmental settings** can benefit from trace visualisation."* The
  environment is the kernel's layer. Three other papers measure the same shortfall from different
  angles: **Dai 2018** (60% of timeout bugs produce no error message), **Gunawi 2016** (59% of 597
  outages have no reported root cause), **Ghanavati 2020** (1 of 491 leak issues found by static
  analysis; 63% only visible at runtime). Four independent studies, four different failure
  families, one conclusion: **the evidence needed to diagnose these is not in the code, the logs,
  or the spans.**
- **The blueprint idea itself fits a growing line of work on troubleshooting guides (TSGs) and LLM agents.** The main works are AutoTSG, Nissist, RCACopilot, Roy et al. FSE 2024, StepFly (FSE 2026: empirical study of 92 real TSGs; the paper reports "a ~94% success rate on GPT-4.1" and a 32.9%–70.4% time reduction for parallelizable TSGs) and FixItFlow. None of them works from kernel traces, and that is your gap and your contribution.

## How to read this report

Each reference has a **status tag**:
- **[V]** = I opened the page or saw its full abstract in this session.
- **[S]** = seen only in a search snippet or reported by a helper search. Open the page before you cite it.
- **[M]** = well-known work, but the details come from my memory. Check the DOI before you cite it.

Each reference also has a **relation** to the blueprint claim: **supports**, **refines** (it adds a condition), or **contradicts** (it warns against a naive reading).

---

## Cross-cutting references (cite these in every blueprint's "Method" section)

1. **Giraldeau, F., Dagenais, M. "Wait Analysis of Distributed Systems Using Kernel Tracing." IEEE TPDS 27(8), 2016.** DOI: 10.1109/TPDS.2015.2488629 [M: check DOI]. It builds the "active path" of a task from sched_switch, wakeups, softirq and network events, across hosts. **Supports** the idea that kernel scheduler and wakeup events are enough to explain where time goes. This is the backbone for all "blocked vs. running vs. preempted" discriminators. **Scope limit, checked against the paper:** the method needs `sched_ttwu` (a kprobe on `try_to_wake_up`, because the stock `sched_wakeup` tracepoint fires on the destination CPU and loses the wake-up SOURCE) and `inet_sock_local_in/out` via netfilter. We collect `sched_wakeup` and device-level `net_dev_xmit`/`net_if_receive_skb` instead. **Cite the principle - the wake-up identifies the wait - not the implementation. We have not done active-path analysis.**
2. **Nemati, H., Tetreault, F., Puncher, J., Dagenais, M. R. "Critical Path Analysis through Hierarchical Distributed Virtualized Environments Using Host Kernel Tracing." IEEE Transactions on Cloud Computing 10:774–791, 2022.** [V] https://www.semanticscholar.org/paper/a42e038f8b36e2247f3a9a131b61de549cecf77f. It gets execution flows and wait dependencies from host tracing only, even for nested VMs.\[1\] **Supports** diagnosis from the host kernel, without instrumenting the guest or container. That matches your pid-namespace attribution.
3. **Gelle, L., Ezzati-Jivan, N., Dagenais, M. R. "Combining Distributed and Kernel Tracing for Performance Analysis of Cloud Applications." Electronics 10(21):2610, 2021 (open access).** [V] https://www.mdpi.com/2079-9292/10/21/2610. The paper says a critical path lets you "observe contention for resources, for example, lock contention and cpu contention."\[2\] **Supports** the lock-contention and CPU-contention blueprints.
4. **Kohyarnejadfard, I., Aloise, D., Azhari, S. V., Dagenais, M. R. "Anomaly detection in microservice environments using distributed tracing data analysis and NLP." Journal of Cloud Computing 11:25, 2022.** DOI: 10.1186/s13677-022-00296-4. Open access: https://pmc.ncbi.nlm.nih.gov/articles/PMC9375740/ [V]. It collects LTTng kernel and user events per span, detects anomalies, and shows them in Trace Compass.\[3\]\[4\] **Supports** LTTng CTF as a microservice RCA data source. Related PhD thesis: Kohyarnejadfard, "System Performance Anomaly Detection using Tracing Data Analysis," Polytechnique Montréal, 2022: https://publications.polymtl.ca/10281/1/2022_ImanKohyarnejadfard.pdf [V].\[5\]
5. **Denys et al. "Distributed computation of the critical path from execution traces." Software: Practice and Experience, 2023.** DOI: 10.1002/spe.3210 [V]. It scales the Giraldeau critical-path algorithm and notes that critical paths across several traces need near-perfect clock sync.\[6\] **Refines** any cross-container, cross-trace step in your blueprints.
6. **Brendan Gregg, USE Method** (https://www.brendangregg.com/usemethod.html) and **Off-CPU Analysis** (https://www.brendangregg.com/offcpuanalysis.html) [M]. USE checks Utilization, Saturation and Errors for every resource. Off-CPU analysis explains blocked time. **Supports** the blueprint structure: check the resource, then saturation, then errors.
7. **Linux PSI docs (Weiner).** https://docs.kernel.org/accounting/psi.html [V via helper]. Quote: "When CPU, memory or IO devices are contended, workloads experience latency spikes, throughput losses, and run the risk of OOM kills." PSI exists per cgroup (cpu.pressure, memory.pressure, io.pressure).\[7\] **Supports** the idea of "stall time" as the central signal. PSI is not in your LTTng trace, but you can rebuild it from the runnable-but-waiting time between sched_wakeup and sched_switch.
8. **Empirical base for microservice faults:** Zhou, Peng, Xie, Sun, Ji, Li & Ding, "Fault Analysis and Debugging of Microservice Systems: Industrial Survey, Benchmark System, and Empirical Study," **IEEE TSE 47(2):243-260, 2021** (the paper that created Train Ticket), DOI 10.1109/TSE.2018.2887384 [V]. **Read in full 30 Sept 2026, and it carries the single strongest result in this pack for the kernel modality.** 16 developers from 12 companies reported 22 real faults; the authors replicated all 22 on TrainTicket and re-debugged each at three tooling levels - basic logs, visual logs, visual traces. **Two faults could not be debugged at ANY level, and both are non-functional *environment* faults**: F3 (JVM memory config conflicts with the Docker cluster limit, so Docker kills the JVM - our `service-memory-cap`) and F4 (fine-grained SSL offloading in almost every container). Their own summary: *"most fault cases **except those caused by environmental settings** can benefit from trace visualisation."* The environment is the kernel's layer. Also useful: time to locate and fix scales **9.5 h (1 microservice) -> 20 h (2) -> 40 h (3) -> 48 h (>3)**, and for interaction faults initial understanding alone takes **3 h with visual traces vs 21 h with basic logs**. Caveat the authors state: TrainTicket is **smaller and less heterogeneous** than the industrial systems surveyed, and the times are participant estimates cross-checked against issue trackers. Pham et al., RCAEval, WWW 2025 Companion, arXiv:2412.17015 [M]. Waseem et al., "On the Nature of Issues in Five Open Source Microservices Systems," EASE 2021, arXiv:2104.12192 [V].\[8\] Waseem et al., "Understanding the Issues, Their Causes and Solutions in Microservices Systems," which mined 2,641 issues from 15 open-source microservice systems on GitHub, plus 15 interviews and a survey of 150 practitioners, arXiv:2302.01894, now in the Journal of Systems and Software [V].\[9\] **These are the MSR-style GitHub-mining papers your supervisor asked for, at the microservice level.**

  **Both read in full 30 Sept 2026, and together they contain the measured justification for building this dataset at all.** They are **not independent** - same first two authors, same method, the 2023 paper extends the 2021 one from 5 systems to 15. Do not add their counts. Cite the 2023 paper by default; keep the 2021 one because **one of its five subject systems is Sock Shop** (`microservices-demo/microservices-demo`, 280 closed issues).

  **The gap between what is filed and what is felt, from inside one study:**

  | | Share of mined issues | Practitioners saying "very often"/"often" |
  |---|---|---|
  | **Performance** | **1.67%** (45/2698, **16th of 19**); 0.67% (9/1345) in the 2021 paper | **63.33%** (5th of 19, mean 3.51) |
  | Monitoring | 3.29% | 52.67% |
  | Technical Debt | 25.46% (1st) | 70.67% |

  **Nearly two thirds of 150 practitioners hit performance problems often; fewer than 1 issue in 50 is about performance.** Technical debt is filed 15x more often while being reported only slightly more frequent. So **a GitHub mining study cannot be the empirical base for performance faults** - the population is not there. Their 45 performance issues spread over 16 types is about **3 per type across 15 systems**. **This is why the fault families have to be injected and labelled, and it is the real reason for the "honest gaps" recorded below** (connection-pool exhaustion, fork storms, queue backlog): the literature is thin because the trackers are thin. Pair with Jin 2012, which gives the mechanism - 935 days to discover a performance bug, because *"judging whether performance bugs have manifested is a unique challenge."*

  Two other things worth taking: their **Performance** subcategories name **SLOW QUERY**, **HIGH CPU USAGE** and **circuit breaker issue** as types, which is a thin but real in-the-wild anchor for three of our families; and their **Monitoring** category (89 issues) is *larger than Performance*, with **60 on tracing and logging management** including DISTRIBUTED TRACING ERROR and OBSERVABILITY ISSUE - i.e. **the observability stack is itself one of the reported problems**. Pair that with Zhou 2021's two undebuggable faults.
9. **Method caution for MSR work:** Kalliamvakou et al., "An in-depth study of the promises and perils of mining GitHub," EMSE 21(5), 2016, DOI 10.1007/s10664-015-9393-5 [V].\[10\] Cite it in your threats-to-validity section if you use GitHub issues as evidence.

---

## Priority blueprints

### 1. host-cpu-saturation (anomaly_cpu)

**Discriminator to ground:** all CPUs busy; long runnable-wait (the time between wakeup and running) for *all* containers, not only one; no throttling marks.

| Reference | Type | Relation |
|---|---|---|
| Gregg, USE Method [M]. https://www.brendangregg.com/usemethod.html | Method | **Supports**: CPU saturation = run-queue length above the CPU count. |
| Lozi et al., "The Linux Scheduler: a Decade of Wasted Cores," EuroSys 2016. DOI 10.1145/2901318.2901326. PDF: https://people.ece.ubc.ca/sasha/papers/eurosys16-final29.pdf [V] | Mechanism | **Refines**: cores "may stay idle for seconds while ready threads are waiting in runqueues."\[11\] So a long runqueue wait does *not* always mean every CPU is busy. Your rule-out should check per-CPU idle time as well as runqueue wait. |
| Kernel PSI doc, cpu "some" [V]. https://docs.kernel.org/accounting/psi.html | Mechanism | **Supports**: CPU pressure = share of time tasks are runnable but not running. |\[12\]
| Giraldeau & Dagenais 2016 [M] | Method | **Supports**: the critical path shows "preempted" segments. |

**Tip:** Host saturation and co-tenant contention (blueprint 7) look the same on one victim. Your discriminator is *breadth*: in host saturation, every container shows high runnable-wait.

### 2. network-path-degradation (anomaly_net, svc_net)

**Discriminator to ground:** more time blocked in recv/poll waiting for peers; retransmissions show up as repeat net_dev_xmit for the same flow; softirq NET_RX timing changes; CPU stays normal.

| Reference | Type | Relation |
|---|---|---|
| Arzani et al., "Taking the Blame Game out of Data Centers Operations with NetPoirot," SIGCOMM 2016. DOI 10.1145/2934872.2934884 [M] | Method | **Supports**: TCP-level signals at the end host alone can tell whether a fault is in the client, the network or the server. This is the closest academic match to "diagnose the network from the host." |
| RFC 6298 (TCP retransmission timer), https://www.rfc-editor.org/rfc/rfc6298 [M] | Mechanism | **Supports**: loss makes the sender wait for the RTO (minimum 1 s in the RFC; Linux uses 200 ms), so a clear gap appears between sends. |
| Giraldeau & Dagenais 2016 [M] | Method | **Supports**: the wait analysis follows a blocked task across the network to the remote host through packet events. |
| Gunawi et al., "Why Does the Cloud Stop Computing?" SoCC 2016. DOI 10.1145/2987550.2987583 [M] | Empirical | **Supports**: NETWORK problems caused 52 outages across 21 services; the paper states "NETWORK problems are responsible for 15% of service outages" (among outages with a known root cause). |

**Limit:** netem delay does not add CPU work. Your "CPU is normal" rule-out is correct, but say that you infer loss from timing gaps, because LTTng does not directly record TCP retransmits unless you enable the `tcp_retransmit_skb` tracepoint.

### 3. connection-pool-exhaustion (conn_pool_exhaustion) — *was weak, now better*

**Discriminator to ground:** connect/accept setup work collapses; threads block waiting for a pool slot (futex wait in user space, not network wait). **Applicability:** does not apply when callers already pool connections.

| Reference                                                                                                                                                                                                                                    | Type | Relation |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|---|
| Ghanavati, Costa, Seboek, Lo, Andrzejak, "Memory and resource leak defects and their repairs in Java projects," Empirical Software Engineering 25(1):678–718, 2020. DOI 10.1007/s10664-019-09731-8. OA: https://arxiv.org/abs/1810.00101 [V] | Empirical (MSR-style: 491 issues, 15 Java projects) | **Supports**: resource leaks (connections, streams, file handles) are common, and "most of the errors manifest on error-free execution paths" (76% of 491 issues), so a leak builds up quietly and then the pool runs dry. Connection leaks in their data are almost entirely two causes: forgot to close (28 issues) and did not close when an exception was thrown (18). Also worth quoting for motivation: **only 1 of the 491 issues was found by a static analyser** (none of the memory leaks), while ~63% were found at runtime with heap dumps or `lsof`. |\[13\]
| Dai, He, Gu, Lu, "Understanding Real-World Timeout Problems in Cloud Server Systems," IEEE IC2E 2018. DOI 10.1109/IC2E.2018.00022. PDF: https://dance.csc.ncsu.edu/papers/IC2E18.pdf [V]                                                     | Empirical (156 bugs, 11 systems) | **Supports**: "81% timeout problems are caused by either misused timeout values or missing timeout checking."\[14\] A missing pool-acquire timeout is one such case. |
| HikariCP, "About Pool Sizing" wiki, https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing [M]                                                                                                                                   | Industrial | **Refines**: small pools are normal and healthy, so a small number of live connections alone is not a fault. |
| Wooldridge (HikariCP README) + Spring Boot reference, "SQL databases" [V]: pooled callers make few connect() calls in steady state. HikariCP is Spring Boot's default pool. Stored: `DOCS/reading-papers/sources/hikaricp-readme/`, `.../spring-boot-datasource-defaults/`                                                                                                                                          | Mechanism | **Contradicts** the naive discriminator: for already-pooled callers, "few connects" is the *normal* state. Your applicability note is right and should cite HikariCP. |
| US Patent 11,750,692 "Connection pool anomaly detection mechanism" (Salesforce) [S], https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11750692                                                                               | Industrial | **Supports** (weak): says exhaustion "may occur frequently" in production and separates "sustained" from "intermittent" exhaustion. Patent text, not peer reviewed. |\[15\]

**Honest gap:** I found **no peer-reviewed MSR paper focused only on connection-pool exhaustion.** The best academic chain is: leak study (Ghanavati) + timeout study (Dai) + pool-sizing theory (HikariCP, industrial). Say this in the thesis. It is a real gap that your work partly fills.

**The gap is narrower than that, though.** Zhou et al. 2021 **F5** is a verified industrial case of exactly this fault, in a peer-reviewed venue: a microservice whose **thread pool is shared between two request types**; high load of one exhausts it and **the other type fails with timeouts**. Reported by an industrial developer, **6 days to locate**, and **replicated in TrainTicket** (ticket-reservation service, shared by searching and booking) so it can be run. It is not a paper *about* pool exhaustion, but it is no longer true that the fault has no peer-reviewed industrial instance.

### 4. deadlock-lock-order (deadlock)

**Discriminator to ground:** the workload appears and then goes almost silent; threads are parked in futex_wait with no matching wake; the event rate is near zero; there is no CPU burn.

| Reference                                                                                                                                                                                    | Type | Relation |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|---|
| Lu, Park, Seo, Zhou, "Learning from Mistakes: A Comprehensive Study on Real World Concurrency Bug Characteristics," ASPLOS 2008. DOI 10.1145/1346281.1346323 [M]                             | Empirical (105 bugs from MySQL, Apache, Mozilla, OpenOffice; 31 deadlocks) | **Supports**: "Almost all (97%) of the examined deadlock bugs involve two threads circularly waiting for at most two resources"; 22% are caused by one thread acquiring a resource it already holds. |
| Tu, Liu, Song, Zhang, "Understanding Real-World Concurrency Bugs in Go," ASPLOS 2019. DOI 10.1145/3297858.3304069 [M]                                                                        | Empirical (Docker, Kubernetes, etcd, gRPC, etc.) | **Supports / refines**: Sock Shop has Go services. In Go, many blocking bugs come from channel misuse, not mutexes. A goroutine blocked on a channel parks in the Go runtime, so on the kernel side you may see *idle epoll/futex* threads, not one futex per blocked goroutine. |
| Franke, Russell, Kirkwood, "Fuss, Futexes and Furwocks: Fast Userlevel Locking in Linux," OLS 2002 [M] (kernel.org OLS mirror)                                                               | Mechanism | **Supports**: an uncontended lock never enters the kernel; only waiting enters FUTEX_WAIT. So a deadlock = FUTEX_WAIT with no FUTEX_WAKE. |\[16\]
| Rezazadeh, Ezzati-Jivan, Galea, Dagenais, "Multi-Level Execution Trace Based Lock Contention Analysis," ISSRE Workshops 2020, pp. 177–182 [V]. Stored: `DOCS/reading-papers/sources/rezazadeh-2020-lock-contention/`                                            | Method | **Refines, and warns**: the paper's contribution is that Giraldeau's KERNEL-ONLY critical path *cannot see* locks implemented in user space - spinlocks, and Apache's filelock in their use case. Their fix is `LD_PRELOAD` pthreads tracepoints splitting `lock_req`/`lock_acq`/`unlock`, which we do NOT have. Cite it for the LIMIT: we see that a thread entered futex, not how long it waited or for whom. Overhead <0.7% user-space, ~7% with a minimal kernel set. |\[17\]\[18\]
| Ezzati-Jivan, Fournier, Dagenais, Hamou-Lhadj, "DepGraph: Localizing Performance Bottlenecks in Multi-Core Applications Using Waiting Dependency Graphs and Software Tracing," SCAM 2020 [S] | Method | **Supports**: waiting dependencies between threads and resources are recoverable from kernel traces, and - unlike a critical path - the graph names the thread HOLDING the blocking resource. Overhead never above 10.1%. **The paper does NOT discuss deadlock or cycle detection**; its use cases are lock, CPU and disk contention. "A cycle in a wait-for graph is a deadlock" is the textbook condition and is OUR reasoning - do not attribute it to this paper. |\[19\]

**Stopping condition tip:** A JVM deadlock does *not* go fully silent: GC, JIT and timer threads keep waking up. Say "the application threads go silent," and cite the JVM futex notes in blueprint 6.

### 5. dependency-outage-retry-storm (dependency_outage)

**Discriminator to ground:** the dependency container has almost no events; callers show repeated connect() → ECONNREFUSED/timeout in a regular retry rhythm; the callers' CPU rises from retry work.

| Reference | Type | Relation |
|---|---|---|
| Bronson, Aghayev, Charapko, Zhu, "Metastable Failures in Distributed Systems," HotOS 2021. DOI 10.1145/3458336.3465286. PDF: https://sigops.org/s/conferences/hotos/2021/papers/hotos21-s11-bronson.pdf [V] | Mechanism/theory | **Refines**: "It is common for an outage that involves a metastable failure to be initially blamed on the trigger."\[20\] Your blueprint should report the *trigger* (the dependency goes silent) and the *sustaining loop* (the retries) as separate findings. |
| Huang et al., "Metastable Failures in the Wild," OSDI 2022 (USENIX open access). Summary: https://www.usenix.org/publications/loginonline/metastable-failures-wild [V] | Empirical (public incident reports) | **Supports**: they found 21 metastable failures in public incident reports, "including four at AWS, four at Google Cloud, and four at Microsoft Azure"; retry storms are a main pattern. |\[21\]
| Dai et al., IC2E 2018 (above) [V]; slides: https://tingdai.github.io/files/understanding_IC2E18_slides.pdf | Empirical | **Supports**: the slides show a DynamoDB outage where overload plus "no proper limit of retry" made an outage last about 5 hours. |\[22\]
| Microsoft Azure Architecture Center, "Retry Storm antipattern," https://learn.microsoft.com/en-us/azure/architecture/antipatterns/retry-storm/ [S] | Industrial | **Supports**: an industry definition. |
| Brooker, "Metastability and Distributed Systems," 2021, https://brooker.co.za/blog/2021/05/24/metastable.html [V] | Industrial (AWS engineer) | **Supports**: explains how retries turn small outages into persistent ones. |\[23\]

**Rule-out vs. network degradation:** in a retry storm, connect() *fails fast* or times out repeatedly. In network degradation, connections succeed but reads are slow. That split fits the timeout taxonomy in Dai et al.

### 6. lock-contention-futex-storm (lock_contention)

**Discriminator to ground:** futex wait/wake rate *relative to the service's own baseline*; short runs between futex calls; high context-switch rate; many waiters on one futex address.

| Reference                                                                                                                                                                                                               | Type | Relation |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|---|
| Franke, Russell, Kirkwood, OLS 2002 [V] | Mechanism | **Supports**: an uncontended lock never enters the kernel - "kernel involvement is only necessary when there is contention" - so a futex syscall in the trace means someone waited. **Checked against the paper: its benchmarks are native C/C++ (synthetic plus databases), which is exactly why the JVM case below is an exception rather than a contradiction.** The paper also names busy-waiting as a legitimate way to wait, and busy-waiting is invisible from the kernel. |
| Rezazadeh et al., ISSRE-W 2020 [V]; Gelle et al., Electronics 2021 [V] | Method | **Supports, with a limit**: lock contention is visible in MULTI-LEVEL traces. Rezazadeh's whole contribution is that the kernel level alone is not enough - user-space `lock_req`/`lock_acq` tracepoints are what separate waiting for a lock from holding it. We have neither, so our signal is a futex-rate change, which is weaker. |
| Hamala, "LockSupport.parkNanos() Under the Hood and the Curious Case of Parking," Hazelcast blog, 2019, https://hazelcast.com/blog/locksupport-parknanos-under-the-hood-and-the-curious-case-of-parking/ [S via helper] | Mechanism (JVM) | **Contradicts the naive rule**: "the implementation of the park() method that the JVM uses when running on Linux uses the POSIX Threads API".\[24\] So idle thread pools, timed waits and executors all generate futex calls with no lock contention. |
| OpenJDK bug JDK-6900441, https://bugs.openjdk.org/browse/JDK-6900441 [V]. Stored: `DOCS/reading-papers/sources/openjdk-jdk-6900441/` (markdown only - the tracker refuses a plain fetch)                                                                                                                                            | Mechanism (JVM) | **Supports the JVM caveat**: Thread.sleep, Object.wait and LockSupport.park are built on pthread_cond (PlatformEvent / Parker). |\[25\]
| Kernel doc "Futex Requeue PI," https://docs.kernel.org/locking/futex-requeue-pi.html [S]                                                                                                                                | Mechanism | **Completes the chain**: glibc pthread_cond_wait calls futex_wait. |\[26\]
| Quarkus discussion #30231, https://github.com/quarkusio/quarkus/discussions/30231 [S]                                                                                                                                   | Industrial | **Supports** (weak): 7.7% of benchmark CPU time was spent in LockSupport.unpark(), linked to futex. |\[27\]

**Important framing for your thesis:** The literature treats a futex rate as a contention signal. That holds for C/C++ programs, where an uncontended lock never calls the kernel. On the JVM, *parking is the normal idle path*, so the futex share is high at baseline. **No single source says "JVM services are futex-heavy by default"**; you build it from the chain JVM park → pthread_cond → futex. Present it as your own observation, backed by the chain of citations. Your discriminator should be the *change against the service's own baseline* plus *many waiters on the same futex address*, not the raw share.

### 7. cpu-contention-co-tenant (noisy_neighbor)

**Discriminator to ground:** the victim's runnable-wait grows while it is preempted by threads from *another* pid namespace; the victim has no throttling; the host is not fully busy, or only one CPU set is.

| Reference | Type | Relation |
|---|---|---|
| Zhang et al., "CPI2: CPU performance isolation for shared compute clusters," EuroSys 2013. DOI 10.1145/2465351.2465388 [M] | Empirical + method (Google) | **Supports**: co-located "antagonists" hurt victims; Google finds them by correlating victim slowdown (CPI from hardware counters) with antagonist CPU use. **It is a weaker mechanism than ours, not the same one:** CPI2 must correlate statistically because cache and memory-bus interference cannot be attributed directly, whereas `sched_switch` names the task that took the CPU outright. Note also that CPI2 addresses CACHE/memory-bus interference, while our `noisy_neighbor` is CPU-time contention. |
| Lo, Cheng, Govindaraju, Ranganathan, Kozyrakis, "Heracles: Improving Resource Efficiency at Scale," ISCA 2015 (DOI 10.1145/2749469.2749475); TOCS 2016 (DOI 10.1145/2882783); PDF: http://csl.stanford.edu/~christos/publications/2016.heracles.tocs.pdf [V] | Empirical (Google) | **Supports**: "even small amounts of interference can cause significant SLO violations" for latency-critical services. |\[28\]\[29\]
| Gelle et al. 2021 [V] | Method | **Supports**: CPU contention is visible on the critical path. |
| Giraldeau & Dagenais 2016 [M] | Method | **Supports**: preemption shows in the "preempted by" relation in sched_switch (prev_state = R). |

### 8. priority-inversion-nice (priority_inversion)

**Discriminator to ground:** a low-weight (high nice) task holds a lock that a normal task needs; the lock holder is often runnable but not running; waiters sit in futex_wait.

| Reference | Type | Relation |
|---|---|---|
| Sha, Rajkumar, Lehoczky, "Priority Inheritance Protocols: An Approach to Real-Time Synchronization," IEEE Trans. Computers 39(9), 1990. DOI 10.1109/12.57058 [M] | Mechanism | **Refines**: classic priority inversion uses *strict* priorities (real-time). Under CFS, nice values are *weights*, so the low task still runs, just less. Call your fault "weighted lock-holder starvation" or "nice-induced inversion," not classic inversion. |
| Linux kernel "CFS Scheduler" design doc, https://docs.kernel.org/scheduler/sched-design-CFS.html, and sched(7) man page [M] | Mechanism | **Supports**: nice changes the CPU share through the weight table (nice 0 = 1024, nice -20 = 88761; weights change about 1.25x per step); the kernel/sched/core.c comment says "Nice levels are multiplicative, with a gentle 10% change for every nice level changed" [S: check against the kernel source]. |
| Kernel "Futex Requeue PI" doc [S]; kernel rt-mutex docs [M] | Mechanism | **Refines**: Linux has priority inheritance only for PI futexes / RT scheduling, not for normal CFS nice values. So the inversion is not fixed automatically, which is why your fault shows up. |
| Rezazadeh et al. 2020 [V] | Method | **Refines**: lock-holder and waiter analysis is possible from traces, but only with USER-SPACE lock tracepoints (`lock_req`/`lock_acq`/`unlock`), which separate waiting-for-the-lock from holding-it. Kernel-only data - ours - cannot make that split. |

**Version caveat:** Since Linux 6.6, EEVDF replaced CFS as the default fair scheduler (source: the Wikipedia CFS article, which cites Phoronix [S]).\[30\] Nice weights still exist, but write down your kernel version in the blueprint's "applicability" field.

### 9. db-latency-dependency-wait (slow_db) — *was weak, now better*

**Discriminator to ground:** the caller threads block in recv/poll on the DB socket (off-CPU, waiting on the network); the DB container shows the work (CPU or disk), or long idle gaps if delay is injected; the caller's own CPU is low.

| Reference | Type | Relation |
|---|---|---|
| Yang, Subramaniam, Lu, Yan, Cheung, "How not to Structure Your Database-Backed Web Applications: A Study of Performance Bugs in the Wild," ICSE 2018, pp. 800–810. DOI 10.1145/3180155.3180194. PDF: http://hyperloop.cs.uchicago.edu/220-HowNotStructure.pdf [V] | Empirical (MSR-style: issue reports from 12 ORM apps) | **Supports**: DB-access performance bugs are common in real apps and come from ORM misuse, database design and application design. |\[31\]\[32\]
| Dai et al., IC2E 2018 [V] | Empirical | **Supports**: a slow dependency without a proper timeout turns into a hang for the caller. |
| Giraldeau & Dagenais 2016 [M]; Nemati et al. 2022 [V] | Method | **Supports**: the critical path crosses from the caller's blocked recv to the DB's work, which is exactly "whose fault is the wait." |
| Gregg, Off-CPU Analysis [M] | Method | **Supports**: blocked time, not CPU time, is where the latency goes. |
| Zhou et al., IEEE TSE 47(2), 2021 (Train Ticket) [V] | Empirical (22 industrial fault cases) | **Supports**: dependency and DB-related faults are among the fault types in the industrial survey. Specifically **F6** (endless recursive requests caused by SQL errors in a dependency, 3 days to locate), **F7** (overload of a third-party service leads to denial of service, 2 days) and **F17** (nested `select`/`from` clauses, the `slow_query` shape). |

**Rule-out vs. connection-pool exhaustion:** in slow_db, threads wait on the *socket* (network wait). In pool exhaustion, they wait on a *futex* (user-space lock) before any socket I/O. This is a strong discriminator, and it follows directly from the wait-analysis categories.

### 10. service-cpu-throttle (svc_cpu_cap)

**Discriminator to ground:** the service runs in bursts and then *the threads on a throttled run-queue stop together* until the next period (100 ms by default), with no other task taking the CPU; runnable-wait with idle CPUs available. **Not "all its threads":** throttling is enforced per `cfs_rq`, i.e. per logical CPU per cgroup, and one local pool being throttled does not throttle the others (Turner 2010 §6; Ugedal 2022 §II-B). An individual task is never throttled - only its group.

| Reference | Type | Relation |
|---|---|---|
| Kernel doc "CFS Bandwidth Control," https://docs.kernel.org/scheduler/sched-bwc.html [V] | Mechanism | **Supports**: "Within each given 'period' (microseconds), a task group is allocated up to 'quota' microseconds of CPU time."\[33\] When the quota runs out, the group is throttled until the next period. |
| Turner, Rao, Rao, "CPU bandwidth control for CFS," Linux Symposium (OLS) 2010, pp. 245–254. https://www.kernel.org/doc/mirror/ols2010.pdf [V] | Mechanism (original design, Google/IBM) | **Supports**: the design paper for the quota/period mechanism. |\[34\]\[35\]
| Ugedal, Kannan, "Mitigating Unnecessary Throttling in Linux CFS Bandwidth Control," SBAC-PAD 2022. PDF: https://rakeshk.folk.ntnu.no/pubs/SBACPAD22.pdf [V] | Mechanism + empirical | **Refines**: bandwidth control "might unnecessarily throttle processes," because per-CPU slices end up with negative runtime.\[36\] So throttling can happen *even when average use is below the quota*. |
| Dan Luu, "The container throttling problem," https://danluu.com/cgroup-throttling/ [M]; Kubernetes issue #67577 [M] | Industrial | **Refines**: multi-threaded services hit the quota in a few ms and then stall, so average CPU looks fine while tail latency is bad. |
| LWN, "CFS bandwidth control," 2011, https://lwn.net/Articles/428230/ [V] | Mechanism | **Supports**: explains cpu.cfs_period_us and cpu.cfs_quota_us. |\[37\]
| Gelle, Ezzati-Jivan, Dagenais, Electronics 10(21):2610, 2021, §4.3 [V] | Empirical (LTTng, injected fault) | **Supports, directly.** They limit a Cassandra cpu cgroup to 1% and read the result out of an LTTng kernel trace. They report exactly our discriminator: requests go from ~5 ms to ~2 s, `PREEMPTED` dominates the critical path, preemption recurs **every 100 ms**, the CPU becomes **underused**, and the deciding event is `sched_switch prev_comm=java, prev_state=0, next_comm=swapper/2` - preempted but **not replaced**. This is independent published evidence for the `prev_state=0` + `next_comm=swapper` test below. They do not name the 100 ms as `cfs_period_us`; we can. |

**Key discriminator vs. noisy neighbor:** in throttling, the victim's threads go off-CPU *while CPUs are idle*. With a noisy neighbor, a *foreign* task is running on the CPU. You can see this directly in sched_switch next_comm/next_pid. Gelle et al. 2021 §4.3 publish the raw `sched_switch` line for the throttled case, which is the closest external confirmation of this test that the pack contains.

---

## Secondary blueprints

### 11. dns-delay

**Discriminator:** a pause of about 5 s (or a multiple of it) between a UDP sendto/sendmmsg to port 53 and the next DNS send; A and AAAA sent in parallel; the service then connects normally.

| Reference | Type | Relation |
|---|---|---|
| Yang et al., "A Deep Dive into DNS Query Failures," USENIX ATC 2020, https://www.usenix.org/conference/atc20/presentation/yang [V] | Empirical (3B queries) | **Supports**: "13.5% of DNS queries fail" in the wild, so DNS failure is common. |\[38\]
| Pumputis, "Racy conntrack and DNS lookup timeouts," Weave Works blog, 2018; mirror: https://lambda.lt/blog/2018/racy_conntrack.html [V via helper] | Industrial post-mortem | **Supports**: "glibc and musl libc both perform A and AAAA DNS lookups in parallel. One of the UDP packets might get dropped by the kernel due to the races, so the client will try to re-send it after a timeout which is usually 5 seconds." Related issues: kubernetes/kubernetes#56903, weaveworks/weave#3287. |\[39\]
| resolv.conf(5), https://man7.org/linux/man-pages/man5/resolv.conf.5.html [S] | Mechanism | **Supports**: the default timeout is 5 s, the default ndots is 1, and glibc runs parallel IPv4/IPv6 lookups (since 2.9). |\[40\]
| Lagresle (XING), "A reason for unexplained connection timeouts on Kubernetes/Docker," 2018; mirror: https://maximelagresle.fr/posts/a-reason-for-unexplained-connection-timeouts-on-kubernetes-docker [S] | Industrial | **Refines**: the same conntrack race affects SNAT connects, not only DNS.\[41\] So a 1 s/3 s SYN-retry gap can look like a DNS delay. |

**Gap:** there is no MSR-style study of DNS *incidents in microservices*. ATC 2020 is about queries on the Internet.

### 12. fd-exhaustion

**Discriminator:** open/socket/accept return -24 (EMFILE) or -23 (ENFILE); the fd count rises steadily before the failure; new connections fail while existing ones keep working.

| Reference | Type | Relation |
|---|---|---|
| Ghanavati et al., EMSE 2020 [V] | Empirical (MSR-style) | **Supports**: resource leaks (including file handles) are common, and developers mostly find them by hand - 44.7% of resource leaks were found by manual code inspection, and file handles are the largest resource-leak category in Lucene (55.9% of its issues) and Hadoop (42.9%). |\[42\]
| neo4j issue #1799, https://github.com/neo4j/neo4j/issues/1799 [S] | GitHub issue | **Supports**: the fd count climbs past a 10k limit, and then "Too many open files". |\[43\]
| sveltejs/kit issue #11617, https://github.com/sveltejs/kit/issues/11617 [S] | GitHub issue (Alpine container) | **Supports**: shows `errno: -24, code: 'EMFILE', syscall: 'open'`, the exact trace signature. |\[44\]
| open(2)/errno(3) man pages [M] | Mechanism | **Supports**: EMFILE = per-process limit (RLIMIT_NOFILE); ENFILE = system-wide limit. |

### 13. fork-storm

**Discriminator:** a burst of clone/fork syscalls and sched_process_fork events in one pid namespace; clone returns -EAGAIN once pids.max is reached; many short-lived processes.

| Reference | Type | Relation |
|---|---|---|
| Kernel doc "Process Number Controller," https://docs.kernel.org/admin-guide/cgroup-v1/pids.html [V] | Mechanism | **Supports**: it can "stop any new tasks from being fork()'d or clone()'d after a certain limit is reached." |\[45\]
| Kernel "Control Group v2" (PID section), https://www.kernel.org/doc/Documentation/cgroup-v2.txt [V] | Mechanism | **Supports**: fork/clone "will return -EAGAIN if the creation of a new process would cause a cgroup policy to be violated." The PIDs counted are *TIDs*, so thread storms count too. |\[46\]
| Kubernetes issue #43783, "Allow setting pids-limit on containers," https://github.com/kubernetes/kubernetes/issues/43783 [V] | GitHub issue | **Supports**: calls the pids limit "very critical to avoid fork bombs" in containers. |\[47\]
| LKML patch "cgroup: Add pids controller event when fork fails because of pid limit" (Kenny Yu, 2016), https://lkml.iu.edu/hypermail/linux/kernel/1606.2/03729.html [V] | Mechanism | **Supports**: pids.events `max` counts failed forks; logging is rate-limited "during a fork bomb." |\[48\]

**Gap:** no academic study of fork storms in microservices. Kernel docs plus GitHub issues are the honest evidence.

### 14. host-disk-saturation

**Discriminator:** tasks in D state (uninterruptible, prev_state = D in sched_switch) waiting on block I/O; long block_rq_issue → block_rq_complete latency; fsync/write syscalls take a long time; across containers.

| Reference | Type | Relation |
|---|---|---|
| Kernel PSI doc (io.pressure), https://docs.kernel.org/accounting/psi.html [V/S] | Mechanism | **Supports**: io "some"/"full" stall time, per cgroup. |\[49\]
| Gregg, biolatency (BCC), https://github.com/iovisor/bcc/blob/master/tools/biolatency.py [S] | Method | **Supports**: block I/O latency histogram from block tracepoints; `-Q` includes kernel queue time. |\[50\]
| Gregg, USE Method [M] | Method | **Supports**: disk utilization vs. saturation (queue length). |

**Tip:** Enable the LTTng `block_rq_*` events. Without them you only see slow syscalls and D-state sleeps, which can also come from NFS or memory reclaim.

### 15. service-memory-cap

**Discriminator:** reclaim/stall work inside one cgroup (page-fault and kswapd-like activity, D state); then an OOM kill (a signal sent to one task in that pid namespace, the process exits, and the container restarts).

| Reference | Type | Relation |
|---|---|---|
| Kernel "Control Group v2" (memory.max), https://docs.kernel.org/admin-guide/cgroup-v2.html [S] | Mechanism | **Supports**: "If a cgroup's memory usage reaches this limit and can't be reduced, the OOM killer is invoked in the cgroup." memory.events has max/oom/oom_kill counters. |\[51\]\[52\]
| Weiner et al., "TMO: Transparent Memory Offloading in Datacenters," ASPLOS 2022. DOI 10.1145/3503222.3507731 [S; check author list] | Empirical + mechanism (Meta) | **Supports**: PSI measures stalls "per-process and per-container," and memory pressure causes latency before any OOM happens. |\[53\]\[54\]
| Facebook PSI / oomd docs, https://facebookmicrosites.github.io/psi/docs/overview [S] | Industrial | **Supports**: oomd kills early, based on PSI thresholds. |\[55\]
| Kubernetes issue #128339 (tmpfs memory keeps causing OOM after restarts), https://github.com/kubernetes/kubernetes/issues/128339 [V] | GitHub issue | **Refines**: tmpfs pages count against the limit, so the "memory cap" can be hit by files, not only by heap. |\[56\]

### 16. data-exfiltration

**Discriminator:** unusual outbound volume (many net_dev_xmit bytes) to a new peer from a container that normally only answers requests; read() of files followed by send() on a new socket.

| Reference | Type | Relation |
|---|---|---|
| Gassais, Ezzati-Jivan, Fernandez, Aloise, Dagenais, "Multi-level host-based intrusion detection system for Internet of things," Journal of Cloud Computing 9:62, 2020. DOI 10.1186/s13677-020-00206-6 [V] | Method (DORSAL, LTTng) | **Supports**: an LTTng host IDS that lists "Data exfiltration" as a threat, and notes "intrusions cannot easily or reliably be detected from network traces." IoT, not containers. **Read in full 30 Sept 2026.** The most reusable thing in it is the **published tracepoint list** (their Table 2): `sched_switch`, `sched_process_fork/exec/exit`, `net_dev_queue`, `module_load`, **`power_cpu_frequency`**, and ~110 syscalls weighted to process, privilege, filesystem, module-loading and network calls - a **security-shaped** profile where ours is performance-shaped. Their custom spying tool is our exfiltration fault, and their note on it is the honest one: it *"does not change the device behavior much, unlike the other intrusions."* **Do NOT cite their 99.97-100% as a detection rate.** Labels were assigned by **novelty** against a one-hour benign trace, two of the seven attacks failed outright, and the Mirai payload was replaced with an echo - so the number largely measures the labelling procedure. Cite it for *the signal is present in host traces*, which is all we need. |\[57\]
| Jewell, Beaver, "Host-Based Data Exfiltration Detection via System Call Sequences," ICIW 2011, pp. 134–142 (ORNL), https://www.ornl.gov/publication/host-based-data-exfiltration-detection-system-call-sequences [S] | Method | **Supports**: system-call sequences can detect exfiltration. |\[58\]
| El Khairi, Caselli, Peter, Continella, "REPLICAWATCHER: Training-less Anomaly Detection in Containerized Microservices," NDSS 2024, https://www.ndss-symposium.org/wp-content/uploads/2024-286-paper.pdf [V] | Method (containers, kernel events) | **Supports**: compares microservice replicas using kernel events. The closest match to your setting - Sysdig, containers, per-container attribution, real GKE. 13 real-CVE scenarios on two apps, **avg AUC 0.9960 / 0.9827**, precision 0.9248, recall 0.9813. **Read in full 30 Sept 2026, and its feature study is the most directly useful thing in it for us.** Ranking every candidate feature by dissimilarity across *identical replicas under identical load*, they found **syscall frequency, latency, delta time, IPs/ports and buffer length all "exhibit substantial dissimilarity"** and rejected them; **only process-based features showed "little to no dissimilarity"**. Selection rule: max dissimilarity **< 0.2** at a **30 s** interval, with **longer intervals giving greater similarity**. **Several of our discriminators are rate-based**, so this is published evidence that rate is noisy between things that should behave identically - worth testing against our own no-fault window-to-window variation before trusting any ratio threshold. Two caveats on citing it: the method **requires replicas**, which our Sock Shop deployment does not have, and every scenario is an **adversarial CVE exploit**, not a performance fault. Its normality-drift finding is also an argument for our pinned builds: **almost every new version of GOB's `cart` added one previously unseen syscall** over ten versions - `getrlimit` appeared from a .NET SDK patch bump. |\[59\]

### Related families (short)

- **nagle_delayed_ack:** Mogul & Minshall, "Rethinking the TCP Nagle Algorithm," ACM SIGCOMM CCR, Jan 2001, http://ccr.sigcomm.org/archive/2001/jan01/ccr-200101-mogul.pdf [V], which talks about "the well-known potential for deadlock between the Nagle algorithm and the delayed ACK policy."\[60\] **Read in full 30 Sept 2026, and it gives this family three things the pack lacked.** (a) **The exact trigger condition:** a message of length strictly between **(2N+1) x MSS and (2N+2) x MSS** - "odd full segments plus a short final segment", OF+SFS. Messages **below 2 x MSS are never delayed**. With MSS 1460 the first bands are **2,921-4,379 bytes** and **7,301-8,759 bytes** - **check the fault recipe targets one of them, or the injection may reproduce nothing and read as a null result.** (b) **A measured prevalence:** in a real HTTP trace, **6.71%-18.78% of responses had a vulnerable length**; at the Ethernet MSS it is **10.05%-18.78%**. (c) **Their application taxonomy puts our workload in the class they declare unfixable.** Bulk transfer and Telnet-style are fine with Nagle; RPC-style is fixable; **pipelined soft-realtime exchanges (NFS over TCP, P-HTTP - i.e. modern keep-alive/gRPC microservice traffic) cannot be fixed**, because wanting a small message sent immediately is "antithetical to the original intent". So the real-world fix is `TCP_NODELAY`, which most microservice runtimes set by default - **that is a rule-out the blueprint needs, and it means our injection must be disabling it.** **Scope:** 2001, BSD-derived stacks; Linux has carried Minshall's variant for years and its delayed-ACK timeout is adaptive, not a flat 200 ms. Cite the mechanism and the OF+SFS bands; measure the timing on our own kernel. **One discriminator falls out of it:** the deadlock ends when a *timer* fires, so the delay is **quantised at a timer boundary** rather than continuously distributed - the same kind of fingerprint as the 100 ms CFS period in blueprint 10, and a candidate separator from `network-path-degradation`, whose delays are variable. Hypothesis, not a finding. Stuart Cheshire, "TCP Performance problems caused by interaction between Nagle's Algorithm and Delayed ACK," https://www.stuartcheshire.org/papers/nagledelayedack/ [V].\[61\] Brooker, "It's always TCP_NODELAY," 2024, https://brooker.co.za/blog/2024/05/09/nagle.html [V].\[62\] RFC 896 and RFC 1122 [M]. **Trace signature:** a gap of about 40 ms (Linux minimum delayed-ACK time) between a small write and the next send, in a write-write-read pattern.\[63\]
- **error_storm / queue_backlog:** Bronson 2021 and Huang 2022 (feedback loops); Dai 2018 (timeouts).
- **resource_abuse / anomaly_mem:** CPI2, Heracles, TMO, cgroup v2 docs. **TMO (Weiner et al., ASPLOS 2022) read in full 30 Sept 2026 - it is the paper PSI came from**, by the kernel MM and cgroup maintainers, and it pins down three things we use loosely. (a) **`some` vs `full`**: `some` = at least one process in the domain stalled, `full` = all of them simultaneously; `some` is added latency, `full` is total unproductivity. **Our blueprints do not make this split and it is computable from what we collect.** (b) **CPU `full` pressure is only possible inside a container, and has exactly two causes: "outside competition" or "configured limits on the cgroup's CPU cycles"** - i.e. blueprint 7 and blueprint 10, named by PSI's own author as the only two candidates. (c) **Memory pressure is recorded from exactly three events**: reclaim triggered on allocation, waiting on IO for a **refault** (major fault on a recently evicted file page), and **blocking on a swap-in**. That is a ready-made discriminator list for `service-memory-cap`; check which three our profile captures. They also confirm the pack's reading of CPU PSI: it is *"the periods of time when a process is runnable but needs to wait for an idle CPU"* - our runnable-wait. **And a warning for us:** their reason for rejecting *promotion rate* is that a rate threshold **does not transfer across hardware** ("with a faster offloading device, a higher promotion rate can be tolerated"). Our ratio thresholds were measured on one VM shape. Finally, the honest framing: *"Before PSI, operators relied on correlating indirect metrics such as kernel time, variations in application throughput, event counters for reclaim activity, file re-reads, and swap-ins ... [requiring] an intuitive understanding of the storage hardware device characteristics and kernel behavior."* **That is a description of what a blueprint does.** Meta answered it by adding a kernel mechanism; we answer it by encoding the intuition. Worth saying rather than implying nobody noticed. Limit to state: PSI is a **counter interface**, not a trace - it says how much was lost, never **which container took the resource**. That gap is our WHERE axis.
- **General performance-bug evidence:** Jin, Song, Shi, Scherpelz, Lu, "Understanding and Detecting Real-World Performance Bugs," PLDI 2012, DOI 10.1145/2254064.2254075 [V]. **Read in full 30 Sept 2026. The number to quote is not the taxonomy - it is the lifetime.** In Mozilla, 36 performance bugs took **935 days on average to be discovered**, against **252 days** for 36 functional bugs randomly sampled from the same project; both took ~120-140 days to fix once found. So this class survives **3.7x longer undetected**, and their sentence for why is *"judging whether performance bugs have manifested is a unique challenge in performance testing."* Two more findings bear on us: **~2/3 of these bugs need large-scale input to manifest perceivably** (the general form of our fault-calibration risk), and **over 3/4 live in an input-dependent loop or event handler with about half involving I/O or other time-consuming system calls** - i.e. at the boundary a kernel trace records. Scope: five **C/C++ desktop and server** applications, 2012, no distributed systems. Note their **Uncoordinated Functions** category is the same mechanism Chen 2014 calls one-by-one processing and Yang 2018 calls N+1 - cite the three together once, not as separate findings (Shan Lu is an author on two). The TScope (ICAC 2018) and TFix (ICDCS 2019) papers by He, Dai, Gu for timeout bug detection and fixing [V].\[64\]

---

## Related work: positioning the blueprint idea

**Troubleshooting guides (TSGs) and runbooks, empirical studies:**
- **AutoTSG** (Microsoft, ESEC/FSE 2022 Industry), arXiv:2205.13457 [V]: "more than 50,000 TSGs which are used regularly for incident resolution by over 60,000 engineers every month"; a taxonomy of TSG quality issues from 400+ on-call engineers.\[65\] **Supports** the claim that written investigation procedures are standard practice.
- **StepFly** (Mao et al., Proc. ACM Softw. Eng. 3(FSE), 2026). DOI 10.1145/3808143. arXiv:2510.10074. Code: https://github.com/microsoft/StepFly [V]. An empirical study of 92 real TSGs; turns TSGs into execution DAGs; the paper reports "a ~94% success rate on GPT-4.1" and an "execution time reduction of 32.9% to 70.4% for parallelizable TSGs." **Closest to your blueprints**: structured steps, executed by an agent.
- **Nissist** (Microsoft), arXiv:2402.17531 [V]: an incident mitigation copilot built on TSGs.\[66\]
- **FixItFlow**, arXiv:2607.13035 [S]: generates TSGs from incident data. An internal study lists the top TSG problems: "missing information (32.24%), broken links (13.32%), and incorrect instructions (11.21%)."\[67\] **Supports** your explicit "what to collect / stopping condition" fields.
- **RunbookFX** (Xiao, Li, Ge), PACMPL 10(ICFP), 2026. DOI 10.1145/3828675 [S]: type- and effect-safe LLM synthesis of executable runbooks.\[68\]
- **Flow-of-Action: SOP-enhanced LLM multi-agent system for RCA**, WWW 2025 Companion [S].\[69\]

**LLM agents for RCA and incident management:**
- **RCACopilot** (Chen et al., Microsoft), arXiv:2305.15778 (EuroSys 2024) [V]: predefined handlers collect diagnostic data and an LLM predicts the root-cause category. It found that "incidents stemming from similar or identical root causes often recur," which **supports** reusable blueprints.\[70\]\[71\]
- **Roy et al., "Exploring LLM-based Agents for Root Cause Analysis,"** FSE 2024 Companion (Industry). DOI 10.1145/3663529.3663841. arXiv:2403.04123 [V]: a ReAct agent with retrieval tools on production incidents.\[72\]
- **Xpert** (query recommendation for incidents), arXiv:2312.11988 [V].\[73\]
- **OpenRCA** (ICLR 2025) and **AIOpsLab** (arXiv:2501.06706) [M]: benchmarks for LLM agents on RCA. Use them as your evaluation neighbours.
- **LLexus** (Microsoft, an AI agent that executes TSGs) [M; cited by StepFly, so check the venue in StepFly's reference list].\[74\]
- **"Beyond Fault Localization: A Trajectory-Level Study of LLM Agents for Microservice Root Cause Analysis,"** arXiv:2608.21310 [S], and **"From General Agents to RCA Experts: A Self-Evolving Harness for Root Cause Analysis,"** arXiv:2608.25661 [S]: recent studies of agent trajectories and skills.\[75\]\[76\] Very close to your "with/without blueprint" evaluation.
- **"Mining root cause knowledge from cloud service incident investigations for AIOps,"** ICSE-SEIP 2022, arXiv:2204.11598 [S]: mines past investigations, the same idea as writing solved investigations down.\[75\]

**Kernel-trace anomaly detection and RCA for microservices and containers:** Kohyarnejadfard et al. 2022 and thesis; Nemati et al. 2022 and PhD thesis (https://publications.polymtl.ca/3902/1/2019_HaniNemati.pdf [V]); Gelle et al. 2021; Denys et al. 2023; REPLICAWATCHER (NDSS 2024); and dblp lists a new DORSAL/Brock paper, "HybridRCA: Lightweight Critical-Path-Aware Hybrid Tracing for Root-Cause Analysis in Production Microservices" (Dagenais, Ezzati-Jivan, Lamothe et al.) [S; venue unknown, check dblp].\[77\]\[78\]

**Your positioning in one sentence:** existing TSG and agent work uses logs, metrics and KQL queries; the DORSAL work uses kernel traces but without reusable, agent-executable procedures; your blueprints join the two.

---

## Best practices: citing references in a machine-readable blueprint schema

1. **Link at the claim level, not the blueprint level.** Give every discriminator, rule-out and stopping condition an ID (for example `B6.D2`). Attach references to that ID.
2. **Type each link.** Use a small, fixed set of words: `supports`, `refines`, `contradicts`, `background`, `method`. These map to the CiTO ontology (Citation Typing Ontology: `cito:supports`, `cito:disagreesWith`, `cito:extends`, `cito:usesMethodIn`) [M], so tools can read them.
3. **Store a short verbatim quote and a locator** (page, section or figure). An agent can then check the claim without reading the whole paper.
4. **Store a stable ID and an access URL separately:** `doi`, `arxiv`, `url_oa` (open PDF), `retrieved` (date). Prefer DOI and arXiv. For GitHub issues, keep the issue number.
5. **Store evidence strength:** `peer_reviewed | industrial | issue | doc`, plus a `verified: true/false` flag (like the [V]/[S]/[M] tags here).
6. **Keep the scope:** for example, `applies_to: {runtime: "JVM", kernel: ">=5.x, CFS"}`. This lets you record the JVM-futex and EEVDF caveats.

Example (YAML):

```yaml
claim_id: B6.D1
text: "Futex share alone does not indicate contention on JVM services."
evidence:
  - ref: hazelcast-parknanos-2019
    relation: supports
    quote: "the implementation of the park() method that the JVM uses when running on Linux uses the POSIX Threads API"
    url: https://hazelcast.com/blog/locksupport-parknanos-under-the-hood-and-the-curious-case-of-parking/
    strength: industrial
    verified: false
  - ref: franke-ols-2002
    relation: contradicts   # the general literature treats futex calls as a contention signal
    scope: {runtime: "C/C++ native"}
```

---

## Caveats

- **Check tags before you submit.** Items tagged [M] come from memory (mostly DOIs of classic papers); [S] items were seen only in snippets. Open each link once. Most are on arXiv, USENIX, kernel.org, ACM or GitHub.
- **Some blueprints have no MSR-style academic study:** connection-pool exhaustion, fork storm, DNS delay in microservices. Say this openly and use leak, timeout and outage studies as the closest evidence. This is a real contribution space, not a weakness to hide.
- **Fault injection ≠ real faults.** Most empirical sources describe *organic* bugs (leaks, bad timeouts). Your injected faults copy the *symptom*, not the *cause*. Cite the empirical studies as "this symptom occurs in practice," not "our injection is realistic."
- **Kernel version matters.** CFS was replaced by EEVDF in Linux 6.6.\[30\] Throttling behaviour also changed over time (Ugedal et al., cfs_burst_us).\[33\] Record the kernel version in each blueprint.
- **Tracepoint coverage limits what you can claim.** Retransmits, block I/O and OOM kills need specific LTTng events (tcp_retransmit_skb, block_rq_*, oom/mark_victim). If you did not enable them, your discriminators are inferences from timing, and each blueprint should say so.

## Sources

1. [Critical Path Analysis through Hierarchical Distributed Virtualized Environments Using Host Kernel Tracing | Semantic Scholar](https://www.semanticscholar.org/paper/Critical-Path-Analysis-through-Hierarchical-Using-Nemati-Tetreault/a42e038f8b36e2247f3a9a131b61de549cecf77f)
2. [Combining Distributed and Kernel Tracing for Performance Analysis of Cloud Applications](https://www.mdpi.com/2079-9292/10/21/2610)
3. [Anomaly detection in microservice environments using distributed tracing data analysis and NLP - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9375740/)
4. [Anomaly detection in microservice environments using distributed tracing data analysis and NLP | Journal of Cloud Computing | Springer Nature Link](https://link.springer.com/article/10.1186/s13677-022-00296-4)
5. [Titre: Title: System Performance Anomaly Detection using Tracing Data Analysis](https://publications.polymtl.ca/10281/1/2022_ImanKohyarnejadfard.pdf)
6. [Distributed computation of the critical path from execution traces - Denys - 2023 - Software: Practice and Experience - Wiley Online Library](https://onlinelibrary.wiley.com/doi/full/10.1002/spe.3210)
7. [PSI - Pressure Stall Information — The Linux Kernel documentation](https://docs.kernel.org/accounting/psi.html)
8. [On the Nature of Issues in Five Open Source Microservices Systems: An Empirical Study](https://arxiv.org/pdf/2104.12192)
9. [Understanding the issues, their causes and solutions in microservices systems: An empirical study - ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0164121226000622)
10. [An in-depth study of the promises and perils of mining GitHub | Empirical Software Engineering](https://dl.acm.org/doi/10.1007/s10664-015-9393-5)
11. [The Linux scheduler: a decade of wasted cores](https://dl.acm.org/doi/10.1145/2901318.2901326)
12. [PSI - Pressure Stall Information — The Linux Kernel 5.2.0-rc6-next-20190626+ documentation](https://www.infradead.org/~mchehab/rst_conversion/accounting/psi.html)
13. [\[1810.00101\] Memory and Resource Leak Defects and their Repairs in Java Projects](https://arxiv.org/abs/1810.00101)
14. [Understanding Real-World Timeout Problems in Cloud Server Systems Ting Dai,](https://dance.csc.ncsu.edu/papers/IC2E18.pdf)
15. [Connection pool anomaly detection mechanism](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11750692)
16. [Futex Internals - Linux Kernel Internals](https://kernel-internals.org/locking/futex/)
17. [| Directory of Experts](https://www.polymtl.ca/expertises/en/dagenais-michel/publications)
18. [2020 IEEE International Symposium on Software Reliability Engineering Workshops, ISSRE Workshops, Coimbra, Portugal, October 12-15, 2020 - researchr publication](https://researchr.org/publication/issre-2020w)
19. [Naser EZZATI-JIVAN | Professor (Assistant) | PhD | Brock University, St. Catharines | Department of Computer Science | Research profile](https://www.researchgate.net/profile/Naser-Ezzati-Jivan)
20. [Metastable Failures in Distributed Systems Nathan Bronson∗ Rockset, Inc.](https://sigops.org/s/conferences/hotos/2021/papers/hotos21-s11-bronson.pdf)
21. [Metastable Failures in the Wild | USENIX](https://www.usenix.org/publications/loginonline/metastable-failures-wild)
22. [Understanding Real-World Timeout Problems in Cloud ...](https://tingdai.github.io/files/understanding_IC2E18_slides.pdf)
23. [Metastability and Distributed Systems - Marc's Blog](https://brooker.co.za/blog/2021/05/24/metastable.html)
24. [LockSupport.parkNanos() Under the Hood and the Curious Case of Parking (Part I)](https://dzone.com/articles/locksupportparknanos-under-the-hood-and-the-curiou-1)
25. [Loading...](https://bugs.openjdk.org/browse/JDK-6900441)
26. [Futex Requeue PI — The Linux Kernel documentation](https://docs.kernel.org/locking/futex-requeue-pi.html)
27. [Techempower benchmark spends 7.7% of time in LockSupport.unpark()? · quarkusio/quarkus · Discussion #30231](https://github.com/quarkusio/quarkus/discussions/30231)
28. [6 Improving Resource Efficiency at Scale with Heracles](http://csl.stanford.edu/~christos/publications/2016.heracles.tocs.pdf)
29. [Heracles: Improving Resource Efficiency at Scale – the morning paper](https://blog.acolyer.org/2015/06/16/heracles-improving-resource-efficiency-at-scale/)
30. [Completely Fair Scheduler](https://en.wikipedia.org/wiki/Completely_Fair_Scheduler)
31. [How not to Structure Your Database-Backed Web Applications: A Study of Performance Bugs in the Wild | IEEE Conference Publication | IEEE Xplore](https://ieeexplore.ieee.org/document/8453153)
32. [How not to structure your database-backed web applications:](http://hyperloop.cs.uchicago.edu/220-HowNotStructure.pdf)
33. [CFS Bandwidth Control — The Linux Kernel documentation](https://docs.kernel.org/scheduler/sched-bwc.html)
34. [Proceedings of the Linux Symposium July 13th–16th, 2010 Ottawa, Ontario Canada](https://www.kernel.org/doc/mirror/ols2010.pdf)
35. [\[PDF\] CPU bandwidth control for CFS | Semantic Scholar](https://www.semanticscholar.org/paper/CPU-bandwidth-control-for-CFS-Turner-Rao/c33fca3c4e4f541a5066cc4b9415a75511c05b00)
36. [Mitigating Unnecessary Throttling in Linux CFS Bandwidth Control Odin Ugedal](https://rakeshk.folk.ntnu.no/pubs/SBACPAD22.pdf)
37. [CFS bandwidth control \[LWN.net\]](https://lwn.net/Articles/428230/)
38. [A Deep Dive into DNS Query Failures | USENIX](https://www.usenix.org/conference/atc20/presentation/yang)
39. [2018-08-16: Racy conntrack and DNS lookup timeouts](https://lambda.lt/blog/2018/racy_conntrack.html)
40. [resolv.conf(5) - Linux manual page](https://man7.org/linux/man-pages/man5/resolv.conf.5.html)
41. [A reason for unexplained connection timeouts on Kubernetes/Docker](https://maximelagresle.fr/posts/a-reason-for-unexplained-connection-timeouts-on-kubernetes-docker)
42. [Memory and resource leak defects and their repairs in Java projects | Empirical Software Engineering](https://link.springer.com/article/10.1007/s10664-019-09731-8)
43. [github.com](https://github.com/neo4j/neo4j/issues/1799)
44. [EMFILE: too many open files · Issue #11617 · sveltejs/kit](https://github.com/sveltejs/kit/issues/11617)
45. [Process Number Controller — The Linux Kernel documentation](https://docs.kernel.org/admin-guide/cgroup-v1/pids.html)
46. [================ Control Group v2 ================ :Date: October, 2015](https://www.kernel.org/doc/Documentation/cgroup-v2.txt)
47. [Allow setting pids-limit on containers · Issue #43783 · kubernetes/kubernetes](https://github.com/kubernetes/kubernetes/issues/43783)
48. [Linux-Kernel Archive: \[PATCH\] cgroup: Add pids controller event when fork fails because of pid limit](https://lkml.iu.edu/hypermail/linux/kernel/1606.2/03729.html)
49. [PSI - Pressure Stall Information — The Linux Kernel 5.10.0-rc1+ documentation](https://www.infradead.org/~mchehab/kernel_docs/accounting/psi.html)
50. [bcc-biolatency: Summarize block device I/O latency as a histogram. | Man Page | System Administration | bcc-tools | ManKier](https://www.mankier.com/8/bcc-biolatency)
51. [Control Group v2 — The Linux Kernel documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html)
52. [.. \_cgroup-v2: ================ Control Group v2 ================](https://www.kernel.org/doc/Documentation/admin-guide/cgroup-v2.rst)
53. [TMO: Transparent Memory Offloading in Datacenters | Communications of the ACM](https://dl.acm.org/doi/10.1145/3746651)
54. [TMO: transparent memory offloading in datacenters | Proceedings of the 27th ACM International Conference on Architectural Support for Programming Languages and Operating Systems](https://dx.doi.org/10.1145/3503222.3507731)
55. [Getting Started with PSI · PSI](https://facebookmicrosites.github.io/psi/docs/overview)
56. [When containers use memory backed tmpfs and hit a OOM limit they will keep OOM on restarts. · Issue #128339 · kubernetes/kubernetes](https://github.com/kubernetes/kubernetes/issues/128339)
57. <https://link.springer.com/content/pdf/10.1186/s13677-020-00206-6.pdf>
58. [Host-Based Data Exfiltration Detection via System Call Sequences | ORNL](https://www.ornl.gov/publication/host-based-data-exfiltration-detection-system-call-sequences)
59. [REPLICAWATCHER: Training-less Anomaly Detection in Containerized Microservices](https://www.ndss-symposium.org/wp-content/uploads/2024-286-paper.pdf)
60. [Rethinking the TCP Nagle Algorithm Jeffrey C. Mogul](http://ccr.sigcomm.org/archive/2001/jan01/ccr-200101-mogul.pdf)
61. [TCP Performance problems caused by interaction between Nagle’s Algorithm and Delayed ACK](https://www.stuartcheshire.org/papers/nagledelayedack/)
62. [It's always TCP\_NODELAY. Every damn time. - Marc's Blog](https://brooker.co.za/blog/2024/05/09/nagle.html)
63. [How to Debug TCP Nagle Algorithm Delays](https://oneuptime.com/blog/post/2026-03-20-debug-tcp-nagle-algorithm-delays/view)
64. [Timeout](https://dance.csc.ncsu.edu/projects/sysMD/timeout.html)
65. [AutoTSG: Learning and Synthesis for Incident Troubleshooting](https://arxiv.org/pdf/2205.13457)
66. [Nissist: An Incident Mitigation Copilot based on Troubleshooting Guides](https://arxiv.org/pdf/2402.17531)
67. [FixItFlow: Automated Troubleshooting Guide Generation from Cloud Incidents](https://arxiv.org/pdf/2607.13035)
68. [Exploring LLM-Based Agents for Root Cause Analysis | Companion Proceedings of the 32nd ACM International Conference on the Foundations of Software Engineering](https://dl.acm.org/doi/10.1145/3663529.3663841)
69. [SiriusHelper: An LLM Agent-Based Operations Assistant for Big Data Platforms](https://arxiv.org/pdf/2605.00043)
70. [Automatic Root Cause Analysis via Large Language Models for Cloud Incidents](https://arxiv.org/pdf/2305.15778)
71. [Exploring LLM-based Agents for Root Cause Analysis Devjeet Roy∗](https://arxiv.org/pdf/2403.04123)
72. [Exploring LLM-based Agents for Root Cause Analysis (FSE 2024 - Industry Papers) - FSE 2024](https://2024.esec-fse.org/details/fse-2024-industry/20/Exploring-LLM-based-Agents-for-Root-Cause-Analysis)
73. [Xpert: Empowering Incident Management with Query Recommendations via Large Language Models](https://arxiv.org/pdf/2312.11988)
74. [StepFly: Agentic Troubleshooting Guide Automation for Incident Diagnosis | Proceedings of the ACM on Software Engineering](https://doi.org/10.1145/3808143)
75. [From General Agents to RCA Experts: A Self-Evolving Harness for Root Cause Analysis](https://arxiv.org/pdf/2608.25661)
76. [Beyond Fault Localization: A Trajectory-Level Study of LLM Agents for Microservice Root Cause Analysis](https://arxiv.org/pdf/2608.21310)
77. [Titre: Title: Virtual Machine Flow Analysis Using Host Kernel Tracing Auteur:](https://publications.polymtl.ca/3902/1/2019_HaniNemati.pdf)
78. [dblp: Naser Ezzati-Jivan](https://dblp.org/pid/54/10412.html)
