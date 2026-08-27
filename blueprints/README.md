# Observability blueprints

A blueprint is one solved investigation written down so it can be **re-executed** — by a
person or by an agent. It records what to *collect*, what to *run*, and what to *produce*,
not just what was concluded.

Source: the 2026-08-26 meeting (`blueprint-idea.md`). Naser's term is **blueprint**, not
"template".

## What is here

```
blueprints/
├── schema/blueprint.schema.json      the format
├── cpu-contention-co-tenant.json     blueprint 1
├── db-latency-dependency-wait.json   blueprint 2
└── lib/blueprint_to_skill.py         validator + skill generator
```

The two blueprints are **mutually exclusive on purpose**. They are the same tool on the
same trace reaching opposite verdicts:

| | CPU contention | Datastore wait |
|---|---|---|
| Kernel signature | `runnable_wait` up — ready to run, no CPU free | `off_cpu_io_wait` up — blocked on something external |
| On-CPU share | low, and the service is *not* working | near zero, and the component is idle |
| Culprit | an off-call-path container | the converged-on datastore |
| Kernel events needed | **5**, scheduler only | **8**, scheduler **plus syscall entry/exit** |

That last row is the point worth showing: the two collection orders genuinely differ. CPU
contention only needs to know *that* a thread stopped running; the datastore case needs to
know *which syscall it stopped in*. A blueprint that says "collect kernel data" would be
useless for both.

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

## The rule: measure first, then write

**No claim goes into a blueprint until it has been measured on our own data.** Not one
discriminator, not one threshold. Confidence is not evidence.

The order is always: write the measurement script -> run it on labelled incidents -> read
the numbers -> author the blueprint from what was observed. `lib/measure_wait_signature.py`
and `lib/measure_signature.py` exist for exactly this, and the validator **rejects** any
discriminator that does not cite the measurement that proved it.

This is not theoretical. Both blueprints here reached v2 because measurement contradicted
the first draft:

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

## Layout — one folder per problem

Everything for one anomaly lives together, so this holds up at hundreds of blueprints:

```
blueprints/
├── schema/blueprint.schema.json
├── lib/                                shared: generator, validator, measurement
└── problems/<problem-id>/
    ├── blueprint.json                  the record
    ├── skill.md                        GENERATED - never hand-edit
    ├── scripts/                        this problem's analysis code
    ├── evidence/                       the measurements that justify every claim
    └── results/                        per-run outputs
```

## Using it

```bash
# validate only
python3 blueprints/lib/blueprint_to_skill.py "blueprints/problems/*/blueprint.json"

# validate and generate the agent-facing skills
python3 blueprints/lib/measure_wait_signature.py --out evidence/wait_signature.json   # ALWAYS FIRST
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

## Not done yet

- `lib/cpu_attribution.py`, `lib/edge_convergence.py`, `lib/dependency_verdict.py` — the
  final per-blueprint steps that emit the JSON verdict, chart and explanation. The earlier
  steps in both blueprints run today against existing code.
- The with/without-blueprint experiment (RQ1).
