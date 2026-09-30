# Paper Context: Fuss, Futexes and Furwocks — Fast Userlevel Locking in Linux (OLS 2002)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is the **origin paper for the futex**, cited by blueprints 4 and 6. It is the source of
> the single most important sentence for our lock work: **an uncontended lock never enters the
> kernel.** Section 7 explains why that sentence is true for C/C++ and misleading for the JVM.

---

## 1. Bibliographic info

- **Title:** Fuss, Futexes and Furwocks: Fast Userlevel Locking in Linux
- **Authors:** Hubertus Franke (IBM T. J. Watson Research Center), Rusty Russell (IBM Linux
  Technology Center), Matthew Kirkwood
- **Venue:** Ottawa Linux Symposium (OLS) 2002, p. 479 onward
- **Length:** 19 pages
- **Status at the time:** futexes had been integrated into Linux kernel **2.5.7**

```bibtex
@inproceedings{franke2002fuss,
  title     = {Fuss, Futexes and Furwocks: Fast Userlevel Locking in Linux},
  author    = {Franke, Hubertus and Russell, Rusty and Kirkwood, Matthew},
  booktitle = {Proceedings of the Ottawa Linux Symposium}, year = {2002}
}
```

---

## 2. One-paragraph summary

Before futexes, every lock operation on Linux was a **system call** - System V semaphores,
`flock()`, and so on. When a lock is rarely contended, that system call is pure overhead. A
futex moves the lock state into **shared memory**, where processes change it with **atomic
operations**. The kernel is called **only when there is contention**, to queue the waiter and
schedule it. The paper traces how the design arrived there, benchmarks it synthetically and
against real databases, and sketches future directions.

---

## 3. Why it exists

- Linux 2.4 made the OS viable for enterprise workloads - SAP, WebSphere, Oracle, DB2.
- Those applications are **multi-process and multi-threaded**: threads exploit SMP hardware,
  separate processes give fault tolerance (one process aborting does not take the suite down).
- Separate subsystems still have to share state. Their example: **databases keep shared I/O
  buffers in user space**, accessed concurrently by engines and prefetchers.
- Traditional UNIX synchronisation (System V IPC, `flock()`) exposes an opaque handle to a
  **kernel object**. Every access is a system call.
- **"When locks have low contention rates, the system call can constitute a significant
  overhead."**

---

## 4. The mechanism

A user-level lock lives in a **shared memory region** and is changed with **atomic
operations**.

- **Uncontended acquire and release: entirely in user space. No system call.**
- **Contended: the kernel is invoked** to queue the waiter and to schedule.

Two parts ship: a **user library** and a **kernel service** (in 2.5.7).

Synchronisation needs two things, and the paper is careful to name both:
1. **Shared state** saying whether a resource is free or busy.
2. **A way to wait** for it - either **busy-waiting**, or an explicit/implicit call to the
   scheduler.

They also distinguish **exclusive** locks (one holder) from **shared** locks (multiple readers,
single writer).

They note the idea is not new and credit earlier work, including a study of locking's impact on
**JVM performance**.

---

## 5. What is evaluated

Benchmarks are **synthetic** plus **adaptations to existing databases**. The claim being tested
is throughput and overhead of the locking mechanism itself, on 2002-era hardware.

**No numbers from this paper should be carried forward.** They are 23 years old and about a
kernel version that no longer exists. Cite the *mechanism*, not the measurements.

---

## 6. The one sentence that matters for us

> **Kernel involvement is only necessary when there is contention on a lock.**

Read as a trace signature: **a `futex` syscall in the trace means someone waited.** An
uncontended lock leaves no kernel trace at all. That is what makes futex event rate a
contention signal in the first place, and it is the whole basis of blueprint 6's original
premise and blueprint 4's "FUTEX_WAIT with no FUTEX_WAKE" rule.

---

## 7. What this means for our work — and the limit

**What it supports.**

- Blueprint 4 (`deadlock`): a deadlock is `FUTEX_WAIT` with no matching `FUTEX_WAKE`. The
  waiting is what enters the kernel; the never-waking is what makes it a deadlock.
- Blueprint 6 (`lock_contention`): futex syscalls happen only under contention, so the futex
  rate is a contention signal **in general**.

**Where "in general" does the work.** This paper describes **native locking in C/C++**, which
is what its benchmarks use. On a **managed runtime it does not hold**:

- The JVM's `LockSupport.park()` is implemented on **pthreads**, which go through
  `pthread_cond`, which calls `futex_wait`.
- So **idle thread pools, timed waits and executors all generate futex traffic with no lock
  contention whatsoever.**

That is why blueprint 6's discriminator is a **change against the service's own baseline**
plus **many waiters on one futex address**, not the raw futex share. Our own measurement found
the JVM baseline is already futex-heavy.

**How to cite the pair correctly:**

| Claim | Citation |
|---|---|
| futex syscalls occur only under contention | **this paper** (Franke et al. 2002) |
| on the JVM, parking is the normal idle path, so this does not hold | Hazelcast blog + OpenJDK JDK-6900441 + kernel futex-requeue-pi docs, **and our own measurement** |

The reference pack already states this correctly: *"No single source says 'JVM services are
futex-heavy by default'; you build it from the chain JVM park → pthread_cond → futex. Present
it as your own observation."* Reading this paper confirms that framing - it is the C/C++ half
of the chain, and it does not claim more than that.

**A detail worth keeping.** The paper names **busy-waiting** as one of the two legitimate ways
to wait. Busy-waiting is invisible in a kernel trace - the same blind spot Giraldeau 2016
reports for OpenMPI barriers and Rezazadeh 2020 reports for spinlocks. Three of our sources
independently flag this, and it belongs in our threats-to-validity as a known limit of the
kernel view, not as a surprise.

---

## 8. Safe claims

- Before futexes, every lock operation on Linux required a system call (System V IPC,
  `flock()`), which is significant overhead when contention is low.
- A futex keeps lock state in shared memory, changed by atomic operations.
- **The kernel is involved only when there is contention**, to queue waiters and schedule.
- Therefore an uncontended lock acquire/release leaves **no kernel trace**.
- Futexes were integrated into the Linux kernel at version **2.5.7**.
- Synchronisation requires shared state plus a way to wait; waiting can be busy-waiting or a
  call to the scheduler.
- The motivating workloads are enterprise multi-process/multi-threaded applications such as
  databases with shared user-space I/O buffers.

## 9. Do NOT claim

- Any performance number from this paper as current. The benchmarks are from 2002 on kernel
  2.5.
- That futex activity implies contention **on the JVM**. Parking is the normal idle path there.
- That this paper discusses Java. It cites one prior study of locking and JVM performance; it
  does not analyse the JVM itself.
- That the futex interface described here is today's. The paper's own closing section is about
  future directions, and the API has changed substantially since.

## 10. Reusable ideas

- **Put the fast path in user space and call the kernel only for the slow path.** The reason
  the kernel trace is a *contention* signal rather than a *usage* signal is this design choice.
- **Name both halves of synchronisation** - the state and the waiting. Our discriminators tend
  to look only at the waiting; the state is invisible to us, which is worth saying.
- **Busy-waiting is a legitimate design, and it is invisible from the kernel.** Any blueprint
  that concludes "no futex activity means no contention" is wrong for spinning code.
