# Phase 1 findings — kernel traces only

Running log of what the specificity work (E1) actually shows. Newest first.
Protocol: `RESEARCH-PLAN-phase1-kernel.md`.

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
