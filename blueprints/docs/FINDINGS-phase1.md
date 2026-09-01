# Phase 1 findings — kernel traces only

Running log of what the specificity work (E1) actually shows. Newest first.
Protocol: `RESEARCH-PLAN-phase1-kernel.md`.

---

## F18 — The disk fault separates cleanly, but on the opposite signal to the one predicted

**Block-layer sweep**, job 2233638, 58 runs, **all 13 families**, both applications.
Raw: `/scratch/yuvraj17/blockio/blockio_summary.json`.

### What works: who arrived on the disk

| Family | I/O newcomer, requests/s gained |
|---|---|
| `anomaly_disk` (Sock Shop) | **6598 – 6944** |
| `anomaly_disk` (Train Ticket) | **4724 – 4852** |
| `anomaly_mem` (SS) | 1142 – 1170 |
| `svc_mem_cap` (SS) | 250 – 282 |
| `queue_backlog` (SS) | 118 – 127 |
| every other family, both apps | **0 – 113** |

**Disk-fault floor 4724, every-other ceiling 1170 — a 4.0× gap that holds on both
applications.** A bar at 2000 req/s fires on 2 of 2 disk families, on nothing else, with
2.4× margin above and 1.7× below.

This is only the second signal in the whole phase to separate on both apps without a
per-application scenario. The first was packet loss.

### What does NOT work: the signal the catalogue predicted

`fault_catalog.md` pre-registers *"block_rq_* dominated by the stressor, DB threads in D-state
waits"*. The first half is right. The second is not.

| Family | device p95 latency change |
|---|---|
| `anomaly_disk` | **0.54 – 1.12×** — flat, and on Sock Shop it FALLS |
| `anomaly_mem` (SS) | **10.66 – 14.49×** |
| `svc_net` (SS) | 1.99 – 6.21× |
| `svc_cpu_cap` (SS) | 1.17 – 2.74× |

**The disk fault does not make disk requests slower.** It makes them far more numerous. The
stressor's own writes are large and sequential, so they complete quickly and pull the
distribution down rather than up.

Queue depth behaves the same way — it *falls* under the disk fault (0.51–0.65×) and rises
under memory pressure (1.88–2.38×). Both are the opposite of the intuition.

The automated overlap check confirms it: on device latency the disk fault overlaps other
families on **both** applications.

### A lead for the memory fault, which we had written off

`anomaly_mem` on Sock Shop shows **10.66–14.49× device latency**, 1142–1170 req/s of new I/O,
and queue depth up 1.88–2.38×. That is memory pressure driving reclaim and swap onto the disk,
and it is the clearest `anomaly_mem` signature found anywhere in this phase.

F10 recorded that `anomaly_mem` could not be separated because our traces carry no `mm_*` or
`kmem_*` tracepoints. That remains true — but it turns out the **block layer sees the
consequence** even though the memory layer is untraced.

It does not transfer: Train Ticket `anomaly_mem` measures 0.76–1.07× device latency and
52–182 req/s. So it is a Sock Shop lead, not a rule — but it is a real one, and it is the
first crack in the three remaining `anomaly_mem` wrong answers.

---

## F17 — I made the mistake E1 exists to catch: I tested the network signal on 8 families, not 13

**Network blueprint test**, job 2233310, 84 runs, both applications, network families scored as
positives for the first time.

**It scored 10 of 12** — Sock Shop 6/6, Train Ticket 4/6. But it caused **six regressions**,
and the cause is my own testing gap.

### What I claimed, and why it was wrong

F14 and F15 said packet loss is specific to network faults: *"a slow datastore does not drop
packets. Nor does a CPU cap, a frozen container, a memory limit or an error storm."*

That was based on a sweep covering **8 of 13 families**. `svc_mem_cap` was not among them.

| Family | worst retransmit % |
|---|---|
| `svc_mem_cap` (Train Ticket) | **95.1–95.6** |
| `svc_mem_cap` (Sock Shop) | **59.1–69.4** |
| `svc_net` | 25.6–60.7 |
| `anomaly_net` | 0.15–40.9 |
| `anomaly_cpu` | 1.2–33.3 |

**A memory cap retransmits harder than any network fault.** Plausible in hindsight — the
container cannot keep up, receive buffers fill, packets are dropped and re-sent — but it was
never measured because that family was left out of the sweep.

`anomaly_cpu` also crosses the bar on two runs, presumably softirq starvation dropping packets.

**Consequence:** 4 false fires on `svc_mem_cap`, and 2 `anomaly_cpu` runs turned into misses
because two blueprints fired at once and the verdict went ambiguous.

The rule that exists to prevent exactly this — *check a new signal against the other families,
not just its own* — is the one I skipped.

### The fix, and it is mechanism-matched

The second measurement in the same script separates them cleanly. **Queue drops** — buffers
handed to a device and never transmitted — happen *inside the queueing discipline*, which is
where netem sits. Loss caused by a full receive buffer happens somewhere else entirely.

| Family | retransmit % | **queue drop %** |
|---|---|---|
| `anomaly_net` (SS) | 18.5–40.9 | **0.122–0.289** |
| `svc_net` (SS) | 25.6–52.6 | **0.055–0.125** |
| `svc_net` (TT) | 38.1–60.7 | **0.002–0.003** |
| `svc_mem_cap` | 59.1–95.6 | **0.000** |
| `anomaly_cpu` | 1.2–33.3 | **0.000** |
| every other family | ≤7.1 | **0.000** (two runs at 0.001) |

**Queue drops are non-zero only where netem was applied.** Nothing else in 84 runs produced
one, on either application.

So the rule becomes **retransmission ≥12% AND queue drops present**. No non-network family
passes both: the two runs that reach 0.001% drop have retransmission of 0.16% and 2.41%, far
under the first bar.

### The cost, stated plainly

Requiring queue drops loses `tt_anomaly_net` entirely — all three runs measure **0.000%**
drop. On Train Ticket the host-wide network fault barely registers at all, which F15 had
already flagged when one run showed just 0.15% retransmission.

So: **6 regressions fixed for 1 more miss.** Network positives go 10/12 to 9/12, and the
Train Ticket host-wide case is recorded as not detectable rather than caught by luck.

### A data-completeness note

21 of the 84 runs have no on-CPU evidence in their packs — they were added to the task list
for this test and only the network measurements were built for them. Some CPU-family results
in this run are therefore incomplete and should not be compared against F16's numbers
directly.

---

## F16 — The datastore fix: wrong answers 13 → 4, and its own error count 11 → 1

**Retest**, job 2227463, 69 runs, both applications, with the two added clauses.

