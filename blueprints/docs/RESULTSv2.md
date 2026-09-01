# Blueprint results — how well are they doing?

Last run: 31 August 2026. 81 test runs. Two different apps. Kernel traces only.
All 5 blueprints tested the same way, including the new network one.

---

## Short answer

**64 of 81 runs correct (79%).**

| | Count |
|---|---|
| Right answer | **64** |
| Wrong answer | **3** |
| Said "I don't know" | 14 |

**When a blueprint fires, it names the right fault 38 times out of 41 (93%).**

It has **never** picked the wrong blueprint on a fault it covers. Not once, in any test.

---

## Score for each blueprint

| Blueprint | Shop app | Booking app | Total |
|---|---|---|---|
| Noisy neighbour | 5 / 5 | 5 / 5 | **10 / 10** ✅ |
| Host out of CPU | 3 / 3 | 3 / 3 | **6 / 6** ✅ |
| Network dropping packets | 6 / 6 | 3 / 6 | **9 / 12** |
| Slow database | 5 / 7 | 4 / 7 | **9 / 14** |
| Service CPU cap | 4 / 5 | 0 / 5 | **4 / 10** |

**Two blueprints are perfect on both apps.** Noisy neighbour and host-out-of-CPU got every
run right, on both systems.

**The network one is perfect on the shop app** (6 of 6) and gets half the booking app.

---

## What happens when there is nothing to find

29 runs it should say nothing about — faults with no blueprint, plus healthy machines.

| Fault we showed it | Runs | Stayed quiet | Wrong |
|---|---|---|---|
| Healthy machine | 5 | **5** | 0 |
| Hung service | 6 | **6** | 0 |
| Disk fault | 4 | **4** | 0 |
| Error storm | 4 | **4** | 0 |
| Memory cap | 4 | **4** | 0 |
| Queue backlog | 2 | **2** | 0 |
| Memory fault | 4 | 1 | **3** |
| **All** | **29** | **26** | **3** |

**Every healthy run was left alone.** No false alarms on a working system.

Six of seven fault types with no blueprint were correctly ignored, every single run.

---

## The 3 wrong answers

All three are the same thing.

| What it was | What it said |
|---|---|
| Memory fault ×3 | Noisy neighbour |

The memory test **really does** run a program that eats a CPU core. So the rule is not wrong
about what it sees — the two faults genuinely overlap.

We cannot fix this with what we collect. Our traces have **no memory events at all**.

---

## The 14 "don't know" answers

A "don't know" is much better than a confident wrong answer. Here is every one.

| Runs | Reason |
|---|---|
| Service CPU cap, booking app ×5 | **No signal exists.** CPU moved 83.14% → 83.16%. The blueprint says so and points to per-container counters. |
| Slow database, booking app ×3 | The test works on the shop app, not the booking app. Known, written down. |
| Network fault, booking app ×3 | The host-wide fault barely shows up there. No packets dropped in the queue at all. |
| Slow database, mild ×2 | Signal is 4.4×, our bar is 5×. We did **not** lower the bar to score better. |
| Missing data ×1 | The pack for that run was never fully built. Our fault, not the blueprint's. |

**11 of the 14 are on the booking app.** That app is genuinely harder for us.

---

## How much this improved

Same tests, through the session.

| Stage | Wrong answers |
|---|---|
| Where we started | **13** |
| After rewriting the CPU rules | 13 |
| After fixing the database rule | 4 |
| After adding the network blueprint | 7 |
| **After fixing the network rule** | **3** |

At the start, the rules got **42–62% of the "say nothing" runs wrong**. One healthy machine
was called a host fault at 80% confidence.

Now: **every healthy run left alone**, and 26 of 29 "say nothing" runs correct.

---

## The two big lessons

### 1. The first signal you trust is usually the wrong one

We started deciding CPU faults on "how long threads wait for CPU". It sounded right. But it
goes up for **every** CPU problem — and for a healthy machine under a burst of load:

| What was wrong | Threads waiting |
|---|---|
| Host out of CPU | 52× |
| Service CPU cap | 15.7× |
| Noisy neighbour | 7.1× |
| **Nothing — just busy** | **3.7×** |

Same story with the network. We thought "packets being re-sent" meant a network fault. Then
we measured a **memory cap** and it re-sent packets *harder than any network fault* — 95%.

An overloaded container cannot read its sockets fast enough, so packets pile up and get
dropped. Obvious afterwards. Not obvious before we measured it.

### 2. Always check a new signal against **every** fault, not just its own

We found the memory-cap problem only because we tested the network blueprint against all 13
fault types. The first check had covered 8. **The one we skipped was the one that broke it.**

The fix came from asking *where* the packet was lost:

| | Re-sent packets | **Dropped in the queue** |
|---|---|---|
| Real network fault | 18–61% | **yes** |
| Memory cap | 59–96% | **no** |
| Everything else | under 8% | **no** |

A network fault drops packets **in the outgoing queue**. An overloaded container drops them
in its **receiving buffer**. Different place, and the trace shows the difference.

Across all 81 runs, queue drops happened **only** where a network fault was injected.

---

## What we learned about the two apps

They behave differently, and that is now written into the blueprints instead of averaged away.

| | Shop app | Booking app |
|---|---|---|
| Normal CPU use | 48% | **82%** |
| Services | ~16 | 40+ |

- **Percentages do not travel.** The same fault moved CPU 48%→65% on one app, 80%→85% on the other.
- **Absolute numbers do.** The intruder took **1–2 CPU cores on both apps**, every time.
- **A ceiling always works.** "CPU is full" needed no adjusting on either app.
- **Some faults are invisible on the booking app.** Capping one of 40+ services does not move
  host numbers at all. Nor does the host-wide network fault. The blueprints say so.

---

## What we could not build

**Hung service (paused container).** Six attempts, all measured, all failed:

| Attempt | Result |
|---|---|
| CPU per process | Process names shared between containers |
| Threads that stop running | Healthy machines do this too |
| Threads that stop being woken | Buried in normal process churn |
| Slow endpoints | Looks the same as a healthy machine |
| Packet loss | 0% — it does not drop packets |
| Queue drops | 0% |

A paused container does not lose packets or go quiet in the scheduler. It stops **answering**.
That needs request traces or logs — exactly what `fault_catalog.md` predicted before we started.

---

## Honest limits

- **One test run each.** Numbers can move ±9 points on a repeat. Repeats are owed.
- **Only two apps**, both ours, both on one machine.
- **Kernel traces only.** Logs, metrics and request traces come later.
- **Two tests do not transfer** to the booking app: the database one and the CPU-cap one.
- **Nothing is human-verified yet.** Every blueprint still says `verified_by: PENDING`.
- **A few packs were incomplete**, costing 1 miss. Our bookkeeping, not the method.

---

## What is worth doing next

1. **Repeat runs.** Every number here is a single run. We do not know the noise yet.
2. **Add logs or request traces.** That unlocks the hung service, the error storm and the
   memory faults — most of what we cannot do today.
3. **Make the booking app work.** 11 of 14 "don't knows" are there.

---

## The five blueprints

| Blueprint | What it finds | Score |
|---|---|---|
| `cpu-contention-co-tenant` | Another workload stealing CPU | 10/10 |
| `host-cpu-saturation` | The machine is out of CPU | 6/6 |
| `network-path-degradation` | The network is dropping packets | 9/12 |
| `db-latency-dependency-wait` | The database answers slowly | 9/14 |
| `service-cpu-throttle` | One service is capped | 4/10 |

All five pass the format checks. Full evidence: `FINDINGS-phase1.md` (F1–F17).
