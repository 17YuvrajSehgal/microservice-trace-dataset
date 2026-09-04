# A1 — Why a request gets slow, and which of it kernel traces can see

Written 4 Sept 2026 for the 2 Sept meeting task A1.

Naser asked for 5–10 reasons for latency, single and combined, and for each: can kernel traces
see it? He said to use AI for the list because it is textbook knowledge.

The list below is textbook. **The "can we see it" column is not** — it comes from our own 109
runs, and each answer points at the finding that measured it. Where we have not measured, it
says so.

---

## What our traces actually record

Every run records:

- **every system call**, entry and exit
- `sched_*` — the scheduler
- `block_*` — disk
- `net_* netif_* napi_* skb_* sock_* tcp_* udp_*` — network
- `irq_* softirq_*` — interrupts

Deliberately **not** recorded (too big; `KERNEL_MEM=1` turns them on):

- `kmem_* mm_* vmscan_* writeback_* compaction_* migrate_*` — memory

Not recorded: `lock_*` kernel lock tracepoints, `power_*` CPU frequency.

`lock_*` usually needs a kernel built with lock debugging turned on. **We have not checked
whether our VM has them** — the VM is stopped. Worth one `lttng list --kernel` before planning
around it.

Checked on a real trace, not from the config file.

---

## The 11 causes

| # | Cause | Can kernel traces see it? | Evidence |
|---|---|---|---|
| 1 | Waiting for a free CPU | **Yes** | F3, F6, F7 |
| 2 | Waiting for disk | **Yes** | F18, F20 |
| 3 | Packets lost on the network | **Yes** | F14, F15, F17 |
| 4 | Waiting on a slow downstream service | **Yes** | F16 |
| 5 | Container hit its memory cap | **Yes** | F20 |
| 6 | Interrupt load | **Yes** | F20 |
| 7 | Lock contention | **Partly** | F21, F22 |
| 8 | Host running low on memory | **One app only** | F20 |
| 9 | A service stops answering | **No** | F11–F13 |
| 10 | Work queues up behind a stopped consumer | **No** | F19 |
| 11 | Slow CPU clock, priority problems | **Not tested** | — |

---

## The ones we can do

### 1. Waiting for a free CPU

A thread is ready but no CPU is free. Three different reasons, and they need different fixes:

| Reason | What it looks like |
|---|---|
| The whole machine is out of CPU | host use 99% |
| Another workload is stealing CPU | a new process takes 1–2 cores |
| The container hit its own CPU cap | the service's CPU **falls** |

We have a blueprint for each. All three score well.

**The lesson worth repeating (F3):** we first decided this on "how long threads wait for CPU".
That goes up for all three, and for a healthy machine under load. The signal that works is
**how much CPU each process actually used**.

### 2. Waiting for disk

Blueprint built. Decides on how many disk requests arrive, not how slow the device is (F18).

Interrupt time agrees, from a different part of the kernel: **12.9–14.3x** on Sock Shop,
**5.8–6.7x** on Train Ticket (F20). Two independent signals for the same fault.

### 3. Packets lost on the network

Blueprint built. Decides on **where** the packet was lost, not how many were lost (F17).

- a real network fault drops packets in the **send queue**
- an overloaded container drops them in its **receive buffer**

This matters because a container at its memory cap re-sends packets **harder than any network
fault** — 95%. We nearly shipped a rule that called it a network problem.

### 4. Waiting on a slow downstream service

Blueprint built. The service sits inside a socket read for a long time, while its CPU wait
stays flat (F16).

### 5. Container hit its memory cap — NEW

**This was filed as impossible without logs. It is not.**

Interrupt time separates it on both apps: **6.2x** on Sock Shop, **3.2–4.3x** on Train Ticket,
against a ceiling of **1.8x** everywhere else (F20).

Honest caveat: the model already gets this fault right 2 times in 3 without help. So it is a
win for our rule engine, not a case where a blueprint beats the agent.

### 6. Interrupt load

Not a fault we inject, but a real signal. It is how we see causes 2 and 5.

---

## The partly-there one

### 7. Lock contention

Naser asked for this by name. Where we stand:

**Good news.** Total lock wait does not move for **anything** we inject — 1.38x on Sock Shop,
1.11x on Train Ticket, across all families (F22). So we already have the negative control
before writing the blueprint. That is the opposite of the F17 mistake.