| App | Class | Before | After |
|---|---|---|---|
| Sock Shop | positive | 17/19 (89%) | 17/19 (89%) |
| Sock Shop | negative | 10/21 (**48%**) | **18/21 (86%)** |
| Train Ticket | positive | 15/19 (79%) | 12/19 (63%) |
| Train Ticket | negative | 5/6 (83%) | **8/9 (89%)** |
| **Wrong answers** | | **13** | **4** |
| Missed | | 5 | 9 |

**The datastore rule went from 11 wrong answers to 1.** Everything it used to claim wrongly —
network faults, service network faults, hung dependencies, memory caps — is now correctly
declined.

### The four that remain

| Run | Called it | Why |
|---|---|---|
| `anomaly_mem` ×2 (SS) | co-tenant | the memory-stress recipe genuinely runs a container taking ~1 core |
| `tt_anomaly_mem` ×1 | co-tenant | same |
| `error_storm` ×1 | datastore-wait | the only surviving datastore false fire |

Three of four are the known `anomaly_mem` family overlap, which cannot be resolved from
kernel data — the event census found no `mm_*` or `kmem_*` tracepoints.

### The cost, which was predicted and is real

Misses rose 5 → 9. All four new ones are the endpoint floor doing what the measurement said
it would:

- `tt_slow_db_aggressive_steady` ×3 — the datastore fault reaches only 9.75–13.59× endpoint
  slowdown on Train Ticket, below the 18× floor measured on Sock Shop
- `tt_svc_cpu_cap_subtle` ×1 — previously a **wrong answer** (`datastore-wait`), now a miss

That last one is an improvement, not a cost: a decline is strictly better than a confident
wrong answer. So the honest trade is **9 wrong answers eliminated for 3 new misses**, all
three on the application where the threshold was known not to transfer.

### On the threshold itself

The suggested 39× would have missed the lowest Sock Shop datastore run outright, which
measures **38.60×**. The safe window is (8.58, 38.60], and 18 sits at its geometric midpoint
with 2.1× margin on both sides. Choosing the midpoint of a measured gap rather than a round
number next to the data is the whole difference between a threshold and a fitted constant.

### What each clause bought

- **Retransmission veto (12%)** — universal, works on both applications, and is the clause
  that killed the network false fires. Only possible because F14/F15 established that packet
  loss is specific to network faults.
- **Endpoint slowdown floor (18×)** — Sock Shop only, and recorded as such. It killed the
  hung-dependency, memory-cap and error-storm false fires there, and cost three Train Ticket
  datastore runs.

---

## F15 — Packet loss confirmed across 40 runs. It answers "is it the network", not "which one".

**Confirmation sweep**, job 2227189, 40 runs, 8 families, both applications.
Raw: `/scratch/yuvraj17/netloss/netloss_summary.json`.

| App | Family | interfaces impaired | worst retransmit % |
|---|---|---|---|
| Sock Shop | `anomaly_net` | 7–12 | **18.5–40.9** |
| Sock Shop | `svc_net` | 1–3 | **25.6–52.6** |
| Sock Shop | `slow_db` | 1 | 1.2–7.1 |
| Sock Shop | `noisy_neighbor` | 0–2 | 0–3.9 |
| Sock Shop | `svc_cpu_cap` | 0–1 | 0–2.3 |
| Sock Shop | `normal` | 0–1 | 0–0.5 |
| Sock Shop | `dependency_outage`, `error_storm` | **0** | **0** |
| Train Ticket | `svc_net` | 1–2 | **38.1–60.7** |
| Train Ticket | `anomaly_net` | 0–1 | **0.15–33.3** |
| Train Ticket | `svc_cpu_cap` | 1 | 1.1–3.7 |
| Train Ticket | everything else | 0 | 0–0.2 |

### The question it answers well: is this a network fault?

**Baseline retransmit rate is 0.00% in every one of the 40 runs, both applications.** There is
no noise floor to fight.

| | worst retransmit % |
|---|---|
| network faults (excluding one outlier) | **18.5–60.7** |
| every non-network family, both apps | **≤7.1** |

A gap of 2.6×, and it holds on both applications — the first discriminator in this phase that
does. `dependency_outage` and `error_storm` sit at exactly **0**, which is what a specific
signal looks like.

**The outlier:** one Train Ticket `anomaly_net` run measured 0.15%. That would be a *miss*,
not a false positive — the blueprint declines rather than misdiagnosing.

### The question it does not answer: which network fault?

Breadth separates the two on Sock Shop (7–12 interfaces against 1–3) and **fails on Train
Ticket** (0–1 against 1–2). The host-wide fault does not spread there.

So this is one problem, not two. **The right artifact is a single
`network-path-degradation` blueprint** that fires on retransmissions and reports *which*
interfaces are impaired — with the count as evidence of scope rather than as a second
blueprint's discriminator. Building `host-network-degradation` and A3 as separate blueprints
would assert a separation that only exists on one application.

### Where this leaves the pair I was asked to build

- **A3 `service-network-path`** — buildable, merged into `network-path-degradation`, because
  splitting it from the host-wide case is not supported on both apps.
- **A4 `frozen-dependency`** — still not buildable. It measured **0 interfaces, 0%** here, as
  it should: a paused container does not drop packets, it stops answering. Five constructions
  tried, all negative, and the catalogue pre-registered traces and logs for it.

---

## F14 — Yes: packet loss makes network faults distinct, and it separates them from each other

The question was whether anything in a kernel trace is specific to a network fault. F13 said
no, but F13 measured **latency**, which every fault changes. The network recipes do one thing
nothing else in the catalogue does: **they drop packets.**

| Recipe | netem |
|---|---|
| `anomaly_net` | on **every** container's eth0 — 80 ms delay, 20 ms jitter, **2% loss** |
| `svc_net` | on **one** container's eth0 — 150 ms delay, 40 ms jitter, **4% loss** |

A dropped TCP segment is re-sent with the same sequence number, and our trace carries `seq`
in the packet header. So retransmissions are countable, per interface.

### The result

| Run | interfaces impaired | worst retransmit | baseline median |
|---|---|---|---|
| `anomaly_net` (host-wide) | **12 of 16** | 28.6% | **0%** |
| `svc_net` (one container) | **1 of 18** | 52.6% | **0%** |
| `slow_db` | 1 of 18 | **1.18%** | 0% |
| `normal` | **0 of 18** | **0%** | 0% |

Three things make this the strongest signal found in phase 1:

1. **The baseline is exactly zero in every run.** Healthy traffic here does not retransmit at
   all, so any retransmission is signal rather than something to threshold against noise.
