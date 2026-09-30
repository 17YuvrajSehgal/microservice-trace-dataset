# Paper Context: Understanding Real-World Concurrency Bugs in Go (ASPLOS 2019)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Paired with Lu et al. 2008 in blueprint 4, and it is the **Go half** of that pairing — which
> matters because Sock Shop has Go services. Its headline result is counter-intuitive and
> directly relevant: **more blocking bugs come from message passing than from shared memory.**
> §9 explains why that changes what a deadlock looks like in a kernel trace.

---

## 1. Bibliographic info

- **Title:** Understanding Real-World Concurrency Bugs in Go
- **Authors:** Tengfei Tu (BUPT / Penn State), Xiaoyu Liu (Purdue), Linhai Song (Penn State),
  Yiying Zhang (Purdue). Tu and Liu contributed equally.
- **Venue:** ASPLOS '19, 13-17 April 2019, Providence, RI. 14 pages
- **DOI:** 10.1145/3297858.3304069

```bibtex
@inproceedings{tu2019understanding,
  title     = {Understanding Real-World Concurrency Bugs in Go},
  author    = {Tu, Tengfei and Liu, Xiaoyu and Song, Linhai and Zhang, Yiying},
  booktitle = {ASPLOS '19}, year = {2019},
  doi       = {10.1145/3297858.3304069}
}
```

---

## 2. One-paragraph summary

Go was designed to make concurrent programming safer, and it pushes **message passing**
(channels) over shared memory on the belief that explicit messaging is less error-prone. This
paper is the first systematic test of that belief. The authors studied **171 concurrency bugs**
across **six widely used Go systems** — Docker, Kubernetes, etcd, CockroachDB, gRPC-Go and
BoltDB. **More than half are caused by Go-specific problems**, and the headline finding
contradicts the design premise: **more blocking bugs come from misusing message passing than
from misusing shared memory.** Goroutines are also shorter-lived and created far more often
than C threads.

---

## 3. Method

Six applications, chosen for wide production use:

| Application | What it is |
|---|---|
| **Docker** | container system |
| **Kubernetes** | container orchestration |
| **etcd** | distributed key-value store |
| **CockroachDB** | distributed database |
| **gRPC-Go** | RPC library |
| **BoltDB** | key-value database |

Bugs were collected by searching commit logs for concurrency keywords — *race, deadlock,
synchronization, concurrency, lock, mutex, atomic, compete,* plus the Go-specific *context,
once,* and **goroutine leak**.

**171 bugs total.**

---

## 4. The two-dimensional taxonomy

This is the structure worth copying. They classify along **two independent axes**:

| Axis | Categories |
|---|---|
| **Cause** | misuse of **shared memory** vs misuse of **message passing** |
| **Behaviour** | **blocking** (one or more goroutines cannot proceed) vs **non-blocking** (all goroutines finish, but behaviour is wrong) |

**Their definition of blocking is deliberately broader than deadlock.** Deadlock requires a
*circular* wait across threads; blocking includes any situation where goroutines cannot
proceed. They explicitly want attention paid to **non-deadlock blocking bugs**.

### The breakdown (Table 5)

| | count |
|---|---|
| **Blocking bugs** | **85** |
| **Non-blocking bugs** | **86** |
| Caused by wrong **shared memory** protection | **105** |
| Caused by wrong **message passing** | **66** |

---

## 5. The nine observations

1. **Goroutines are shorter but created more frequently than C threads** — both statically and
   at runtime.
2. Traditional shared-memory synchronisation remains heavily used, **and** Go programmers use
   a significant amount of message-passing primitives.
3. **Contrary to the common belief that message passing is less error-prone, more blocking bugs
   were caused by wrong message passing than by wrong shared memory protection.**
   (Around **58%** of blocking bugs are caused by message passing.)
4. Most blocking bugs from shared-memory synchronisation have **the same causes and fixes as in
   traditional languages**. A few differ, because of Go's new implementation of existing
   primitives or its new programming style.
5. **All** blocking bugs caused by message passing relate to Go's new semantics such as
   channels. They are **difficult to detect**, especially when message passing is mixed with
   other synchronisation mechanisms.
6. Most blocking bugs — both kinds — **can be fixed with simple solutions**, and fixes correlate
   strongly with causes.
7. (on non-blocking bugs)
8. **Far fewer non-blocking bugs** come from message passing than from shared memory.
9. Traditional shared-memory synchronisation remains the larger source of non-blocking bugs.

---

## 6. The worked example

