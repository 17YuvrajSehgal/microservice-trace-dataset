# Which blueprints are missing, and which of them we can actually build

Measured 13 September 2026 over all 272 v2 packs, 25 fault families, 45 signals.
Reproduce: `python3 blueprints/lib/sweep_uncovered.py --packs <packs>`

---

## The short answer

**11 families have a blueprint. 13 do not — 106 runs.**

But the more useful answer is that **we cannot write 13 more blueprints.** The data does not
support them. Only two are worth attempting, and both need a per-deployment reference rather
than a shipped number.

---

## What we have

| family | runs | apps | blueprint |
|---|---|---|---|
| `slow_db` | 22 | 2 | db-latency-dependency-wait |
| `anomaly_net` | 16 | 2 | network-path-degradation |
| `noisy_neighbor` | 16 | 2 | cpu-contention-co-tenant |
| `svc_cpu_cap` | 16 | 2 | service-cpu-throttle |
| `svc_mem_cap` | 16 | 2 | service-memory-cap |
| `anomaly_cpu` | 10 | 2 | host-cpu-saturation |
| `anomaly_disk` | 10 | 2 | host-disk-saturation |
| `data_exfiltration` | 10 | 2 | data-exfiltration |
| `fd_exhaustion` | 10 | 2 | fd-exhaustion |
| `fork_storm` | 10 | 2 | fork-storm |
| `svc_net` | 10 | 2 | network-path-degradation |

Plus 20 `normal` control runs.

---

## What is missing, and whether it is buildable

A signal counts only if one cut holds on **both** applications with every other family as a
negative. A cut that works on one deployment tells you nothing about whether you found a
property of the fault or a property of the machine.

### Worth attempting — 2 families, 20 runs

| family | runs | apps | the signal | status |
|---|---|---|---|---|
| `priority_inversion` | 10 | 2 | share of threads at a non-default priority | separates at **2.55x**, but the cut differs per application |
| `lock_contention` | 10 | 2 | short futex waits | clean band **within** each application, no shared band |

Both are exactly the cases Naser named as the most interesting. Both are buildable **with a
per-deployment reference** — the `profile_decide.py` approach, where the bar comes from that
deployment's own healthy runs instead of from a constant we ship.

`priority_inversion` also shows a band on `error_newcomer_per_s` (1218–1299) that does hold
across both applications. **Do not use it.** It is fitted to the positives' own range, it has
no margin, and there is no mechanism connecting an error rate to priority inversion. It is
what overfitting looks like.

### Not buildable from what we have — 11 families, 86 runs

| family | runs | apps | what we tried |
|---|---|---|---|
| `anomaly_mem` | 16 | 2 | separates on `thief_share` **per application only**. Also the cause of 15 of our 19 remaining false fires — it is inseparable from `svc_mem_cap` |
| `conn_pool_exhaustion` | 10 | 2 | nothing, across all 45 signals |
| `deadlock` | 10 | 2 | nothing. Futex shape was the hypothesis and it does not hold |
| `resource_abuse` | 10 | 2 | per application only. It runs a hidden CPU loop, so it is probably not separable from `noisy_neighbor` at all |
| `nagle_delayed_ack` | 10 | 2 | best shared cut is **1.08x** — too thin. And one of the two candidates was `iops_per_irq`, which for this family is our own tracer's disk writes (CAMPAIGN-ISSUES 16), so it is an artifact, not a signal |
| `code_event_loop_block` | 5 | 1 | nothing |
| `code_lock_across_io` | 5 | 1 | nothing |
| `code_n_plus_one` | 5 | 1 | nothing |
| `code_serial_awaits` | 5 | 1 | nothing |
| `code_unbounded_cache` | 5 | 1 | nothing |
| `dns_delay` | 5 | 1 | nothing |

---

## Two things worth knowing about that table

### The five code defects do not separate from each other, and grouping does not rescue them

Each of the five has to separate from the other four, and they are the same kind of fault.
So I tested them as **one group** — "a defect in the calling service" as a single blueprint
covering five faults. That also fails: the only thing that separates the group is a band
fitted to its own range on one application.

This does **not** contradict the anti-pattern ceiling added on 13 Sept. That ceiling
(`socket_block_x < 306`) is a **veto** — it stops the datastore blueprint claiming a healthy
datastore when the caller is at fault. It is not a **detector**: `dns_delay`, `fd_exhaustion`
and `conn_pool_exhaustion` also park the caller, so a high value says "not the datastore",
never "a code defect". Those are different claims and only the first is supported.

### Six of the thirteen were collected on one application only

`dns_delay` and all five `code_*` families are Sock Shop only. They can never satisfy the
two-application rule as things stand — that is a **collection gap, not an analysis gap**.
`dns_delay` has a reason: Train Ticket makes no DNS queries. The code defects do not; the
recipes were written against Sock Shop's services.

**If we want blueprints for those six, the next step is collection, not analysis.**

---

## What this means for the plan

The todo list assumed the next step was writing more blueprints. The measurement says
otherwise:

- **11 of 13 missing families have no portable signal.** Adding blueprints for them would mean
  shipping thresholds we have already proved do not transfer.
- **2 are worth attempting**, and both need the per-deployment reference rather than a constant.
- **6 need collection on a second application** before they can even be assessed.

Naser asked for negative results, twice. This is one: **kernel traces alone do not separate
most of the remaining fault families**, and we can now say exactly which and on what evidence.

The effort is better spent on the two open items that do not depend on new blueprints:

1. **The with/without agent comparison** (H1). Everything measured so far is the rule engine.
   The blueprints have never been tested in the hands of an agent, which is what they are for.
2. **`service-memory-cap` re-derived against `anomaly_mem`**, or recorded as inseparable. That
   single pair is 15 of the 19 remaining false fires.
