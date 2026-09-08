# Blueprint 1 (CPU family) on v2 — 62 runs, two applications

Measured 7 September 2026. Job `2274153`, 20 minutes on one 192-core node.

This retires the blueprint's stated limit — *"one run per family so far"* — by re-running the
four-way CPU separation on every v2 repeat of every relevant family, on **both** applications.
The v1 thresholds were read off 17 Sock Shop runs.

Thresholds were **imported** from `blueprint_decide.py`, not copied, so this scores the rules
that actually ship.

## The scores

| rule | recall | false fires | Sock Shop | Train Ticket |
|---|---|---|---|---|
| `host-cpu-saturation` | **10/10 (100%)** | **0/52** | 5/5 | 5/5 |
| `cpu-contention` **as shipped** | 8/16 (50%) | 0/46 | **8/8** | **0/8** |
| `cpu-contention` thief-only | **16/16 (100%)** | **0/46** | 8/8 | 8/8 |
| `service-cpu-throttle` | unscorable | — | — | — |

`service-cpu-throttle` needs runqueue delay for its `waiting_for_cpu` clause and only on-CPU
attribution was measured. Reported unscorable rather than counted as 62 misses.

## What holds

**`SATURATED = 0.95` is application-independent.** `anomaly_cpu` measured 0.993–0.998 on both
applications; the next family down tops out at 0.889. Ten out of ten, zero false fires in 52
negatives. This threshold is earned.

**The thief signal is perfect.** `stress-ng-cpu` was identified as the newcomer in all 26 runs
of the two stress families and in none of the 36 others. `BIG_THIEF = 4.0` separates host
saturation (6.34–6.49 cores on Sock Shop, 9.49–9.80 on Train Ticket — it has 16 CPUs) from
co-tenant (0.99–2.00 on both) with a wide margin.

## What breaks, and why

**`CONTENDED = 0.55` fails on Train Ticket — it measures the machine, not the fault.**

The co-tenant rule requires `util_incident >= 0.55`. On Train Ticket:

| | utilisation |
|---|---|
| `noisy_neighbor` during the fault | 0.213–0.282 — **below** the threshold |
| `normal`, no fault at all | 0.657–0.710 — **above** it |

The ordering is *inverted*. Applied to Train Ticket the clause would call every healthy run
contended and every genuinely contended run healthy. It survives here only because the other
clauses (`has_thief`) veto the false fires — so the rule fails safe rather than fails loud,
which is worse for finding it.

Dropping `busy` and keeping the thief test takes recall from 50% to **100% with no new false
fires**. That is not threshold-tuning: an absolute utilisation floor measured on a 12-vCPU
Sock Shop host cannot transfer to a 16-vCPU host running 40 JVMs. The thief measurement is a
**delta**, and deltas travel.

**Caveat on that recommendation.** The 46 negatives here are three families. The `busy` clause
presumably guarded against a small thief appearing on an otherwise idle host, and this test set
does not contain that case. Before changing the shipped rule, score thief-only against all 20+
v2 families as negatives.

## The finding that is not about the blueprint

**Baseline host utilisation drifted during the v2 campaign, on both applications, in opposite
directions.** Ordering every run by collection time:

**Train Ticket — a sharp step, 4.6×:**

| collected | families | baseline util |
|---|---|---|
| 07:37 – 12:02, 5 Sept | `normal`, `anomaly_cpu` | 0.626 – 0.709 |
| 18:08 onward | `noisy_neighbor`, `svc_cpu_cap` | **0.138 – 0.145** |

**Sock Shop — a gradual rise, 1.6×:** 0.514 → 0.549 (`normal`) → 0.567–0.592 (`noisy_neighbor`,
5 Sept) → 0.609–0.624 (`svc_cpu_cap`) → **0.794–0.814** (the 6 Sept re-collected runs).

The split falls on **collection time, not on family**. Two consequences:

1. **Any threshold on absolute host utilisation is measuring when a run was collected.** This is
   exactly what broke `CONTENDED`, and it would break any similar rule in a future blueprint.
2. **A fault's measured magnitude depends on when it ran.** Sock Shop `svc_cpu_cap` collapsed to
   0.25× of baseline on 5 September and only 0.87× on 6 September — same recipe, same intensity.
   Cross-run comparisons of effect size on Sock Shop need the collection time stated.

The cause is not established. The Train Ticket step falls in the gap where the campaign was
stopped, reset and restarted (CAMPAIGN-ISSUES issue 17), which is suggestive but not evidence.
Recorded as an open question rather than an explanation.

## Reproducing

```bash
python blueprints/lib/v2_tasks.py --families noisy_neighbor,anomaly_cpu,svc_cpu_cap,normal \
    --out blueprints/lib/tasks-v2-cpu.txt
sbatch blueprints/lib/cluster-v2_cpu.sbatch
python blueprints/lib/score_v2_cpu.py \
    --oncpu /scratch/yuvraj17/stratatrace/results/v2-blueprint1-cpu/oncpu \
    --tasks blueprints/lib/tasks-v2-cpu.txt
```

Per-run numbers: `results/v2-blueprint1-cpu/scored_v2.json`.

## Next

1. Measure runqueue delay over the same 62 runs so `service-cpu-throttle` can be scored. Its
   `COLLAPSE_RATIO` rule is the one most exposed to the drift above.
2. Score thief-only against **all** v2 families as negatives before changing the shipped rule.
3. Then blueprint 2 (`db-latency-dependency-wait`), whose `BLOCK_X = 5.0` was measured on a
   single run pair.
