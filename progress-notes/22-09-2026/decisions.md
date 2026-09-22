# 22-09-2026 — decisions

Continues 21-09. The 360-run matrix finished at 03:40 and the day's work is what it showed.

## 1. The full matrix: 360/360, 4h 21m, nothing failed

Write-up: `blueprints/docs/Q2-FULL-6-problems.md`. Decisions here.

| problem | WHERE ok | described (v2) |
|---|---|---|
| anomaly_cpu | 60/60 | 79% |
| anomaly_net | 47/60 | 48% |
| noisy_neighbor | 47/60 | 67% |
| slow_db | 21/60 | 68% |
| svc_cpu_cap | **0/60** | 33% |
| svc_net | **0/60** | 37% |

The split is by **scope**: host-wide faults 47-60 of 60, single-service faults zero, twice.

## 2. I nearly published a false modality claim

"Kernel traces cannot localise per-service faults" was the obvious reading of those two zeros.
I checked it against the raw trace before writing it, and it is wrong.

Every event carries the namespaces of the task that produced it:

```
{ pid = 0  tid = 0  procname = "swapper/3"
  cgroup_ns = 4026531835  pid_ns = 4026531836  net_ns = 4026531833 ... }
```

**One `pid_ns` is one container.** 21 per run. `java` alone is five separate containers -
13.3M, 1.74M, 99k, 69k and 20k events. My index kept procname and dropped the namespace, so the
agent saw `java` with no way to tell which, and answered `host`: 56 of 60 on svc_net, 43 on
svc_cpu_cap.

That is the tool, not the modality. The evidence-first rule earned its keep here - the claim
was one paragraph away from being written down.

Index and all three process tools now carry `pid_ns`. Re-run of the two problems is in
`results/q2-ns` with everything else held fixed.

### What the trace still cannot do

There is **no service name anywhere** in a kernel trace, and no mapping to one in the bundle:
`meta/` has container names but no PID list, `ust/` is the Python relay only, `logs/` has names
but no PIDs. So the most precise answer available is "the java in pid_ns 4026533460" - one
container out of 21.

**Decision: that counts as getting WHERE right**, under a new `container` outcome. It is not
"carts", but it is emphatically not "host" either, and marking it wrong would have made the
whole namespace fix invisible - the same silent-zero shape as the empty culprit lists on 21-09.

## 3. The pooled blueprint effect was +0, and that number is meaningless

Pooling six problems that behave nothing alike - three near the ceiling, two on the floor -
averages a real effect against an unrelated zero. Per problem, in percentage points:

| problem | WHERE | window | describe | fault |
|---|---|---|---|---|
| anomaly_cpu | 0 | +3 | +17 | +33 |
| anomaly_net | **+37** | **-37** | -17 | +17 |
| noisy_neighbor | **+23** | +20 | **+44** | +50 |
| slow_db | **+23** | -3 | +29 | +57 |
| svc_cpu_cap | 0 | +27 | +23 | +100 |
| svc_net | 0 | -13 | -6 | +17 |

Three things follow.

- **The blueprint helps where there is headroom.** +37/+23/+23 on the three problems not
  already at ceiling or floor.
- **Its biggest effect is on explaining the mechanism, not naming things**: +44, +29, +23, +17.
  That is what a blueprint is for, and `describe` is not a label match.
- **The fault column is still the tautology** from the first pilot. +100 on svc_cpu_cap means
  the blueprint named the fault. Given-not-chosen; the column measures reading.

**Never report the pooled number.** `q2_arms.py` exists so the per-problem split is the default.

## 4. Open: the anomaly_net window regression

The blueprint makes window-finding **37 points worse** on `anomaly_net`, and it is also the
only problem where the blueprint hurts the description (-17). Large, wrong direction, unexplained.

First guess - the network blueprint sends the agent after packet-level evidence this profile
does not record - is a guess. **Do not write any of this up until it is understood.**

## 5. The window results split cleanly by fault mechanism

| problem | window hits / 60 |
|---|---|
| svc_cpu_cap | 46 |
| noisy_neighbor | 36 |
| svc_net | 22 |
| anomaly_net | 21 |
| slow_db | **1** |

