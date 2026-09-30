# Paper Context: Memory and Resource Leak Defects and their Repairs in Java Projects (EMSE 2020)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited twice in our pack — for **connection-pool exhaustion** (blueprint 3) and for **file-handle
> exhaustion** (blueprint 12). Both citations are accurate. §8 has one number we should add to
> the pack, and §9 flags two internal inconsistencies in the paper itself.

---

## 1. Bibliographic info

- **Title:** Memory and resource leak defects and their repairs in Java projects
- **Authors:** Mohammadreza Ghanavati, Diego Costa (Heidelberg), Janos Seboek (Heidelberg),
  David Lo (Singapore Management University), Artur Andrzejak (Heidelberg)
- **Venue:** *Empirical Software Engineering* 25(1):678-718, 2020
- **DOI:** 10.1007/s10664-019-09731-8
- **Open access preprint:** arXiv:1810.00101v2, 27 June 2019
- **Replication package:** https://github.com/heiqs/leak_study

```bibtex
@article{ghanavati2020memory,
  title   = {Memory and resource leak defects and their repairs in Java projects},
  author  = {Ghanavati, Mohammadreza and Costa, Diego and Seboek, Janos and Lo, David and Andrzejak, Artur},
  journal = {Empirical Software Engineering}, volume = {25}, number = {1}, pages = {678--718}, year = {2020},
  doi     = {10.1007/s10664-019-09731-8}
}
```

---

## 2. One-paragraph summary

Leaks survive garbage collection. In Java the GC frees anything unreachable, but an unused object
that is **still referenced** is never freed, and **finite system resources — file handles, threads,
connections — are not GC's job at all**; the programmer has to close them. The authors read
**491 leak issues from 15 large open-source Java projects** and build four taxonomies: leak
types, how they were detected, root causes, and repair actions. The headline finding for us:
**76% of leaks are triggered on error-free execution paths** — the code that gets tested most.
They also find that **manual code inspection and manual runtime observation are still the main
detection methods**, that **only one issue in 491 was found by a static analyser**, and that
**13 recurring code transformations** cover most repairs.

---

## 3. Background — the two kinds of leak

**Memory leak.** The GC uses reachability to estimate liveness. If an unused object is **still
reachable from a live object**, it cannot be reclaimed. So a Java memory leak is *"a process
maintaining unnecessary references to unused objects."*

**Resource leak.** Finite system resources — **connections, threads, file handles** — are wrapped
in handle objects. Allocation looks like normal object allocation, but disposal must be
**explicit**: call the disposal method, or make sure the thread has stopped. Forget it, and the
resource leaks. And you must *also* drop the references, or you get a memory leak on top.

Why they matter and why they escape testing: leaks are **non-functional**, so they *"are likely
to escape traditional testing processes and become first visible in a production environment."*
Also — important for diagnosis — *"the root cause of a memory leak can differ from the allocation
which exhausts the memory."*

---

## 4. The dataset

- **491 issues**, **15 large open-source Java projects**.
- Projects: ActiveMQ, Cassandra, CXF, Derby, Hadoop, HBase, Hive, HttpComponents, Lucene, Solr,
  Selenium, Realm Java, Logstash, RxJava, Spring Boot.
- Manual classification; inter-rater agreement reported per taxonomy (leak type 0.86, detection
  type 0.83, detection method 0.70, defect type 0.69, repair type 0.57).

**Leak types (RQ1):** Memory, **File handle**, **Connection**, **Thread**.

- **Resource leaks 253, memory leaks 238** — resource leaks slightly more common.
- Distribution varies sharply by project: file-handle leaks are **55.9% of Lucene** and **42.9% of
  Hadoop** issues; memory leaks dominate ActiveMQ (67.5%), Cassandra (54.3%), CXF (78.4%), Derby
  (75.5%); **connection leaks** are most frequent in **HBase (37.5%)**, HttpComponents (30%) and
  Hive (27.3%); **10 of Spring Boot's 12 issues are thread leaks**.

---

## 5. How leaks get found (RQ2)

