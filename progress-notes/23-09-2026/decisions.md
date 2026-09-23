# 23 September 2026

## The 6000-char reply cap was deleting the answer, not trimming it

Went looking at `SENT_CAP = 6000` because it was flagged as maybe-too-small. It is worse than
too small. Measured across all 720 q2 transcripts, 11,189 tool calls:

| tool | calls | cut | median result | thrown away |
|---|---|---|---|---|
| `ctf_proclife` | 742 | **99.3%** | 41 KB | **86%** |
| `ctf_procdiff` | 1201 | 87.3% | 7.8 KB | 23% |
| `ctf_lines` | 3016 | 67.7% | 7.6 KB | 29% |

Two separate faults, both from the same line - `sent = full[:SENT_CAP]`, a slice of the JSON
**string**:

**1. Every cut result was unparseable.** All 3,827 of them, chopped mid-number or mid-string.
The model was being handed broken JSON and reasoning on it anyway.

**2. A prefix slice does not sample a result, it deletes late keys outright.** `json.dumps`
keeps insertion order. `ctf_proclife` returns two lists, and the second one never arrived:

| field | reached the model |
|---|---|
| `present_for_only_part_of_the_recording` | 99.3% |
| `present_throughout` | **4.7%** |
| `n_containers_seen` | **0%** |
| `how_to_read` | **0%** |

**Why this is the whole story.** An injected stress process SPAWNS, so it lands in the first
list. A CPU-capped or network-degraded container was already running, so it only lands in
`present_throughout` - the list the agent essentially never saw. WHERE splits exactly there,
on both applications:

| culprit | Sock Shop | Train Ticket |
|---|---|---|
| spawns (anomaly_cpu, noisy_neighbor) | 55/60, 40/60 | 54/60, 55/60 |
| already running (slow_db, svc_cpu_cap, svc_net) | 24/60, 1/60, 0/60 | 3/60, 0/60, 0/60 |

**The cap was buying nothing.** Peak context use is 26.6k tokens at the median run and 48.7k at
the maximum - 6.6% of the model's 400k window. We were destroying evidence to save room that
was never in use.

### The fix

`_fit_result()` trims by dropping whole ROWS from the longest lists, then grows them back to
fill the budget, and writes a `_truncated` block naming what it dropped so the model can tell a
subset from a complete answer and re-query. Per-tool budgets sized to carry each tool's median
result whole (`ctf_proclife` 45 KB, `ctf_procdiff` 24 KB, `ctf_lines` 18 KB, default 12 KB).

Replayed over the real results. At the new budgets nothing is cut at all. Held to the OLD
6000-char budget, so the comparison is like for like:

| | old slice | new fitter |
|---|---|---|
| unparseable output | 100% of cut results | 0 |
| `present_throughout` delivered | 8.7% | 99.0% |
| `how_to_read` delivered | 0% | 99.0% |

**This invalidates the 720 runs for comparison against anything run after it.** That is the
right trade - the old number is a measurement of a harness bug - but it means the q2-ss/q2-tt
results are now "agent v1" and must be labelled that way, not silently compared against.

**Lesson worth keeping: the tool results were always correct.** Everything above was already
sitting in the transcripts. The agent was never the bottleneck we thought it was; the pipe to
it was. Before adding capability to an agent, check what it is actually receiving.

## Exercising the tools on five runs found four bugs, three of them silent

Ran every tool across five runs spanning five fault families and both applications, checking
the tools against EACH OTHER rather than just checking that they return. A per-tool smoke test
proves a tool answers; only a cross-check tells you the answer is right.

**1. run_python gave wrong numbers on every Java application.** `pd.read_csv(comment="#")`
treats `#` as starting a comment ANYWHERE in a line, not only in column 0 - and the JVM names
its garbage-collector threads `GC Thread#0` .. `GC Thread#12`. Those rows were truncated at the
`#`, leaving 3 fields instead of 6, so `pid_ns` came back float64 full of NaN and the counts
dropped out of every sum.

| run | rows with `#` | events they carry |
|---|---|---|
| `tt_slow_db_..._r1` | 594,066 | **23,013,384** |
| `tt_deadlock_..._r1` | 372,821 | 643,085 |
| any Sock Shop run | 0 | 0 |

