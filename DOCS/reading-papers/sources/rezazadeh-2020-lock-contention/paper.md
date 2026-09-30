# Paper Context: Multi-Level Execution Trace Based Lock Contention Analysis (ISSRE Workshops 2020)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is a **6-page workshop paper** from the same lab as Giraldeau 2016, and it is cited by
> blueprints 4, 6 and 8. **Read section 10 first.** Its central claim is that kernel tracing
> alone is *not enough* for lock contention - it needs user-space tracepoints we do not have.
> That is a limit on what we can cite it for, and it is easy to get wrong.

---

## 1. Bibliographic info

- **Title:** Multi-Level Execution Trace Based Lock Contention Analysis
- **Authors:** Majid Rezazadeh (Polytechnique Montreal), Naser Ezzati-Jivan (Brock),
  Evan Galea (Brock), Michel R. Dagenais (Polytechnique Montreal)
- **Venue:** 2020 IEEE International Symposium on Software Reliability Engineering Workshops
  (ISSREW), pp. 177-182. 6 pages
- **DOI:** 10.1109/ISSREW51248.2020.00068
- **ISBN:** 978-1-7281-7735-9/20
- **Funding:** Ciena, NSERC, EfficiOS, Ericsson, Google

```bibtex
@inproceedings{rezazadeh2020multilevel,
  title     = {Multi-Level Execution Trace Based Lock Contention Analysis},
  author    = {Rezazadeh, Majid and Ezzati-Jivan, Naser and Galea, Evan and Dagenais, Michel R.},
  booktitle = {2020 IEEE International Symposium on Software Reliability Engineering Workshops (ISSREW)},
  pages     = {177--182}, year = {2020},
  doi       = {10.1109/ISSREW51248.2020.00068}
}
```

---

## 2. One-paragraph summary

Locks slow multi-threaded programs down, and existing tools need the source code or prior
knowledge of the bug. This paper diagnoses lock contention from **execution traces only**, with
no source access and no recompilation. The key move: Giraldeau's critical-path algorithm works
on **kernel** events, so it cannot see locks that never enter the kernel - a spinlock, for
example. So they add **user-space tracepoints on the pthreads library** via `LD_PRELOAD`, and
extend the critical-path algorithm to build one graph from both levels. The result shows who
holds a lock and who is waiting, at any moment. Overhead: under 0.7% for user-space tracing,
about 7% with the minimal kernel event set.

---

## 3. Problem and motivation

- Multi-threaded performance problems are hard to diagnose; you need detailed runtime data but
  cannot afford much overhead.
- Most existing tools **need the source code**, which is impractical for large applications.
- **Performance counters give incomplete information.** Their concrete complaint about Perf:
  you can get total wait time across all mutex instances over a period, but you *cannot* tell
  **which threads** were hurt most, or **which specific mutex instance** caused the wait.
- Prior work sits at either user level or kernel level, and cannot follow a problem that spans
  both - which is the usual case for contention.

### The motivating anecdote

They analysed two releases of **Trace Compass** with their own method and found a lock
contention problem **they did not expect**. Looking at the source then explained it, and it was
fixed in a later release. That is what prompted the paper.

---

## 4. The gap in Giraldeau 2016 (the point of this paper)

Giraldeau's active-path algorithm extracts thread states - running, interrupt handling, waiting
for disk / network / timer / another task - by building an execution graph from **operating
system events**.

**It cannot see a lock that stays in user space.** A spinlock's acquire and release are
implemented in user space. In their Figure 2, the kernel-only critical path shows the threads
simply "running" (green) with no indication of when they took the lock or waited for it.

So the extension is: capture lock events at the user level too, and build one graph from both.

---

## 5. Data collection

Tools: **LTTng 2.10** and **Trace Compass 4**.

**Why both levels.** Mutex and semaphore block and wake through the kernel (`futex` syscall).
Spinlock does not touch the kernel at all. To cover both, they trace both.

