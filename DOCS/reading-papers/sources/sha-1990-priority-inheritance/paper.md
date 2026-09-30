# Paper Context: Priority Inheritance Protocols — An Approach to Real-Time Synchronization (IEEE TC 1990)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is the **definitional source for priority inversion**, cited by blueprint 8. It is the
> reason our fault should **not** be called classic priority inversion. Read §7 - the mismatch
> between this paper's model and Linux CFS is the whole point of citing it.

---

## 1. Bibliographic info

- **Title:** Priority Inheritance Protocols: An Approach to Real-Time Synchronization
- **Authors:** Lui Sha (Software Engineering Institute + CS Dept, Carnegie Mellon),
  Ragunathan Rajkumar (IBM T. J. Watson), John P. Lehoczky (Statistics, Carnegie Mellon)
- **Venue:** IEEE Transactions on Computers, vol. 39, no. 9, September 1990, pp. 1175-1185
- **DOI:** 10.1109/12.57058
- **Received** Dec 1987, revised May 1988
- **Funding:** Office of Naval Research, Naval Ocean Systems Center, IBM Federal Systems

```bibtex
@article{sha1990priority,
  title   = {Priority Inheritance Protocols: An Approach to Real-Time Synchronization},
  author  = {Sha, Lui and Rajkumar, Ragunathan and Lehoczky, John P.},
  journal = {IEEE Transactions on Computers},
  volume  = {39}, number = {9}, pages = {1175--1185}, year = {1990},
  doi     = {10.1109/12.57058}
}
```

---

## 2. One-paragraph summary

In a real-time system, a high-priority job should run as soon as it is ready. **Priority
inversion** breaks that: a high-priority job gets blocked by a low-priority one that holds a
lock it needs. Worse, a *medium*-priority job can then preempt the lock holder, so the
high-priority job waits for an **indefinite** time. The paper defines the problem and gives two
protocols that fix it. **Basic priority inheritance**: while a low-priority job holds a lock a
high-priority job wants, it temporarily inherits the higher priority, so nothing in between can
preempt it. **Priority ceiling**: a stronger version that bounds the worst-case blocking to
**one critical section of one lower-priority task**, and additionally **prevents deadlock**.
They also derive conditions for when a set of periodic tasks using the protocol is schedulable.

---

## 3. The problem, in the paper's own terms

- **Priority inversion** = a higher-priority job is blocked by lower-priority jobs.
- Some blocking is unavoidable: if a low-priority job already holds shared data, the
  high-priority job must wait for it to finish. That is correct behaviour.
- **Uncontrolled** priority inversion is the bug: the blocking becomes **indefinite**, because
  jobs of intermediate priority can preempt the lock holder while the high-priority job waits.
- Consequence: deadlines are missed **even at low resource utilisation**.
- **Schedulability** = the utilisation level reachable before a deadline is missed. Minimising
  blocking is how you keep it high.

They are explicit that this arises from a *direct application* of ordinary synchronisation -
semaphores, monitors, locks, the Ada rendezvous. The primitives are necessary; using them
naively is what causes the problem.

**Context for why this mattered in 1990:** Ada was mandated by the US DoD for real-time
systems and supports priority-driven preemptive scheduling, so the problem was not academic.

---

## 4. The two protocols

### Basic priority inheritance

When a job blocks a higher-priority job, it **inherits** that higher priority for the duration
it holds the resource. Medium-priority jobs can then no longer preempt it, so the blocking is
bounded rather than indefinite.

### Priority ceiling protocol

An enhanced version. Two stated properties:

1. **Worst-case blocking is at most the duration of a single critical section of a single
   lower-priority task.**
2. **It prevents deadlock.**

Both protocols are defined for a **uniprocessor** and in terms of **binary semaphores**.

They then derive sufficient conditions for schedulability of periodic tasks under the protocol,
in combination with rate-monotonic scheduling.

---

## 5. Scope and assumptions — these matter

| Assumption | Value |
|---|---|
| Processors | **uniprocessor** |
| Synchronisation | **binary semaphores** |
| Scheduling | **priority-driven preemptive**, strict priorities |
| Task model | **periodic** tasks with hard deadlines |
| Analysis pairs with | rate-monotonic scheduling |

