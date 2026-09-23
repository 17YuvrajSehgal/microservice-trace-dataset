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

## 11. Five new kernel-only blueprints. 6 testable problems becomes 11

Yuvraj, while the matrices ran: "help me to build new blueprints that we can use kernel only
data... give it a try even if you think that the kernel traces are not enough."

They are enough, for five of the seven families tried. The two that are not are recorded as
limits rather than dropped.

### The instrument first, before any candidate list

`428 event types` in the profile. Checked rather than assumed, and it changed the plan:

- **no memory or reclaim events at all** - no `mm_`, `kswapd`, `vmscan`, `page_fault`
- **futex 26.9M events** - so the lock family has something to work with
- **192 syscall types**, including connect/accept/socket and mmap/madvise
- `sched_stat_runtime` 21.8M - real CPU time per task

### Two rejections before anything was written down

**The specificity sweep** (`lib/discover_signature.py`) measured every event's rate in the
injection window against a baseline, then ran the same measurement across all eight families.
It threw out `unlinkat` (x11-24), `ftruncate` (x0.1), `block_split`, `lseek` and `dup` - each
moves the same way in six unrelated faults, so they measure the WINDOW rather than the fault.
That is the `slow_db` 0.48 trap from the campaign, caught on the first pass.

**The harness check** (`lib/who_makes_it.py`) asked who emitted what survived. It killed
`nagle_delayed_ack` outright: its `poll` x11.9 and `sendto` x6.7 are **94% a python3 process
going 0 -> 57,338/s**, which is our own load generator.

**And it caught my own error.** The first harness rule listed `python3` by name, which nearly
discarded every signature - these faults are injected as SIDECAR CONTAINERS, so the
containerised python3 *is* the fault. Corrected to namespace: collection runs in the host
pid_ns, anything in a container namespace is the application or the injected fault. Process
name was the wrong test.

### Shares, not rates

The absolute rates separate these families perfectly and **transfer to nobody**: 63,000/s is
our injector's 16 threads at 200 us, not a property of lock contention. What survives a
parameter change is what share of its OWN events the culprit spends on each kind of work.

|  | futex | churn | on-CPU | softirq | network | ioctl | file ops | n |
|---|---|---|---|---|---|---|---|---|
| lock_contention | **47.0** | 26.4 | 14.7 | 5.9 | . | . | . | 5 |
| priority_inversion | **41.0** | 22.2 | 18.5 | 13.4 | 1.2 | . | . | 5 |
| nagle_delayed_ack | 25.8 | 16.9 | 9.7 | 9.4 | 17.9 | . | . | 5 |
| deadlock | **4.3** | 9.0 | 6.8 | 3.3 | 0.2 | 0.4 | **22.1** | 5 |
| conn_pool_exhaustion | . | 7.7 | 3.2 | 9.8 | 35.6 | **17.3** | . | 5 |
| anomaly_mem | . | 11.6 | 34.0 | 42.8 | 1.5 | . | 0.6 | 8 |
| noisy_neighbor | . | 27.8 | 27.0 | 35.7 | 2.9 | . | . | 3 |
| anomaly_cpu | . | 45.1 | 29.2 | 21.3 | 1.8 | . | . | 3 |

### The finding worth keeping

**A deadlocked container is QUIETER than an idle one.** 70-84 events/s against 63,000 for lock
contention - a factor of 800 - because parked threads make no syscalls. Nobody would guess it;
it falls out of the measurement. The blueprint states the consequence plainly: **a high futex
share RULES OUT deadlock**, which is the reverse of the intuition.

`ioctl` at 17.3% is the cleanest single separation in the whole table - it appears in no other
family at all.

### Two limits, written into the blueprints rather than dropped

**`anomaly_mem` does not separate from `noisy_neighbor` by shape** (on-CPU 34.0/softirq 42.8
against 27.0/35.7). The profile records no `mm_` or reclaim events, so a memory stressor reads
as a CPU stressor from the kernel side. **This is a limit of the modality, not the tooling** -
the first case today where the honest answer is that we need metrics.

