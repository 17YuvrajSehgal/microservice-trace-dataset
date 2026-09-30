# Paper Context: How Not to Structure Your Database-Backed Web Applications — A Study of Performance Bugs in the Wild (ICSE 2018)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited by blueprint 9 (`slow-query-db`) as the "it happens in the wild" evidence for
> database-access performance bugs. The citation is accurate. The paper's most useful gift to
> us is a **named vocabulary of nine causes** — see §8.

---

## 1. Bibliographic info

- **Title:** How not to structure your database-backed web applications: a study of performance
  bugs in the wild
- **Authors:** Junwen Yang, Pranav Subramaniam, Shan Lu (University of Chicago);
  Cong Yan, Alvin Cheung (University of Washington)
- **Venue:** ICSE 2018, Gothenburg, pp. 800-810
- **DOI:** 10.1145/3180155.3180194
- **Project:** Hyperloop, http://hyperloop.cs.uchicago.edu

```bibtex
@inproceedings{yang2018hownot,
  title     = {How not to structure your database-backed web applications: a study of performance bugs in the wild},
  author    = {Yang, Junwen and Subramaniam, Pranav and Lu, Shan and Yan, Cong and Cheung, Alvin},
  booktitle = {ICSE 2018}, pages = {800--810}, year = {2018},
  doi       = {10.1145/3180155.3180194}
}
```

---

## 2. One-paragraph summary

Web apps talk to databases through **Object Relational Mapping** frameworks, which hide the SQL.
That convenience is also the problem: developers cannot see what queries their code generates,
and the framework cannot see what the application means. The authors study **12 real Ruby on
Rails applications** two ways — reading **140 fixed performance issues** from their bug trackers,
and **profiling the latest version of each one**. From about **200 issues** they generalise **9
performance anti-patterns** in three groups: ORM API misuse, database design, and application
design trade-offs. They then **fix 64 issues by hand** and get a **median 2x speedup, up to 39x**,
with **fewer than 5 lines of code in 78% of fixes**.

---

## 3. The applications studied

12 apps in 6 categories, all Rails, all real and popular.

| Category | Apps |
|---|---|
| Forum | Discourse (21k stars), Lobsters |
| Collaboration | **Gitlab** (19k stars), Redmine |
| E-commerce | Spree, Ror_ecommerce |
| Task management | Fulcrum, Tracks |
| Social network | Diaspora, Onebody |
| Map | OpenStreetMap, Fallingfruit |

They argue the findings carry to Django and Hibernate, since Rails offers the same
functionality — but the study itself is Rails only.

---

## 4. RQ1 — how badly do they actually perform?

Under a workload **no larger than today's typical workload**, and for some apps much smaller:

- **11 of 12 applications** have pages taking **more than 2 seconds** to load.
- **6 of 12** have pages taking more than 3 seconds.
- **Tracks** is worst: all 10 of its most time-consuming pages exceed 2 seconds.
- **40 problematic server actions** found across the 12 apps. Of these, **34 have scalability
  problems** and **28 take more than 1 second of server time**.
- Pages also **scale super-linearly** with data size.

**Server time dominates.** It is at least **40% of end-to-end latency** for more than half the
top-10 pages in all but one application, and **over 50% of problematic pages spend more than 80%
of their loading time on the server.**

Their motivating stakes: nearly half of users expect a page in under 2 seconds and abandon after
3; every extra 0.5 s of latency cuts traffic by 20%.

---

## 5. The nine anti-patterns

### Group A — ORM API misuse (about half of all issues)

| Code | Name |
|---|---|
| **IC** | Inefficient Computation |
| **UC** | Unnecessary Computation |
| **ID** | Inefficient Data Accessing |
| **UD** | Unnecessary Data Retrieval |
| **IR** | Inefficient Rendering |

### Group B — database design

| Code | Name |
|---|---|
| **MF** | Missing Fields |
| **MI** | Missing Indexes |

### Group C — application design trade-offs

| Code | Name |
|---|---|
| **DT** | Content Display Trade-offs |
| **FT** | Functionality Trade-offs |

**6 of the 9 appear in more than half of the studied applications.** All but one appear both in
past fixed bugs and in the current version — i.e. these are not historical mistakes, they are
live.

### The ones that matter for a kernel-trace view

**Inefficient lazy loading — the "N+1" query problem.** Load N objects with one query, then issue
**N more queries**, one per object, to load each one's association. Found in **15 problematic
actions and 9 issue reports**, despite being well known. Their Lobsters example: 50 objects
became **51 queries and 51 network round-trips**; batching them cut page load from **1.10 s to
0.34 s**.

**Inefficient eager loading — the opposite mistake.** Always loading eagerly creates huge memory
pressure. In Spree-5063, loading **405 products** eagerly pulled in **13,811 variants** containing
**276,220 option_values**, and the page froze. The authors note there is **little tool support**
for detecting it, unlike N+1.

**Inefficient updating.** N separate `update` calls instead of one `update_all`. Their static
checker finds this in **6 of the 12** latest versions.

**Inefficient computation.** `any?` versus `exists?` generate very different SQL — one scans the
whole table to count, the other stops at the first match. Replacing it improved one OneBody
action by **1.7x**, and the checker finds the same problem in **9 of 12** applications.

---

## 6. RQ3 — the fixes

64 fixes across 39 problematic actions, measured on a 20,000-record database.

