# 29 September 2026

## The note_finding gap closed, and four iterations of inspecting single runs to get there

Requirement: nothing cut anywhere - tool output, worker memory, scratchpad, synthesiser input -
verified by looking, not by assuming. Built `agentic-rca/inspect_run.py` to open one run all the
way up, because none of the existing summaries would have shown any of what follows.

### The result

| | run 1 (before) | run 4 (after) |
|---|---|---|
| `dependency_outage` WHERE | unknown | **`app in pid_ns 4026532822` - correct** |
| window IoU | 0.92 | **1.00** |
| fault type | normal | **dependency_outage** |
| `lock_contention` WHERE | - | **`python3 in pid_ns 4026533609` - the injector** |
| tool results cut | 1 | **0** |
| computations truncated | 10 of 26 | **0** |
| results dropped for length | yes | **no** |
| worker threads elided | 0 | 0 |
| peak prompt | 23k tokens (5.7%) | 39k tokens (9.8%) |

`dependency_outage` is now exactly right: right container, right fault, IoU 1.00, confidence
0.98. It is the first time this problem has been answered correctly.

### Four separate causes, found one per iteration

**1. The scratchpad only carried what a worker chose to write.** Fixed by capturing every
run_python result automatically and showing it to the synthesiser as raw output under its own
heading, with an instruction to trust the numbers over any worker's summary. Recording a CLAIM
stays voluntary; recording WHAT WAS COMPUTED is not. A worker that ends having recorded nothing
now gets one nudge, because silence reads identically to "checked and found nothing".

**2. Three sandbox bugs cost 8 snippets across two runs, all ours.**

- `count` is a column name AND a DataFrame method, so `df.groupby(x).count.sum()` returns the
  method and dies. Three snippets lost, including the one computing this blueprint's deciding
  test. Added an identical `n` column, said so in the description, enriched the error message.
- `unstack` and `pivot_table` import `pandas.core.reshape.reshape` on first use, which the
  descriptor cap blocks. Four snippets lost. The warmup now exercises every reshape entry point.
- The path-traversal scan rejected any `..`, which also matches range notation in printed output
  like `11:16..11:18`. One snippet lost to a false positive. Now `../` and `/..` only.

**3. Every cap was set below what the data needs.** Measured over 140 tool calls: `run_python`
was cut at 12,000 when its largest real result was 12,177, and the computed-output cap of 1,600
cut 25 of 47. All re-sized to the observed maximum plus 50%. That headroom is free - the biggest
prompt any model call saw was 23k tokens against a 400k window, so we were destroying
information to save context that was 94% empty.

`THREAD_BUDGET` is the one deliberate exception and stays tight, because a worker thread is
re-sent every step and its cost grows with the square of the turns. Trimming there is safe now
precisely because run_python output is captured separately.

**4. The workers kept filtering the answer out by SIZE, and the recipe never told them not to.**

This was the last one and the most interesting. The silent container ran at 1,242 events/s; the
busiest on the same host ran at 87,866. Workers restricted to "substantial containers" and the
synthesiser then wrote, in good faith:

> no active service container fell to near zero relative to its own baseline

True of the set it looked at, and the set excluded the answer.

**That is not the model being careless. It is a filter I would have written myself, and did** -
my own offline measurement of this same signature used a baseline floor. The mistake is that a
floor on absolute volume removes exactly the container this fault produces, because a service
that has stopped is small by definition and was often small before it stopped.

The recipe now says so explicitly, with the numbers, and gives a floor of ~50 events/s whose
only job is dropping pure noise.

### What this changes about how we read the earlier results

Three problems - `svc_net`, `svc_cpu_cap`, `dependency_outage` - have now each been shown to
fail for a reason that was NOT the agent's reasoning. Two were answer-format, one was this. In
every case the agent had computed the right number.

**The general lesson is about where the evidence dies, not about model capability.** It died at
a string slice, at a column-name collision, at a descriptor limit, at a cap set from a round
number, and at a sensible-looking filter. None of those would show up in a score.

### Cost on the new model

| | |
|---|---|
| `dependency_outage` | 930k tokens in, 981 s |
| `lock_contention` | 439k tokens in, 206 s |

Wider than the old model's 345k and more variable. A 1,320-cell campaign at ~700k average is
roughly 900M tokens. Worth sizing deliberately rather than assuming.

### One open item, not a bug

`lock_contention` scored `container_unverified`, because its ground truth target is `host` -
the fault is a sidecar injection, so there is no service to map a namespace to. The agent named
the injector correctly. The scorer has no way to confirm that, which is the sidecar caveat
already recorded on 28-09 showing up in the scoring rather than in the blueprint.