A blocking bug from **Kubernetes** (their Figure 1). `finishReq` creates a child goroutine with
an anonymous function to handle a request — "a common practice in Go" — and the child sends its
result back to the parent through a **channel**. The bug is fixed by changing the channel from
**unbuffered to buffered**, so the child can send without a waiting receiver.

Three Go-specific hazards they name: buffered vs unbuffered channels, the non-determinism of
waiting on multiple channel operations, and mixing message passing with other synchronisation.

---

## 7. Detector evaluation

They ran **two publicly available Go bug detectors**, including Go's built-in runtime deadlock
detector, against the collected bugs. The built-in detector's limits on **blocking** bugs are
discussed — the point being that Go's own tooling does not catch the message-passing blocking
bugs, which are the majority.

---

## 8. What kind of paper this is

- A **commit-log and bug-report study**, like Lu et al. 2008.
- It **does** add dynamic work that Lu does not: goroutine/thread creation counts, normalised
  execution time of goroutines vs threads in gRPC-Go, and reproduction experiments.
- **No kernel traces, no runtime signatures for diagnosis.** It characterises bugs; it does not
  detect them from telemetry.

---

## 9. What this means for our work

**This is the citation for why blueprint 4's deadlock signature may not hold on Go services.**
The reference pack already states the concern correctly:

> In Go, many blocking bugs come from channel misuse, not mutexes. A goroutine blocked on a
> channel parks in the Go runtime, so on the kernel side you may see *idle epoll/futex* threads,
> not one futex per blocked goroutine.

This paper supplies the evidence for the first half: **58% of blocking bugs are message
passing**, and **all** message-passing blocking bugs involve channels. The second half — what
that looks like in a kernel trace — is our inference, and should be labelled as ours.

**Why it matters concretely.** Sock Shop's `catalogue` and several other services are Go. Our
`deadlock` fault injects an **AB-BA mutex** deadlock in a Python container, which is the shape
Lu et al. describe for C/C++. If we ever inject a *Go-native* deadlock, this paper says the
realistic shape is **channel misuse**, and the kernel evidence would be different — goroutines
multiplexed onto fewer OS threads, blocking inside the runtime scheduler rather than one futex
wait per blocked unit of work.

**The taxonomy is worth borrowing.** Two independent axes — *cause* (shared memory vs message
passing) and *behaviour* (blocking vs non-blocking) — is a cleaner structure than a single list
of bug types. Our fault families could use the same treatment: what the fault *is* versus what
it *does to the system* are different questions, and our current family names conflate them.

**One finding that cuts against automated detection generally.** Observation 5: message-passing
blocking bugs are "difficult to detect especially when message passing operations are used
together with other synchronization mechanisms". Mixed mechanisms defeat single-signal
detection. That is the same lesson our own coverage sweep reached from a different direction.

---

## 10. Safe claims

- 171 real concurrency bugs from six widely used Go systems: Docker, Kubernetes, etcd,
  CockroachDB, gRPC-Go, BoltDB.
- **85 blocking, 86 non-blocking; 105 from shared memory misuse, 66 from message passing.**
- **More blocking bugs come from message passing than from shared memory** — around 58% —
  contradicting the belief that message passing is safer.
- **All** message-passing blocking bugs relate to Go-specific semantics such as channels.
- More than half of all 171 bugs are caused by non-traditional, Go-specific problems.
- Goroutines are shorter-lived and created more frequently than C threads.
- Most blocking bugs have simple fixes, strongly correlated with their causes.
- Blocking is defined more broadly than deadlock: deadlock needs a circular wait, blocking does
  not.
- Far fewer *non-blocking* bugs come from message passing than from shared memory.

## 11. Do NOT claim

- Any statement about what a Go deadlock looks like in a kernel trace. The paper has no runtime
  telemetry.
- That these are all concurrency bugs in those projects — they are keyword-selected from commit
  logs.
- That Go's built-in detectors handle these. The paper evaluates them and the message-passing
  blocking bugs are the hard case.
- That the finding generalises beyond Go. It is specifically about Go's concurrency model.

## 12. Reusable ideas

- **Classify on two axes, not one.** Cause and behaviour are independent, and the cross-product
  is where the interesting cells are.
- **Define your terms wider than the textbook when the data demands it.** Their "blocking"
  deliberately includes non-deadlock cases, because that is where the bugs actually were.
- **Test the language's own premise.** Go claims message passing is safer; they measured it and
  it is not. Worth doing to our own assumptions.
- **Search commit logs for language-specific keywords** — adding *goroutine leak*, *context* and
  *once* to the standard concurrency word list is what surfaced the Go-specific half.