That is why it looked fine: Sock Shop has no `#` in any procname, so run_python matched
query_ctf exactly there and under-reported by 2% on Train Ticket. **A tool that is wrong only
on one application, by a few percent, with no error** - the worst kind. Now `skiprows=1` with
no comment character.

**2. ctf_timespan reported the last BUCKET START as the end of the recording.** A bucket is
100 ms, so the recording ends one bucket later. `query_ctf` takes a half-open `[begin, end)`
and dropped that bucket; `ctf_timeline` covered it. Two tools, same question, different answers
- 16,831,871 against 16,834,031 on `svc_cpu_cap_..._r1`. Small, but the agent is asked to work
out WHEN something happened, and the end of a recording is exactly where a recovery sits.

**3. Printing a dtype crashed the sandbox with `KeyError: '__import__'`.** Leaving `__import__`
out of builtins looked safe and was not usable: numpy imports lazily from inside ordinary
operations, so `print(df['pid_ns'].dtype)` died. A baffling error for a correct line of pandas,
which an agent would read as "the tool is broken". Now served from `sys.modules` only - nothing
new loads, no file opens, and the AST scan still rejects the name.

**4. My own test claimed a tool bug that was mine** - it summed `series[i]["count"]` when the
key is `"n"`, and reported ctf_timeline as returning zero. Worth recording because a test that
cries wolf costs more than no test.

**What did NOT break**, across both applications: ctf_proclife's container count against the
index, ctf_procdiff's rates, the new `value_sum` (1151.7 CPU-seconds over 244 wall-seconds on
a 21-container host is physically sane), and the TCP header now present in network lines on
all five runs.

**Method note worth keeping.** Every one of these came from two tools disagreeing, not from a
tool failing. Checking that a tool returns something would have passed all four.

## v2 on the network problems: it fixes WHEN, not WHERE - and WHERE was never a data limit

Ran three arms on `svc_net` and `anomaly_net`, both applications, 48 cells each. The middle arm
is the point: without it "v2 is better" cannot be attributed to the agent rather than to the
plumbing fixed underneath it the same day.

| | A v1+old tools | B v1+fixed | C v2+fixed |
|---|---|---|---|
| SS `svc_net` window IoU | 0.543 | 0.569 | **0.776** |
| SS `anomaly_net` window IoU | 0.310 | 0.333 | **0.623** |
| TT `svc_net` window IoU | 0.262 | 0.311 | **0.559** |
| TT `anomaly_net` window IoU | 0.090 | 0.154 | 0.190 |
| SS `svc_net` WHERE | 0/30 | 0/12 | **0/12** |
| TT `svc_net` WHERE | 0/30 | 0/12 | **0/12** |

**A->B is small, B->C is the move.** The tool fixes bought speed (334 s -> 115 s a cell, from
the line samples) and about +0.04 IoU. The new agent roughly doubles IoU on three of four.

**And WHERE did not move at all on `svc_net`. Zero in every arm, on both applications.**

### Why: it answers `host`, and that is a guidance failure, not a data limit

The agent says `host` in 10-11 of 12 cells on both applications. So I checked offline whether
the kernel trace can localise this fault at all. The fault is `tc qdisc` netem inside one
container's netns - 150 ms delay, 40 ms jitter, 4% loss on its eth0 - so that container's
packets should slow while every other container's do not. Summed network events per `pid_ns`,
baseline against the real injection window:

| run | target | lowest ratio | median of the rest | separation |
|---|---|---|---|---|
| `svc_net_..._r1` | carts | 0.184 | 0.694 | 3.8x |
| `svc_net_..._r2` | carts | 0.155 | 0.630 | 4.1x |
| `svc_net_..._r3` | carts | 0.179 | 0.729 | 4.1x |
| `tt_svc_net_..._r1` | ts-basic-service | 0.087 | 0.688 | 7.9x |
| `tt_svc_net_..._r2` | ts-basic-service | 0.095 | 0.786 | 8.2x |
| `tt_svc_net_..._r3` | ts-basic-service | 0.130 | 1.285 | 9.9x |

**Six of six, both applications. Exactly one container collapses to 9-18% of its baseline
packet rate while the median container sits at 63-129%.** The signal is large, consistent and
sitting in a column the agent already has.