`slow_db` at 1 is the pattern, not an outlier: the process tools find a fault by spotting a
process that arrives or leaves, and a slow database is an existing process answering slowly.

> The WHO tools fixed the fault class whose signature is a new process, and did nothing for the
> class whose signature is timing inside an existing one.

Both halves of that are worth reporting.

## 6. Two scoring bugs caught before spending compute, not after

Both would have hidden the very thing the namespace re-run exists to measure.

- No outcome existed for a container-level answer, so "java in pid_ns 4026533460" would have
  scored `ambiguous` or `wrong`.
- The namespace regex was written through a heredoc that turned `\b` into a literal backspace
  character, so it matched nothing at all.

Caught by running the scorer against six example answers before launching 120 cells. **Third
time heredoc escape mangling has damaged this codebase** - patterns are now built without
literal escapes in the patch text.

## 7. The per-service re-run: 120/120, and the fix barely moved the score

`results/q2-ns`, everything held fixed except `pid_ns` in the index. Verified the cluster repo
stayed at the pre-fix commit for the whole run, so no cell saw a different prompt.

| | svc_cpu_cap | svc_net |
|---|---|---|
| WHERE right | 0/60 -> **1/60** | 0/60 -> **0/60** |
| answered "host" | 43 -> **33** | 56 -> **28** |
| ambiguous (bare `java`) | 13 -> **21** | 1 -> **7** |

So the namespace data moved the agent off "host" - by 10 and 28 runs - but it went to bare
`java`, not to a specific container.

**It is using the namespaces.** 42/60 and 45/60 mention a `pid_ns` in their reasoning. Only
1/120 put one in the answer field. And one run says exactly why:

> The specific throttled service cannot be named from kernel comm alone; the trace shows
> multiple `java` containers, including pid_ns 4026532538 and 4026533460, but not which one
> has the quota.

That is correct reasoning and an honest refusal, not a failure.

## 8. So: is svc_cpu_cap solvable from the trace? Three tests, and the third says yes

This is the third time today a "the modality cannot do it" claim has failed verification, so I
tested rather than asserted.

**Test 1 - event rate per container.** Useless. Capping carts stalls the whole request path, so
EVERY container drops 3x to 100x, all four java containers included (0.14, 0.19, 0.30, 0.32).
There is no odd one out. The agent answering "everything slowed" is reading the trace correctly.

**Test 2 - wake-to-switch ratio.** A throttled cgroup should be woken and then denied a CPU, so
its ratio should rise. It does not. It FALLS for every java container, because upstream traffic
stopped so they are not being woken either.

**Test 3 - `sched_stat_runtime`.** Decisive:

```
java  pid_ns 4026532538    before 0.551 CPU-s/s    during 0.195 CPU-s/s
carts cap                                          0.200 CPU
```

Pinned at its cap, measured. A CPU cap limits CPU *time*, not event count - so the signal was
never going to be in a count.

**The trace can identify the throttled container. My index cannot, because it sums nothing -
it counts events and discards their payload.** Tooling limit, not modality limit, again.

There is no cgroup or throttling tracepoint in the profile (405 event types, none matching
throttl/cgroup/cfs/quota), so `sched_stat_runtime` is the only route - but it is enough.

### Decision

The index needs to carry summed `sched_stat_runtime.runtime` per (bucket, procname, pid_ns)
alongside the counts, and a tool to read it as CPU-seconds per container. That is a schema
change, another full rebuild, and another re-run - real compute - so it is Yuvraj's call rather
than something to start unannounced at 05:30.

### The pattern worth keeping

Three claims of the form "kernel traces cannot do X" were tested today. All three were false,
and all three were my own tooling:

1. cannot localise per-service faults -> the trace carries `pid_ns`, my index dropped it
2. cannot find the window for host-wide faults -> my prompt told the agent to reject the signal
3. cannot identify a throttled container -> the trace carries runtime, my index counts only

**A count-based summary of a kernel trace loses exactly the information that identifies
resource-limit faults.** That is a real finding about summarisation, and it is worth more to
the paper than any of the three false claims would have been.

