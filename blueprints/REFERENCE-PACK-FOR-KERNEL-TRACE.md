# Reference Pack for Kernel-Trace RCA Blueprints (Sock Shop / Train Ticket, LTTng)

Every blueprint can be grounded in the literature, but not in one way: each needs a **mechanism source** (kernel docs or OS papers), an **empirical source** (bug or outage studies that mine issues or post-mortems), and a **method source** (a kernel-trace diagnosis paper, mostly from the DORSAL lab and Brendan Gregg). The strongest empirical sources are mining studies of bug trackers and post-mortems, not the fault injection papers.

## TL;DR

- **The priority blueprints are well supported.** The kernel docs explain the signals (CFS bandwidth control, pids controller, cgroup v2 memory.max, PSI, futex). Mining studies give "it happens in the wild" evidence: Lu et al. ASPLOS 2008 (concurrency), Dai et al. IC2E 2018 (timeouts), Ghanavati et al. EMSE 2020 (resource leaks), Yang et al. ICSE 2018 (DB performance bugs), Huang et al. OSDI 2022 (metastable failures / retry storms), Gunawi et al. SoCC 2016 (597 unplanned outages from 1,247 news and post-mortem reports at 32 services). The DORSAL papers (Giraldeau & Dagenais 2016, Nemati et al. 2022, Rezazadeh et al. 2020, Kohyarnejadfard et al. 2022) show that your data source (LTTng kernel traces with sched_switch and wakeups) is an accepted method.
- **Some sources refine or contradict your discriminators, and you should say so openly.** Examples: CFS throttling can happen while average CPU use is low (Dan Luu; Ugedal et al. 2022). JVM parking goes through pthread_cond and then futex, so a high futex share is normal on Java services. Nice values under CFS are weights, not strict priorities, so "priority inversion via nice" is weaker than the classic real-time definition (Sha et al. 1990). Bronson et al. warn that metastable outages are often wrongly blamed on the trigger.
- **The blueprint idea itself fits a growing line of work on troubleshooting guides (TSGs) and LLM agents.** The main works are AutoTSG, Nissist, RCACopilot, Roy et al. FSE 2024, StepFly (FSE 2026: empirical study of 92 real TSGs; the paper reports "a ~94% success rate on GPT-4.1" and a 32.9%–70.4% time reduction for parallelizable TSGs) and FixItFlow. None of them works from kernel traces, and that is your gap and your contribution.

## How to read this report

Each reference has a **status tag**:
- **[V]** = I opened the page or saw its full abstract in this session.
- **[S]** = seen only in a search snippet or reported by a helper search. Open the page before you cite it.
- **[M]** = well-known work, but the details come from my memory. Check the DOI before you cite it.

Each reference also has a **relation** to the blueprint claim: **supports**, **refines** (it adds a condition), or **contradicts** (it warns against a naive reading).

---

## Cross-cutting references (cite these in every blueprint's "Method" section)