| Detection method | Memory leaks | Resource leaks |
|---|---|---|
| **Manual code inspection** | 68 (28.6%) | **113 (44.7%)** |
| Static analyser | **0 (0.0%)** | **1 (0.4%)** |
| Failed test | 17 (7.1%) | 40 (15.8%) |
| Out-of-memory error | 43 (18.1%) | 12 (4.7%) |
| Warning message | 8 (3.4%) | 11 (4.3%) |
| Runtime, other | 102 (42.9%) | 76 (30.0%) |

- **Runtime detection dominates memory leaks: 170 of 238 issues (71.4%).**
- **Source-code detection is more common for resource leaks: 114 issues (45.1%)**, because
  resource disposal is explicit in the code and so visible to review.
- **309 issues (about 63%) are detected or manifest at runtime.** Users reach for third-party
  memory analysers (`jmap`, MAT, YourKit) or **OS commands such as `lsof`**.
- **Exactly one issue in 491 was detected by a static analyser** (CASSANDRA-7709). The authors are
  careful: this does not prove static analysers are unused, only that they are not what found
  these bugs. They point to false positives, complex usage, and lack of awareness as likely
  obstacles.
- **57 issues (11.6%) were found by a test case.** Three projects had built their own leak
  detection and warned the user at runtime — e.g. Netty's
  `"SEVERE: LEAK: ByteBuf.release() was not called before it's garbage-collected."`
- **Out-of-memory errors appear over three times more often in memory-leak issues.** They
  deliberately exclude OOMs caused by a **misconfigured heap size**, on the grounds that a leak
  OOMs *regardless* of heap size while a misconfiguration does not.

---

## 6. Root causes (RQ4)

| Root cause | Issues |
|---|---|
| **Non-closed resource on an error-free path** (`nonClosedRes`) | **149 (30.35%)** |
| **Object not disposed if an exception is thrown** (`exception`) | **98 (19.96%)** |
| **Dead objects referenced by a collection** (`collection`) | **93 (18.94%)** |
| Unreleased reference on an error-free path (`unreleasedRef`) | 59 (12.02%) |
| Race condition (`concurrency`) | 18 (3.67%) |
| Wrong call schedule of the disposal method (`callSchedule`) | 16 (3.26%) |
| Over-sized cache or buffer (`cache`) | 14 (2.85%) |
| Incorrect API usage (`wrongAPI`) | 10 (2.04%) |
| Thread-local variable (`threadLocal`) | 10 (2.04%) |
| Classloader bi-directional reference (`classloader`) | 10 (2.04%) |
| JNI (`jni`) | 8 (1.63%) |
| Leak inside a third-party library (`leakyLib`) | 7 (1.43%) |

### The three findings

1. **76% of defects manifest on a normal, error-free execution path.** The authors flag this as
   counter-intuitive: error-free paths are executed and checked most often, so defects there
   should be *less* likely. For leaks they are not.
2. **Bad exception handling is second overall (98 issues, ~20%) and rises to about 32% when you
   count resource leaks only** — roughly **5× more common for resource leaks than memory leaks**.
   Exception paths are by definition rarely exercised, so they are rarely tested.
3. **Collection mismanagement is the top cause of memory leaks (39%).** Their `nonClosedRes`
   accounts for **58% of resource leaks**.

**The connection-leak column of their heatmap** (Figure 6) is worth reading on its own:
`nonClosedRes` 28, `exception` 18, `concurrency` 3, `threadLocal` 1. So connection leaks are
almost entirely *"forgot to close"* and *"did not close when it threw"*.

---

## 7. Repairs (RQ5, RQ6)