## Earliness scoring, built for the next campaign rather than retrofitted to the last

The rescorer for existing runs was dropped: everything is being re-run anyway, so salvaging old
scores is wasted work. What matters is that the NEXT run produces the metric end to end.

### The metric

| | |
|---|---|
| `onset_error_s` | claimed start minus true start, signed. Negative = named a start before the fault began |
| `detect_delay_s` | lateness only. Being early is not rewarded without limit - past a point it is an over-wide claim |
| `earliness` | `1 - delay/duration`, normalised by the incident's own length so faults of different durations compare |
| `earliness_gated` | **earliness x IoU. The headline** |

**The gate is the part that matters.** Earliness alone is trivially gamed - claim the whole
recording and the delay is zero by construction. Verified on constructed cases:

| case | onset | earliness | gated |
|---|---|---|---|
| exact | +0s | 1.00 | **1.00** |
| 30 s late | +30s | 0.75 | 0.56 |
| 60 s late | +60s | 0.50 | 0.25 |
| noticed after it ended | +128s | 0.00 | 0.00 |
| **claimed the whole trace** | -222s | **1.00** | **0.20** |

**An abstention scores None, not zero.** The agent's schema says a wrong window is worse than an
admitted gap; scoring an abstention as maximum lateness would contradict that and make honesty
cost more than guessing. They are excluded from the average and counted separately.

### Why this was worth doing at all

Measured on our own runs, IoU moved 0.543 -> 0.776 between agent versions while onset error
moved 121 s -> 7 s at p90. **The metric we published was hiding most of the difference.**

### Scored is not reported

Adding it to `score.json` and stopping there would have been the same as not having it. The
per-problem table now carries a `noticed` column - median onset error - and the report has a
section explaining the four numbers, the gate, and the abstention policy. `q2_svcnet_report` and
`q2_cmp_agents` print a median onset column too.

### Tested without the cluster, on purpose

`test_earliness_report.py` synthesises a results tree and generates a real report, checking that
a problem which notices instantly and one which notices a minute late come out distinguishable
(+0s against +62s), that the abstention does not drag the average, and that the explanatory
section is present. It runs locally in a second.

That test exists because the failure mode this week has repeatedly been a break BETWEEN two
correct components - a slice, a column-name collision, a cap, a filter. Scoring and reporting
are two components, and nothing was checking the join.

## conn_pool_exhaustion, first full matrix: 27/30 with the blueprint against 2/30 without

60 cells, Sock Shop, the published design, **0 failures and 0 rate-limit retries**. The first
time this blueprint has been run at all.

| arm | ask | n | container right | window hit | noticed |
|---|---|---|---|---|---|
| given | hint | 15 | **13** | 11 | -1s |
| given | nohint | 15 | **14** | 14 | -2s |
| none | hint | 15 | 2 | 8 | -2s |
| none | nohint | 15 | **0** | 0 | **+177s** |

**90% with the blueprint, 7% without.** That is the largest blueprint effect measured anywhere
in this study, and it is on the problem whose rewrite changed most - the generated version named
the connection HOLDER when the ground-truth target is the DATASTORE being exhausted.

### The earliness metric earned its place immediately

Look at the `none/nohint` row: **+177s median onset**. Without a blueprint and without a hint the
agent notices the trouble nearly three minutes after it starts, on a 120-second fault - it is
describing the recovery, not the incident. Every other arm notices within 2 seconds.

IoU could not have shown that. It would have reported "0 of 15 hit" and left the reason
invisible. The first real matrix run since adding the metric is also the first one where the
metric changed what we know.

### A rate limit that arrived as a success

The first attempt at this matrix lost all 120 cells. OpenRouter reports a token rate limit as
HTTP 200 with `choices: null` and the status buried in an error body, so the SDK raised nothing
and our retry never fired. Every cell died on `'NoneType' object is not subscriptable`, a
message that says nothing about the cause.

Fixed by raising on a 200-with-an-error-body, which puts it back on the retry path that already
existed, and by lengthening the backoff for rate limits specifically - 2/4/8 seconds put all
three retries inside the same exhausted window. Concurrency was the underlying cause: 6 cells x
2 applications x up to 4 workers is up to 48 concurrent calls. One application at `--jobs 3` is
12, and ran 60 cells with zero retries.

### The fault vocabulary had no word for this fault

`fault_ok` scored **0/60**, and it is an artifact rather than a failure. `conn_pool_exhaustion`
was not in `FAULT_TYPES`, so the agent could not utter it; it said `other` 33 times, which its
blueprint explicitly tells it to do when nothing fits, and was marked wrong every time.