**`nagle_delayed_ack`** has no app-side signature separable from the injector.

### `dependency_outage` needed its own route

It **removes** a container rather than adding one, so the newcomer search that finds every
other fault returns nothing in every run. Its signature is a retry storm confined to one
existing container: `getrusage` 5.3/s -> 2,474-2,701/s in ONE java namespace while three
identical siblings hold at 6.7/s, 100% application and 0% harness. That both detects AND
localises, which is exactly what the `svc_*` families failed at this morning.

### What each blueprint admits it cannot do

- a deadlock cannot be told from a crashed container without process-exit events
- the exhausted pool was measured only from the holder's side, never the datastore's
- `getrusage` is n=2 and JVM-specific, so the SHAPE is the discriminator and the syscall is a
  runtime detail
- priority inversion rests on two weak secondary shares, because futex alone does not separate
  it from lock contention (41.0 vs 47.0). **`sched_switch` carries `prev_prio`/`next_prio` and
  we never read them** - the count index keeps counts only. That is the single most valuable
  thing to add next and would likely make it decisive.

### The leak scanner earned its place twice

It rejected real service names in the dependency-outage text, then flagged "two **orders** of
magnitude" because `orders` is a Sock Shop service. Reworded rather than loosening the scanner:
a false positive costs a minute, a missed leak costs the experiment.

16/16 blueprints validate, 0 unrunnable commands, 0 `--gt` leaks.

## 12. The prompt fix did not work, and the real cause was a sentence I wrote

Sock Shop re-ran in full on the corrected prompt: 360/360, 0 failed. Identical runs, identical
tools, one change. The comparison against `q2-full` is clean, and it says the fix failed.

### It did not do what it was for

The fix targeted the arm GAP, not the pass rate: the blueprint arm abstained on anomaly_net
windows 14 times in 30 against 1 without it.

| | none | given | gap |
|---|---|---|---|
| abstentions BEFORE | 1/30 | 14/30 | **+13** |
| abstentions AFTER | 0/30 | 13/30 | **+13** |

Unchanged. Mean IoU in the given arm did improve, 0.284 -> 0.410, and hits 5 -> 7 - but the
behaviour the fix existed to remove is still there.

### And it cost something

`noisy_neighbor` without a blueprint: WHERE 20/30 -> 15/30, and `ambiguous` answers 1 -> 8. The
new wording pushed the agent toward host-wide readings, so it answered `java` more often instead
of naming `stress-ng-cpu`.

**So: a change made on a plausible diagnosis, tested, and it failed both ways.** The evidence
for the original diagnosis was real - the agent quoted my heuristic back while abstaining - but
quoting a rule is not the same as being bound by it.

### The real cause, and it is mine, from this morning

The network blueprint's deciding discriminator is TCP retransmission rate. The kernel recipe I
wrote for it says:

> There is no TCP retransmission tracepoint in this profile, so a retransmission RATE is not
> measurable - say that rather than inferring one from packet counts.

That is **false**, and the trace says so plainly:

```
net_if_receive_skb: ... transport_header = { source_port = 8079  dest_port = 46922
                                             seq = 148521618  ack_seq = 3861148859 ... }
```

The full TCP header is captured. A repeating `seq` on one flow IS a retransmission - which is
exactly how the campaign measured 51.9-61.8% retransmission **from these same traces**
(DATASET-v2-INVENTORY, issue 25). I wrote "not measurable" from the general fact that there is
no `tcp_retransmit_skb` tracepoint, without checking what this profile captures.

So the agent was told its deciding check was impossible, and honestly refused to conclude. It
behaved correctly on a false premise.

**I made this error in `blueprint_to_skill.py` - the file that enforces the evidence-first rule
on every discriminator.** The rule applies to the recipes too, and nothing was checking them.

### The finding that survives

