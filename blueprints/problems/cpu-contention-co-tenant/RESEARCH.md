# Research dossier — co-tenant CPU contention

What the literature establishes, what we measured ourselves, and what is still open.
Phase 1 (kernel traces only). Written 2026-08-29.

Companion to `blueprint.json`. The blueprint carries the claims; this file carries the
reasoning and the citations behind them.

---

## 1. The signal

A thread becomes runnable (`sched_waking`), then waits until a CPU actually runs it
(`sched_switch` with `next_tid`). The gap is **runqueue delay**.

It answers a question utilisation cannot: *the service is not busy, so why is it slow?*
Under co-tenant contention the service is never busy — it is repeatedly ready and repeatedly
made to wait. CPU utilisation of the container stays flat or falls, which is why dashboards
look normal.

Two tracepoints, nothing else.

---

## 2. What the literature actually says — and a gap worth knowing about

We searched all **71 papers** in `DOCS/reading-papers/` (the full reading tracker corpus).

| Term | Papers mentioning it |
|---|---|
| "runqueue" / "run queue" | **0** |
| "scheduling latency" / "scheduler latency" | **0** |
| "waiting on/for CPU" | **1** — Gelle et al. 2021 |
| "PREEMPTED" | 2 — Gelle et al. 2021, Gebai & Dagenais 2018 |
| "cpu steal" | 1 — MicroCause |

**The microservice RCA literature does not use this signal.** RCAEval (735 failure cases,
11 fault types), LEMMA-RCA, Nezha, Eadro, BARO, MicroRCA and the rest all work on metrics,
logs and spans. None of them read the scheduler.

This cuts both ways and both need saying:

- **It is why we have something to contribute.** Our measured result — every LLM arm scored
  0/5 on co-tenant contention while the blueprint scored 5/5 — is consistent with a signal
  the field has not been using.
- **It also means nobody has stress-tested it for us.** There is no published false-positive
  rate for runqueue delay as an RCA discriminator. Whatever specificity it has, we have to
  measure ourselves. That is E1.

### The one paper that covers this ground

**Gelle, Ezzati-Jivan & Dagenais, "Combining Distributed and Kernel Tracing for Performance
Analysis of Cloud Applications", Electronics 10(21):2610, 2021.**
(`DOCS/reading-papers/electronics-10-02610.pdf`)

Directly relevant, and by our own supervisor. What it establishes:

- Distributed tracing "cannot explain why some subrequests are too long when this is caused
  by operating-system level contention — waiting on CPU, disk, network or mutexes."
  That is our blind-spot argument, already published.
- Their critical-path analysis assigns each thread state one of RUNNING, **PREEMPTED**,
  BLOCK_DEVICE, NETWORK, TIMER, USER_INPUT, INTERRUPTED. **PREEMPTED is waiting-for-CPU** —
  the same phenomenon our runqueue delay measures, reached by a different construction.
- Their worked example is a **cgroup CPU limit**: threads show as "waiting on CPU", requests
  jump from ~5 ms to ~2 s, and CPU becomes *underused* when the limit engages.

That last point matters to us directly. Their demonstration is the mechanism of our
`svc_cpu_cap` family, not our `noisy_neighbor` family — and both produce "threads waiting
for CPU". **That is precisely the confusion E1 is built to detect.** The published work
shows the signal appears; it does not show the signal *separates* the two causes.

### The lineage we should read next — currently missing from the tracker

Cited by that paper, none present in `reading_tracker.csv`:

| Work | Why it matters here |
|---|---|
| Giraldeau & Dagenais, "Wait analysis of distributed systems using kernel tracing", IEEE TPDS 2016 | the wait-analysis method our approach descends from |
| Zhou et al., **wPerf**, OSDI 2018 | generic off-CPU analysis to identify bottleneck waiting events — the closest thing to a principled version of our discriminator |
| Ezzati-Jivan et al., **DepGraph**, SCAM 2020 | waiting dependency graphs; attributing a wait to who caused it, which is our weakest step |

Added to the reading tracker as phase-1 priority reads.

---

## 3. The methodological lesson we learned the hard way — and that this literature predicted

Our v1 blueprint claimed the delayed services show a raised `runnable_wait` **share**. It was
false: across 93 runs it never exceeds 4% in any fault family, and was 1.6% on the
co-tenant run itself. The reason is dilution — a share of wall time is swamped by ordinary
idle waiting, so every service looks the same.

The Gelle paper computes waiting states **along a request's critical path**, not as a share
of an interval. That distinction is exactly what saves it from the dilution we hit. Our fix
went the other way — from shares to **per-wakeup latency** — and works for the same
underlying reason: measure per-event, never per-interval-share.

Worth recording as a general rule for future blueprints: *a share of wall time is almost
always the wrong statistic in a mostly-idle system.*

There is also an unexplored option here. Per-request critical path is a third construction,
between our per-wakeup latency and the discredited per-interval share. It attributes the
wait to a request rather than a thread, which is what makes it explainable to a service
owner. Not needed for phase 1, but it is the natural bridge when spans re-enter in phase 2.

---

## 4. What we measured

From raw L0 via babeltrace2. Full numbers in `evidence/`.

| Signal | Co-tenant | Slow-datastore control |
|---|---|---|
| Runqueue delay, busiest app process p95 | **7.12×** (n=48,886) | 0.97× |
| Runqueue delay, median across high-volume processes | **1.78×** | 0.84× |
| Max socket-waiting syscall inflation | 1.5–2.99× (5 runs) | 36.83× |
| Call-graph convergence | none (max 1.7×, 0 slow edges) | 717.7× |
| Co-tenant container CPU | 0.00 → 2.00 cores | — |
| Host CPU | 5.31 → 7.96 cores (×1.5, **not exhausted**) | — |

Refinement found only by testing more runs: **general syscalls lengthen under CPU starvation
too**, because the thread is descheduled inside them — `connect()` reached 5.3× and wrongly
vetoed the verdict. Only *socket-waiting* calls may be used as the veto. This is the kind of
error that one run cannot reveal and five can.

Retracted claims are kept in `blueprint.json` under `problem.unverified_do_not_claim`.

---

## 5. Open questions this dossier cannot yet answer

These are the reliability questions, and none of them are answered by the evidence above.

1. **Does it fire on host CPU saturation (`anomaly_cpu`)?** Mechanically it should — a
   saturated host also makes threads wait. If it does, "runqueue delay is high" is not
   sufficient and the blueprint needs a second, separating signal.
2. **Does it fire on a cgroup cap (`svc_cpu_cap`)?** The published use case above is exactly
   this, and it reports threads waiting on CPU. The likely separator is *breadth*: a cap
   delays one service, a co-tenant delays many. The rule already requires ≥3 inflated
   processes, but that number was chosen, not measured.
3. **Does it stay quiet on a healthy run?** Never tested. The 2× threshold has no measured
   false-positive rate.
4. **How much of the 2× threshold is Sock Shop's architecture?** The datastore blueprint's
   equivalent constant did not transfer to Train Ticket. There is no reason to assume this
   one is safer.

E1 answers 1–3 directly. E3 answers 4.

---

## 6. Honest limitations

- One labelled co-tenant run drove the original discriminators; five now inform the
  socket-wait veto. Still small.
- Attribution is by process name — workable on Sock Shop, ambiguous on Train Ticket where
  every service reports `java`.
- The host-attributed nature of this fault means there is no culprit-side L2 record at all,
  so the container-level "who took the CPU" step depends on metrics, which phase 1 excludes.
