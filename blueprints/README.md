# Observability blueprints

A blueprint is one solved investigation written down so it can be **re-executed** — by a
person or by an agent. It records what to *collect*, what to *run*, and what to *produce*,
not just what was concluded.

Source: the 2026-08-26 meeting (`blueprint-idea.md`). Naser's term is **blueprint**, not
"template".

## The claim we are testing

A blueprint carries knowledge that actually helps during an RCA.

That is testable, so we test it. We give an LLM agent read-only tools over a raw kernel
trace, ask it to find the root cause, and vary two things independently:

| | no hint | hint |
|---|---|---|
| **no blueprint** | the hardest case | is a symptom description enough? |
| **blueprint** | does the method alone carry it? | both |

Four arms. The blueprint effect is the gap between the rows; the hint effect is the gap
between the columns. Separating them matters — otherwise "the agent did better" could just
mean "we told it what was wrong".

Every problem runs **3 incidents × 2 arms × 2 asks × 5 repeats = 60 runs**.

## What we have found so far

Kernel traces only. The agent is never told when the fault happened, or that there was one.

| problem | with blueprint | without | first run |
|---|---|---|---|
| `deadlock` | **30 / 30** | 3 / 30 | 2026-09-30 |
| `conn_pool_exhaustion` | **27 / 30** | 2 / 30 | 2026-09-29 |

"With blueprint" counts naming the right container, pooled across both asks. Both matrices
ran 60 cells with 0 failures.

The gap is large and it is the point of the project. But read the next section before
treating any single number as a property of blueprints.

### Three times the "limit" was our own plumbing

The published 720-run study reported 0–3 out of 60 on per-service faults and we read it as
*kernel traces cannot localise a fault to a service*. **That reading was wrong three
separate times**, and each time the agent had been right while the harness could not record
it:

| what looked like a limit | what it actually was |
|---|---|
| per-service faults score 0/60 | a 6000-char reply cap sliced tool results mid-JSON; the container list reached the model 4.7% of the time |
| `conn_pool_exhaustion` names the fault 0/60 | the fault name was missing from the vocabulary, so the agent literally could not say it |
| `deadlock` names the container 0/60 | the fault runs in its own container, ground truth says `target_service: host`, so the scorer had nothing to verify against |

The discipline that follows: **check the harness before believing the score.**
`agentic-rca/run_digest.py` leads with harness health — truncations, elisions, snippet
errors, peak prompt — and only then shows results.

## Capability-first: the blueprint never names a tool

This is the structural rule from Naser's architecture, and it is what separates a blueprint
from a script wrapper. A blueprint declares the **capability** it needs:

```
needs: kernel.scheduler.runqueue_delay
```

`providers.json` binds that capability to whatever tool is actually available — our
babeltrace2 script here, Trace Compass or a vendor's own analyser elsewhere. **Swap the
tool and the blueprint does not change.** That is what makes the knowledge portable, and
what makes the architecture tool-agnostic and model-agnostic rather than one more telemetry
pipeline.

The two supervisor constraints looked contradictory and are reconciled by this split:

| | |
|---|---|
| Naser: a blueprint must not name tools, only requirements | satisfied by `capability` |
| Mahsa: the exact callable must reach the model, or accuracy drops | satisfied by binding, which resolves to a real command before the agent sees it |

The validator enforces both: it rejects a capability with no *implemented* provider, so a
blueprint can never claim to be executable in an environment where it is not.

## A blueprint covers a class, not one incident

Each blueprint is placed in a problem taxonomy (domain → category → subcategory) with its
sibling causes listed, because many historical problems should collapse into one reusable
blueprint. It also carries:

- **applicability** — when to use it, when *not* to, and the cheapest check to run first
- **stopping conditions** — when to conclude, when to stop and switch to another blueprint,
  and what to say when the evidence is insufficient
- **adaptation rules** — what to do when the evidence does not fit the expected shape

