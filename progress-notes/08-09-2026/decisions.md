# 8 September 2026 — decisions

## Context

The v2 dataset is on Trillium and extracted. First real test of the blueprint library against it.

---

## 1. Tested all seven blueprints, and separated two kinds of miss

136 runs, both applications, kernel traces only. One evidence pack per run — seven measurements
from one trace decode, because seven separate decodes is ~26 min per run against ~7 min shared.

Raw recall was 58/116. But **not every miss is the rules' fault**: a fault the campaign itself
could not confirm is one a blueprint is right to decline. Cross-checking every non-fire against
that run's own `verification.json` split 58 misses into **36 real** and **22 defensible**.
Corrected recall 62%, not 50%.

Reporting the raw number alone would have blamed the rules for faults that never landed. This
check is now the default before any blueprint score is quoted.

## 2. The pattern under everything: 71% on one application, 29% on the other

Every threshold in `blueprint_decide.py` was read off Sock Shop v1. The one exception,
`host-cpu-saturation`, scored 5/5 on both — and it is the only rule keyed on a quantity with a
physical ceiling.

That observation turned out to be the whole finding of the day (§5).

## 3. Re-derived the thresholds from v2, and the ratio was the answer

`anomaly_disk` and `svc_mem_cap` overlap **in opposite directions on the two applications**:
arrivals separate them on Sock Shop, interrupt time on Train Ticket. Neither works alone.

Both faults raise both numbers. What differs is the **mix**:

| `iops_gained / hardirq_x` | `anomaly_disk` | `svc_mem_cap` |
|---|---|---|
| Sock Shop | 568–719 | 63–235 |
| Train Ticket | 546–602 | 136–352 |

One cut at 450 holds both. That single ratio fixed two blueprints:
`host-disk-saturation` 1/10 → 10/10, `service-memory-cap` 3/16 → 16/16.

Recall overall 50% → 76%, false fires unchanged at 3 in 826. **Four of seven blueprints now score
100% with zero false fires and identically on both applications.**

**Cuts were placed against the other families' extreme, never fitted to the positives.** Fitting
to the positives is how a threshold ends up describing one deployment.

## 4. Removing a clause revealed a confusion rather than causing one

Dropping `CONTENDED = 0.55` took co-tenant recall to 16/16 and produced 7 false fires, all Train
Ticket `svc_mem_cap`. That is not a regression: a memory-capped container runs a stress tool that
**eats a core**, so it presents as a co-tenant. The old clause hid it on Train Ticket only because
TT utilisation sits below 0.55 — luck, not discrimination, bought at the price of eight true
positives.

Vetoing with the now-clean memory-cap signature removed all seven without touching a real
co-tenant run.

## 5. The finding worth taking to the thesis: not all constants are equally fragile

`CONTENDED = 0.55` failed because it encoded a **deployment's typical level** — different per
host, and it drifted 4.6× during our own collection.

`SATURATED = 0.95` holds because it encodes a **physical bound**: utilisation cannot exceed 1.0,
so "within 5% of the ceiling" means the same on a 12-vCPU host and a 16-vCPU one.

That is sharper and more testable than "thresholds are bad".

## 6. Train Ticket `slow_db` is not metrics-blind in the way the note assumed

The calibration note said these faults are metrics-blind and the **kernel** carries them. The
first half is right. The second needed checking, and the answer is more specific:

| `socket_block_x >= 5` | Sock Shop | Train Ticket |
|---|---|---|
| `slow_db` | 11/11 | 1/11 |
| `anomaly_net` | 8/8 | 0/8 |

**Process-level socket blocking is a Sock Shop signal only.** Train Ticket reports all ~40 Java
services as one comm, `java`, so the blocked service's p95 is averaged into thirty-nine idle
peers. The endpoint measurement, which keys on address/port rather than process name, sees the
same runs at 10.3–4836×.

The fault is visible. The instrument was looking through the wrong lens. This is the same trap
already documented for futex — *"idle parking drowns the total"* — in a new place, and it is a
general property of JVM fleets rather than a quirk of this deployment.

Also fixed a verdict that reported seven of those runs as *"runqueue delay 1.41x indicates CPU
starvation"* with runqueue delay flat at 1.0–1.6×. A verdict naming the wrong cause is worse than
one that says nothing.

## 7. Threshold-free deciding: worse as a replacement, better as a hint layer

| | hardcoded rules | profile |
|---|---|---|
| recall | 76% | 71% |
| false fires | 0.4% | 4.6% |
| ambiguous runs | 3 | **0** |
| per-signal magnitudes | 12 | **1** |

It should not ship as the decision layer. It is better at what it was built for: one candidate
per run or none, and one magnitude instead of twelve, so it carries to a new deployment without
re-measurement. The two blueprints it improves are the two the hardcoded rules could not fix.

**The division of labour:** the rules are the deterministic baseline the thesis already promises;
the profile is what an agent should be handed.

**Which reference a signal needs is a property of the signal.** Sigma when healthy varies with a
stable spread; **presence** when healthy is invariant (`thief_cores` is exactly 0.0 in every
healthy run); **comparison** between two signals when both faults move one the same way.

## 8. The design took five passes, and that is a result

Each failure was specific and none was obvious in advance: `flat` counting as evidence (fired on
14 of 20 healthy runs), directions written against a look-alike instead of healthy (0/16),
zero-variance signals discarded (both CPU rules to 0), "not saturated" written as "flat" (0/16),
and reporting everything above a bar instead of top-1 (116 of 136 ambiguous).

The hardcoded rules are wrong in ways you can see. A profile matcher is wrong in ways that need
136 labelled runs to detect. Any claim that removing thresholds makes a blueprint portable has to
account for that.

## Still open

- `service-cpu-throttle` and `datastore-wait` cannot be re-derived: Train Ticket has **zero**
  campaign-confirmed runs for `svc_cpu_cap` or `slow_db`, so nothing validates a cross-application
  cut, and no single signal separates either on Sock Shop alone.
- The with/without agent comparison has not been run on v2. Everything above is the rule engine.
- `fault_catalog.md` pre-registration for the 15 new families.