The model is **strict priority**: a higher-priority job runs instead of a lower one, always.
That is the property the whole argument rests on.

---

## 6. What kind of paper this is

- **Theory.** Formal definitions, protocol specifications, proofs of properties, and derived
  schedulability conditions.
- **No implementation, no experiment, no measurement.** There are no runtime numbers anywhere.
- It is the paper that gave the field its vocabulary: *priority inversion*, *priority
  inheritance*, *priority ceiling*.

---

## 7. What this means for our work — the key mismatch

**Our fault is not what this paper describes, and blueprint 8 is right to say so.**

| Sha et al. 1990 | Linux CFS (our setting) |
|---|---|
| **Strict priorities** - a higher-priority job always runs instead of a lower one | **Weights.** `nice` changes the *share* of CPU, not the order |
| A blocked high-priority job waits **indefinitely** | The low-`nice` holder **still runs**, just less often |
| Uniprocessor, binary semaphores, periodic hard-deadline tasks | multicore, futex, containerised services with no deadlines |
| Fixed by priority inheritance in the protocol | Linux has priority inheritance only for **PI futexes** and **RT scheduling**, not for normal CFS `nice` values |

So the fault we inject - a high-`nice` task holding a lock a normal task needs - produces
**slower** progress, not **indefinite** blocking. The reference pack's suggested names,
**"weighted lock-holder starvation"** or **"nice-induced inversion"**, are the accurate ones.

**Why cite it at all, then?** Because it defines the term we are deliberately not using. The
citation's job is to mark the boundary: this is the classic phenomenon, ours is the weaker
CFS analogue. That is an honest use and it belongs in the blueprint's applicability field.

**The second reason it matters.** Sha et al. show priority inheritance *solves* the problem.
Linux does not apply it to CFS `nice`, which is precisely **why our injected fault produces an
observable effect at all**. If CFS inherited weights the way PI futexes inherit priority, the
fault would self-correct and there would be nothing to detect. That is worth one sentence in
the blueprint.

**A third connection, easy to miss.** The priority ceiling protocol **prevents deadlock** as a
side effect. That links blueprint 8 to blueprint 4: the same discipline that bounds inversion
also removes lock-ordering deadlocks. Both of our faults exist because neither mechanism is
present in an ordinary Linux container.

---

## 8. Safe claims

- Priority inversion is a higher-priority job being blocked by lower-priority jobs.
- A direct application of semaphores, monitors, locks or the Ada rendezvous can cause
  **uncontrolled** priority inversion - blocking for an indefinite period.
- Prolonged blocking causes missed deadlines **even at low resource utilisation**.
- Basic priority inheritance: a job holding a resource inherits the priority of the highest
  job it blocks.
- The priority ceiling protocol bounds worst-case blocking to **one critical section of one
  lower-priority task** and **prevents deadlock**.
- Both are defined for a **uniprocessor** with **binary semaphores** and strict priorities.
- The paper derives sufficient schedulability conditions for periodic tasks using the protocol.

## 9. Do NOT claim

- That our `priority_inversion` fault is classic priority inversion. Under CFS, `nice` is a
  weight, not a priority, and the low-weight holder keeps running.
- Any measurement, overhead, or detection figure. The paper is entirely theoretical.
- That Linux implements these protocols generally. It applies priority inheritance only to PI
  futexes and RT scheduling, not to CFS `nice`.
- That the results extend to multiprocessors as stated. The model is explicitly uniprocessor.

## 10. Reusable ideas

- **Separate necessary blocking from unbounded blocking.** Waiting for a lock holder is
  correct; waiting behind an unrelated medium-priority job is the bug. A good discriminator
  distinguishes the two.
- **Bound the worst case, not the average.** The ceiling protocol's value is a guarantee on the
  worst case - which is what matters when the failure is a missed deadline.
- **Name the phenomenon precisely.** This paper's vocabulary survived 35 years because the
  definitions are tight. Our fault deserves its own accurate name rather than borrowing this
  one.