**The trap, already hit.** Total lock wait was **408 seconds per second** of real time. Java
alone waited 6,684 s across 22,036 calls, about 300 ms each. That is thread pools **parked
waiting for work**, not contention. Idle parking drowns the total.

**So the blueprint must key on the shape, not the total:**

| | Wait count | Each wait |
|---|---|---|
| Idle parking | few | long (~300 ms) |
| Real contention | many | short |

**What we can see today:** user-level locks, through the `futex` system call. That is what our
109 runs contain.

**What we have not checked:** kernel-level locks. `lock_*` tracepoints are not in our profile,
and they usually need a kernel built with lock debugging. Whether our VM offers them at all is
**unverified** — one `lttng list --kernel` on the VM answers it.

Naser asked for *kernel* lock contention. So run that check first. If the tracepoints are not
there, we either rebuild the kernel or write the blueprint for user-level locks and say so.

---

## The ones that only work on one app

### 8. Host running low on memory

Interrupt time looked like a fix. On Sock Shop, host memory stress gives 2.4–3.5x, clear of
noisy neighbour at 1.2–1.4x.

**It does not survive the second app.** On Train Ticket it is 1.0–1.2x, and noisy neighbour is
0.8–1.0x. Both sit inside the healthy range.

So our 3 remaining wrong answers — memory faults called noisy neighbour — are still open.

Recording the failure on purpose: with one app we would have called this fixed.

**Untried option:** turn on `KERNEL_MEM=1` and re-collect. Then we would see reclaim and paging
directly, instead of guessing from interrupts.

---

## The ones we proved we cannot do

### 9. A service stops answering

Six measured attempts, all failed (F11–F13): CPU per process, threads that stop running,
threads that stop being woken, slow endpoints, packet loss, queue drops.

A paused container does not lose packets or go quiet in the scheduler. It stops **answering**.
That needs request traces or logs.

### 10. Work queues up behind a stopped consumer

Same shape as number 9 (F19). Both are defined by something **not happening**.

---

## Not tested

### 11. Slow CPU clock, priority problems

CPU frequency scaling, priority inversion, NUMA effects. We record no `power_*` events, so we
cannot see frequency at all today. Nobody has tried the others.

Application-level causes — garbage collection pauses, a bad algorithm, retry storms — are also
untested and mostly not visible below the application.

---

## Combined causes

Naser asked for these too. Every one below is measured, and each is a case where one fault
**looks like** another.

| Combination | What happens | Why it matters |
|---|---|---|
| Memory cap → network | Container cannot read its sockets fast enough, so packets pile up and drop. Re-sends hit **95%** | Beats every real network fault. Nearly broke our network rule (F17) |
| CPU cap → locks | A throttled thread is frozen for the rest of its 100 ms slice. Anything waiting on it inherits that wait | Lock wait p95 lands on ~100 ms, the CFS quota period. Not a lock bug (F21) |
| Memory stress → CPU | The stress tool itself eats a core | This is why memory faults get called noisy neighbour. Our 3 wrong answers |
| Memory pressure → disk | Reclaim and paging drive disk work | Both raise interrupt time. Order is disk > memory cap > rest (F20) |
| Disk → downstream | A slow disk under a database makes its callers wait | A caller cannot tell disk from network from a slow query |

**The pattern.** In every case the second-order effect is **larger** than the first-order one.
That is why a single signal cannot name a fault, and why every new signal has to be checked
against *all* families, not just its own.

---

## What to do next

Ranked by value:

1. **Check the VM for `lock_*` tracepoints** (`lttng list --kernel`). One command, and it
   decides whether B1 is about kernel locks or user-level locks.
2. **Build the lock blueprint (B1).** Negative control already in hand. Must key on the shape,
   never the total.
3. **Build the container-memory-cap blueprint (B4).** Signal measured on both apps.
4. **Re-collect with `KERNEL_MEM=1`** on a few runs. This is the only open route to host
   memory faults, and would settle our last 3 wrong answers.
5. **Drop causes 9 and 10 from scope.** Six and one measured attempts. Naser agreed: "if that
   doesn't work, forget about it."
6. **Cause 11 needs new events** before it can even be tried.

---

## How this changes the blueprint list

| | Before | Now |
|---|---|---|
| Built | 6 | 6 |
| Newly buildable | — | **2** (locks, container memory cap) |
| Proved impossible | 2 | 2 |
| Blocked on other data | 3 | **2** |
| Never tried | — | 1 |
