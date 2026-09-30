# How to read a run digest

What every line in the **Result** block of `run_digest.py` means, and how it is computed.

The worked example throughout is the `deadlock` matrix (60 cells, Sock Shop, 30 Sept 2026) —
`results-download/deadlock/DIGEST.md`.

```
named the right container    33 / 60
named the wrong one          3
named one we cannot verify   0
fault type right             29 / 60
window hit                   32 / 60
noticed, median / p90        +1s / +180s
earliness (gated), mean      0.737
abstained on the window      20
```

**These are three independent things**: *where* the fault is, *when* it happened, and *what
kind* it was. A run can get one right and the others wrong. They do not sum to anything.

Source: `blueprints/lib/q2_judge.py` (WHERE) and `blueprints/lib/q2_run_one.py`
(`score_window`, for WHEN and earliness).

---

## WHERE — the first three lines

A kernel trace carries **no service names**, only a numeric `pid_ns` per container. So
"naming the container" means the agent answered something like
`python3 in pid_ns 4026533609`. That is the most precise answer the trace allows.

All 60 cells fall into one of these:

| verdict | n | meaning |
|---|---|---|
| `container` | **33** | named a pid_ns, and it was the right one |
| `container_wrong` | **3** | named a pid_ns, wrong container |
| `wrong` | 21 | did not name a container and was not right (mostly "unknown") |
| `scope` | 3 | answered **"host"** — true for a host-scoped fault, but less useful |
| `named` | 0 | named the service by name (rare; the kernel gives no names to work from) |
| `ambiguous` | 0 | a shared runtime process (`java`) that maps to several services |

**36 cells committed to a specific container.** The three digest lines break those 36 down.

### named the right container — 33 / 60

The agent's pid_ns matched the true one.

**Verified, not trusted.** The scorer resolves the true namespace itself and compares —
`nsmap.ns_for_service` for a service-targeted fault, `nsmap.ns_for_workload` for a fault that
runs in its own container. The denominator is all 60 cells, not the 36 that answered.

> An earlier version of this branch credited **any** pid_ns as correct. That was harmless
> while no blueprint asked the agent to pick a container, and stopped being harmless the
> moment one did. It was caught one commit before it would have produced a fake improvement.

### named the wrong one — 3

Committed to a container and picked a different one. A real error, and a different kind from
"I don't know".

### named one we cannot verify — 0

The agent named a pid_ns but the scorer **could not work out which container was true**, so
it refuses to credit *or* penalise.

**This is a harness health check, not a result.** If it is high, the scorer is blind and the
other two numbers are understated. It read **8** on this matrix before re-scoring: `deadlock`
runs in a container of its own, ground truth says `target_service: host`, and the scorer had
nothing to resolve. Those 8 were all correct answers.

`score.json` records `true_ns` and `true_ns_via` (`service` / `workload` / `unresolved` /
`error`) so this is auditable after the fact instead of needing to be re-derived by hand.

---

## WHEN — the next four lines

The agent is never told the fault happened, or when. It must state a window itself.

### window hit — 32 / 60

Overlap between the claimed window and the true injection window, as IoU
(intersection ÷ union):

| verdict | n | rule |
|---|---|---|
| `hit` | **32** | IoU ≥ 0.5 |
| `partial` | 1 | overlapped, but IoU < 0.5 |
| `miss` | 7 | no overlap at all |
| `abstained` | **20** | said "unknown" |

Two numbers sit behind IoU, because one hides the failure modes:

- **recall** — how much of the real incident the claim covers. Low = missed it.
- **precision** — how much of the claim is really incident. Low = claimed half the recording
  and happened to contain the answer, which is not a finding.

### abstained on the window — 20

The agent declined to guess. **Scored as nothing, not as wrong.**

The answer schema tells the agent that a wrong window is worse than an admitted gap. The
metric has to agree, or the instruction is a lie and the agent is punished for honesty.
Abstentions are excluded from the earliness mean rather than counted as 0.

### noticed, median / p90 — +1s / +180s

```
onset_error_s = claimed_start − true_start      signed: negative = noticed EARLY
```

Over the 40 cells that gave a window: min +1s, median +1s, max +181s.

- **median +1s** — the typical run pins the start to within a second
- **p90 +180s** — the worst tenth are about three minutes late, on a **125-second fault**.
  They are describing the recovery, not the incident.

**This is why the metric exists.** Those 40 cells could all have identical IoU and still
differ by three minutes in when they noticed. Measured across agent versions, IoU moved
0.543 → 0.776 while onset error at p90 moved 121 s → 7 s. IoU alone would have called them
nearly the same.

### earliness (gated), mean — 0.737

Two steps:

```
earliness = 1 − (lateness ÷ fault duration)     clamped to 0..1
                                                1.0 = caught it as it started
                                                0.0 = not until it was over
gated     = earliness × IoU
```

`lateness` is `max(0, onset_error_s)` — noticing early is not penalised, but it does not earn
extra credit either. Normalising by the fault's own duration lets faults of different lengths
compare.

**Why the gate.** Earliness alone is trivially gamed: claim the whole recording and lateness
is zero by construction. IoU punishes an over-wide claim through precision, so the product is
only high for a window that is both **early and tight**.

Mean is over the 40 cells that answered.

---

## WHAT — one line

### fault type right — 29 / 60

The agent picks a label from a fixed list of 17. Here it said `deadlock` 29 times, `normal`
21, `other` 10.

**This is the least important axis, and the one to treat with most suspicion.** It read
**0/60** the previous morning — `deadlock` was missing from the list, so the agent could not
say the word and scored zero no matter how well it diagnosed the problem. Four fault families
had no entry at all.

The real answer is `what_is_wrong`, the agent's own prose, scored by concept coverage. The
label is a tally convenience.

---

## Reading them together

For the `deadlock` matrix:

| | |
|---|---|
| 33 of 60 named the right container | **all 30 blueprint cells, plus 3 of 30 without** |
| 3 named the wrong one | **all 3 in the no-blueprint arm** |
| 20 abstained on the window | rather than guess |

The blueprint arm produced **zero wrong containers**. Its failures are abstentions, which is
the behaviour we want when the evidence is thin.

---

## Before trusting any of it: the harness block

`run_digest.py` prints harness health **above** the result, deliberately.

| check | what a bad value means |
|---|---|
| tool results truncated | the model never saw part of an answer |
| thread messages elided | trimming dropped context (re-sendable, not lost) |
| runs with no findings recorded | workers investigated and recorded nothing |
| workers nudged for silence | a worker stalled and had to be prompted |
| code snippets that errored | the sandbox rejected the agent's own analysis |
| peak prompt | how close to the context limit the run came |

**Three times we read a low score as a limit of kernel traces and all three were our own
bugs**: a reply cap slicing JSON mid-number, a fault name missing from the vocabulary, and a
scorer with nothing to verify against. Each time the agent had been right and the harness
could not record it.

Check the harness before believing the score.

## Opening one run

```
python agentic-rca/inspect_run.py <path>/transcript.jsonl --full
```

Prints the run in order: every tool call with arguments and full result, whether anything was
truncated, what thread trimming removed, the scratchpad, the code the agent wrote and ran,
and what the synthesiser was finally given.
