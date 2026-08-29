# Phase 1 findings — kernel traces only

Running log of what the specificity work (E1) actually shows. Newest first.
Protocol: `RESEARCH-PLAN-phase1-kernel.md`.

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
