# Paper Context: Learning from Mistakes — A Comprehensive Study on Real World Concurrency Bug Characteristics (ASPLOS 2008)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is the **empirical base for blueprint 4** (`deadlock-lock-order`). It is the paper that
> says real deadlocks are simple: two threads, two resources. Section 9 explains what it does
> and does **not** support for us - in particular it says nothing about how a deadlock *looks*
> at runtime, only about how the bugs are shaped in source code.

---

## 1. Bibliographic info

- **Title:** Learning from Mistakes - A Comprehensive Study on Real World Concurrency Bug
  Characteristics
- **Authors:** Shan Lu, Soyeon Park, Eunsoo Seo, Yuanyuan Zhou (University of Illinois at
  Urbana-Champaign)
- **Venue:** ASPLOS '08, 15 March 2008, Seattle, pp. 329-339
- **DOI:** 10.1145/1346281.1346323
- **ISBN:** 978-1-59593-958-6/08/03

```bibtex
@inproceedings{lu2008learning,
  title     = {Learning from Mistakes: A Comprehensive Study on Real World Concurrency Bug Characteristics},
  author    = {Lu, Shan and Park, Soyeon and Seo, Eunsoo and Zhou, Yuanyuan},
  booktitle = {ASPLOS '08}, pages = {329--339}, year = {2008},
  doi       = {10.1145/1346281.1346323}
}
```

---

## 2. One-paragraph summary

The authors read **105 real concurrency bugs** from the bug databases of MySQL, Apache, Mozilla
and OpenOffice, and classify each one by pattern, by what it takes to trigger it, and by how it
was fixed. The message is that real concurrency bugs are **much simpler than the theoretical
worst case**. Almost all non-deadlock bugs are one of two shapes. **97% of deadlocks involve
two threads and at most two resources.** 92% of all the bugs can be triggered by forcing an
order among **four or fewer memory accesses**. But fixing them is hard: 73% of non-deadlock
bugs were *not* fixed by adding or changing a lock, and many fixes were wrong on the first try.

---

## 3. Method

**Applications** - four mature open-source programs, 9-13 years old, 1-4 million lines of code,
all C/C++:

| Application | Type | Non-deadlock bugs | Deadlock bugs |
|---|---|---|---|
| MySQL | database server | 14 | 9 |
| Apache | web server | 13 | 4 |
| Mozilla | browser suite | 41 | 16 |
| OpenOffice | office suite | 6 | 2 |
| **Total** | | **74** | **31** |

**Bug selection.** The databases hold over 500,000 reports. They searched with concurrency
keywords (`race`, `deadlock`, `synchronization`, `lock`, `mutex`, `atomic`, `compete` and
variants), took about **500 reports at random** that had clear root-cause descriptions, source
and fix information, then manually confirmed each was really caused by a wrong assumption about
concurrent execution. That left **105**.

For each bug they read the report, the source, the patches, and the developers' discussion.

**Deadlock and non-deadlock bugs are studied separately**, because they behave differently and
need different detection and recovery.

---

## 4. Definitions that matter

| Term | Definition |
|---|---|
| **Atomicity violation** | a code region was meant to be atomic and was not |
| **Order violation** | A was meant to run before B, and the order was not enforced |
| **Manifestation condition** | the **smallest set of memory accesses** whose execution order, if enforced, guarantees the bug appears |

**They deliberately do not treat "data race" as a bug pattern.** Their reasoning: a race may
be benign (a while-flag), and being race-free does not mean being concurrency-bug-free.

---

## 5. All 13 findings (their Table 1)

### Bug patterns

1. **97%** of non-deadlock bugs are either atomicity violation or order violation.
2. **32%** are **order violations** - and these are not addressed by existing race or atomicity
   detectors.

### Manifestation

3. **96%** of all concurrency bugs are guaranteed to appear if a partial order between **2
   threads** is enforced.
4. **22% of deadlock bugs are caused by one thread acquiring a resource it already holds** -
   a single-thread deadlock.
5. **66%** of non-deadlock bugs involve accesses to **one variable** only.
6. **34%** involve **multiple variables** - which most tools miss.
7. **97% of deadlock bugs involve two threads circularly waiting for at most two resources.**
8. **92%** of all bugs are guaranteed to appear if an order among **no more than 4 memory
   accesses** is enforced. This turns the interleaving space from exponential to polynomial.

### Fixes

9. **73%** of non-deadlock bugs were fixed by something **other** than adding or changing
   locks. The fix strategies they classify are: condition check, code switch, design change,
   lock strategy, other.
10. **61% of deadlock bugs were fixed by preventing a thread from acquiring a resource**
    (giving it up) - and such a fix **can introduce non-deadlock bugs**.

### Avoidance with transactional memory