2. **The no-fault run reports 0 of 18 impaired and 0% worst.** A clean control, which neither
   the endpoint view nor any scheduler construction managed.
3. **Breadth separates the two network faults exactly as the recipes describe them.** Twelve
   of sixteen interfaces against exactly one — "netem on every container" against "netem on
   one container", recovered from the trace without being told.

`slow_db` trips one interface at 1.18%, which is 45× below `svc_net`'s 52.6% and comes from a
handful of segments. Worth a magnitude floor, not a redesign.

### Why the first run of this was wrong, and how the output said so

The first attempt reported ~50% retransmits on *every* run including the healthy one, and
listed interfaces named `swapper/4`, `mongod`, `conn15`. Two bugs:

- the interface pattern `name = "` also matches inside `procname = "`, so every "interface"
  was a process;
- one packet fires `net_if_receive_skb` on more than one interface (veth, then bridge), so
  every second sighting counted as a retransmission — which is exactly why the rate was ~50%
  everywhere.

**A rate that identical across a healthy run and three different faults is a bug, not a
signal.** Now deduplicated by `skbaddr`.

### What this unlocks

Both network blueprints become buildable, which F13 had ruled out:

- **`host-network-degradation`** — many interfaces impaired
- **A3 `service-network-path`** — exactly one interface impaired, at a high rate

And it is mechanism-matched rather than fitted: the discriminator is *packet loss*, which is
literally what the fault injects. Confirmation across all runs and both applications is the
next step before either is written.

---

## F13 — A3 and A4 cannot be built from kernel data. A different blueprint can.

**Endpoint sweep**, job 2223505, 40 runs, 7 families, both applications.
Raw: `/scratch/yuvraj17/endpoints/endpoint_summary.json`.

### Sock Shop

| Family | endpoints slowed | worst slowdown | vanished |
|---|---|---|---|
| `anomaly_net` (host network) | **13–13** | 42.6–72.2× | 1 |
| `slow_db` | 3–9 | **38.6–47.6×** | 0–2 |
| `svc_net` (A3) | 3–6 | 8.0–14.0× | 1 |
| `svc_mem_cap` | 1–2 | 3.4–8.6× | 1 |
| `dependency_outage` (A4) | 1–2 | 2.5–3.0× | 1 |
| `error_storm` | 1–1 | 2.6–3.1× | 0 |
| `normal` | 1–3 | 2.5–2.9× | 0 |

### The verdict on A3 and A4

**A3 `service-network-path` — not buildable.** Its endpoint count (3–6) overlaps healthy runs
(1–3) and slow datastore (3–9); its worst slowdown (8.0–14.0×) overlaps `svc_mem_cap`. On
Train Ticket it collapses to 1–2 endpoints, inside the healthy range.

**A4 `frozen-dependency` — not buildable.** 1–2 endpoints slowed at 2.5–3.0×, which is
*indistinguishable from a healthy system* (1–3 at 2.5–2.9×). On Train Ticket, 0 of 21.

Both match their pre-registration in `fault_catalog.md`, which names **traces** as the winning
modality for each. Phase 1 is kernel-only, so this is the pre-registration being right rather
than a surprise.

### Two things worth having, found by looking

**1. Host network impairment is cleanly identifiable — on Sock Shop.**
`anomaly_net` slowed **13 of 22 endpoints in all three runs**, and the automated overlap check
puts it in **no overlapping pair** on that signal. Nothing else exceeds 9. That is a stronger
separation than either blueprint I was trying to build, and it belongs to
`host-network-degradation`, which the backlog had parked in Tier C as "needs traces".

Not portable: on Train Ticket the same fault gives 1–2 of 27, inside the healthy range. So it
is a scenario, not a rule — the same shape as every other cross-app result here.

**2. A measured fix for the datastore rule's false fires.**
The current rule fires on socket blocking ≥5×, which every impostor also trips. Endpoint
slowdown separates them on Sock Shop far better:

| | worst endpoint slowdown |
|---|---|
| `slow_db` | **38.6–47.6×** |
| everything except `anomaly_net` | **≤14.0×** |

The overlap check confirms `slow_db` overlaps only `anomaly_net` on this signal, and those two
are separated by endpoint count (3–9 against 13–13). A two-signal rule would address the false
fires on `dependency_outage`, `svc_net`, `svc_mem_cap`, `error_storm` and healthy runs in one
move — all of which sit at 2.5–8.6×, nowhere near 38×.

Train Ticket does not support it (`slow_db` 9.8–1477.7× overlaps `svc_mem_cap` at 221–225×),
so it would go in as a Sock-Shop-shaped scenario, not a universal threshold.

### Two metrics that failed and should not be used

- **`tail_ratio` is unusable as defined.** It divides by the change in p50, which is often near
  zero, so it produced 1735, 18545, 246522. Dropped, not reported.
- **`min reply ratio` separates nothing** — 0.00 in every Sock Shop family, overlapping all 21
  pairs.

### One architecture-specific signal for A4

On **Train Ticket only**, `dependency_outage` shows **6–8 endpoints vanishing** against 1–2 for
healthy, and it is in no overlapping pair for that signal there. On Sock Shop it vanishes 1,
same as three other families. So a frozen dependency is visible on a wide fan-out system by
what disappears, and invisible on a short chain — worth recording as a scenario if A4 is ever
revisited, but far too thin to build a blueprint on now.

---

## F12 — Wakeups do not separate frozen from blocked either. The scheduler stream is exhausted for A4.

F11 left one idea open: a thread blocked on a socket gets **woken** when its reply arrives,
while a thread in the freezer cgroup will not run whatever arrives. So count `sched_waking`
per thread, baseline against incident.

Frozen dependency (payment paused) against a slow datastore as the control:

| | frozen dependency | slow datastore |
|---|---|---|
| `docker` | 187/194 threads stop being woken | 170/176 |
| `runc` | 28/28 | 33/33 |
| `containerd-shim` | 6/42 | — |
| `app` (contains payment) | **1/22** | — |
| `mongod` | — | 1/28 |

**It does not separate them.** Both runs show the same shape, and for the same uninteresting
reason: `docker` and `runc` are transient processes — every health check spawns one — so
"threads that stop being woken" is dominated by ordinary process churn in *any* run.

And the fault's own service barely moves: `app` shows **1 of 22** threads. The freezer stops a
task **running**; it does not stop the kernel **waking** it. Packets still arrive, wakeups
still fire, the task just never gets to the CPU.

### The scheduler stream is now exhausted for this problem

Three constructions tried, all measured, none separating:

