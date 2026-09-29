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
