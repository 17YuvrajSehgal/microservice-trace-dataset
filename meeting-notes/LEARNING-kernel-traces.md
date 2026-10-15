# Learning kernel traces, starting from zero

For Task 2 of `ACTIONS-30-09-2026.md` — "understand the problem yourself". Uses the trace
already on your PC:

```
C:\traces\svc_cpu_cap_aggressive_steady_r1\kernel\kernel
```

`carts` capped at 0.2 CPUs. Fault window **11:19:46 → 11:21:46** on your clock (15:19:46 UTC).

---

## 1. What a kernel trace actually is

Not metrics. Not samples. **Every single thing the kernel did, in order, with a timestamp.**

This trace: 404 distinct event types, ~1.3 million events *per second*, 243 seconds.

| event | count here | what it records |
|---|---|---|
| `sched_switch` | 16.8M | a CPU stopped running one thread and started another |
| `power_cpu_idle` | 13.9M | a CPU went idle / woke up |
| `sched_stat_runtime` | 12.9M | how many nanoseconds a thread just ran for |
| `sched_waking` / `sched_wakeup` | 9.2M each | a thread became runnable again |
| `syscall_entry_*` / `syscall_exit_*` | many | a thread entered / left the kernel |
| `irq_softirq_entry` | 4.0M | deferred interrupt work (network, timers) |

You will never read these one at a time. You aggregate them, or you let Trace Compass draw them.

---

## 2. The one mental model

**Every latency problem is: where did the time go?**

At any instant a thread is in exactly one of three states:

| state | meaning | cause of latency |
|---|---|---|
| **running** | on a CPU, doing work | nothing wrong |
| **runnable** | ready, wants a CPU, isn't getting one | **contention or throttling** |
| **blocked** | waiting for something else | I/O, lock, network, another service |

That's it. That's system-level latency analysis. Every problem in the catalog is a specific
answer to "which of the three, and why".

- `svc_cpu_cap` (your trace) → **runnable**. The kernel refuses to schedule it.
- `noisy_neighbor` → **runnable**. Someone else took the CPU.
- `slow_db` → **blocked**. Waiting on a reply that is slow.
- `deadlock` → **blocked** forever, in `futex`.
- `anomaly_net` → **blocked** on the network.

**The kernel field that tells you which: `prev_state` on `sched_switch`.**

When a thread stops running, `sched_switch` records *why*:

| `prev_state` | meaning |
|---|---|
| `0` | **preempted — still wants the CPU** → runnable |
| `1` | interruptible sleep → blocked, waiting |
| `2` | uninterruptible sleep → blocked, usually disk I/O |
| `128`, `256`… | exiting / dead |

**Verify this yourself rather than trusting the table** — Exercise 3 below.

---

## 3. Exercises, in order

Each one has a question. Write the answer down. If you cannot answer it from the trace, that
is the thing to dig into.

### Exercise 1 — Find the fault without being told

Zoom the **bottom histogram** across the whole trace.

> **Q: Can you see where the fault is, from event density alone?**

Already measured: 1,329,154 events/s before → 323,829 during → 1,488,309 after. A 4× drop,
within one second of injection.

> **Q: Only ONE container was capped. Why did the WHOLE host's event rate fall 4×?**

This one matters more than the first. The answer tells you why the histogram can find *when*
but never *where*.

### Exercise 2 — Watch a thread change state

Open **Control Flow**. Zoom to **11:19:40 → 11:22:00**.

Colours: green = running, **yellow = runnable (wants CPU, denied)**, blue = blocked,
grey = not alive.

> **Q: Which threads turn yellow in the window? Which turn blue?**
> **Q: What is the difference between a yellow thread and a blue thread, in one sentence?**

Yellow is the culprit (`carts`, throttled). Blue is the victim (`front-end`, waiting on carts).
If you can see that split on screen, you have understood this fault.

### Exercise 3 — Prove it with numbers, not colours

Select the fault window, open **Statistics**. Then do the same for an equal window before it.

> **Q: How does the count of `sched_switch` with `prev_state=0` change for carts?**

Use the event table's `<srch>` filter on the Contents column to isolate `prev_state=0`.

This is the step that turns "the picture looks different" into a measurement a blueprint can
cite. **A blueprint claim needs a number and a ratio, not a screenshot.**

### Exercise 4 — Find the container without being told

Kernel traces have **no service names**. Only numeric `pid_ns` — one per container.

Click any thread → **Properties** → find `context.pid_ns`.

> **Q: How many distinct pid_ns are in this trace?**
> **Q: Which one is carts, and how did you decide — without opening ground_truth.json?**

This is the hardest part of the whole project and the reason the agent scored 1/60 on this
family. "Something is wrong" is easy. "It is *this* container" is not.

### Exercise 5 — Tell it apart from its look-alikes

> **Q: If this were `noisy_neighbor` instead, what would look DIFFERENT?**

Both produce yellow threads. The difference: under throttling the host has idle CPU
(`power_cpu_idle` stays high) while carts still cannot run. Under contention the CPUs are
genuinely busy.

> **Q: What one measurement separates them?**

**That measurement is the discriminator, and a discriminator is what a blueprint is made of.**

---

## 4. When you are done

Naser's bar: explain the problem and its kernel signature **without reading from a document**.

Concretely, be able to answer:

1. What does the kernel do when a cgroup exceeds its CPU quota?
2. Which events show it, and why those and not others?
3. What number distinguishes it from CPU contention? From a slow dependency?
4. Why can't the global event-rate histogram identify the culprit?

---

## 5. Where to go for answers

- **Ask AI to teach you** — explicitly endorsed: "ask AI to teach it to you, to teach the
  problem and how to use kernel-level data." Using it to *learn* is the point. Using it to
  *skip* learning is what was criticised.
- **`meta/` in your trace** — 1,325 cgroup snapshots, ~12s apart, with `cpu.max` and throttle
  counters per container. Independent confirmation of what the kernel view shows.
- **The existing blueprint** — `blueprints/problems/service-cpu-throttle/` — is what you are
  going to rewrite. Read it *after* the exercises, not before, then judge whether it says what
  you found.