**User-space instrumentation via `LD_PRELOAD`.** A preloaded shared object replaces pthreads
functions with wrappers containing tracepoints. No recompile needed. Nine events:

| Event | Meaning |
|---|---|
| `pthread_mutex_lock_req` | thread requests the mutex |
| `pthread_mutex_lock_acq` | thread acquires it |
| `pthread_mutex_unlock` | thread releases it |
| `pthread_spin_lock_req` / `_acq` / `pthread_spin_unlock` | same three, for spinlocks |
| `sem_wait_req` / `sem_wait_acq` / `sem_post` | same three, for semaphores |

**The req / acq split is the whole trick.** The gap between *request* and *acquire* is the wait
for the lock. The gap between *acquire* and *unlock* is the critical section. Neither is
visible without both events.

They note the approach is not language-specific: because instrumentation is set up with
environment variables generating wrappers, it can trace pre-compiled libraries of any language.
They demonstrate on C++ and PHP.

---

## 6. Data model: states, attributes, state system

- A **state** is the time between two events. `pthread_mutex_lock_req` →
  `pthread_mutex_lock_acq` becomes a **"wait for lock"** state; `_acq` → `_unlock` becomes
  **"running critical section"**.
- A **State Provider** maps events to state changes.
- States are stored in a **state system** - a tree-based on-disk history of attribute values
  over time (Montplaisir et al.).
- An **attribute** is one resource aspect (a thread, a CPU, a file), organised in an
  **attribute tree**, which they compare to a filesystem: paths are directories, attribute
  names are filenames, and the "file content" is the value history.

---

## 7. Algorithm 1 — execution graph from lock events

Input: trace, thread set, and three event sets - `*_lock_req`, `*_lock_acq`, `*_unlock`.
It keeps one variable, `LOCKHOLDER`.

- On a **request** event: add a horizontal edge marking the thread **blocked**, and a vertical
  edge from that thread to the current `LOCKHOLDER`.
- On an **acquire** event: add a vertical edge from `LOCKHOLDER` to this thread, a horizontal
  edge marking it **running**, and set `LOCKHOLDER` to this thread.
- On an **unlock** event: set `LOCKHOLDER` to this thread.

The graph is two-dimensional and sparse, like Giraldeau's: horizontal edges are a thread's
state over time, vertical edges are blocking dependencies between threads. The critical path is
then extracted exactly as in Giraldeau - recursively replacing a thread's waiting edges with
the edges of the thread that woke it.

> Note: the unlock branch setting `LOCKHOLDER` to the unlocking thread reads oddly - you would
> expect it to clear the holder. Take the algorithm as indicative; the paper is 6 pages and
> does not discuss it.

---

## 8. Visualisation (Trace Compass plugins)

Four views: **wait-block**, **timeline**, **flame graph**, **critical flow**.

- **Wait-block timeline** - shows threads blocking each other; when one enters the critical
  section the others are blocked until the mutex frees.
- **Flame graph** - each entry aggregates calls to a function at one call-stack depth with the
  same caller. In their 3-thread example, thread 15122 takes the mutex first, 15124 and 15123
  follow.
- **Critical flow** - execution dependencies between the interacting threads only, with
  unrelated activity removed. Shows blocking and preemption caused by thread priorities around
  taking and releasing a lock.

---

## 9. Evaluation

**Overhead**

| Level | Cost |
|---|---|
| User-space tracing (lock events only) | **< 0.7%** of execution time |
| Per kernel event | up to **10 ns** |
| **All** kernel events enabled | up to **25%** |
| **Minimal** kernel set (their method: scheduling, syscalls incl. futex, interrupt, timer) | **7%** |

The paper's headline is the **7%** figure for doing lock contention analysis.

**Analysis time.** Offline. The slow part is converting events to state values. Three cases,
fastest to slowest: read events only < read + analyse + keep states in memory < build the full
state database and write it to disk.