| Repair action | Issues |
|---|---|
| R1 Dispose in regular paths (`disposeReg`) | 111 (22.61%) |
| R3 Remove elements from a collection (`removeElm`) | 104 (21.18%) |
| R2 Dispose in exceptional paths (`disposeExcep`) | 97 (19.76%) |
| R4 Release the reference (`releaseRef`) | 69 (14.05%) |
| R5 Shut down thread after the task (`threadDown`) | 45 (9.16%) |
| R6 Improve thread safety (`threadSafe`) | 23 (4.68%) |
| R7 Use a more efficient API (`correctAPI`) | 12 (2.44%) |
| R8 Strong reference to weak reference (`weakRef`) | 9 (1.83%) |
| R9 Use a non-leaky library (`nonLeakyLib`) | 4 (0.81%) |
| R10 Other | 17 (3.46%) |

- **About 93% of resource leaks are repaired by just three actions**: `disposeReg`,
  `disposeExcep`, `threadDown`. **About 73% of memory leaks** by two: `releaseRef` and
  `removeElm`.
- **13 recurring code transformations** cover **over 86% of issues**. The simplest example:
  `dispose(obj)` becomes `if (obj != null) obj.dispose()`.
- **54% of defects are fixed by changing one source file**; about 81% within three files; only
  12% touch more than three.
- **Median code churn under 20 lines** for nearly every repair action. Median added lines 29.5,
  median removed 16.5 — **fixes grow the codebase**.
- **Leak defects are fixed slightly faster than non-leak defects: median 5.88 days versus 6.04
  days.** The authors suggest leak fixes are more concentrated in fewer files.

---

## 8. What this means for our work

**Both of our citations are accurate.**

- Blueprint 3 (`connection-pool-exhaustion`) cites it for "resource leaks are common, and most
  errors manifest on error-free execution paths, so a leak builds up quietly and then the pool
  runs dry." Correct, and the paper's connection-leak numbers back it specifically.
- Blueprint 12 (`fd-exhaustion`) cites it for "file-handle leaks are common, and developers
  mostly find them by hand." Also correct — **44.7% of resource leaks were found by manual code
  inspection**, and file handles are the biggest resource-leak category in Lucene and Hadoop.

**One number we should add to the pack, because it is the strongest thing in the paper for us.**
**One issue in 491 was found by a static analyser. Zero for memory leaks.** Meanwhile **63%
manifest at runtime** and people diagnose them with `lsof` and heap dumps. That is a direct
argument for **runtime evidence over code analysis**, from an MSR study, and our pack does not
currently quote it. It belongs next to Dai's 60% and Gunawi's 59%.

**A pattern is now visible across three independent papers**, and it is the backbone of our
motivation:

| Source | What is missing |
|---|---|
| **Dai 2018**, 156 timeout bugs | 60% produce **no error message** |
| **Gunawi 2016**, 597 outages | 59% have **no reported root cause** |
| **Ghanavati 2020**, 491 leaks | 1 of 491 found by **static analysis**; 63% only visible at runtime |

Three different failure families, three different methods, same conclusion: **the evidence you
need is not in the code and not in the logs. It is in what the system did.**

**It also names our fault honestly.** Our `fd_exhaustion` and `conn_pool_exhaustion` faults are
injected instantly. Real leaks are **slow accumulations on paths that run all the time**, and the
authors note that *"the root cause of a memory leak can differ from the allocation which exhausts
the memory."* That is the classic trap for a diagnosis method: **the thread that hits the limit
is usually not the thread that leaked.** Our WHERE scoring would credit the container that
crashed, which for a real leak may be the right container but is not the right *place*. Worth
stating as a limitation.

**Something we could actually test.** Their two dominant resource-leak causes have different
runtime shapes:

| Their root cause | What the trace would show |
|---|---|
| `nonClosedRes` on a normal path | **steady, monotonic** growth in open fds — one un-closed handle per request |
| `exception` path | growth **only in bursts**, correlated with error responses |

Steady versus bursty accumulation is measurable from `open`/`close` syscall counts. If we ever
want a *realistic* fd-exhaustion fault instead of an injected one, this is the recipe, and it
comes with a published frequency (58% vs 32% of resource leaks).

**A caution on scope.** Every project here is **Java**. Sock Shop's services are Go and Node;
only Train Ticket is Java. The `threadLocal` and `classloader` causes are JVM-specific and do not
transfer at all.

---

## 9. Two internal inconsistencies in the paper — read carefully before quoting