**So `svc_net` scoring 0/60 in the published results is not evidence that kernel traces cannot
localise a per-service network fault.** It is evidence that nothing ever told the agent to
compute a per-container network rate and rank it. That is a blueprint change with measurement
behind it, which is the bar this repo sets.

### Two bugs found on the way, both mine, both silent

`run_python` failed **80% of the time** in the first pass - and that run is what produced the
first, worse, v2 table. 42% rejected for `import pandas as pd`, a habit no prompt wording
prevents; 38% killed by `libgomp: Thread creation failed` when eight parallel cells each
started a numpy child that sized an OpenMP pool to a 192-core shared login node. Those cells
ran with no working code tool at all and nothing said so. After fixing both: failures 80% ->
10-33%, and TT `anomaly_net` abstentions 11/12 -> 5/12. **The TT regression I was about to
report was my sandbox, not the agent.**

A second-round review crashed every cell it touched with `KeyError: '_task'` - `_after_review`
returned the node NAME, and a plain conditional edge hands the node the whole graph state while
`Send` hands it the per-worker payload. 13 of 48 cells, only the ones where the reviewer asked
for more work, which reads as flakiness.

### Cost

| arm | secs/cell | tokens/cell |
|---|---|---|
| A v1 + old tools | 334 | 100k |
| B v1 + fixed tools | 115 | 159k |
| C v2 + fixed tools | 215 | 345k |

v2 is 3.5x arm A's tokens for roughly double the window accuracy. Worth it for a study; worth
watching before a 1320-cell campaign.

## Per-container ranking in the network blueprint: first non-zero WHERE on svc_net

Four steps, each one exposing the next.

**1. Measure before writing.** Summed network events per `pid_ns`, baseline against the real
injection window: on one application the injected container ranks FIRST in 3 of 3 runs at
0.155-0.184 of baseline against a median of 0.63-0.73. Verified it is the RIGHT container, not
just an outlier, with a new `nsmap.py` that matches containers to namespaces by CPU time -
`meta/` records `cpu.stat usage_usec` per container, the index records summed
`sched_stat_runtime` per `pid_ns`, and both measure the same thing.

**2. The scorer credited any namespace as correct.** `score_where` returned `container` for ANY
`pid_ns` the agent mentioned. Harmless until a blueprint asks the agent to pick one - then
"rank them and name the lowest" scores right whether the ranking worked or not. **I was one
commit from measuring exactly that.** Now three outcomes: `container`, `container_wrong`,
`container_unverified`.

`nsmap` refuses when ambiguous, and that matters: on the second application 27 of 41 adjacent
containers sit within 15% of each other on CPU, so rank-matching put the target at rank 4, 21
and 5 across three runs. **Everything below is therefore one-application evidence.** The other
application is not a negative result, it is an unmeasurable one.

**3. The agent computed the ranking and then threw it away.** Blueprint v4 landed: 6 of 6
given-arm cells ran `groupby('pid_ns')`, with all 20 namespaces in their own output. Then they
answered `java`, `node`, `conn487`, `host`. `submit_diagnosis` was asking for that - its
description led with "a process name", so the schema and the blueprint disagreed about the
shape of the answer. A bare `java` locates nothing on a host running several Java services.

**4. Requiring the pid_ns is what produced the result.**

| | WHERE correct | wrong container | still `host` |
|---|---|---|---|
| blueprint v3 | 0/6 | 0 | 6 |
| blueprint v4 | 0/6 | 0 | 3 (+3 named a runtime) |
| v4 + pid_ns required | **2/6** | 2 | 2 |

The two correct ones answered `java in pid_ns 4026532538`, which is exactly the injected
container. Of the two wrong ones, one named the database that container talks to - the victim,
not the culprit. A sensible error rather than a random one.

**Honest limits.** n=6 per cell, so 2/6 is two runs; this establishes direction and mechanism,
not size. The window numbers moved around by 2-3 runs in both directions and should not be read
at this n. What IS established: the signal exists, the agent now computes it, and the answer
format was the last thing in the way.

**The general lesson, and it has now cost four separate bugs today.** `svc_net` scoring 0/60
looked like a finding about kernel traces. It was three layers of plumbing: a reply cap that
deleted the container list, a blueprint that reasoned only about interfaces, and an answer
schema that asked for a process name. **Check what the agent receives and what it is allowed to
say before concluding anything about what it can do.**
