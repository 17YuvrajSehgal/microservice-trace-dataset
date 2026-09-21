# Q2 pilot: does a blueprint help on `noisy_neighbor`?

All 60 runs finished. 89 minutes. Nothing failed.

Setup:

- 1 problem, 3 runs of it, 2 arms (blueprint / no blueprint), 2 asks (hint / no hint), 5 repeats
- kernel traces only. No metrics, no logs, no spans
- the agent is not told when the fault was, or that there was one
- model `gpt-5.4-mini` (azure), blueprint `cpu-contention-co-tenant`, handed over not chosen
- results in `/scratch/yuvraj17/stratatrace/results/q2`

## The numbers

| ask \| arm | n | both right | service | fault | narrowed to top 2 | set-F1 | sec | tokens |
|---|---|---|---|---|---|---|---|---|---|
| nohint \| none | 15 | 0% | 47% | 20% | 53% | 0.367 | 428 | 54,640 |
| nohint \| given | 15 | 13% | 13% | 100% | 87% | 0.453 | 300 | 67,050 |
| hint \| none | 15 | 7% | 67% | 20% | 47% | 0.267 | 339 | 53,920 |
| hint \| given | 15 | 40% | 47% | 93% | 93% | 0.489 | 272 | 80,452 |

The blueprint helped. Both-right went up 13 and 33 points. Narrowing went up 34 and 46 points.
It used about 25% more tokens. It was faster in real time.

Three of those columns are misleading. Here is why.

## 1. The fault score is almost free

The blueprint is named `cpu-contention-co-tenant`. Its text describes a co-tenant eating host
CPU. The answer list has `noisy_neighbor` defined in nearly the same words.

So the agent can read the answer off the blueprint. 100% here means "it read the page".

The no-blueprint arm is more interesting. It said `cpu_saturation` 21 times out of 30. That is
the right mechanism with the wrong name. The only difference between the two names is whether
the host still has spare CPU. That is exactly what the blueprint's "telling it apart" section
answers.

So the blueprint does add something real. But we gave it the right blueprint, so we cannot
tell how much.

**Fix: add an arm where the agent picks its own blueprint from all 11.**

## 2. The service score is measuring hedging

The scorer counts both `host` and `stress-ng*` as correct. Those are very different answers.
One is a safe guess. One is finding the actual process.

| ask \| arm | scored correct | said `host` | named the process | wrong |
|---|---|---|---|---|---|
| nohint \| none | 7 | 4 | 3 | 8 |
| nohint \| given | 2 | 0 | 2 | 13 |
| hint \| none | 10 | 8 | 2 | 5 |
| hint \| given | 7 | 5 | 2 | 8 |

Naming the real process is 3, 2, 2, 2. Flat in every arm.

So the blueprint did not make localisation worse. It made the agent name a container instead
of saying `host`. It named the wrong container. Its actual skill did not change.

**Fix: report both columns. Never the merged one.**

This matters. "Blueprints hurt localisation" would have been a clean, wrong result.

## 3. Almost every run found the recovery, not the fault

52 of 60 gave a window that starts at or after the real window ended. None started early.

```
real window     13:11:54 - 13:13:55
typical answer  13:13:50 - 13:14:45
```

| ask \| arm | abstained | miss | partial | hit | median IoU |
|---|---|---|---|---|---|---|
| nohint \| none | 2 | 3 | 9 | 1 | 0.047 |
| nohint \| given | 0 | 2 | 13 | 0 | 0.029 |
| hint \| none | 0 | 3 | 12 | 0 | 0.047 |
| hint \| given | 1 | 2 | 12 | 0 | 0.049 |

This is the data, not the agent. Event counts across the whole trace:

```
13:12:01   1,170,092  #################
13:12:45   1,153,546  #################
13:13:30   1,164,320  #################     fault still running
13:13:52   1,307,926  ####################  fault STOPS here
13:14:14   1,334,383  ####################
13:14:36   1,338,374  ####################
```

The fault does not raise the event count. The recovery does. So anything that looks for a jump
in totals lands on the recovery every time.

This is what we predicted for `noisy_neighbor`: the co-tenant eats CPU but the system keeps
working. Now we have shown it in the kernel data.

It also gives us a general point:

> If a fault shows up as a new process rather than more events, looking for a jump in totals
> finds the recovery instead.

The fault is easy to see the right way:

```
stress-ng-cpu   starts 13:11:54.1   ends 13:13:54.2
real window     13:11:54Z - 13:13:55Z
```

Within one second at both ends. The data is fine. The way the agent searched is the problem.
The blueprint even says to look for a new process, not more load. It looked at load anyway.

## What this pilot proved

- The harness works. 60 of 60 ran. Every number is filled in and consistent.
- The blueprint helps the main score, and helps narrowing a lot.
- Two columns need re-reading before they go in a paper.
- The window result is bad in both arms, and that is a real finding.

## Before we scale to 6 problems

1. **Add an arm where the agent picks the blueprint.** Without it the fault score means little.
2. **Split "named the process" out of the service score** for host faults.
3. **Decide if the window task is fair as set up.** Every arm fails it the same way, at IoU
   around 0.04. That tells us nothing about blueprints. Either the agent needs a way to ask
   "which processes are in range A but not range B", or the blueprint has to push much harder
   against looking at load.
4. `macro_f1` shows 1.000 for nohint|given. That is meaningless with one problem and one
   answer class. It only starts working across all 6 problems.
