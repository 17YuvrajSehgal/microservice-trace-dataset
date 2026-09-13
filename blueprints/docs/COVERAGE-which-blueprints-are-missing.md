# Which blueprints are missing, and which of them we can actually build

Measured 13 September 2026 over all 272 v2 packs, 25 fault families, 45 signals.
Reproduce: `python3 blueprints/lib/sweep_uncovered.py --packs <packs>`

---

## The short answer

**12 families have a blueprint. 12 do not — 101 runs.**

*(Updated 13 Sept: `dns-delay` written, after the re-run below showed the original verdict was wrong.)*

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

---

# Re-run, 13 Sept: the six single-application families

Yuvraj pushed back on the "no signal" verdict for these six. He was right, and for five of
them the reason is that **the data is broken, not the analysis**.

## The first test was unfair, and then the second one found the real problem

Two things were wrong with how I tested these six:

1. I required a cut to hold on **two applications**. These exist on one. They could never pass.
2. I required each code defect to separate from **the other four code defects**, which are the
   same kind of fault.

So I re-ran without either constraint, and instead of guessing signals, walked **every numeric
field in the pack** and compared each family's median against the healthy control.

## What that turned up: the baselines are contaminated

| family | retransmission in the BASELINE window | runs affected |
|---|---|---|
| `code_lock_across_io` | 65.4 - 73.2% | 5 of 5 |
| `code_n_plus_one` | 34.7 - 79.9% | 5 of 5 |
| `code_serial_awaits` | 30.4 - 71.2% | 5 of 5 |
| `code_event_loop_block` | 28.6 - 61.4% | 5 of 5 |
| `code_unbounded_cache` | 0 - 53.9% | 3 of 5 |
| **every other family** | **0 - 5.6%, mostly 0** | - |

A healthy baseline measures 0.00%. These measure up to 80%.

The cause is in the recipe. `code_defect_dispatch inject` restarts the container with the
defect's environment variable set, sleeps 6 seconds, verifies it came up - and only **then**
calls `gt_begin` to mark the incident start. The restart therefore lands inside the last
seconds of the baseline window.

Corroborating it: 3-7 endpoints "gone" between windows in every code run, against 1-2
everywhere else. That is containers coming back on new addresses.

**So every ratio in these 25 runs is measured against a restart.** `node|poll` reads 1700x not
because the defect is dramatic, but because the baseline was a service being torn down. Nothing
separates these families because the loudest thing in the data is the injection mechanism.

This violates a rule the project already holds - CLAUDE.md says toxiproxy sits permanently in
the catalogue path precisely because *"fault toggling must be restart-free"*. The code-defect
recipes toggle by restarting. Logged as CAMPAIGN-ISSUES 17, with the fix.

## `dns_delay` is different, and it does have a signal

Its baseline is clean (0 - 0.99%). And EMFILE separates it:

| | EMFILE per second |
|---|---|
| `dns_delay` | 0, **161.3, 234.4, 285.2, 310.1** |
| `anomaly_net` (the highest of anything else) | up to 63.8 |
| `fd_exhaustion` | 0.27 - 1.78 |
| everything else | exactly 0 |

**Four of the five runs separate at a 2.53x margin.** The fifth measures exactly zero - the
injection did not take, which is a property of that run and not of the fault.

Slow name lookups make the front-end pile up sockets waiting for answers, so it exhausts
descriptors far harder than the descriptor-cap fault does. The mechanism is sound and the
margin is real.

**`dns_delay` is blueprintable now**, on Sock Shop, with the honest caveat that transfer cannot
be checked because Train Ticket makes no DNS queries.

## Revised verdict on the six

| family | verdict |
|---|---|
| `dns_delay` | **buildable.** 4/5 runs, 2.53x margin on EMFILE. One run had a failed injection |
| `code_event_loop_block` | **re-collect.** Baseline contaminated by the injection restart |
| `code_lock_across_io` | **re-collect.** Same |
| `code_n_plus_one` | **re-collect.** Same |
| `code_serial_awaits` | **re-collect.** Same |
| `code_unbounded_cache` | **re-collect.** Same, 3 of 5 runs |

That changes the earlier conclusion. It was not that kernel traces cannot see these faults. We
have not yet given them a fair measurement.

---

## `dns-delay` written, 13 Sept

Two gates, because one is not enough and that is the point:

| gate | value | what it excludes | margin |
|---|---|---|---|
| EMFILE as a share of all failing syscalls >= 0.0175 | fault measures 0.0197 - 0.0476 | a service at its own descriptor limit, at 0.0000056 - 0.00176 | **11x** |
| retransmission < 12% | fault measures 0 - 1.9% | a degraded path, at 28.6 - 41.4% on its EMFILE-carrying runs | clean |

On the first gate alone the margin against a network fault is only **1.26x** - too thin to
trust. But the two faults are opposite on packet loss, so the second gate removes that whole
family, and the first is then only responsible for excluding a descriptor cap, where it has
11x. **That is the argument for a blueprint over a threshold, inside a single fault.**

**4 of 5 runs.** The fifth measures EMFILE at exactly zero and its DNS packet rate barely
moves - the injection did not take. Counted as a miss rather than quietly excluded.

**One application only.** Train Ticket resolves nothing by name, so transfer cannot be tested
with the applications we have. Stated on the blueprint rather than worked around.

The interesting thing about this fault, and why it is worth having: its loudest symptom
belongs to a different problem. The service runs out of file descriptors, which reads exactly
like a leak or a limit set too low. Raising the limit changes nothing, because the descriptors
are held by connections waiting for name answers that are not coming.
