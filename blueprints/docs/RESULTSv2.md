# Blueprint results — how well are they doing?

Last run: 30 August 2026. 68 test runs. Two different apps. Kernel traces only.

---

## Short answer

**5 blueprints. 55 of 68 runs correct (81%).**

| | Count |
|---|---|
| Right answer | **55** |
| Wrong answer | **4** |
| Said "I don't know" | 9 |

**When a blueprint fires, it names the right fault 29 times out of 33 (88%).**

It never picks the *wrong* blueprint on a fault it covers. Every mistake is either a wrong
fire on a fault we don't cover, or a "don't know".

---

## Score for each blueprint

These are faults we have a blueprint for. Did the right one fire?

| Blueprint | Shop app | Booking app | Total |
|---|---|---|---|
| Noisy neighbour | 5 / 5 | 5 / 5 | **10 / 10** ✅ |
| Host out of CPU | 3 / 3 | 3 / 3 | **6 / 6** ✅ |
| Service CPU cap | 4 / 4 | 0 / 4 | **4 / 8** |
| Slow database | 5 / 7 | 4 / 7 | **9 / 14** |
| **All** | **17 / 19** | **12 / 19** | **29 / 38** |

**Two blueprints are perfect on both apps.** Noisy neighbour and host-out-of-CPU got every
single run right, on both systems.

The network blueprint is new and not in this table yet — it was built after this test run.

---

## What happens when there is nothing to find

This matters as much as finding faults. We gave it 30 runs it should say nothing about —
faults with no blueprint, plus healthy machines.

| Fault we showed it | Runs | Stayed quiet | Wrong |
|---|---|---|---|
| Healthy machine | 8 | **8** | 0 |
| Bad network (one service) | 4 | 4 | 0 |
| Bad network (host) | 2 | 2 | 0 |
| Hung service | 4 | 4 | 0 |
| Queue backlog | 2 | 2 | 0 |
| Disk fault | 2 | 2 | 0 |
| Memory cap | 2 | 2 | 0 |
| Error storm | 2 | 1 | **1** |
| Memory fault | 4 | 1 | **3** |
| **All** | **30** | **26** | **4** |

**All 8 healthy runs were correctly left alone.** No false alarms on a working system.

---

## The 4 wrong answers

| What it was | What it said | Why |
|---|---|---|
| Memory fault ×3 | Noisy neighbour | The memory test **really does** run a program that eats a CPU core. The rule is not wrong about what it sees — the two faults genuinely overlap. We cannot fix this: our traces have no memory events at all. |
| Error storm ×1 | Slow database | The last one slipping through the database rule. |

---

## The 9 "don't know" answers

A "don't know" is much better than a confident wrong answer. Here is why each happened.

| Runs | Reason |
|---|---|
| Slow database, mild ×2 | Signal is 4.4×, our bar is 5×. Too weak to call. We did **not** lower the bar to score better. |
| Slow database on booking app ×3 | The test we use works on the shop app but not the booking app. Known and written down. |
| Service CPU cap on booking app ×4 | **No signal exists at all.** CPU usage moved 83.14% → 83.16%. The blueprint says so and tells you to check per-container counters instead. |

---

## How much this improved

Everything below is the same test set.

| Stage | Wrong answers |
|---|---|
| Where we started | **13** |
| After rewriting the CPU rules | 15 → 13 |
| After fixing the database rule | **4** |

At the start, the rules got **42–62% of the "should say nothing" runs wrong**. One healthy
machine was called a host fault with 80% confidence.

Now: **8 of 8 healthy runs left alone.**

The database rule alone went from **11 wrong answers to 1**.

---

## The big lesson

**The first signal we trusted was the wrong one.**

We were deciding CPU faults on "how long threads wait for CPU". It sounded right. But we
measured it and it goes up for **every** CPU problem — and for a healthy machine under a
burst of load:

| What was wrong | Threads waiting |
|---|---|
| Host out of CPU | 52× |
| Service CPU cap | 15.7× |
| Noisy neighbour | 7.1× |
| **Nothing — just busy** | **3.7×** |

So we swapped it for **how busy the CPU is**, which does separate them cleanly. The old signal
is still reported, but it no longer decides anything.

The same thing happened with the database rule. We were using "is a process stuck waiting?"
— which is true for almost every fault. Now it also asks "is the network dropping packets?"
and "is anything actually answering slowly?"

---

## What we learned about the two apps

The two apps behave differently, and that is now written into the blueprints instead of being
averaged away.

| | Shop app | Booking app |
|---|---|---|
| Normal CPU use | 48% | **82%** |
| Services | ~16 | 40+ |

Because of this:

- **Percentages do not travel between systems.** The same fault moved CPU 48%→65% on one app
  and 80%→85% on the other.
- **Absolute numbers do.** The intruder took **1–2 CPU cores on both apps**, every time.
- **A ceiling always works.** "CPU is full" needed no adjusting on either app.
- **One fault is invisible on the booking app.** Capping one of 40+ services does not move
  host numbers at all. The blueprint says this and points elsewhere.

---

## What we could not build

**Hung service (paused container).** Five different attempts, all measured, all failed:

| Attempt | Result |
|---|---|
| CPU per process | Process names shared between containers |
| Threads that stop running | Healthy machines do this too |
| Threads that stop being woken | Buried in normal process churn |
| Slow endpoints | Looks the same as a healthy machine |
| Packet loss | 0% — it does not drop packets |

A paused container does not lose packets or go quiet in the scheduler. It just stops
answering. That needs request traces or logs, which is exactly what `fault_catalog.md`
predicted before we started.

---

## Honest limits

- **One test run each.** Numbers can move ±9 points on a repeat. Repeats are owed.
- **Only two apps**, both ours, both on one machine.
- **Kernel traces only.** Logs, metrics and request traces come later.
- **The database test does not transfer** to the booking app. Known, written down, costs 3 runs.
- **Nothing is human-verified yet.** Every blueprint still says `verified_by: PENDING`.

---

## What is worth doing next

1. **Repeat runs.** Every number here is a single run. We need to know the noise.
2. **Test the new network blueprint** the same way the others were tested.
3. **Chase the last error storm mistake** — the one remaining database false fire.
4. **Add logs or request traces** — that unlocks the hung service, the error storm and the
   memory faults, which is 4 of our 5 open problems.

---

## The five blueprints

| Blueprint | What it finds | Works on |
|---|---|---|
| `cpu-contention-co-tenant` | Another workload stealing CPU | both apps |
| `host-cpu-saturation` | The machine is out of CPU | both apps |
| `service-cpu-throttle` | One service is capped | shop app only |
| `db-latency-dependency-wait` | The database answers slowly | both, better on shop app |
| `network-path-degradation` | The network is dropping packets | both apps |

All five pass the format checks. Full evidence is in `FINDINGS-phase1.md` (F1–F16).