A blueprint must also be willing to say **"not applicable here"**. `connection-pool-exhaustion`
is the clearest case: its signature is a collapse in per-connection setup work, and on an
application whose callers pool connections there is nothing to collapse — measured at 0.7–1.1
setup calls/s against 169–177 where it works. The blueprint tells the agent to report that
the check did not apply rather than name the next most suspicious container. A blueprint that
always produces an answer is not carrying knowledge; it is guessing with structure.

## The rule: measure first, then write

**No claim goes into a blueprint until it has been measured on our own data.** Not one
discriminator, not one threshold. Confidence is not evidence.

The order is always: write the measurement script → run it on labelled incidents → read
the numbers → author the blueprint from what was observed. The validator **rejects** any
discriminator that does not cite the measurement that proved it.

This is not theoretical. Both original blueprints reached v2 because measurement
contradicted the first draft:

| Draft claim | What 93 runs actually showed |
|---|---|
| "the delayed services show raised runnable-wait" | runnable-wait never exceeds **4%** in any fault family, and was **1.6%** on the co-tenant case. Unusable. |
| "the culprit's wait decomposition identifies it" | host-attributed faults have **no culprit-side L2 record at all** (5 families). Unmeasurable. |
| "the suspect shows dominant off-CPU external I/O wait" | true — and **equally true of every family** (98-99%). Identifies nothing. |

Retracted claims are not deleted. They stay in the blueprint under
`problem.unverified_do_not_claim`, with the measurement that killed them, and they are
rendered into the skill so the agent is warned off them too.

Note the split: `measurement` names fault families and is for our record; `agent_note` says
the same thing without the answer vocabulary, and that is what reaches the model.

## Scope: kernel traces only, for now

The dataset has four modalities — metrics, logs, distributed traces, kernel traces. **Phase
one uses kernel traces alone.** Not because the others do not matter, but because kernel
traces are the hardest case and the least studied: no service names, no request ids, no log
lines, just syscalls and scheduler events with numeric namespace ids.

If a blueprint helps there, it is carrying real method rather than restating what a log line
already says. The other modalities come after.

Steps a blueprint declares that kernel data cannot reach are marked **NOT REACHABLE**. The
agent is told to skip them, say it skipped them, and not treat their absence as evidence.

## The agent

`agentic-rca/` — a LangGraph plan → work → review → synthesise loop. Workers run in
parallel and record findings to a shared scratchpad that the synthesiser reads.

Seven read-only tools over the trace: `ctf_timespan`, `ctf_timeline`, `query_ctf`,
`ctf_lines`, `ctf_procdiff`, `ctf_proclife`, and `run_python`, plus `submit_diagnosis` to
answer. `run_python` lets the agent write and run its own analysis, which removes the
ceiling where it could only ask questions our fixed tools could express.

**Ground truth is never reachable by the agent.** It sits inside each run directory, so code
handed a run path is one `open()` from the answer. The sandbox never receives a path — only
a pre-loaded table. That rule is written at the top of `ctf_tool.py` and `codetool.py`, and
19 adversarial escape attempts were used to check it.

Generated skills are **leak-scanned**: fault labels, run ids and app names must not reach the
model.

## Evaluation

One score is not enough, because "right answer" has several independent parts.

| axis | what it asks |
|---|---|
| **WHERE** | `named` / `container` / `container_wrong` / `scope` / `wrong` — naming a container is verified against the true pid_ns, never taken on trust |
| **WHEN** | window IoU against the true injection window. `unknown` is an honest abstention, scored as nothing rather than as wrong |
| **earliness** | *how early* it noticed, not only whether the ranges overlapped |
| **WHAT** | concept coverage of the agent's own words, not a label match |
| **fault label** | a tally convenience, and the least important axis |

**Earliness earned its place immediately.** On `deadlock`, the no-blueprint arms show +180s
median onset against a 125-second fault — they are describing the recovery, not the incident.
IoU alone would have said "0 of 15 hit" and left the reason invisible.