| Signal | Result |
|---|---|
| on-CPU time per process | comm names shared; pausing one service moved `app` only to 0.6× |
| threads that stop being scheduled | healthy runs show it too; the *slow datastore* shows it strongest (`mysqld` 10/11) |
| threads that stop being woken | dominated by `docker`/`runc` churn in every run |

### What the fault catalogue already said

Worth stating plainly, because it reframes the whole task. Both blueprints in this pair are
**pre-registered as non-kernel faults**:

- `svc_net` (A3) — *"TRACES win localization … kernel confirms via socket-level waits"*
- `dependency_outage` (A4) — *"TRACES localize (spans at orders pointing at payment); LOGS
  carry the exception detail"*

Phase 1 is kernel-only. So the honest expectation is that neither can be built to the
standard of the CPU cluster from this phase's data, and the pre-registration says so in
advance rather than after the fact.

The remaining evidence is the **endpoint view**, which is kernel data and did show the slow
datastore clearly (8 of 22 endpoints, 11×) while leaving the no-fault run at zero. Whether it
separates these two families is what job 2223505 measures. If it does not, that is the result,
and both blueprints will say where to look instead rather than carrying an invented rule.

---

## F11 — The peer measurement is fixed. The frozen-dependency signal is not what we expected.

### The rewrite works

`socket_peer_wait.py` was replaced by `endpoint_latency.py`, which ignores process names and
works on flows. Two assumptions in the original were wrong, both disproved from the trace:

- **`procname` on a network event is not the socket owner.** Receive processing runs in
  softirq context, so the field holds whatever was on-CPU. Measured: *both directions of one
  flow* attributed to `python3`, elsewhere to `ksoftirqd` and `cadvisor`.
- **There is no "us".** This host runs every container, so it sees both sides of every
  conversation. That is a gift, not a problem: it means a service's true response time is
  measurable from the host alone.