1. **Giraldeau, F., Dagenais, M. "Wait Analysis of Distributed Systems Using Kernel Tracing." IEEE TPDS 27(8), 2016.** DOI: 10.1109/TPDS.2015.2488629 [M: check DOI]. It builds the "active path" of a task from sched_switch, wakeups, softirq and network events, across hosts. **Supports** the idea that kernel scheduler and wakeup events are enough to explain where time goes. This is the backbone for all "blocked vs. running vs. preempted" discriminators.
2. **Nemati, H., Tetreault, F., Puncher, J., Dagenais, M. R. "Critical Path Analysis through Hierarchical Distributed Virtualized Environments Using Host Kernel Tracing." IEEE Transactions on Cloud Computing 10:774–791, 2022.** [V] https://www.semanticscholar.org/paper/a42e038f8b36e2247f3a9a131b61de549cecf77f. It gets execution flows and wait dependencies from host tracing only, even for nested VMs.\[1\] **Supports** diagnosis from the host kernel, without instrumenting the guest or container. That matches your pid-namespace attribution.
3. **Gelle, L., Ezzati-Jivan, N., Dagenais, M. R. "Combining Distributed and Kernel Tracing for Performance Analysis of Cloud Applications." Electronics 10(21):2610, 2021 (open access).** [V] https://www.mdpi.com/2079-9292/10/21/2610. The paper says a critical path lets you "observe contention for resources, for example, lock contention and cpu contention."\[2\] **Supports** the lock-contention and CPU-contention blueprints.
4. **Kohyarnejadfard, I., Aloise, D., Azhari, S. V., Dagenais, M. R. "Anomaly detection in microservice environments using distributed tracing data analysis and NLP." Journal of Cloud Computing 11:25, 2022.** DOI: 10.1186/s13677-022-00296-4. Open access: https://pmc.ncbi.nlm.nih.gov/articles/PMC9375740/ [V]. It collects LTTng kernel and user events per span, detects anomalies, and shows them in Trace Compass.\[3\]\[4\] **Supports** LTTng CTF as a microservice RCA data source. Related PhD thesis: Kohyarnejadfard, "System Performance Anomaly Detection using Tracing Data Analysis," Polytechnique Montréal, 2022: https://publications.polymtl.ca/10281/1/2022_ImanKohyarnejadfard.pdf [V].\[5\]
5. **Denys et al. "Distributed computation of the critical path from execution traces." Software: Practice and Experience, 2023.** DOI: 10.1002/spe.3210 [V]. It scales the Giraldeau critical-path algorithm and notes that critical paths across several traces need near-perfect clock sync.\[6\] **Refines** any cross-container, cross-trace step in your blueprints.
6. **Brendan Gregg, USE Method** (https://www.brendangregg.com/usemethod.html) and **Off-CPU Analysis** (https://www.brendangregg.com/offcpuanalysis.html) [M]. USE checks Utilization, Saturation and Errors for every resource. Off-CPU analysis explains blocked time. **Supports** the blueprint structure: check the resource, then saturation, then errors.
7. **Linux PSI docs (Weiner).** https://docs.kernel.org/accounting/psi.html [V via helper]. Quote: "When CPU, memory or IO devices are contended, workloads experience latency spikes, throughput losses, and run the risk of OOM kills." PSI exists per cgroup (cpu.pressure, memory.pressure, io.pressure).\[7\] **Supports** the idea of "stall time" as the central signal. PSI is not in your LTTng trace, but you can rebuild it from the runnable-but-waiting time between sched_wakeup and sched_switch.
8. **Empirical base for microservice faults:** Zhou et al., "Fault Analysis and Debugging of Microservice Systems: Industrial Survey, Benchmark System, and Empirical Study," IEEE TSE, 2018/2021 (Train Ticket), DOI 10.1109/TSE.2018.2887384 [M]. Pham et al., RCAEval, WWW 2025 Companion, arXiv:2412.17015 [M]. Waseem et al., "On the Nature of Issues in Five Open Source Microservices Systems," arXiv:2104.12192 [V].\[8\] Waseem et al., "Understanding the Issues, Their Causes and Solutions in Microservices Systems," which mined 2,641 issues from 15 open-source microservice systems on GitHub, plus 15 interviews and a survey of 150 practitioners, arXiv:2302.01894, now in the Journal of Systems and Software [V].\[9\] **These are the MSR-style GitHub-mining papers your supervisor asked for, at the microservice level.**
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
| Ghanavati, Costa, Seboek, Lo, Andrzejak, "Memory and resource leak defects and their repairs in Java projects," Empirical Software Engineering 25(1):678–718, 2020. DOI 10.1007/s10664-019-09731-8. OA: https://arxiv.org/abs/1810.00101 [V] | Empirical (MSR-style: 491 issues, 15 Java projects) | **Supports**: resource leaks (connections, streams, file handles) are common, and "most of the errors manifest on error-free execution paths," so a leak builds up quietly and then the pool runs dry. |\[13\]
| Dai, He, Gu, Lu, "Understanding Real-World Timeout Problems in Cloud Server Systems," IEEE IC2E 2018. DOI 10.1109/IC2E.2018.00022. PDF: https://dance.csc.ncsu.edu/papers/IC2E18.pdf [V]                                                     | Empirical (156 bugs, 11 systems) | **Supports**: "81% timeout problems are caused by either misused timeout values or missing timeout checking."\[14\] A missing pool-acquire timeout is one such case. |
| HikariCP, "About Pool Sizing" wiki, https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing [M]                                                                                                                                   | Industrial | **Refines**: small pools are normal and healthy, so a small number of live connections alone is not a fault. |
| Wooldridge (HikariCP README) + Spring Boot reference, "SQL databases" [V]: pooled callers make few connect() calls in steady state. HikariCP is Spring Boot's default pool. Stored: `DOCS/reading-papers/sources/hikaricp-readme/`, `.../spring-boot-datasource-defaults/`                                                                                                                                          | Mechanism | **Contradicts** the naive discriminator: for already-pooled callers, "few connects" is the *normal* state. Your applicability note is right and should cite HikariCP. |
| US Patent 11,750,692 "Connection pool anomaly detection mechanism" (Salesforce) [S], https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11750692                                                                               | Industrial | **Supports** (weak): says exhaustion "may occur frequently" in production and separates "sustained" from "intermittent" exhaustion. Patent text, not peer reviewed. |\[15\]

**Honest gap:** I found **no peer-reviewed MSR paper focused only on connection-pool exhaustion.** The best academic chain is: leak study (Ghanavati) + timeout study (Dai) + pool-sizing theory (HikariCP, industrial). Say this in the thesis. It is a real gap that your work partly fills.

### 4. deadlock-lock-order (deadlock)

**Discriminator to ground:** the workload appears and then goes almost silent; threads are parked in futex_wait with no matching wake; the event rate is near zero; there is no CPU burn.

| Reference                                                                                                                                                                                    | Type | Relation |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|---|
| Lu, Park, Seo, Zhou, "Learning from Mistakes: A Comprehensive Study on Real World Concurrency Bug Characteristics," ASPLOS 2008. DOI 10.1145/1346281.1346323 [M]                             | Empirical (105 bugs from MySQL, Apache, Mozilla, OpenOffice; 31 deadlocks) | **Supports**: "Almost all (97%) of the examined deadlock bugs involve two threads circularly waiting for at most two resources"; 22% are caused by one thread acquiring a resource it already holds. |
| Tu, Liu, Song, Zhang, "Understanding Real-World Concurrency Bugs in Go," ASPLOS 2019. DOI 10.1145/3297858.3304069 [M]                                                                        | Empirical (Docker, Kubernetes, etcd, gRPC, etc.) | **Supports / refines**: Sock Shop has Go services. In Go, many blocking bugs come from channel misuse, not mutexes. A goroutine blocked on a channel parks in the Go runtime, so on the kernel side you may see *idle epoll/futex* threads, not one futex per blocked goroutine. |
| Franke, Russell, Kirkwood, "Fuss, Futexes and Furwocks: Fast Userlevel Locking in Linux," OLS 2002 [M] (kernel.org OLS mirror)                                                               | Mechanism | **Supports**: an uncontended lock never enters the kernel; only waiting enters FUTEX_WAIT. So a deadlock = FUTEX_WAIT with no FUTEX_WAKE. |\[16\]
| Rezazadeh, Ezzati-Jivan, Galea, Dagenais, "Multi-Level Execution Trace Based Lock Contention Analysis," ISSRE Workshops 2020, pp. 177–182 [V]. Stored: `DOCS/reading-papers/sources/rezazadeh-2020-lock-contention/`                                            | Method | **Supports**: lock waits reconstructed from traces. |\[17\]\[18\]
| Ezzati-Jivan, Fournier, Dagenais, Hamou-Lhadj, "DepGraph: Localizing Performance Bottlenecks in Multi-Core Applications Using Waiting Dependency Graphs and Software Tracing," SCAM 2020 [S] | Method | **Supports**: a waiting-dependency graph; a cycle in it = deadlock. |\[19\]

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
| Franke, Russell, Kirkwood, OLS 2002 [M]                                                                                                                                                                                 | Mechanism | **Supports**: futex syscalls happen only under contention, so the futex rate is a contention signal *in general*. |
| Rezazadeh et al., ISSRE-W 2020 [V]; Gelle et al., Electronics 2021 [V]                                                                                                                                                  | Method | **Supports**: lock contention can be seen in kernel and multi-level traces. |
| Hamala, "LockSupport.parkNanos() Under the Hood and the Curious Case of Parking," Hazelcast blog, 2019, https://hazelcast.com/blog/locksupport-parknanos-under-the-hood-and-the-curious-case-of-parking/ [S via helper] | Mechanism (JVM) | **Contradicts the naive rule**: "the implementation of the park() method that the JVM uses when running on Linux uses the POSIX Threads API".\[24\] So idle thread pools, timed waits and executors all generate futex calls with no lock contention. |
| OpenJDK bug JDK-6900441, https://bugs.openjdk.org/browse/JDK-6900441 [V]. Stored: `DOCS/reading-papers/sources/openjdk-jdk-6900441/` (markdown only - the tracker refuses a plain fetch)                                                                                                                                            | Mechanism (JVM) | **Supports the JVM caveat**: Thread.sleep, Object.wait and LockSupport.park are built on pthread_cond (PlatformEvent / Parker). |\[25\]
| Kernel doc "Futex Requeue PI," https://docs.kernel.org/locking/futex-requeue-pi.html [S]                                                                                                                                | Mechanism | **Completes the chain**: glibc pthread_cond_wait calls futex_wait. |\[26\]
| Quarkus discussion #30231, https://github.com/quarkusio/quarkus/discussions/30231 [S]                                                                                                                                   | Industrial | **Supports** (weak): 7.7% of benchmark CPU time was spent in LockSupport.unpark(), linked to futex. |\[27\]

**Important framing for your thesis:** The literature treats a futex rate as a contention signal. That holds for C/C++ programs, where an uncontended lock never calls the kernel. On the JVM, *parking is the normal idle path*, so the futex share is high at baseline. **No single source says "JVM services are futex-heavy by default"**; you build it from the chain JVM park → pthread_cond → futex. Present it as your own observation, backed by the chain of citations. Your discriminator should be the *change against the service's own baseline* plus *many waiters on the same futex address*, not the raw share.

### 7. cpu-contention-co-tenant (noisy_neighbor)

**Discriminator to ground:** the victim's runnable-wait grows while it is preempted by threads from *another* pid namespace; the victim has no throttling; the host is not fully busy, or only one CPU set is.

| Reference | Type | Relation |
|---|---|---|
| Zhang et al., "CPI2: CPU performance isolation for shared compute clusters," EuroSys 2013. DOI 10.1145/2465351.2465388 [M] | Empirical + method (Google) | **Supports**: co-located "antagonists" hurt victims; Google finds them by correlating victim slowdown with antagonist CPU use. That is the same logic as "who preempted me" in sched_switch. |
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
| Rezazadeh et al. 2020 [V] | Method | **Supports**: lock-holder and waiter analysis from traces. |

**Version caveat:** Since Linux 6.6, EEVDF replaced CFS as the default fair scheduler (source: the Wikipedia CFS article, which cites Phoronix [S]).\[30\] Nice weights still exist, but write down your kernel version in the blueprint's "applicability" field.

### 9. db-latency-dependency-wait (slow_db) — *was weak, now better*

**Discriminator to ground:** the caller threads block in recv/poll on the DB socket (off-CPU, waiting on the network); the DB container shows the work (CPU or disk), or long idle gaps if delay is injected; the caller's own CPU is low.

| Reference | Type | Relation |
|---|---|---|
| Yang, Subramaniam, Lu, Yan, Cheung, "How not to Structure Your Database-Backed Web Applications: A Study of Performance Bugs in the Wild," ICSE 2018, pp. 800–810. DOI 10.1145/3180155.3180194. PDF: http://hyperloop.cs.uchicago.edu/220-HowNotStructure.pdf [V] | Empirical (MSR-style: issue reports from 12 ORM apps) | **Supports**: DB-access performance bugs are common in real apps and come from ORM misuse, database design and application design. |\[31\]\[32\]
| Dai et al., IC2E 2018 [V] | Empirical | **Supports**: a slow dependency without a proper timeout turns into a hang for the caller. |
| Giraldeau & Dagenais 2016 [M]; Nemati et al. 2022 [V] | Method | **Supports**: the critical path crosses from the caller's blocked recv to the DB's work, which is exactly "whose fault is the wait." |
| Gregg, Off-CPU Analysis [M] | Method | **Supports**: blocked time, not CPU time, is where the latency goes. |
| Zhou et al., TSE (Train Ticket) [M] | Empirical | **Supports**: dependency and DB-related faults are among the fault types in the industrial survey. |

**Rule-out vs. connection-pool exhaustion:** in slow_db, threads wait on the *socket* (network wait). In pool exhaustion, they wait on a *futex* (user-space lock) before any socket I/O. This is a strong discriminator, and it follows directly from the wait-analysis categories.

### 10. service-cpu-throttle (svc_cpu_cap)

**Discriminator to ground:** the service runs in bursts and then *all its threads stop at the same time* until the next period (100 ms by default), with no other task taking the CPU; runnable-wait with idle CPUs available.

| Reference | Type | Relation |
|---|---|---|
| Kernel doc "CFS Bandwidth Control," https://docs.kernel.org/scheduler/sched-bwc.html [V] | Mechanism | **Supports**: "Within each given 'period' (microseconds), a task group is allocated up to 'quota' microseconds of CPU time."\[33\] When the quota runs out, the group is throttled until the next period. |
| Turner, Rao, Rao, "CPU bandwidth control for CFS," Linux Symposium (OLS) 2010, pp. 245–254. https://www.kernel.org/doc/mirror/ols2010.pdf [V] | Mechanism (original design, Google/IBM) | **Supports**: the design paper for the quota/period mechanism. |\[34\]\[35\]
| Ugedal, Kannan, "Mitigating Unnecessary Throttling in Linux CFS Bandwidth Control," SBAC-PAD 2022. PDF: https://rakeshk.folk.ntnu.no/pubs/SBACPAD22.pdf [V] | Mechanism + empirical | **Refines**: bandwidth control "might unnecessarily throttle processes," because per-CPU slices end up with negative runtime.\[36\] So throttling can happen *even when average use is below the quota*. |
| Dan Luu, "The container throttling problem," https://danluu.com/cgroup-throttling/ [M]; Kubernetes issue #67577 [M] | Industrial | **Refines**: multi-threaded services hit the quota in a few ms and then stall, so average CPU looks fine while tail latency is bad. |
| LWN, "CFS bandwidth control," 2011, https://lwn.net/Articles/428230/ [V] | Mechanism | **Supports**: explains cpu.cfs_period_us and cpu.cfs_quota_us. |\[37\]

**Key discriminator vs. noisy neighbor:** in throttling, the victim's threads go off-CPU *while CPUs are idle*. With a noisy neighbor, a *foreign* task is running on the CPU. You can see this directly in sched_switch next_comm/next_pid.

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
| Ghanavati et al., EMSE 2020 [V] | Empirical (MSR-style) | **Supports**: resource leaks (including file handles) are common, and developers mostly find them by hand. |\[42\]
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
| Gassais, Ezzati-Jivan, Fernandez, Aloise, Dagenais, "Multi-level host-based intrusion detection system for Internet of things," Journal of Cloud Computing 9:62, 2020. DOI 10.1186/s13677-020-00206-6 [V via helper] | Method (DORSAL, LTTng) | **Supports**: an LTTng host IDS that lists "Data exfiltration" as a threat, and notes "intrusions cannot easily or reliably be detected from network traces." IoT, not containers. |\[57\]
| Jewell, Beaver, "Host-Based Data Exfiltration Detection via System Call Sequences," ICIW 2011, pp. 134–142 (ORNL), https://www.ornl.gov/publication/host-based-data-exfiltration-detection-system-call-sequences [S] | Method | **Supports**: system-call sequences can detect exfiltration. |\[58\]
| "REPLICAWATCHER: Training-less Anomaly Detection in Containerized Microservices," NDSS 2024, https://www.ndss-symposium.org/wp-content/uploads/2024-286-paper.pdf [S; check authors] | Method (containers, kernel events) | **Supports**: compares microservice replicas using kernel events; includes an exfiltration scenario. The closest match to your setting. |\[59\]

### Related families (short)

- **nagle_delayed_ack:** Mogul & Minshall, "Rethinking the TCP Nagle Algorithm," ACM SIGCOMM CCR, Jan 2001, http://ccr.sigcomm.org/archive/2001/jan01/ccr-200101-mogul.pdf [V], which talks about "the well-known potential for deadlock between the Nagle algorithm and the delayed ACK policy."\[60\] Stuart Cheshire, "TCP Performance problems caused by interaction between Nagle's Algorithm and Delayed ACK," https://www.stuartcheshire.org/papers/nagledelayedack/ [V].\[61\] Brooker, "It's always TCP_NODELAY," 2024, https://brooker.co.za/blog/2024/05/09/nagle.html [V].\[62\] RFC 896 and RFC 1122 [M]. **Trace signature:** a gap of about 40 ms (Linux minimum delayed-ACK time) between a small write and the next send, in a write-write-read pattern.\[63\]
- **error_storm / queue_backlog:** Bronson 2021 and Huang 2022 (feedback loops); Dai 2018 (timeouts).
- **resource_abuse / anomaly_mem:** CPI2, Heracles, TMO, cgroup v2 docs.
- **General performance-bug evidence:** Jin, Song, Shi, Scherpelz, Lu, "Understanding and Detecting Real-World Performance Bugs," PLDI 2012, DOI 10.1145/2254064.2254075 [M]. The TScope (ICAC 2018) and TFix (ICDCS 2019) papers by He, Dai, Gu for timeout bug detection and fixing [V].\[64\]

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
