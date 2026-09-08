# Deciding without thresholds — measured against the hardcoded rules

8 September 2026. Same 136 packs, same runs, same ground truth. Only the decision layer differs.

## The two approaches, side by side

| | hardcoded rules (re-derived) | profile, threshold-free |
|---|---|---|
| recall | **88/116 (76%)** | 82/116 (71%) |
| false fires | **3/826 (0.4%)** | 38/826 (4.6%) |
| runs with no verdict | 48 | **16** |
| ambiguous runs | 3 | **0** |
| per-signal magnitudes | **12** | **1** |

Per blueprint:

| blueprint | rules | profile | | rules SS/TT | profile SS/TT |
|---|---|---|---|---|---|
| `host-cpu-saturation` | 10/10, 0 FP | 10/10, 0 FP | = | 5/5 · 5/5 | 5/5 · 5/5 |
| `host-disk-saturation` | 10/10, 0 FP | 10/10, **20 FP** | worse | 5/5 · 5/5 | 5/5 · 5/5 |
| `service-memory-cap` | 16/16, 0 FP | 9/16, 5 FP | worse | 8/8 · 8/8 | 7/8 · 2/8 |
| `cpu-contention-co-tenant` | 16/16, 0 FP | 12/16, 0 FP | worse | 8/8 · 8/8 | 4/8 · 8/8 |
| `network-path-degradation` | 22/26, 2 FP | 22/26, 10 FP | worse | 13/13 · 9/13 | 13/13 · 9/13 |
| `service-cpu-throttle` | 5/16, 0 FP | 8/16, 2 FP | **better** | 5/8 · 0/8 | 8/8 · 0/8 |
| `datastore-wait` | 9/22, 1 FP | 11/22, 1 FP | **better** | 8/11 · 1/11 | 9/11 · 2/11 |

## The answer

**As a replacement, the threshold-free form is worse.** Slightly lower recall and twelve times
the false fires. It should not ship as the decision layer.

**As a hint layer, it is better at the thing it was built for.** Every run gets exactly one
candidate or none — no ambiguity at all, against 3 ambiguous for the rules — and it needs one
magnitude instead of twelve, so it carries to a new deployment without re-measurement. Two
blueprints it actually improves are the two the hardcoded rules could not fix, because Train
Ticket has no confirmed runs to calibrate against.

That is the division of labour to build on: **the rules are the deterministic baseline the thesis
already promises; the profile is what an agent should be handed.** Neither replaces the other.

## What the constants collapsed to

Twelve deployment-specific numbers became:

- `Z_ANOMALOUS = 3.0` — how many sigma counts as moved. Dimensionless, one value for every
  signal and both applications.
- `MATCH_MIN = 0.60` — how much of a signature must match.
- `SATURATED = 0.95` — the one surviving absolute, and the reason it survives is the finding
  below.

## Finding: not all constants are equally fragile

`CONTENDED = 0.55` failed because it encoded a **deployment's typical level** — different per
host, and it drifted 4.6× during our own collection.

`SATURATED = 0.95` holds because it encodes a **physical bound**: utilisation cannot exceed 1.0,
so "within 5% of the ceiling" means the same on a 12-vCPU host and a 16-vCPU one. Measured:
`anomaly_cpu` 0.993–0.998 on both applications, nothing else above 0.889.

This is a sharper claim than "thresholds are bad", and it is testable: **a constant tied to a
physical bound transfers; a constant tied to a deployment's normal level does not.**

## Finding: which reference a signal needs is a property of the signal

Three kinds emerged, and picking the wrong one destroys the signal:

| healthy behaviour | right test | example |
|---|---|---|
| varies with a stable spread | sigma against median/MAD | `hardirq_x`, `util_ratio` |
| **invariant** | **presence** — did it move at all, in the expected direction | `thief_cores`, always exactly 0.0 healthy |
| both faults move it the same way | **comparison** — is this signal more anomalous than that one | `iops_per_irq` vs `hardirq_x` |

The third kind is what replaced `DISK_IOPS_PER_IRQ = 450`: *"the interrupt rise outruns the
arrivals"* says the same thing as the number, without the number.

## Where the threshold-free form breaks, and why

`host-disk-saturation` false-fires on 20 Train Ticket runs. `iops_gained` is invariant at 0 on
healthy Train Ticket, so the presence test fires on *any* disk activity — and `svc_cpu_cap`
(82–131), `svc_net` (29–132) and `slow_db` (0–206) all produce some.

The presence test is decisive only when the fault produces a deviation **and the look-alikes
produce none**. That holds for `thief_cores` and fails for `iops_gained`. It is a
characterisable limit, not a tuning problem.

## The design took five passes, and that is a result

Each failure was specific and none was obvious in advance:

1. **`flat` counted as evidence** → `datastore-wait` fired on 14 of 20 healthy runs. Absence of
   a contradicting signal is not evidence *for* a diagnosis.
2. **Directions written relative to a look-alike, not to healthy** → `service-memory-cap` 0/16,
   because `iops_per_irq` is *up* against healthy and only *down* against the disk fault.
3. **Zero-variance signals skipped as unmeasurable** → both CPU rules to 0, because
   `thief_cores` is the library's most reliable signal and is invariant in healthy runs.
4. **"Not saturated" written as `flat`** → `cpu-contention` 0/16, vetoing its own signature,
   since contention raises utilisation by design.
5. **Everything above a bar reported, instead of top-1** → 116 of 136 runs ambiguous.

Worth recording because it says the threshold-free form is **harder to get right than it looks**.
The hardcoded rules are wrong in a way you can see; a profile matcher is wrong in ways that need
136 labelled runs to detect. Any claim that removing thresholds makes a blueprint portable has to
account for that.

## Reproducing

```bash
python blueprints/lib/profile_decide.py \
    --packs /scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs \
    --tasks blueprints/lib/tasks-v2-latency.txt

# one run as an agent would be handed it
python blueprints/lib/profile_decide.py --packs <dir> --tasks <file> \
    --agent-view tt_slow_db_aggressive_steady_r1
```