The new version identifies flows by their 4-tuple, calls the well-known port the server, and
caps gaps at 2 s (F5's 1–5 *second* baselines were idleness counted as latency). Result on
the four runs that defeated the old one:

| Run | Endpoints slowed ≥2× | Worst |
|---|---|---|
| **no fault** | **0 of 21** | 1.28× |
| slow datastore | 8 of 22 | **11.0×** |
| degraded network | 3 of 21 | 2.17× |
| frozen dependency | 2 of 21 | 1.61× |

**The no-fault run is now clean** — the single measurement that made the old version useless.
And the slow datastore is unmistakable.

### But two families remain too close to call

Network (2.17×) and frozen dependency (1.61×) sit near the healthy ceiling (1.28×). Magnitude
will not separate them.

### The freeze test: comm level found nothing, thread level found the wrong thing

The recipe pauses `payment` with `docker pause`, and its header promises "conspicuous
silence". At **comm level there was none**: Sock Shop runs several Go services as `app`, so
pausing one moved the comm total 0.2024 → 0.1209 cores (0.6×). The largest relative drop
anywhere in the run was 0.234×.

Moving to **thread level** — individual threads either get scheduled or they do not — the
measurement works, but says something different from what was expected:

| Run | Threads that stopped |
|---|---|
| **no fault** | containerd-shim 2/13, dockerd 1/15, java 1/34, python3 2/153 |
| frozen dependency r1 | containerd-shim 7/17, mysqld 2/9, toxiproxy 3/13, **app 1/14** |
| frozen dependency r2 | mysqld 4/9, containerd-shim 5/16, dockerd 2/17 |
| **slow datastore** | **mysqld 10/11**, conn31 1/1, containerd-shim 7/16 |

Three things follow, and none of them are what the hypothesis predicted:

1. **Healthy runs also have threads that stop.** Thread churn is normal, so "some threads
   stopped" is not a fault signal on its own.
2. **The frozen dependency barely registers** — `app 1/14`. Payment is a low-traffic service
   (60 requests in 30 s), so its threads sit below the activity floor and never qualify.
3. **The strongest freeze signature belongs to the slow datastore**: `mysqld 10/11 threads`
   stopped being scheduled, because they are all blocked waiting on the delayed proxy.

That third point is the real limitation: **absence of on-CPU time cannot distinguish
"frozen by the cgroup freezer" from "blocked on I/O"**. Both produce a thread that is not
scheduled. Separating them needs the *reason* a thread left the CPU, which `sched_switch`
does carry in `prev_state` — an avenue, not a result.

### What this means for A4

The honest position before writing anything: a frozen dependency on a **low-traffic path** is
hard to see in aggregate kernel signals, because there is very little traffic to be absent.
That is itself blueprint content — it tells the reader where not to look — and it argues for
per-endpoint evidence with a low request-count floor rather than host-wide statistics.

The 40-run endpoint sweep (job 2223505) will settle whether the per-endpoint view separates
these families across both applications, or whether kernel data genuinely cannot, which the
fault catalogue already predicts for the network family by pre-registering **traces** rather
than kernel as its winning modality.

---

## F10 — Splitting the runqueue threshold: 3 fixed, 1 broken, net +2

Re-test with `STARVED_RQ_X = 5.0` (job 2223438) against the same 69 runs as job 2222638.

| App | Class | Before | After |
|---|---|---|---|
| Sock Shop | positive | 17/19 (89%) | 17/19 (89%) |
| Sock Shop | negative | 11/21 (52%) | **10/21 (48%)** |
| Train Ticket | positive | 13/19 (68%) | **15/19 (79%)** |
| Train Ticket | negative | 4/6 (67%) | **5/6 (83%)** |
| **Total wrong** | | **15** | **13** |

**Fixed (3):** `tt_slow_db_aggressive_steady_r1` and `_r3` — both were called cgroup throttling
and are now correctly the datastore. `tt_anomaly_mem_aggressive_steady_r2` also stopped firing.

**Broken (1):** `svc_mem_cap_aggressive_steady_r1` now fires `datastore-wait`. It has socket
blocking of 105× with runqueue at 2.44×. The old veto (`< 2.0`) happened to block it; the new
one (`< 5.0`) lets it through. It was never *correctly* rejected — it was rejected by
accident, the same way F1's silence was accidental.

That is the honest trade, and it is worth stating rather than smoothing over: loosening the
datastore veto helped the application where the datastore signal is enormous and hurt the one
where an unrelated fault also blocks sockets hard.

### Where the remaining 13 errors live

| Rule | Errors | Kind |
|---|---|---|
| `datastore-wait` | **11** | fires on anything that blocks a socket |
| CPU family | **2–3** | `anomaly_mem` reads as co-tenant contention |

**The CPU cluster work is essentially finished.** Every remaining error except `anomaly_mem`
belongs to the datastore rule, which was deliberately left untouched and is the job of the
`frozen-dependency` and `service-network-path` blueprints (backlog A3/A4).

`anomaly_mem` is a genuine family overlap rather than a rule defect: the memory-stress recipe
runs a `stress-ng` container that really does take ~1 core, so the co-tenant rule is not
wrong about what it sees. Separating them needs a memory signal, and the event census (F5)
found no `mm_*` or `kmem_*` tracepoints in our traces — so it cannot be done from the kernel
data we have.

### Still missed, and why that is the right outcome

- `slow_db_subtle` ×2 — blocking 4.43–4.52× against a 5× bar. Declines rather than guessing.
  Deliberately not lowered; the co-tenant runs reach 2.99×, so the margin would shrink from
  10× to 1.5×.
- `tt_svc_cpu_cap_aggressive` ×3 — no host-level signal exists at all (0.8314 → 0.8316). The
  blueprint records this as its own scenario and sends the reader to cgroup counters.

---

## F8 — The −0.000 utilisation was a midnight-wrap bug, and the first fix made it worse

**Run:** `tt_slow_db_aggressive_steady_r1`. Reported host utilisation of −0.000 in F6.

### What happened

Its fault window is `2026-08-04T23:59:21Z → 2026-08-05T00:01:21Z`. **It crosses midnight.**

Trace timestamps are wall-clock **time of day**, so after midnight they wrap to zero. The
window span is computed as last minus first:

| Window | Range | Span measured | Utilisation |
|---|---|---|---|
| baseline | 23:58:26 → 23:59:21 | 55.0 s | 0.8179 — correct |
| incident | 23:59:21 → 24:00:21 | **−86,340 s** | **−0.0002** |

`21 − 86,361 = −86,340`. Every rate divided by that span came out negative.

**The CPU work itself was measured correctly all along** — 275 seconds of busy time were
decoded across the boundary. Only the divisor was wrong.

### The corrected numbers

| | Before | After |
|---|---|---|
| incident span | −86,340 s | **60.0 s** |
| busy cores | −0.003 | **4.598 of 16** |
| utilisation | −0.0002 | **0.287** |

A ratio of 0.287 / 0.818 = **0.35**, which sits inside the 0.32–0.72 range measured for the
other Train Ticket slow-datastore runs. The run is now usable and consistent with its family.

### The first fix was wrong, and testing caught it

The obvious repair was to wrap `shift()` with a modulo so 23:59:21 + 60 s gives "00:00:21"
instead of "24:00:21". Measured against babeltrace, that is backwards:

| Passed to babeltrace | Result |
|---|---|
| `--begin 23:59:21 --end 24:00:21` | **accepted** — reads it as the next day, 275 s decoded |
| `--begin 23:59:21 --end 00:00:21` | **rejected** — `FLT.UTILS.TRIMMER` error, 0 events |

The reader takes an hour past 24 happily; what it refuses is a window whose end is earlier
than its begin. So the modulo turned a working case into an empty one. Reverted, with the
measurement written next to the line so nobody re-applies it.

The actual repair is an `unwrapper()` in each decode loop that adds a day whenever the clock
jumps backwards. Unit-checked: the wrapping window now yields +4.0 s where it previously
yielded −86,396 s, and ordinary windows are untouched.

### Blast radius

**1 run of 93.** Every run with a fault window was checked. But the failure was **silent** —
it produced a plausible-looking number rather than an error — so all four scripts that window
a trace by time of day were fixed: `oncpu_share`, `runqueue_delay`, `blocking_syscall`,
`socket_peer_wait`.

### Incidental

The two applications run on **different hardware**: Sock Shop on 12 CPUs, Train Ticket on 16.
Utilisation already normalises for this, but any comparison of raw core counts across the two
must account for it. The co-tenant newcomer taking ~2.0 cores is 17% of one machine and 12%
of the other.

---

## F7 — Same fault, two architectures, two different signatures. That is blueprint content, not a bug.

Reframed after Yuvraj's note: a blueprint is a **diagnostic guide**, not a classifier. It does
not have to be one tuned number that fits every system. Where a fault looks different on a
different architecture, the blueprint's job is to **record both pictures** so the reader knows
what to expect and where to look.

So the F6 "failure" is really a measurement of two scenarios. Here is the whole Train Ticket
signature table, from the same re-test.

| Family | util ratio | newcomer cores | biggest loss | runqueue | socket block |
|---|---|---|---|---|---|
| `anomaly_cpu` | 1.23–1.25 (→0.99) | **7.81–8.07** | −0.75 | 9.1–14.4× | 1.5–2.4× |
| `noisy_neighbor` | 1.03–1.08 | **0.99–2.00** | −0.12 to −0.28 | 2.0–3.7× | 1.4–2.6× |
| `anomaly_mem` | 1.02 | **0.98–0.99** | −0.56 to −0.63 | 2.5× | 1.6–155× |
| `svc_cpu_cap` | **0.995–1.008** | **0.00** | **−0.03 to −0.06** | **1.6–1.8×** | 1.1–5.1× |
| `slow_db` | 0.32–0.72 | 0.00 | −0.69 to −2.62 | 1.0–2.6× | **165–1450×** |
| `dependency_outage` | 0.47–0.48 | 0.00 | −1.43 to −1.47 | 1.0–1.5× | **~1.0×** |
| `svc_net` | 0.71–0.79 | 0.00 | −0.51 to −0.64 | 1.1–1.5× | **~1.15×** |

### 1. On a wide fan-out architecture, a single-service CPU cap has no host-level signal

Not a weak signal — **no signal**. Utilisation flat, no newcomer, biggest loss 0.03 cores,
runqueue flat. Capping one of 40+ services is invisible at the host aggregate because the
host keeps working on all the other requests.

This is worth stating plainly in the blueprint: *on this kind of system, do not look for it
in host-level kernel data. Go straight to per-cgroup throttling counters.* That saves an
engineer an hour of looking in the wrong place, which is the whole point of writing it down.

### 2. One signal DID transfer across both applications: the newcomer's core count

| | Sock Shop | Train Ticket |
|---|---|---|
| co-tenant newcomer | 0.988–2.002 cores | 0.989–1.996 cores |
| host saturation newcomer | 6.54–6.62 cores | 7.81–8.07 cores |

Nearly identical, because the number is set by the injected cap, not by the application.
**Absolute cores travel; utilisation percentages do not.** Co-tenant utilisation moved
0.48→0.65 on one app and 0.80→0.85 on the other — the same fault, very different percentages
— while the cores taken were the same both times.

That is a concrete improvement available from evidence: rank the co-tenant rule on the
newcomer's cores, and use utilisation only to say whether the host still had room.

### 3. The datastore look-alikes swap behaviour between the two apps

| Family | Sock Shop block | Train Ticket block |
|---|---|---|
| `slow_db` (the real one) | 36.8× | **165–1450×** |
| `dependency_outage` | **89×** | ~1.0× |
| `svc_net` | **175×** | ~1.15× |

On Sock Shop the impostors shout and cause false fires. On Train Ticket they are silent and
the datastore rule works — which is why Train Ticket scored better on negatives (67%) than
Sock Shop (52%) despite everything else being harder there.

The mechanism is architectural. Sock Shop's front-end is a single `node` process whose event
loop blocks when a dependency hangs. Train Ticket spreads the same work across dozens of Java
services with their own thread pools, so one hung dependency is diluted in the aggregate.

**Neither picture is the truth on its own.** A blueprint that only carried the Sock Shop
numbers would mislead someone running a fan-out system, and vice versa. Both go in.

### 4. A data problem to fix

`tt_slow_db_aggressive_steady_r1` reports utilisation of **−0.000** with a biggest loss of
−2.621 cores. The incident window has almost no scheduler events. Either the trace has a gap
or the system stopped scheduling. Excluded from the ranges above; needs checking before that
run is used for anything.

---

## F6 — Re-test on both applications: the CPU rules work on one app and break on the other

**Re-test**, job 2222638, 69 runs, 1h12m. Both applications, new decision rules.
Raw: `/scratch/yuvraj17/retest/retest.json`.

| App | Class | n | Correct | Rate |
|---|---|---|---|---|
| Sock Shop | positive | 19 | 17 | **89%** |
| Sock Shop | negative | 21 | 11 | 52% |
| Train Ticket | positive | 19 | 13 | 68% |
| Train Ticket | negative | 6 | 4 | 67% |

### What improved on Sock Shop

On the **same 21 negative runs**, wrong answers went **13 → 10**. Every CPU-rule mistake is
fixed except one family:

| Was wrong in E1 | Now |
|---|---|
| `svc_cpu_cap_subtle` ×2 → co-tenant | **correct** (both now `service-cpu-throttle`) |
| `normal_none_burst` ×2 → co-tenant | **correct** (quiet) |
| `anomaly_disk` ×1 → co-tenant | **correct** (quiet) |
| `anomaly_mem` ×2 → co-tenant | **still wrong** |

The eight datastore-rule mistakes are unchanged, as expected — that rule was deliberately
left alone.

### The cross-application result, which is the point of the exercise

**Train Ticket runs hot. Its baseline is 0.82, not Sock Shop's 0.48.**

| Family | Sock Shop | Train Ticket |
|---|---|---|
| host saturation | 0.991–0.998 | **0.994–0.997** |
| co-tenant | 0.619–0.681 | **0.811–0.853** |
| cgroup cap | 0.114–0.365 | **0.800–0.832** |
| no fault | 0.462–0.531 | (baseline ≈0.82) |

Consequences, measured:

- **Host saturation transfers perfectly.** 0.99+ on both. A ceiling is a ceiling, and it is
  the only rule here that is scale-free.
- **The cgroup-cap rule fails completely on Train Ticket.** All three aggressive runs were
  *missed*: utilisation went 0.8314 → 0.8316, 0.8172 → 0.8237, 0.8201 → 0.8191. **No
  collapse at all.** On Sock Shop the same fault collapsed utilisation to a quarter of
  baseline.
- **The reason is architectural.** Sock Shop is a short chain, so throttling one service
  stalls the whole pipeline behind it and the host goes quiet. Train Ticket has 40+ services
  and keeps working on other requests, so one capped service barely dents the total.
- **Co-tenant on Train Ticket (0.811–0.853) sits inside Sock Shop's *saturation* territory
  and on top of Train Ticket's own baseline.** An absolute threshold learned on one app is
  meaningless on the other.

This is the same failure the datastore blueprint had when it fell to 44% precision on Train
Ticket, and it has the same cause: **a threshold measured on one application encodes that
application's architecture.**

### Two new confusions the wider sweep exposed

1. **`anomaly_mem` fires `cpu-contention` on both apps** (SS util 0.749–0.765, TT
   0.797–0.798). The memory-stress recipe runs a `stress-ng` container, which *is* a
   newcomer taking CPU. The rule is not wrong about what it sees; the fault families overlap
   by construction.
2. **`tt_slow_db` ×2 fires `service-cpu-throttle`.** On Train Ticket the datastore fault
   collapses utilisation *and* raises runqueue delay, so the F4 guard does not separate them
   there. One `tt_slow_db` run also reports utilisation of **−0.000**, which is a window with
   effectively no scheduler events — a data problem to check, not a result.

### What this says

The direction of travel was right and the magnitudes are not portable. The fix is not to
re-tune per app, which would be fitting. It is **E3**: express each discriminator relative to
the system's own baseline and its own spread, rather than as an absolute cut, then re-test
the same way. Host saturation already passes that bar because "at the ceiling" needs no
calibration; the other two do not.

---

## F5 — Socket peer attribution: the data is there, the first attempt failed

**Goal.** The datastore rule fires on anything that blocks a socket, and the impostors are
louder than the real fault (network path 175×, hung dependency 89×, real slow datastore
36.8×). Syscall duration says a process is blocked; it cannot say blocked **on what**.

**The data exists.** Our `net_dev_queue` and `net_if_receive_skb` events carry full IP and
TCP headers — source and destination address, both ports, interface name. 60,000 of each in
a 3M-event sample. So the peer is recoverable in principle.

**The first implementation does not work.** `socket_peer_wait.py` pairs each outgoing packet
with the next incoming packet on the same (process, peer) and calls the gap a reply latency.
Run on four labelled incidents, the output is unusable:

| Run | Top "slow peer" | Baseline gap | Peers slowed ≥2× |
|---|---|---|---|
| slow datastore | `node → 172.18.0.10:80` | 1278 ms | 1 of 4 |
| hung dependency | `app → 172.18.0.18:40772` | 2576 ms | 1 of 10 |
| degraded network | `conn10 → 172.18.0.19:27017` | 1468 ms | 2 of 5 |
| **no fault** | — | 1090 ms | **1 of 16** |

Three things are wrong, and they are worth writing down so the next attempt does not repeat
them:

1. **It measures idleness, not latency.** Baseline gaps of 1–5 seconds on a *healthy* system
   give it away. TCP connections are long-lived and mostly quiet, so "time until the next
   packet arrives" is dominated by nothing happening.
2. **The peer key is wrong for half the flows.** Outgoing is keyed on the destination and
   incoming on the source, which matches only when the process is the client. Many rows show
   ephemeral ports (51178, 42330), meaning the process is the *server* there — so the key is
   a different random port per connection and never pairs across windows. `reply_ratio` above
   1.0 (1.24, 1.32) confirms the two directions are not matching up.
3. **The datastore never appears.** `mysqld:3306` is absent from the slow-datastore run
   entirely, because **toxiproxy sits permanently in the catalogue→catalogue-db path**. The
   kernel-visible peer of the caller is the proxy, not the database. Our own deployment
   topology defeats a naive peer lookup.

And the decisive test: the no-fault run reports a slowed peer too. **The signature does not
separate.**

**What the next attempt should do** — recorded, not yet built:
- normalise each flow to its 5-tuple and identify the peer by the **well-known** endpoint
  (port < 32768), so both directions map to one flow
- cap measured gaps (order 200 ms) so idle time cannot enter the statistic
- restrict to flows where the process is the client
- account for the proxy hop, since the peer of a service is not always the service it is
  logically talking to

**Status: no rule written, no blueprint changed.** This is a measurement that failed, kept
because knowing the naive version fails is worth as much as the version that works.

---

## F3 — The CPU cluster separates cleanly, and the discriminator is not runqueue delay

**CPU-cluster measurement**, 17 Sock Shop runs, job 2222558, 17 min.
Raw: `/scratch/yuvraj17/cpucluster/cpu_cluster.json`. Host: **12 CPUs**.

`oncpu_share.py` attributes on-CPU time per process from `sched_switch` alone, baseline
window vs incident window. Nothing here reads metrics.

| Family | n | Host utilisation (baseline → incident) | Newcomer process | Cores it gained |
|---|---|---|---|---|
| `anomaly_cpu` (host saturation) | 3 | 0.488–0.492 → **0.991–0.998** | `stress-ng-cpu` 3/3 | **6.54–6.62** |
| `noisy_neighbor` (co-tenant) | 5 | 0.479–0.496 → **0.619–0.681** | `stress-ng-cpu` 5/5 | **0.99–2.00** |
| `normal` (no fault) | 5 | 0.444–0.507 → **0.462–0.531** | none 4/5 | 0.00–0.30 |
| `svc_cpu_cap` (cgroup cap) | 4 | 0.451–0.507 → **0.114–0.365** | **none 0/4** | 0.00 |

**Host utilisation splits all four families with no overlap.** The automated separation check
reports `NONE - clean split`. Baseline utilisation is 0.444–0.507 in every one of the 17 runs,
so the healthy operating point is stable and *change* is a meaningful frame.

### The surprise: a cgroup cap makes the host do LESS work

Every other family raises utilisation. A cap **collapses** it — 0.451 → 0.114 on the
aggressive runs. And the loss is not confined to the capped service; on
`svc_cpu_cap_aggressive_steady_r1` every busy process drops:

```
node    1.120 -> 0.243  (-0.876)     dockerd  0.452 -> 0.088  (-0.364)
python3 0.767 -> 0.137  (-0.630)     traefik  0.232 -> 0.052  (-0.180)
java    0.673 -> 0.278  (-0.395)     app      0.204 -> 0.033  (-0.171)
```

Throttling one service stalls the whole request pipeline behind it, so the entire system
does less work while its threads wait *more*. That combination is mechanically unique:

| | busy cores | runqueue delay |
|---|---|---|
| co-tenant | ↑ (the newcomer adds work) | ↑ |
| host saturation | ↑↑ to the ceiling | ↑↑ |
| **cgroup cap** | **↓** | ↑ |
| healthy | flat | flat |

**The cap is the only case where the host does less work while threads wait more.** No
amount of runqueue-delay thresholding could have found this; it needed the other half of the
scheduler stream.

### The measurement recovers the injected parameter

A validation worth recording. The `noisy_neighbor` recipe caps its stress container at
`CPUS=1.0` (subtle) or `CPUS=2.0` (aggressive). Measured newcomer cores:

| Intensity | Recipe cap | Measured from the trace |
|---|---|---|
| subtle | 1.0 | 0.988, 0.997 |
| aggressive | 2.0 | 1.978, 1.978, 2.002 |

Within ~1% of ground truth, read out of `sched_switch` with no knowledge of the recipe. That
is strong evidence the attribution is correct rather than merely suggestive.

### Why the earlier failures happened

`noisy_neighbor` and `anomaly_cpu` are **the same mechanism at different intensities** — both
run a `stress-ng` container; one is capped at 1–2 CPUs, the other is uncapped at 2× cores.
So the newcomer's *identity* cannot separate them; only how much it takes, and whether the
host runs out. This is why F2 saw 52× runqueue delay on host saturation against 7.12× on the
co-tenant fault: the same signal, harder.

### What this does NOT settle

- **Which service is capped.** `biggest_loser` names the largest victim (`node`, the
  front-end), not the throttled service (`java`/carts, which lost 0.395). Comm-name
  attribution cannot resolve this, and Train Ticket is worse — everything is `java`. The cap
  blueprint can claim *that* a service is throttled, not *which*, until cgroup-aware
  attribution exists.
- **Portability of the absolute thresholds.** All 17 runs are Sock Shop on one 12-CPU host,
  with a conveniently stable ~0.48 baseline. A system that idles at 0.9 would break any
  absolute cut. The *directions* should travel; the numbers must be re-measured on Train
  Ticket before being trusted. That is E3.
- **One normal run had a newcomer** (`python3.12`, 0.296 cores) — well below the 0.99 floor
  of the co-tenant runs, but it shows "a newcomer exists" is not by itself a fault.

---

## F2 — 42% false-positive rate on the negative class, and every false fire is confident

**E1 batch 1**, Sock Shop, 12 runs from five families neither blueprint should claim.
Job 2221923, 27 min, kernel-only packs. Raw: `/scratch/yuvraj17/specificity/`.

| Truth family | n | Correctly quiet | Fired | Verdict it gave |
|---|---|---|---|---|
| `anomaly_cpu` | 3 | 3 | 0 | — (but see margins below) |
| `svc_cpu_cap` | 2 | 2 | 0 | — (but see margins below) |
| `dependency_outage` | 2 | **0** | **2** | `datastore-wait` → `db_latency` on "java", **conf 0.85** |
| `svc_net` | 2 | **0** | **2** | `datastore-wait` → `db_latency` on "node", **conf 0.85** |
| `normal` (no fault) | 3 | 2 | **1** | `cpu-contention` → `noisy_neighbor` on host, **conf 0.80** |

**5 false fires in 12 negatives — 42%.** None abstained; all reported 0.80–0.85 confidence.
The advertised "100% precision, declines when unsure" does not survive contact with a
negative class: correct-decline rate is 7/12 = 58%.

Worst single case: **`normal_none_burst_r1` — a healthy system under a bursty workload — was
diagnosed as a noisy neighbour on the host at 0.80 confidence.** No fault was injected.

### The two rules fail in different ways

**datastore-wait fires on anything that blocks a socket.** It cannot ask *why* a process is
blocked:

| Run | Blocking call | Inflation | Verdict |
|---|---|---|---|
| `slow_db` (its target) | `poll` on mysqld | 36.8× | correct |
| `dependency_outage` | `poll` on java | **89.0×** | wrong |
| `svc_net` | `epoll_pwait` on node | **175.5×** | wrong |

The impostors produce a *stronger* signal than the real thing, so no threshold change can
fix this. It needs a different question: blocked **on what**.

**cpu-contention's positive conditions are met by almost anything that loads the host.**

| Run | rq max | procs inflated | socket veto | Fired? |
|---|---|---|---|---|
| `noisy_neighbor` (its target) | 7.12× | many | 1.5–2.99× | yes, correct |
| `anomaly_cpu` | **36.97–52.54×** | 12 | 10.5–13.7× | no — vetoed |
| `svc_cpu_cap` | 13.54–15.70× | 5–6 | 19.4–19.6× | no — vetoed |
| `normal` burst | 3.69× | 12 | 1.71× | **yes — wrong** |

Host saturation reaches **52×**, seven times the 7.12× of the fault the blueprint was written
from. It stayed quiet only because its socket waits happened to exceed the veto. The healthy
burst run had no such luck — modest runqueue inflation, quiet sockets — so it fired.
**The veto, not the rule, is doing the discrimination, and the veto is not aimed at any of
these causes.**

This confirms F1 as a live defect rather than a theoretical one, and adds the case F1 did not
anticipate: a *healthy* system can satisfy the rule.

### Margins are thin where it matters

`normal_none_steady_r1` measured 2.36× runqueue — over the 2× threshold — and was saved only
by the ≥3-process breadth requirement, having inflated exactly 1 process. Two of three
no-fault runs sit at or above the firing threshold on the primary signal.

### What this says about the next step

Every false fire names a blueprint that does not exist. `dependency_outage` had nowhere to go
but `datastore-wait`; `svc_net` likewise. A two-blueprint library forces every incident into
one of two answers, and mutual veto is the only thing standing in for "none of these".

The fix is not threshold tuning. It is to **build the confusable siblings** and to make
"nothing here matches" a first-class outcome. See `BLUEPRINT-BACKLOG.md`.

---

## F1 — On a CPU cap, both blueprints' positive evidence was satisfied. Only mutual veto kept them quiet.

**Run:** `svc_cpu_cap_aggressive_steady_r1`, Sock Shop. `carts` capped to 0.2 CPU.
**Correct outcome:** neither blueprint fires — a cgroup cap is neither co-tenant contention
nor a slow datastore.
**Observed outcome:** neither fired. Correct — but not for a reason we can rely on.

| Rule | Its positive condition | Measured | Met? | Why it did not fire |
|---|---|---|---|---|
| cpu-contention | runqueue ≥2× on ≥3 processes | **15.7×** on **5** processes, median 1.91× | **yes** | vetoed: socket-wait 19.43× ≥ 5× |
| datastore-wait | a socket call ≥5× | `epoll_pwait` on `java` at **19.43×** | **yes** | vetoed: runqueue 15.7× ≥ 2× |

**Each blueprint was saved only by the other one's signal being loud.** Neither rule
contains anything that recognises "this is a cgroup cap". They are separable from each
other, not from a third cause.

### Why this matters more than a passing test result

1. **Runqueue inflation does not identify co-tenant contention.** The cap produced **15.7×** —
   more than **twice** the 7.12× measured on the actual co-tenant fault the blueprint was
   written from. Magnitude is not the discriminator we assumed it was; if anything it points
   the wrong way.

2. **The silence is accidental.** It depends on this cap being severe enough to inflate
   socket waits past 5×. A milder cap that inflates runqueue past 2× while leaving socket
   waits under 5× would make the **CPU-contention blueprint fire on a CPU cap** — a
   confident wrong answer. `svc_cpu_cap_subtle_*` is exactly that test and is queued.

3. **It does not scale to a library.** With two mutually exclusive blueprints, mutual veto
   covers the gap. Add a third problem whose signature is "high runqueue **and** high socket
   wait" and every one of these vetoes becomes a false negative. The published account of
   this exact mechanism (Gelle et al. 2021, §use case) demonstrates a cgroup limit producing
   threads "waiting on CPU" — so the collision is known, documented, and ours to resolve.

4. **It explains the earlier comparison result differently than we did.** We reported that no
   LLM arm ever typed co-tenant contention correctly, calling it `cpu_saturation` or
   `cpu_throttling`. Given F1, the model was reading a real signal — broad CPU waiting — that
   genuinely does not separate those three causes. The blueprint got the right answer on
   those 5 runs, but this measurement says it did so without holding a rule that
   distinguishes them.

### Hypothesis for the fix — to be measured, not assumed

Co-tenant contention has something a cap and a saturated host do not: **a thief**. A process
consuming substantial on-CPU time during the incident that consumed almost none in the
baseline, and that is not an application component.

That is computable from `sched_switch` alone — on-CPU time per comm, baseline versus
incident — so it stays inside phase 1 and needs no metrics. It would convert the rule from
*"everything is waiting"* (shared with cap and saturation) to *"everything is waiting **and**
here is what took the CPU"* (unique to co-tenant).

The blueprint already asserts this in prose — `problem.discriminators[3]`, "a container
consumes steady CPU it did not consume in the baseline and has NO call-graph edges" — but
sources it from **metrics**, so it is absent from the kernel-only decision rule. The signal
is already in the trace we decode; we simply never extracted it.

Status: **hypothesis.** Not entering the blueprint until measured across all families,
per the measure-first rule. `anomaly_cpu` is the sharp test — a stress-ng host load is also
a foreign process with no call-graph role, so on-CPU share alone may separate co-tenant from
a cap but *not* co-tenant from host saturation.

### Cost note

Kernel-only pack: **279 s** versus 367–539 s for the full pack that also reads spans. Phase-1
scoping cut analysis time roughly in half, and neither blueprint's fire decision used the
span-derived field.
