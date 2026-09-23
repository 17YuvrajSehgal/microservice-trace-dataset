# Q2 rerun: after adding the two process tools

Same 60 runs, same model, same blueprint. What changed: the agent can now ask **who** is
running, not only **how much** is happening.

All 60 finished, 80 minutes, nothing failed. Results in
`/scratch/yuvraj17/stratatrace/results/attic/q2b`. The old runs stay in `results/attic/q2`.

## The headline: finding the process

| ask \| arm | named the process, before | after |
|---|---|---|
| nohint \| none | 3 of 15 | **10 of 15** |
| nohint \| given | 2 of 15 | **14 of 15** |
| hint \| none | 2 of 15 | **12 of 15** |
| hint \| given | 2 of 15 | **15 of 15** |

Before, it named `stress-ng-cpu` 9 times in 60. Now, 51 times in 60.

What it named now:

```
nohint|none     stress-ng-cpu 10, host 4, dockerd 1
nohint|given    stress-ng-cpu 14, conn33 1
hint|none       stress-ng-cpu 12, host 2, dockerd 1
hint|given      stress-ng-cpu 15
```

All 60 runs used the new tools. Not one ignored them.

## The window

| ask \| arm | before, median IoU | after | hits before | hits after |
|---|---|---|---|---|
| nohint \| none | 0.047 | **0.992** | 1 | 8 |
| nohint \| given | 0.029 | **0.992** | 0 | 14 |
| hint \| none | 0.047 | **0.992** | 0 | 11 |
| hint \| given | 0.049 | **0.992** | 0 | 12 |

1 hit in 60 before. 45 in 60 now.

**Be careful how this is reported.** The window is now mostly a by-product of naming the
process:

| | runs | window hits | mean IoU |
|---|---|---|---|
| named the culprit | 51 | 43 | 0.872 |
| did not name it | 9 | 2 | 0.449 |

`ctf_proclife` gives a process's exact first and last time, so once the agent picks the right
process the window follows for free. The analysis is in picking the process out of 14
candidates. The window should be read as a check on that, not as a separate skill.

## The full table

| ask \| arm | n | both right | service | fault | narrowed@2 | described | sec | tokens |
|---|---|---|---|---|---|---|---|---|
| nohint \| none | 15 | 20% | 93% | 27% | 100% | 71% | 293 | 60,099 |
| nohint \| given | 15 | 93% | 93% | 100% | 100% | 98% | 329 | 91,133 |
| hint \| none | 15 | 60% | 93% | 67% | 93% | 69% | 320 | 62,994 |
| hint \| given | 15 | 100% | 100% | 100% | 100% | 93% | 269 | 96,840 |

The blueprint is worth +73 and +40 points on both-right. It costs about 50% more tokens.

## The most interesting thing in the rerun

Without a hint and without a blueprint, the agent **found the process and then said nothing
was wrong**.

```
nohint|none  labels:  normal 9,  noisy_neighbor 4,  cpu_saturation 2
```

It named `stress-ng-cpu` 10 times but called the run `normal` 9 times. From one of its answers:

> The strongest single clue is not a system-wide crash but a workload boundary:
> container-69a5e6 appears only from 13:11:54 to 13:13:54 ... I do not see clear evidence of a
> host-wide resource fault; this looks more like a workload/container lifecycle change than an
> injected kernel-visible failure.

That is a correct observation and a defensible conclusion. A process starting and stopping is
not by itself a fault. The agent found the anomaly and declined to call it a problem.

Adding the hint moves it to `noisy_neighbor` 10 of 15. Adding the blueprint moves it to 15
of 15.

So the blueprint's contribution has split into two things we can now see separately:

- **finding the thing**: 10 -> 14 of 15. Real, and modest.
- **calling it a problem and describing it**: 27% -> 100% on the label, 71% -> 98% on the
  description. Large.

The second is still partly the "given not chosen" effect from the first pilot - the blueprint
names the fault. But the description score is not a label match, and it moved a long way too.

## Two things that got worse

**set-F1 fell with the blueprint** (-0.078 and -0.034). Not an accuracy drop. The blueprint arm
returns 3 candidates where the control returns 2, and set-F1 penalises a longer list. Both arms
hit@5 at 100%, so the difference is entirely list length.

**macro-F1 reads 1.000 for the blueprint arms.** Still meaningless with one problem and one
answer class, as in the first pilot. Ignore until the six-problem matrix.

## What is still not measured

1. **Blueprint given, not chosen.** Unchanged. The label result is inflated until there is an
   arm where the agent picks from all 11.
2. **Only one problem.** Everything here is `noisy_neighbor`.
3. **The rubric is a first pass.** The full answers are in
   `/scratch/yuvraj17/stratatrace/results/attic/q2b/review.md`, 60 runs in the agent's own words. If
   a run reads correct and scored low, the rubric is wrong.

## What was changed to get here

- `ctf_procdiff` - which processes differ between two ranges the agent picks
- `ctf_proclife` - when each process first and last appears
- the base method no longer says to hunt for "a step, a spike or a collapse". It says a problem
  can be a change in how much OR a change in who, and warns that the biggest jump in a count
  chart is often the recovery just after the problem. Both arms get this.
- blueprints carry a "with your tools" line per step, so the method is runnable here
- `ctf_proclife` sorts by event count, not arrival time, and flags kernel threads
- the answer is free text first; the label may be `other`
