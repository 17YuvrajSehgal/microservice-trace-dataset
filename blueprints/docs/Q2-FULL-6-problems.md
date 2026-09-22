# Q2 full run: 6 problems, 360 runs

All 360 finished. 4 hours 21 minutes. Nothing failed.

- 6 problems, 3 runs each, 2 arms (blueprint / none), 2 asks (hint / none), 5 repeats
- kernel traces only. No metrics, no logs, no spans
- the agent is not told when the fault was, or that there was one
- model `gpt-5.4-mini` (azure); blueprint handed over, not chosen
- results `/scratch/yuvraj17/stratatrace/results/q2-full`
- all 360 answers in full: `results/q2-full/review/review-<problem>.md`

## Did it find the right place?

| problem | target | got WHERE right | described the mechanism |
|---|---|---|---|
| anomaly_cpu | host | **60/60** | 79% |
| anomaly_net | host | 47/60 | 48% |
| noisy_neighbor | host (stress-ng) | 47/60 | 67% |
| slow_db | catalogue-db | 21/60 | 68% |
| svc_cpu_cap | carts | **0/60** | 33% |
| svc_net | carts | **0/60** | 37% |

WHERE is marked against the best answer each fault allows. For `anomaly_net` the netem sits on
the host's own interface, so "host" is the complete answer and there is nothing to name.

The split is by **scope**, not by difficulty:

- **host-wide faults**: 47 to 60 out of 60
- **one service**: zero, twice

## The two zeros are my tool, not the modality

I nearly wrote "kernel traces cannot localise per-service faults". That would have been wrong.

Every kernel event carries the namespaces of the task that produced it:

```
{ pid = 0  tid = 0  procname = "swapper/3"
  cgroup_ns = 4026531835  pid_ns = 4026531836  net_ns = 4026531833 ... }
```

**One `pid_ns` is one container.** There are 21 of them in each run. `java` alone is five
separate containers:

```
java  ns=4026532538   13,292,825 events
java  ns=4026533460    1,742,143
java  ns=4026533815       99,450
java  ns=4026533389       68,966
```

My count index kept only the process name and threw the namespace away. So the agent looking at
a `carts` fault saw `java` with no way to tell which one, and fell back to `host` - 56 times out
of 60 on `svc_net`, 43 on `svc_cpu_cap`.

The index and all three process tools now carry `pid_ns`. A re-run of those two problems is in
`results/q2-ns`, with everything else held fixed, so the difference is one change.

## Does the blueprint help?

Per problem, in percentage points. **Pooled across problems this came out as +0**, which is an
averaging artefact: three problems near the ceiling and two on the floor cancel out. Never
report the pooled number.

| problem | WHERE | window | describe | fault label |
|---|---|---|---|---|
| anomaly_cpu | 0 | +3 | +17 | +33 |
| anomaly_net | **+37** | −37 | −17 | +17 |
| noisy_neighbor | **+23** | **+20** | **+44** | +50 |
| slow_db | **+23** | −3 | +29 | +57 |
| svc_cpu_cap | 0 | +27 | +23 | +100 |
| svc_net | 0 | −13 | −6 | +17 |

**It helps where there is room.** +37, +23, +23 on the three problems that were not already at
the ceiling (`anomaly_cpu`, 60/60) or stuck at the floor (both `svc_*`, the namespace problem).

**Its biggest effect is on explaining the mechanism**, not on naming things: +44, +29, +23, +17.
That is what a blueprint is for, and it is not a label match - it is the agent's own words
covering the mechanism.

**Ignore the fault-label column.** +100 on `svc_cpu_cap` means the blueprint told it the answer.
The blueprint is handed over rather than chosen, so that column measures reading comprehension.
It needs an arm where the agent selects from all 11.

## One result I cannot explain yet

On `anomaly_net` the blueprint makes window-finding **37 points worse**. That is large and it is
the wrong direction. It is not a rounding artefact - `anomaly_net` is also the only problem
where the blueprint hurts the description (−17).

Worth a look before any of this is written up. My first guess is that the network blueprint
sends the agent looking for packet-level evidence that this profile does not record, but that
is a guess and the review sheet is the place to check it.

## What the window results say

| problem | window hits (of 60) |
|---|---|
| svc_cpu_cap | 46 |
| noisy_neighbor | 36 |
| svc_net | 22 |
| anomaly_net | 21 |
| slow_db | **1** |

`slow_db` at 1 is the pattern, not an outlier. The two process tools find a fault by spotting a
process that arrives or leaves. A slow database is an existing process answering slowly -
nothing appears, nothing disappears, so the tools have nothing to grip on.

So: **the WHO tools fixed the fault class whose signature is a new process, and did nothing for
the class whose signature is timing inside an existing one.** Both halves of that are worth
reporting.

## What still needs doing

1. **The `chosen` arm.** Unchanged since the first pilot and still the biggest limitation.
2. **Re-run the two per-service problems** with namespaces. Running now.
3. **Explain the `anomaly_net` window regression** before publishing anything.
4. **Read the review sheets.** 60 answers per problem, in the agent's own words. The rubric
   sorts them; it does not decide. If a run reads correct and scored low, the rubric is wrong.
