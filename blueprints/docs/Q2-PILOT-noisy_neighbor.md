# Question 2, pilot: does a blueprint help on `noisy_neighbor`?

60 runs, all completed, 89 minutes. One problem, 3 incidents, 2 arms, 2 asks, 5 repeats.
Kernel traces only - no metrics, logs or spans. The agent is never told when the fault was,
or that there was one.

- model `gpt-5.4-mini` (azure), temperature left at the model default, 5 repeats measure that
- blueprint `cpu-contention-co-tenant`, **given, not chosen**
- incidents `noisy_neighbor_aggressive_steady_r1/r2/r3` (sockshop)
- results `/scratch/yuvraj17/stratatrace/results/q2`, one directory per cell

## The table

| ask \| arm | n | both | service | fault | narrowed@2 | hit@5 | set-F1 | sec | tokens |
|---|---|---|---|---|---|---|---|---|---|
| nohint \| none | 15 | 0% | 47% | 20% | 53% | 67% | 0.367 | 428 | 54,640 |
| nohint \| given | 15 | **13%** | 13% | 100% | **87%** | 93% | 0.453 | 300 | 67,050 |
| hint \| none | 15 | 7% | 67% | 20% | 47% | 47% | 0.267 | 339 | 53,920 |
| hint \| given | 15 | **40%** | 47% | 93% | **93%** | 93% | 0.489 | 272 | 80,452 |

The blueprint helps on the headline number (+13 and +33 points) and on narrowing (+34 and +46),
costs about 25% more tokens, and is *faster* in wall clock (x0.7, x0.8).

**Three of those columns do not mean what they look like.** Taking them in turn.

## 1. Fault accuracy is close to tautological in the given arm

| ask \| arm | what it answered |
|---|---|
| nohint \| none | cpu_saturation 9, noisy_neighbor 3, normal 2, disk_io 1 |
| nohint \| given | **noisy_neighbor 15** |
| hint \| none | cpu_saturation 12, noisy_neighbor 3 |
| hint \| given | noisy_neighbor 14, normal 1 |

The blueprint is called `cpu-contention-co-tenant` and its body describes a co-tenant consuming
host CPU while KPIs stay near-normal. The fault vocabulary defines `noisy_neighbor` in almost
those words. So 100% is mostly "the agent read the blueprint it was handed".

What is genuinely interesting is the control arm's answer. Without a blueprint it says
`cpu_saturation` 21 times out of 30 - the right *mechanism*, the wrong label. The only thing
separating the two is whether the host keeps headroom, which is exactly what this blueprint's
"telling it apart" section exists to settle.

So the blueprint does contribute something real: it discriminates between look-alikes. But
because it was **given rather than chosen**, this pilot cannot separate that contribution from
simply being told the answer. Measuring it needs an arm where the agent selects from all 11
blueprints. Recommended as the next change.

## 2. The service metric is measuring hedging, not localisation

`_svc_match` scores both `host` and `stress-ng*` as correct for a host-scoped fault. That is
defensible - but it merges a hedge with a find. Split apart:

| ask \| arm | service_ok | said `host` | **named the culprit** | wrong |
|---|---|---|---|---|
| nohint \| none | 7 | 4 | **3** | 8 |
| nohint \| given | 2 | 0 | **2** | 13 |
| hint \| none | 10 | 8 | **2** | 5 |
| hint \| given | 7 | 5 | **2** | 8 |

**Naming the actual injected process is 3, 2, 2, 2 - flat across all four arms.** Every
difference in the service column comes from how often the agent hedged to `host`.

So the apparent finding "the blueprint makes localisation worse" (47% -> 13%) is not that. The
blueprint pushes the agent to commit to a named container instead of hedging, and it commits to
the wrong one. Localisation ability is unchanged at about 13%; what changes is willingness to
guess.

This also means `service_ok` should not be read as localisation for host-scoped faults at all.
Worth reporting both columns in the paper rather than the merged one.

## 3. Almost every run found the recovery, not the fault

The clearest result here, and it is the same in all four arms.

**52 of 60 claimed a window that starts at or after the true window ended.** None started early.

```
true window     13:11:54 - 13:13:55
typical claim   13:13:50 - 13:14:45
```

| ask \| arm | abstained | miss | partial | hit | median IoU |
|---|---|---|---|---|---|
| nohint \| none | 2 | 3 | 9 | 1 | 0.047 |
| nohint \| given | 0 | 2 | 13 | 0 | 0.029 |
| hint \| none | 0 | 3 | 12 | 0 | 0.047 |
| hint \| given | 1 | 2 | 12 | 0 | 0.049 |

The reason is in the data, not the agent. Whole-trace `sched_switch` counts, from the index:

```
13:12:01   1,170,092  #################
13:12:45   1,153,546  #################
13:13:30   1,164,320  #################     <- fault still running
13:13:52   1,307,926  ####################  <- fault STOPS here
13:14:14   1,334,383  ####################
13:14:36   1,338,374  ####################
```

The injected fault produces **no step in aggregate event volume**. The recovery does. So any
change-point search over totals lands on the recovery, and lands there consistently.

That is `noisy_neighbor`'s pre-registered property - a co-tenant consumes host resources while
KPIs barely move - confirmed from the kernel side, and it has a consequence worth stating:

> For a fault whose signature is *presence* rather than *volume*, aggregate change-point
> detection systematically finds the recovery instead of the fault.

The fault is perfectly visible if you look the right way. From the index:

```
stress-ng-cpu   first 13:11:54.1   last 13:13:54.2   1,682,336 events
ground truth    injection 13:11:54Z - 13:13:55Z
```

Both ends within a second. The information is there; the search strategy is what fails. The
blueprint says this in as many words - the newcomer is identified by presence, not by load -
and the agent still searched on volume.

## What this pilot is good for

- The harness works end to end. 60/60 completed, every metric populated and internally
  consistent.
- The blueprint has a measurable effect on the headline number and a large one on narrowing.
- Two of the four headline columns need re-reading before they go anywhere near a paper, and
  the third (window) is a clean negative result in both arms.

## What to change before scaling to six problems

1. **Add a `chosen` arm.** Without it, fault accuracy in the given arm measures reading
   comprehension. This is the single biggest limitation of the current design.
2. **Report `named the culprit` separately from `service_ok`** for host-scoped faults.
3. **Consider whether the window task is winnable as posed.** Every arm fails it the same way.
   Either the agent needs a presence-oriented search primitive, or the blueprint needs to push
   much harder on "do not look for a volume step".
4. `macro_f1` reads 1.000 for nohint|given - degenerate with one problem and one class. It only
   becomes meaningful across the six-problem matrix.