`score.json` also records `true_ns` and `true_ns_via` — which namespace the scorer treated
as truth and how it resolved it — so a verdict can be audited afterwards instead of
re-derived by hand.

## Layout — one folder per problem

Everything for one anomaly lives together, so this holds up at hundreds of blueprints:

```
blueprints/
├── schema/blueprint.schema.json       the format
├── thresholds.json                    measured cut-offs, cited by blueprints
├── lib/                               generator, validator, measurement, scoring
└── problems/<problem-id>/
    ├── blueprint.json                 the record
    ├── skill.md                       GENERATED - never hand-edit
    ├── scripts/                       this problem's analysis code
    ├── evidence/                      the measurements that justify every claim
    └── results/                       per-run outputs
```

16 problem folders exist; **11 are wired into the experiment harness**:

| problem | blueprint |
|---|---|
| `anomaly_cpu` | host-cpu-saturation |
| `anomaly_net`, `svc_net` | network-path-degradation |
| `conn_pool_exhaustion` | connection-pool-exhaustion |
| `deadlock` | deadlock-lock-order |
| `dependency_outage` | dependency-outage-retry-storm |
| `lock_contention` | lock-contention-futex-storm |
| `noisy_neighbor` | cpu-contention-co-tenant |
| `priority_inversion` | priority-inversion-nice |
| `slow_db` | db-latency-dependency-wait |
| `svc_cpu_cap` | service-cpu-throttle |

## Using it

```bash
# measure FIRST - nothing enters a blueprint unmeasured
python3 blueprints/lib/measure_signature.py --out evidence/signature.json

# validate, and generate the agent-facing skills
python3 blueprints/lib/blueprint_to_skill.py "blueprints/problems/*/blueprint.json"

# run one problem's full matrix (60 cells)
python3 blueprints/lib/q2_run_matrix.py --problems deadlock --app sockshop \
    --incidents 3 --repeats 5 --agent v2 --jobs 3

# harness health first, scores second
python3 agentic-rca/run_digest.py <results-dir> --out digest.md

# open ONE run completely - every tool call, result, snippet, scratchpad note
python3 agentic-rca/inspect_run.py <path>/transcript.jsonl --full
```

The generator is why the blueprint is the artifact we maintain: the skill is derived, so the
two cannot drift apart.

## What the validator enforces

These are the rules that stop a blueprint from being prose:

- **every processing step carries a runnable command**, not a description (Mahsa's finding:
  naming the exact callable cuts model non-determinism)
- **exact tracepoint names** in the collection order — "kernel data" is rejected
- **discriminators are mandatory** — each says what this problem looks like *and* what it
  would look like if it were the look-alike instead
- **`rule_out` is mandatory** — a blueprint must say when *not* to conclude it
- **every declared output is produced by some step**
- **the generated skill body is leak-scanned** — fault labels, run ids and app names must
  not reach the model. `covers:` stays in the frontmatter, which the harness strips.

Blueprints not yet signed off carry `verified_by: PENDING` and the validator warns. Human
verification is part of the loop, not an afterthought.

## Cost

Measured, not estimated: **60 cells ≈ $5 and 2.5–3.5 hours** at 3 parallel runs, at about
750k prompt tokens per run. A full 11-problem campaign on both applications is roughly
**$120 and 50 hours** — worth deciding deliberately rather than assuming.

## Not done yet

- **9 of 11 problems have not had a full matrix on the current agent.** `deadlock` and
  `conn_pool_exhaustion` have; `dependency_outage` and `lock_contention` have smoke cells
  only; `priority_inversion` has nothing.
- Train Ticket matrices for the two finished problems.
- The other three modalities — metrics, logs, distributed traces.
- References: 8 entries across 16 blueprints, 9 blueprints carry none, and no citation
  currently reaches the agent.