Strip the mistake away and there is still a real result underneath, and a sharper one:

> A blueprint whose deciding signal is unavailable in the deployed modality is WORSE than no
> blueprint. The agent follows the method, cannot reach the deciding check, and abstains -
> while an agent without the blueprint looks at what is actually there and answers.

That is worth stating in the paper, because it is an argument about blueprint portability
rather than about this bug. It also gives the fix: a blueprint needs to name a FALLBACK when
its deciding signal is unavailable, instead of leaving the agent with nothing.

### Corrected, and the honest limit stated

The recipe now says the sequence numbers are there and how to look, and then bounds the claim:
`ctf_lines` returns at most 40 lines, so the agent can show retransmission **is or is not
happening** but cannot compute a **rate** over a window. Saying which of the two it did is now
part of the instruction.

**That is a concrete tool gap.** A field histogram over the trace - count repeated `seq` per
flow - would make `anomaly_net` properly answerable. It is the same shape as the
`sched_stat_runtime` gap found this morning: the data is in the trace, and the count index
throws away the field that matters.

### Do not revert the prompt yet

The prompt change also cost noisy_neighbor 5 points. Whether to revert it is a separate
question from the recipe fix, and it should be decided on a run where the recipe is correct -
the two were changed together and their effects are currently confounded.

## 13. The blueprint-hurts result, resolved on both applications

`anomaly_net` re-ran with the corrected recipe: 60 cells per application, 120 total, 0 failed.
Write-up in `blueprints/docs/WHEN-A-BLUEPRINT-HURTS.md`.

| abstention gap, given minus none | Sock Shop | Train Ticket |
|---|---|---|
| false recipe | +13 | +14 |
| **true recipe** | **+8** | **+8** |

Both land on exactly +8. Train Ticket's given-arm hits went 1 -> 6.

So our false sentence explained about a third of the damage. The residual is identical on two
very different codebases, which is what you expect if it comes from the blueprint rather than
from either application.

**The residual is structural.** The discriminator is a threshold on a rate - "at least one
interface retransmits heavily, measured 18.5% to 60.7%" - and the corrected recipe truthfully
says the agent can show retransmission is or is not happening but cannot compute a RATE from 40
raw lines. It can see the signal and still cannot satisfy the check as written, so it abstains.

> A blueprint whose deciding check is a threshold on a quantity the deployed tools cannot
> compute will make an agent abstain, even when the underlying signal is plainly visible.

**Decision: every thresholded discriminator needs a qualitative fallback.** Here it is easy and
true - "retransmission present at all, against a baseline of none" is what the campaign
actually measured and what `ctf_lines` can show. Not yet implemented; it is the next change to
the network blueprint.

## 14. ctf_lines: 295 s -> 0.8 s

Yuvraj asked whether runs could be parallelised, since we have the Azure API. Measured first:

    11 cells running, 11 in babeltrace, 11 of 192 cores used, load 34

Every cell was CPU-bound in babeltrace, not waiting on the API - which accounts for 27 s of a
500 s run. So more `--jobs` would have spent 3x the CPU on the same wasted work: re-decoding
385 million events to return 40 lines, five times per run.

The index pass already decodes every event once, so it now keeps one raw line per
(bucket, event). Measured on the same three calls:

| | before | after |
|---|---|---|
| sched_switch | 72.1 s | 0.2 s |
| sched_waking | 103.9 s | 0.3 s |
| net_dev_xmit | 119.0 s | 0.3 s |
| **total** | **295.1 s** | **0.8 s** |

Same ten lines returned. 66 samples installed, 2.0 GB, index dir now 2.3 GB.

**Built on a compute node and staged, installed only once nothing was in flight** - dropping it
beside the live index mid-run would have changed `ctf_lines` underneath the experiment and left
half the cells with a different cost and a different sample.

A run should now be ~2 minutes rather than ~9. **Raise `--jobs` to 12-16 for the next matrix**:
now that cells are API-bound rather than CPU-bound, parallelism finally pays.

