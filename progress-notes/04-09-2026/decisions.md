# 04-09-2026 — A1: the latency cause list

Task from the 2 Sept meeting. Naser asked for 5–10 causes of latency, single and combined, and
for each whether kernel traces can see it. He said to use AI for the list, since it is
textbook knowledge.

Output: `blueprints/docs/LATENCY-CAUSES.md`.

## The choice that shaped it

The list of causes is textbook, as asked. **The "can we see it" column is not.** Every answer
points at one of our own findings across 109 runs, and anything unmeasured says so.

Doing it the other way would have been faster and useless. We already know from F17 that a
signal which "should" work can lose to a fault nobody thought to test it against.

## Where we stand: 11 causes

| Can kernel traces see it | Count | Which |
|---|---|---|
| Yes | 6 | CPU wait (3 kinds), disk, network loss, downstream wait, container memory cap, interrupt load |
| Partly | 1 | lock contention |
| One app only | 1 | host memory pressure |
| Proved impossible | 2 | service stops answering, queue backlog |
| Never tried | 1 | CPU frequency, priority, NUMA |

## Two things the list changed

**Container memory cap moves from impossible to buildable.** It was filed Tier C, "needs logs,
OOM-kill is the tell". F20 shows interrupt time separates it on **both** apps — 6.2x on Sock
Shop, 3.2–4.3x on Train Ticket, against a ceiling of 1.8x. That is a blueprint we can write
now.

Caveat kept in the doc: the model already gets this fault right 2 times in 3 unaided. So it
helps the rule engine, not the with/without story.

**Lock contention is further along than expected, but aimed at the wrong locks.**

Good: total lock wait moves for nothing we inject (1.38x / 1.11x across all families, F22). The
negative control exists before the blueprint does — the reverse of the F17 mistake.

Bad: we only see **user-level** locks, via `futex`. Naser asked for **kernel** locks. `lock_*`
tracepoints are not in our profile and usually need a kernel built with lock debugging.

**Recorded as unverified rather than assumed.** The VM is stopped; one `lttng list --kernel`
settles it. That check is now step 1 of B1, because it decides what B1 even is.

## The trap already found, before writing anything

Total futex wait on the first probe was **408 seconds per second of wall clock**. Java alone
waited 6,684 s over 22,036 calls — about 300 ms each. That is thread pools **parked waiting for
work**, not contention.

Contention has the opposite shape: many waits, each short. So the lock blueprint must key on
the shape and never the total. Written into the doc so nobody rediscovers it.

## Combined causes

Naser asked for these as well, and they turned out to be the most useful section. All five are
measured, and every one is a case where a fault **looks like** a different fault:

- memory cap → 95% packet re-sends, harder than any real network fault (F17)
- CPU cap → lock waits landing on ~100 ms, which is the CFS quota period, not a lock bug (F21)
- memory stress → eats a core, so it reads as a noisy neighbour — our 3 wrong answers
- memory pressure → disk work, so both raise interrupt time (F20)
- slow disk under a database → its callers cannot tell disk from network from a slow query

**The pattern:** the knock-on effect is consistently **larger** than the direct one. That is
the argument for why one signal cannot name a fault, and why E1 specificity testing is not
optional.

## Still open

The 3 wrong answers (memory faults called noisy neighbour) survive. Interrupt time looked like
the fix on Sock Shop and died on Train Ticket. Only route left is re-collecting a few runs with
`KERNEL_MEM=1`, which records reclaim and paging directly instead of inferring them.

## Do we need new collection? Yes — three things

Full list: `blueprints/docs/COLLECTION-PLAN.md`. Written because a new GCP project is being
set up and the machine shape depends on what we intend to collect.

### The three that block work

**1. Memory events (`KERNEL_MEM=1`).** Our 3 wrong answers are all memory faults called noisy
neighbour, and we have tried twice to reach them indirectly — disk latency (F18) and interrupt
time (F20). Both worked on one application and died on the other. There is no third
workaround. The memory layer has to be recorded. 12 runs per app; ~8 GB per run instead of
2–3 GB, so ~200 GB for both.

Do one app first. If the memory layer does not separate memory stress from a noisy neighbour
there, stop rather than spend the second app.

**2. A lock contention positive example.** F22 gave us the negative control for free — total
lock wait moves for nothing we inject. But we have never injected lock contention, so we know
what its absence looks like and not what it looks like. Needs a program, plus its look-alike
(an idle thread pool), because idle parking swamped the total on the first look: 408 seconds
of wait per second of wall clock, which was Java pools parked waiting for work.

**3. Priority inversion and Nagle/delayed-ACK.** Both are cases where every signal we collect
says the system is healthy — no resource is busy, no packet is lost. That is exactly the shape
Naser asked for: the agent alone should fail, the blueprint should win.

### Cheap while the machine exists

- **Compound faults — we have zero.** All 12 recipes inject one thing. Naser asked for combined
  causes. Every look-alike pair we know is a candidate, starting with a CPU cap applied while
  a lock is held.
- Top up `svc_mem_cap` (4 runs total, thinnest threshold in the library) and `anomaly_disk`.
- More healthy runs at varied load. Our thresholds are set by the busiest healthy run, so this
  is the cheapest way to learn whether they are safe or lucky.
- The intensity calibration the VM already owed.

### The split worth knowing before picking machine types

Steps 1–3 need **no microservice deployment**. They are small programs on a plain VM. Only the
memory re-collection and compound faults need the full stack. So two machines may be cheaper
than one: a small one for the programs, the usual shape for the microservice runs.

### One thing to run before planning

`lttng list --kernel | grep -i lock` on the new VM. Naser asked for KERNEL lock contention;
today we can only see user-level locks through futex. That one command decides what B1 is.