11. TM could avoid about **39%** of the bugs.
12. TM could avoid **42%** if certain concerns are handled - long code regions, operations
    that are hard to roll back (I/O and system calls), and code whose design resists becoming
    a transaction.
13. **19%** cannot benefit from basic TM because of their pattern - mostly order violations,
    which C/C++ has no good way to express.

---

## 6. Threats to validity (their own)

- Four C/C++ server and client applications. **Not** scientific code, not operating systems,
  **not Java**.
- Only **fixed and reported** bugs. Unreported or unfixed ones may differ, and concurrency bugs
  are known to be under-reported because non-determinism makes them hard to describe.
- They state plainly that they do not intend to draw general conclusions about all concurrent
  applications.

---

## 7. What kind of paper this is

- A **source-code and bug-report study**. Everything is derived from reading reports, patches
  and discussions.
- **No runtime measurement of any kind.** No traces, no timings, no profiles.
- **No tool.** It is a characterisation study meant to guide the design of tools.

---

## 8. What this means for our work

**The two numbers blueprint 4 uses, and they are solid.**

- *"Almost all (97%) of the examined deadlock bugs involve two threads circularly waiting for
  at most two resources."*
- *"22% are caused by one thread acquiring a resource it already holds."*

Both are direct quotes from findings 7 and 4. They justify the blueprint's framing that a real
deadlock is small and simple - not a many-way cycle.

**The limit to be honest about: this paper never looks at a running program.** It says what
deadlock bugs *are* in source code. It says nothing about what one *looks like in a kernel
trace* - no futex counts, no event rates, no silence. Our blueprint's actual discriminator
(the workload appears then goes almost silent, threads parked in futex with no matching wake)
is **our own measurement**, and this paper is background on the bug class, not evidence for
the signature.

**A caveat that cuts against our Sock Shop setting.** All four applications are **C/C++**. The
paper's own threats-to-validity says it may not reflect Java. Sock Shop is Java and Go. The Go
gap is covered by Tu et al. 2019 (ASPLOS), which the reference pack already pairs with this
one. The **Java** gap is not covered by either.

**One finding worth using that we currently do not.** Finding 4: **22% of deadlocks are a
single thread re-acquiring what it already holds.** That is a *self*-deadlock - one thread, one
lock. Our blueprint assumes the two-thread AB-BA shape, which is what our injector produces.
If we ever widen the fault family, the single-thread case is the second most common real shape
and it would look different in a trace (one thread parked, not two).

**A useful contrast for the thesis.** Finding 9 - **73% of non-deadlock bugs were not fixed by
touching locks** - supports a point our work implies: knowing *where* the contention is does not
tell you *what to change*. Our blueprints stop at localisation, and this is the citation for
why that is a reasonable place to stop.

---

## 9. Safe claims

- 105 real concurrency bugs (74 non-deadlock, 31 deadlock) from MySQL, Apache, Mozilla and
  OpenOffice.
- **97% of deadlock bugs involve two threads circularly waiting for at most two resources.**
- **22% of deadlock bugs are one thread acquiring a resource it already holds.**
- 97% of non-deadlock bugs are atomicity violations or order violations; 32% are order
  violations.
- 96% of bugs manifest if a partial order between two threads is enforced.
- 92% manifest if an order among no more than four memory accesses is enforced.
- 66% of non-deadlock bugs involve one variable; 34% involve several.
- 73% of non-deadlock bugs were fixed without adding or changing locks.
- 61% of deadlock fixes work by giving up a resource, and such fixes can introduce new
  non-deadlock bugs.
- Transactional memory could avoid 39% of the bugs (42% if rollback and code-length concerns
  are addressed); 19% cannot benefit.

## 10. Do NOT claim

- Anything about how a deadlock looks at runtime. The paper contains no runtime data.
- That the findings cover Java or Go. All four applications are C/C++, and the authors say so.
- That these are all concurrency bugs in those projects. They are a random sample of ~500
  screened reports, narrowed to 105.
- That data races are or are not bugs on this paper's authority - it explicitly declines to
  treat race as a bug pattern.

## 11. Reusable ideas

- **Separate the bug classes before measuring them.** Deadlock and non-deadlock are studied
  apart because they behave differently. Our fault families deserve the same treatment rather
  than one pooled score.
- **Define the manifestation condition as the smallest sufficient set.** "How few accesses must
  I order to guarantee this appears" is a much sharper question than "how complex is this bug".
- **Report the negative finding about fixes.** 73% not fixed by locks is the most useful number
  in the paper for tool designers, and it is the one that says their tools were aimed wrong.
- **State the language scope up front.** Their threats-to-validity naming C/C++ is why we can
  tell the finding does not transfer to our JVM services.