This is not a general problem with the vocabulary - the six published problems map onto the
descriptive names and score 5-52 of 60. Four families simply had no entry: `conn_pool_exhaustion`,
`deadlock`, `lock_contention`, `priority_inversion`. All four added.

**The same shape as every other failure this week: the agent behaved correctly and the harness
could not record it.**

### Harness health

| | |
|---|---|
| tool results truncated | 1 of ~1900 - a `ctf_lines` result of 37,512 chars against a 25,000 cap |
| thread messages elided | 280, mean 10.6 KB - re-sent less often, not lost, since run_python output reaches the synthesiser separately |
| runs with no findings | 0 |
| workers nudged for silence | 0 |
| code snippets that errored | 32 of 1,166 (2.7%, down from 80% a week ago) |
| peak prompt | 53k tokens, 13.3% of the window |

The one truncation is worth raising `ctf_lines` for; 40 raw network lines can exceed 25 KB
because each carries the full TCP header.

### Cost, measured rather than estimated

749k prompt tokens median, 410 s median wall. 60 cells cost about **$5** and took **2.4 hours**
at `--jobs 3`. A full 1,320-cell campaign is roughly **$120 and 50 hours** at this concurrency -
worth deciding deliberately rather than assuming.

## deadlock: 30/30 with the blueprint, 3/30 without - and the scorer could not see it

60 cells, Sock Shop, 0 failed, 0 rate-limit retries, 3.5 hours. First run of this blueprint.

| arm | ask | n | container right | window hit | noticed |
|---|---|---|---|---|---|
| given | hint | 15 | **15** | 15 | +1s |
| given | nohint | 15 | **15** | 15 | +1s |
| none | hint | 15 | 3 | 2 | +180s |
| none | nohint | 15 | **0** | 0 | +180s |

Every blueprint cell got both the container and the window right. The fault runs 125 s, so the
`+180s` in the no-blueprint arms means they describe the recovery rather than the incident.

### The scorer was blind to correct answers, again

`deadlock` degrades no Sock Shop service. The recipe starts a container of its own running
`deadlock.py`, so ground truth says `target_service: host` with the real container buried in
`parameters.container`. `ns_for_service` had `host` to look up, resolved nothing, and every
correct answer scored `container_unverified`.

The agent named `pid_ns 4026533609` in 6 of the first 9 cells and was credited for none. That
namespace runs python3 where Sock Shop is Java/Go/Node, is absent from all 14 compose services,
and exists only 04:05:48.5-04:07:50.8 against an injection of 04:05:47-04:07:52. It is born with
the fault and dies with it.

**Third time this week that a "limit of kernel traces" was our own plumbing.**

`nsmap.ns_for_workload` resolves it by that lifespan - a property of `workload_start`/
`workload_stop`, not a pattern fitted to one trace. It refuses unless exactly one namespace
qualifies.

### The first version of that fix would have corrupted the other matrix

`conn_pool_exhaustion` also starts its own container, but its target is the DATASTORE being
exhausted - the victim, not the attacker. An unguarded fallback would have supplied the attacker
namespace as truth and marked every correct answer wrong. The fallback now fires only when
`target_service` is host or empty. Verified on real runs:

| | resolved via | changed by re-score |
|---|---|---|
| deadlock | `workload` 60/60 | 8 cells, all `container_unverified -> container` |
| conn_pool_exhaustion | `service` 60/60 | **0 of 60** |

That zero is the regression test passing on real data. It also confirms conn_pool independently:
the agent answered `mysqld in pid_ns 4026533886` and `catalogue-db` resolves to that namespace.

### Two process lessons, both self-inflicted

**I reset the cluster repo mid-matrix**, which CLAUDE.md says not to do. It split the run's
scoring across two versions. It did NOT affect the agent - `agent.py` was committed before
launch - so the 60 cells stay comparable, and re-scoring made them consistent. Cheap this time
because only the scorer had changed. It would not have been if I had touched the agent.

**The rescorer's first dry run tried to change all 60 cells to `none`.** Two bugs: `diagnosis.json`
IS the diagnosis rather than `{"diagnosis": ...}`, and `judge` returns the WHERE axis one level
down. Had it written, all 60 scores would have been destroyed and only a 3.5-hour re-run could
have recovered them. **Dry-run-before-write is the only reason that was a non-event.**

### Why re-score rather than re-run

Standing preference is to re-run. It was wrong here: the RUN was right and the SCORER was wrong,
so the answers on disk are already correct and a re-run costs 3.5 hours and about $5 to reach
them again. `q2_rescore_where.py` reads only files the run already wrote, calls no model, and is
idempotent - a second pass changes nothing. `score.json` now records `true_ns` and `true_ns_via`
so this class of problem is visible on disk next time instead of needing to be re-derived by hand.