One honest caveat, stated in the tool's own output: this is a DIFFERENT sample. `ctf_lines`
used to return the first n matching lines in a range, which can all fall inside a few
milliseconds; it now returns one per 100 ms bucket, spread across the range. Arguably better,
definitely different.

---

## The recipe fix is proven on one application, not two

Checked the corrected-recipe re-runs arm by arm before committing the reports. The `none` arm
receives no blueprint and no kernel recipe, so it is a control: it must not move between the
false-recipe and true-recipe runs.

| abstentions, out of 30 | Sock Shop | Train Ticket |
|---|---|---|
| given arm | 13 -> 11 | 23 -> 17 |
| control arm | 0 -> 3 | 9 -> 9 |
| given-arm window hits | 7 -> 8 | 1 -> 6 |

Train Ticket's control arm is flat, so all 6 points belong to the recipe. Sock Shop's control
arm moved 3 runs on its own, so only 2 of its 5-point move is the recipe.

**Why this matters.** Both applications landing on +8 read as a clean replication, and it is
not one. Written up that way, a reviewer who re-ran it would find the Sock Shop half does not
hold. `WHEN-A-BLUEPRINT-HURTS.md` now says which half is evidence.

**It also gives us a noise floor we did not have: 3 runs in 30, about 10 points.** Any single
cell in the matrix moving by less than that is not a result. Worth applying to the whole report
- several per-problem deltas are in that range.

## Charts and reports were already correct; only the repo copy was stale

I suspected the Sock Shop charts had been built without the `anomaly_net` override, because
`anomaly_net` still showed -13 on "found the time". Checked instead of assuming: -13 IS the
corrected number (the false recipe gives -27), and the regenerated files are byte-identical to
the downloaded ones. The override had been applied all along.

Two measures were being confused, and the doc names both now:
- **abstention gap** (given minus none): +13 -> +8
- **window hit change** in percentage points: -27 -> -13

Also confirmed the report's numbers against a recompute straight from `score.json`, which found
two apparent mismatches, both correct on inspection:
- `anomaly_net` WHERE is 50/60 not 0/60 - the per-problem ceiling counts `scope` as right,
  since a host-wide network fault has no service to name.
- `described` comes from the phrase-based rescore, not the `what_score` stored at run time.

## One results directory per application, superseded runs to attic

The corrected `anomaly_net` was sitting in a separate dir and being substituted at report time
with `--override`. That worked but left a false-recipe copy next to a true-recipe copy, both
called something starting `q2-`. Folded the corrected runs in and moved the rest aside:

| now | was |
|---|---|
| `results/q2-ss` - 360 cells, Sock Shop | `q2-ss2` + `q2-net-ss/anomaly_net` |
| `results/q2-tt` - 360 cells, Train Ticket | `q2-tt` + `q2-net-tt/anomaly_net` |
| `results/charts-ss`, `charts-tt` | `charts-ss`, `charts-tt`, and an older `charts` |
| `results/attic/` | `q2-full`, `q2-ns`, `q2`, `q2b`, `charts`, both false-recipe `anomaly_net` |

**Kept rather than deleted.** `WHEN-A-BLUEPRINT-HURTS.md` isolates one variable at a time, so
it needs the old-prompt and false-recipe runs to stay reproducible. `attic/README.md` says
which condition each one is, so nothing there can be mistaken for a current result.

Verified the swap by fingerprint, not by filename: the true-recipe `anomaly_net` has 3/11
abstentions on Sock Shop and 9/17 on Train Ticket; the false one had 0/13 and 9/23.

Reports no longer carry the `--override` footnote, and the review-sheet pointer follows
`--full` instead of hardcoding `q2-full` - it had been pointing into a directory that moved.

**`q2_run_matrix.py` and `q2_run_one.py` still default `--out-dir` to `results/q2`, on purpose.**
A run started without `--out-dir` should land somewhere throwaway, not on top of `q2-ss`.