## 9. Train Ticket: and why Sock Shop gets re-run with it

Yuvraj: "Now run all the tests on the TT dataset."

### The picker never reached Train Ticket

`incidents_for` took the first N runs from a list that puts Sock Shop first, and Sock Shop
always has enough. So all 600 runs so far are one application, and nothing said so. Added
`--app`.

The runs were always there - 5 to 11 per problem per app. This was a one-line slice, not a
data gap.

### Targets differ, and the scorer already handles it

| problem | Sock Shop | Train Ticket |
|---|---|---|
| slow_db | catalogue-db | `mysql` |
| svc_net | carts | `ts-basic-service` |
| svc_cpu_cap | carts | `ts-travel-service` |
| the three host faults | host | host |

Nothing to change: since §2 the accept list comes from each run's own `ground_truth.json`
rather than a list I wrote. Had it still been my hand-written list, every Train Ticket
per-service run would have scored wrong and it would have looked like an application
difference.

### Sock Shop is being re-run alongside it

`q2-full` and `q2-ns` both ran at the commit **before** the anomaly_net prompt fix (§4), and
that fix changed the base METHOD for every problem, not just that one.

So running Train Ticket alone would leave **two** things different between the applications -
the app and the prompt - and the whole reason for a second application is to show a result is
not an artefact of one codebase. That argument does not survive a harness change in the middle
of it.

**Decision: run both now, on the corrected prompt, concurrently.** 5 jobs each on the login
node; they are API-bound and idle most of their wall clock. About 5-6 hours for both against 9
sequentially.

Running Train Ticket alone on the old prompt would have produced 360 runs I would have had to
throw away.

`q2-full` keeps its value as the record of what the old prompt did - it is what §4's -37 point
regression is measured on.

### Two refusals in the launcher

It will not start if any of the 36 indexes is missing or lacks `pid_ns`, and it will not start
if `agent.py` still contains the old heuristic. Both failure modes are silent otherwise: the
first falls back to a capped raw read and produces plausible rows built on 1.6% of the trace,
and the second would quietly reintroduce the bug the re-run exists to remove.

## 10. 80% of the agent's wall clock is one tool

Measured from the transcripts while the Train Ticket matrix ran, because 13 hours looked wrong
and guessing at the cause would have been worse than measuring it.

| | tool time per run | of which `ctf_lines` | API time |
|---|---|---|---|
| Train Ticket | 473 s | **378 s (80%)** | 27 s |
| Sock Shop | 333 s | **261 s (78%)** | 22 s |

Median `ctf_lines` call: 56 s on TT, 90 s on SS. **Every other tool answers in about 2 s**,
because they read the count index. The API is not the bottleneck and never was - 218 s of API
across eight whole runs.

The cause is the thing measured on 21-09: **babeltrace cannot seek.** To hand back 40 raw event
lines from 100 s into the trace it decodes everything before that point and discards it. The
agent calls `ctf_lines` about five times a run.

So the honest cost statement is not "the agent is slow" or "the model is slow". One tool of six
costs 40x what the others do, for a fixed reason in the tracing toolchain. Worth reporting: any
kernel-trace agent that reads raw event lines pays this, and the count index is what made the
other five cheap.

**Not changed mid-run.** Half the cells would carry a different tool cost and the time column
would stop meaning anything - the same reason the rubric was left alone during the last matrix.
Trillium's repo is deliberately NOT being synced until both matrices finish, because each cell
imports `ctf_tool.py` fresh at start and a sync would change the tool under a running
experiment.

### The fix, ready for next time

The index pass already decodes every event once. It can keep, for each (bucket, event), the
first raw line - so `ctf_lines` reads a file instead of re-decoding the trace. About 2.9M lines
per run, which is the row count of the count index.

One semantic change, and it must be stated rather than hidden: `ctf_lines` currently returns
the first n matching lines **in the range**, which can all fall inside the first few
milliseconds. Served from the sample it returns one line per bucket, spread across the range.
That is arguably the better sample, but it is a different one.

Expected effect: a run drops from about 9 minutes to about 2.
