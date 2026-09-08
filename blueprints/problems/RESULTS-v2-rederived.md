# Re-derived thresholds — before and after, on the same 136 v2 runs

7 September 2026. Same packs, same runs, same scorer; only `blueprint_decide.py` changed.

## Result

| blueprint | before | after | Sock Shop | Train Ticket |
|---|---|---|---|---|
| `host-cpu-saturation` | 10/10, 0 FP | **10/10, 0 FP** | 5/5 | 5/5 |
| `host-disk-saturation` | 1/10, 0 FP | **10/10, 0 FP** | 5/5 | 5/5 |
| `service-memory-cap` | 3/16, 0 FP | **16/16, 0 FP** | 8/8 | 8/8 |
| `cpu-contention-co-tenant` | 8/16, 0 FP | **16/16, 0 FP** | 8/8 | 8/8 |
| `network-path-degradation` | 22/26, 2 FP | 22/26, 2 FP | 13/13 | 9/13 |
| `datastore-wait` | 9/22, 1 FP | 9/22, 1 FP | 8/11 | 1/11 |
| `service-cpu-throttle` | 5/16, 0 FP | 5/16, 0 FP | 5/8 | 0/8 |

**Recall 58/116 → 88/116 (50% → 76%).** False fires 3 → 3.

**Four of seven blueprints now score 100% with zero false fires, and score *identically* on both
applications.** That is the property that was missing: the library measured 71% on Sock Shop
against 29% on Train Ticket because every threshold had been read off Sock Shop alone.

Runs with no verdict fell from 76 to 48. Twenty of those are `normal` and correctly silent, and
20 more are faults the campaign could not confirm either — leaving about 8 genuinely unanswered.

## What changed, and why each is a measurement and not a tune

### `host-disk-saturation`: an arrival count → a ratio

`DISK_IOPS_GAINED = 2000` came from Sock Shop v1 and scored 1/10. Sock Shop's disk fault gains
1893–2015 req/s, so exactly one run cleared the bar. Train Ticket's gains 698–897, because TT's
own tracing already writes 176 MB/s of a 206 MB/s disk — the instrument caps how large the fault
can be. **No arrival count can hold both.**

The real problem is that `anomaly_disk` and `svc_mem_cap` overlap, and **in opposite directions
on the two applications**:

| | separates them on | overlaps on |
|---|---|---|
| disk arrivals | Sock Shop (1893–2015 vs 287–873) | Train Ticket |
| interrupt time | Train Ticket (1.18–1.49 vs 2.73–5.55) | Sock Shop |

Both faults raise both numbers. What differs is the **mix** — a disk flood is many requests per
unit of interrupt rise; reclaim inside one cgroup is the reverse:

| `iops_gained / hardirq_x` | `anomaly_disk` | `svc_mem_cap` |
|---|---|---|
| Sock Shop | 568.3 – 719.1 | 62.6 – 234.7 |
| Train Ticket | 545.8 – 602.0 | 136.3 – 352.4 |

Highest negative anywhere 352.4, lowest positive 545.8. **`DISK_IOPS_PER_IRQ = 450`** sits at the
midpoint with margin either side, and holds both applications.

### `service-memory-cap`: the veto was eating its own family

`IRQ_X = 2.5 AND iops_gained < 500`. The second half is what broke it: Sock Shop memcap gains a
median 553 req/s and Train Ticket 1033, so **most runs of the family this rule owns were vetoed
by their own disk activity.** 3/16.

Replacing that veto with the same ratio, and lowering `IRQ_X` to **2.0** — once the disk fault is
excluded, the highest non-disk negative is 1.19 against memcap floors of 3.21 and 2.73 — gives
16/16 on both applications.

### `cpu-contention-co-tenant`: an absolute level → a delta, plus one veto

`CONTENDED = 0.55` inverts on Train Ticket (fault 0.213–0.282, healthy 0.657–0.710). Removed.

Removing it took recall to 16/16 **and produced 7 false fires**, all Train Ticket `svc_mem_cap`.
That is not a regression the change caused — it is a confusion the change *revealed*. A container
against its memory limit runs a stress tool that eats a core, so it presents a thief in exactly
the co-tenant band. `LATENCY-CAUSES` lists "memory stress → CPU" as a known look-alike and blames
three earlier wrong answers on it. The old `busy` clause hid it on Train Ticket only because TT
utilisation sits below 0.55 — luck, not discrimination, bought at the price of all eight true
positives.

The fix is the memory-cap signature itself, now measured and clean on both applications: interrupt
time up with few disk requests per unit of that rise. It cannot touch a real co-tenant run —
`noisy_neighbor` measures hardirq 0.74–0.91 and 0.91–1.18, far below `IRQ_X`. Same shape as the
retransmission veto the datastore rule already carries: **where two faults share a signature, the
one with the sharper discriminator vetoes the other.**

## What was deliberately not changed

`service-cpu-throttle` (5/16) and `datastore-wait` (9/22) keep their thresholds.

**Train Ticket has zero campaign-confirmed runs for either `svc_cpu_cap` or `slow_db`**, so there
is nothing to validate a cross-application cut against. And no single signal separates either
family on Sock Shop alone — `util_ratio`, `loser_cores`, `rq_max` and `thief_cores` all overlap,
which is why the shipped rule uses a four-way conjunction.

Tuning them on one application is precisely the mistake this exercise exists to undo. They stay
as they are until Train Ticket's verdicts are calibrated (CAMPAIGN-ISSUES 13).

## One signal that must never ship

`softirq_x` for `svc_mem_cap` points in **opposite directions** on the two applications:

| | Sock Shop | Train Ticket | healthy range |
|---|---|---|---|
| `svc_mem_cap` softirq_x | 0.71 – 0.80 | 1.55 – 7.42 | ~1.0 |

Below healthy on one, far above on the other. On either application alone it would have looked
like a clean discriminator with a 7x separation. This is the concrete case for the rule that a
discriminator does not enter a blueprint until it has been checked on both applications.

## Reproducing

```bash
python blueprints/lib/derive_v2_thresholds.py \
    --packs /scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs \
    --tasks blueprints/lib/tasks-v2-latency.txt
```

Cuts are placed against the other families' extreme, never fitted to the positives, and a cut
that works on one application is reported as failing rather than averaged.