**Use case: Apache.** Apache uses worker threads that supposedly avoid communication, so
contention should not happen - yet extra latency appeared under concurrent requests. Apache
uses **filelock**, implemented in **user space**, which kernel-only analysis cannot see. With
the multi-level method they traced it to **OPcache**: processes must wait to write into the
shared compiled-script cache, so one process holds up others during concurrent script
execution.

That use case is the argument for the whole paper: the lock was invisible from the kernel.

---

## 10. What this means for our work — read before citing

**The honest reading: this paper argues against using kernel traces alone for lock contention.**

Our blueprints 4, 6 and 8 cite it as method support for "lock waits can be reconstructed from
traces". That is true, but incomplete. The paper's own contribution is that Giraldeau's
kernel-only method **does not reveal user-space lock behaviour**, and their fix is user-space
tracepoints.

| The paper uses | We have | Consequence |
|---|---|---|
| `pthread_mutex_lock_req` / `_acq` / `_unlock` via `LD_PRELOAD` | nothing at user level | We cannot separate **waiting for a lock** from **holding it** |
| `pthread_spin_*` | nothing | Spinlocks are invisible to us, as the paper says |
| kernel `syscall_entry_futex` | **yes** | We see that a thread entered futex, not what it was waiting on |

So we can see **that** a thread is in futex. We **cannot** see the req/acq split, which is what
turns "futex activity" into "this thread waited N ms for a lock held by that thread".

**What we can safely cite it for:**
- lock contention is diagnosable from execution traces without source code;
- the two-dimensional graph (horizontal = state, vertical = dependency) extends beyond kernel
  events;
- overhead of trace-based lock analysis is about 7% with a minimal kernel event set;
- **user-space locks are invisible to kernel-only tracing** - this is the citation for a
  limitation in *our* blueprints, not a capability.

**What we must not claim:** that we perform lock contention analysis in their sense. We detect
a *change in futex rate against a baseline*, which is a much weaker signal, and blueprint 6
already says so.

**A useful connection to blueprint 6.** This paper says uncontended locks never enter the
kernel, so futex means contention. Blueprint 6's measured finding is that on the **JVM**,
parking is the normal idle path, so futex is high at baseline with no contention at all. Both
are true - the first for C/C++ native code, which is what this paper tests, the second for
managed runtimes. Our blueprint should cite this paper for the general rule and then state the
JVM exception as our own measurement.

---

## 11. Safe claims

- Lock contention can be analysed from execution traces alone, without source code,
  recompilation, or prior knowledge of the bug.
- Kernel-only critical-path analysis cannot see locks implemented in user space, such as
  spinlocks and Apache's filelock.
- Adding `LD_PRELOAD` tracepoints on pthreads (`req` / `acq` / `unlock`) makes the wait for a
  lock and the critical section separately measurable.
- Overhead: under 0.7% for the user-space lock events; about 7% total with a minimal kernel
  event set; up to 25% with all kernel events enabled; roughly 10 ns per kernel event.
- Perf-style counters give total wait time but cannot attribute it to a thread or a specific
  mutex instance.
- Applied to Apache, the method located contention on the shared OPcache.

## 12. Do NOT claim

- That kernel traces alone are sufficient for lock contention analysis. The paper argues the
  opposite.
- That we reproduce this method. We have no user-space lock tracepoints.
- Any accuracy or detection-rate figure. The paper reports none - it is a tooling and
  visualisation paper with one use case.
- That the 7% overhead applies to our event set. Theirs is scheduling + syscalls + interrupt +
  timer; ours differs.

## 13. Reusable ideas

- **Instrument the request and the acquisition separately.** One event tells you a lock was
  taken; two tell you how long the wait was.
- **`LD_PRELOAD` wrappers** for non-invasive user-space instrumentation of a pre-compiled
  library, in any language.
- **One graph across levels.** Keep the same horizontal/vertical edge model and just feed it
  events from wherever they come.
- **Trace Compass state system** (attribute tree + state history) as a way to store and query
  "what was this thread doing at time T".
- **Report overhead for the minimal event set**, not just for everything enabled. 7% versus
  25% is the difference between usable and not.