- **More than 60% of fixes give more than 2x speedup**; about a quarter give more than 5x.
- **Largest single speedup: 39x.**
- The **40 fixes that change neither display nor functionality** average **2.2x**, max 9.2x.
- Across all 39 actions: average **server time 3.57 s to 0.49 s**; **end-to-end 4.17 s to
  0.69 s**. In their words, these anti-patterns **degrade application performance by about 6x**.
- **78% of fixes are fewer than 5 lines.** 27 fixes are a **single line**. The biggest is 56
  lines. Among fixes giving 3x or more, **over 90% are under 10 lines**. About 60% touch only one
  function.
- Reported to developers: **14 responses so far, all confirmed as real performance problems, 7
  already fixed.**

---

## 7. What kind of paper this is

- An **empirical bug study** plus manual profiling, manual fixing, and a simple static checker.
- **Ruby on Rails only.** Generalisation to Django/Hibernate is argued, not measured.
- Signal is **source code and bug reports**, not telemetry. There are no traces here.
- The unit of analysis is a **web page action**, not a microservice.

---

## 8. What this means for our work

**The citation in our pack is correct.** "DB-access performance bugs are common in real apps and
come from ORM misuse, database design and application design" is a fair one-line summary of the
paper's RQ2 answer.

**The real value is the vocabulary.** Blueprint 9 currently says a slow query looks like long
waits on the DB socket. This paper says **there are at least four different causes with different
shapes**, and a kernel trace can tell some of them apart:

| Their anti-pattern | What a kernel trace would show |
|---|---|
| **N+1 lazy loading** | **many small round-trips** to the DB — high count of send/recv pairs, each short |
| **Inefficient eager loading** | **few round-trips, huge byte volume**, and memory pressure on the app container |
| **Missing index** | **one round-trip, long DB-side time**, app blocked the whole while |
| **Inefficient updating** | N small writes instead of one |

**N+1 and missing-index are opposite signatures and we should be able to separate them.** Many
tiny exchanges versus one long one. That is a discriminator our blueprint does not currently
state, and it is exactly the kind of thing a kernel trace is good at — we count syscalls, we do
not need to parse SQL. **This is worth testing on our own data before it goes in a blueprint.**

**It also bounds what we should claim.** Our `slow_query` fault is injected, so it is the
missing-index shape: one query, artificially slow. **We have no N+1 fault.** If we cite this paper
for "DB performance bugs are common", fine. If we imply our dataset covers the family it
describes, that would be wrong — we cover one of nine patterns.

**Two numbers worth borrowing for motivation.** Server time is over 80% of page load for more
than half of problematic pages, and the anti-patterns cost about **6x end-to-end**. Both say the
back end is where the time goes, which is where our traces look.

**A caution.** This is Rails. Sock Shop's catalogue is Go with hand-written SQL, and Train
Ticket is Java with Hibernate. **Only Train Ticket is an ORM application.** If we ever want to
study N+1 for real, Train Ticket is the place, not Sock Shop.

---

## 9. Safe claims

- 12 real Rails applications in 6 categories; **140 fixed issues** from bug trackers plus **64**
  found by the authors' own profiling — about **200 performance issues** total.
- **9 ORM performance anti-patterns** in three groups: API misuse (IC, UC, ID, UD, IR), database
  design (MF, MI), application design trade-offs (DT, FT). **6 of the 9 appear in more than half
  the applications.**
- **11 of 12 applications** have pages taking over 2 seconds, under a workload no larger than
  today's typical one; pages also scale super-linearly.
- **40 problematic server actions**; 34 have scalability problems, 28 exceed 1 second of server
  time.
- **Server time is at least 40% of end-to-end latency** for most slow pages, and **over 80%** for
  more than half of the problematic ones.
- The **N+1 query problem is still prevalent** — 15 problematic actions and 9 issue reports —
  despite being well studied. One example turned 50 objects into 51 queries and 51 round-trips.
- **Eager loading has the opposite failure**: 405 products pulled 13,811 variants and 276,220
  option_values, freezing the page. There is **little tool support** for detecting it.
- Fixes give **median 2x, up to 39x**; average server time 3.57 s to 0.49 s, end-to-end
  4.17 s to 0.69 s — about **6x degradation** from the anti-patterns.
- **78% of fixes are under 5 lines**; 27 are one line.
- **14 of the fixes drew developer responses, all confirmed; 7 already merged.**

## 10. Do NOT claim

- That the study covers Java or Python ORM applications. It is **Rails only**; the authors argue
  the findings transfer but do not test it.
- That it uses traces, telemetry, or runtime monitoring. It reads **code and bug reports** and
  profiles page loads.
- That "median 2x speedup" is an end-to-end user-visible number in all cases — it is the
  **server-time** speedup per fix.
- That our dataset covers these anti-patterns. Our injected `slow_query` is one shape out of
  nine.

## 11. Reusable ideas

- **Two-pronged study design.** Past fixed bugs tell you what people noticed; profiling the
  current version tells you what is still there. Neither alone is honest.
- **Fix the bugs to prove they matter.** Their 64 manual fixes turn a taxonomy into a measured
  6x. A catalogue without that is just opinion.
- **Report how small the fix was.** 78% under 5 lines is what makes the result actionable rather
  than depressing.
- **Name the opposite mistake too.** N+1 is famous; over-eager loading is the same problem
  mirrored, and nobody tools for it. Our blueprints should look for the mirrored failure of each
  signature we define.
- **An abstraction that hides the cost creates the bug.** ORM hides SQL; our equivalent is that
  container orchestration hides the kernel.