1. **Leak counts.** The RQ1 *summary* box says **253 resource / 238 memory = 491**, and the
   detection percentages in their Figure 4 are computed against 253 and 238. But **Finding 1 of
   the same section says "233 issues" and "219 issues"**, which sums to 452. **Use 253 and 238** —
   they are consistent with the rest of the paper and with the 491 total.
2. **Exception count.** Table 5 gives `exception` = **98 (19.96%)** and their heatmap sums to 98
   (18+51+16+13). But Finding 2's text says *"20% of the issues (93 issues)"* — 93 is the
   **collection** count. **Use 98.**

Neither changes any conclusion, but quoting the wrong figure would be traceable.

---

## 10. Safe claims

- **491 leak issues from 15 large open-source Java projects**, manually classified into
  taxonomies for leak type, detection, root cause and repair.
- Four leak types: **memory, file handle, connection, thread**. **Resource leaks (253) slightly
  outnumber memory leaks (238).**
- **76% of leak defects manifest on error-free execution paths** — the ones exercised and tested
  most.
- Most common root causes: **non-closed resource on a normal path 30.35%**, **bad exception
  handling 19.96%**, **collection mismanagement 18.94%**. `nonClosedRes` is **58% of resource
  leaks**; `collection` is **39% of memory leaks**; bad exception handling is about **32% of
  resource leaks** and roughly **5× more common for resource than memory leaks**.
- **Manual code inspection and manual runtime observation remain the main detection methods.**
  **Only 1 of 491 issues was detected by a static analyser**, and **none** of the memory leaks.
- **309 issues (~63%) are detected or manifest at runtime**, using heap analysers (`jmap`, MAT,
  YourKit) or OS commands such as **`lsof`**.
- **57 issues (11.6%) were found by a test case.** Three projects ship their own runtime leak
  warnings.
- **Out-of-memory errors are over 3× more common in memory-leak issues.** The authors exclude
  OOMs caused by heap misconfiguration, since a leak OOMs at any heap size.
- **93% of resource leaks** are fixed by three actions (dispose on the regular path, dispose on
  the exception path, shut down the thread); **73% of memory leaks** by two (release the
  reference, remove collection elements).
- **13 recurring code transformations cover over 86% of issues.**
- **54% of fixes touch one source file**; median code churn **under 20 lines**; median added 29.5
  lines versus 16.5 removed.
- **Leak defects are fixed marginally faster than non-leak defects: 5.88 vs 6.04 days median.**
- Leaks are **non-functional**, so they escape ordinary testing and first appear in production;
  and **the root cause of a memory leak can differ from the allocation that exhausts memory**.

## 11. Do NOT claim

- That the findings cover non-Java languages. All 15 projects are Java, and several root causes
  (`threadLocal`, `classloader`, `jni`) are JVM-specific.
- That static analysers do not work. The paper says only that **one issue in this dataset** was
  reported as found by one, and explicitly declines to generalise.
- That 76% refers to *detection*. It refers to the **execution path on which the defect
  manifests**.
- That leaks are hard to fix. The paper's point is the opposite: **small, concentrated, fast
  fixes** — they are hard to *find*.
- The figures 233 / 219 / 93 — see §9.

## 12. Reusable ideas

- **Separate "hard to find" from "hard to fix".** Their whole result is that leaks are cheap to
  repair and expensive to locate. That is exactly the case for a diagnosis dataset.
- **Count what actually found the bug.** "1 of 491 by static analysis" is a far stronger statement
  about tooling than any tool evaluation, because it comes from the record rather than a
  benchmark.
- **Taxonomy plus heatmap.** Cross-tabulating root cause against leak type is what shows
  connection leaks are almost entirely two causes. Our fault families deserve the same treatment
  against our signals.
- **Exclude the near-miss category explicitly.** Ruling out heap-misconfiguration OOMs, with a
  stated test for telling them apart, is the kind of discipline our fault labelling needs.
- **The allocation that fails is not the defect.** Applies directly to any exhaustion fault we
  score.
