# Agent design: RCA from a trace, with no idea what is wrong

Written 16 September 2026. This is a design. Nothing here is built yet.

## The setting we are building for

A company hands us a trace file. That is all.

- We do not know what the problem is.
- We do not know if there **is** a problem. It may be a healthy trace.
- The agent must work it out and say what it found.

This is harder than what we have tested so far. Every test to date told the agent
there was a fault. It only had to say which one.

---

## Three things block this today

I checked the 11 blueprints before designing. These need fixing first.

### 1. The symptom words are made up per blueprint

Each blueprint lists `applicable_symptoms`. There are 24 words across 11 blueprints.
**22 of the 24 are used by only one blueprint.**

| word | used by |
|---|---|
| `throughput_drop_without_errors` | 5 blueprints |
| `many_services_slow_simultaneously` | 3 blueprints |
| the other 22 | 1 blueprint each |

Each blueprint invented its own words. So matching on them would pick the right blueprint
almost every time. Not because selection works. Because the word names the answer.

**If we build on this, our selection score is meaningless.**

**Fix:** one shared word list. Every blueprint picks from it. No blueprint may add a word
that only it uses. Then two blueprints that look alike will share words, and selection has
to do real work.

### 2. `cheap_precheck` is a sentence, not a test

Ten blueprints have one. All are prose. Example:

> "host CPU utilisation over the incident window: if it is not near the ceiling, this
> blueprint does not apply and a cheaper answer exists"

A person can run that. A program cannot.

**Fix:** each precheck needs a capability id, a threshold, and a direction. Then it runs.

### 3. `service-memory-cap` is incomplete

It has no `cheap_precheck` and no `capabilities_required`. So it cannot be pre-filtered and
cannot drive collection. It is one of our 11.

---

## How the agent will work

Five steps.

```
1 TRIAGE      is anything wrong at all?        -> if no, stop and say "healthy"
2 SURVEY      cheap, fixed measurements        -> a list of symptom words
3 RANK        score all 11 blueprints          -> an ordered shortlist
4 CONFIRM     run the top one properly         -> verdict, or switch, or give up
5 REPORT      fault, service, evidence, confidence
```

### Step 1: triage

Needed because the trace may be healthy. Nothing in our harness does this today.

Compare the incident window against the run's own baseline window. If nothing moves beyond
a set margin, answer "healthy" and stop.

This step alone decides whether the agent is usable in industry. A tool that finds a fault
in a healthy system is worse than no tool.

### Step 2: survey

A small fixed set of cheap measurements. The same set for every run. It does not depend on
any blueprint, so it cannot leak the answer.

Output: which symptom words are true, from the shared list.

### Step 3: rank

For each blueprint, score it against the survey:

- symptom words that match: score up
- `do_not_apply_when` conditions that are true: score down hard
- `cheap_precheck` fails: drop it

Output: an ordered list, not one pick. Keep the order. We need it for the ranking scores.

**This is where brute force is avoided.** The cheap prechecks remove most blueprints before
any expensive work runs.

### Step 4: confirm

Run the top blueprint's `processing` steps. Check `decision.verdict_when`.

- verdict holds: report it
- `decision.rule_out` matches: switch to the blueprint it names, try again
- confidence below the floor: collect more, up to `max_evidence_rounds`
- shortlist exhausted: say "I do not know", do not guess

Count how many blueprints get fully run. That number is the anti-brute-force score.

### Step 5: report

Fault, service, the numbers that decided it, and a confidence. Or one of two honest answers:
"healthy" or "I could not tell".

---

## Not guessing is a feature

The agent must be allowed to say "I do not know".

An agent that always answers will score better on plain accuracy and be worse in practice.
So we score answers and abstentions separately, and report both.

---

## The scores we will report

For a top venue, one accuracy number is not enough.

### Did it spot a problem at all

Uses the `normal` runs. 10 per app.

| score | meaning |
|---|---|
| precision, recall, F1 | over "is there a fault" |
| false alarm rate | how often it cries wolf on a healthy trace |

### Did it name the right fault

| score | meaning |
|---|---|
| AC@1, AC@3, AC@5 | right answer in the top 1, 3, 5 |
| Avg@5 | the mean of AC@1 to AC@5 |
| MRR | how high the right answer sat |
| per-fault precision, recall, F1 | catches a fault that is always wrong |
| macro-F1 | all faults count equally, not just common ones |
| confusion matrix | shows which faults get mixed up |

The confusion matrix matters. We already know memory faults get called CPU faults.

### Did it point at the right service

AC@1 and AC@3 on the service. The harness has this already.

### Did it know when to stop

| score | meaning |
|---|---|
| coverage | how often it answered at all |
| accuracy when it answered | is it right when it speaks |
| risk-coverage curve | accuracy as we force it to answer more |

### Was it efficient

| score | meaning |
|---|---|
| blueprints fully run per trace | 1 is ideal, 11 is brute force |
| tool calls, tokens, wall time | cost |
| seconds of data needed | early detection |

### Is the difference real

| what | why |
|---|---|
| repeat every run several times | one run tells us nothing |
| 95% ranges, not single numbers | show the spread |
| paired test between setups | same traces both sides, so pair them |
| noise floor measured first | September guessed it |

---

## What we compare against

A number alone means nothing. Each of these answers "compared to what".

| baseline | why it matters |
|---|---|
| pick at random | the floor |
| **run all 11, keep the best** | the brute-force one. Shows what selection is worth |
| no blueprint, model alone | the September control |
| rule engine only, no model | it already gets 38 of 41 |
| RCAEval / BARO | a published method, not ours |

The brute-force baseline is the one reviewers will ask about. If our agent matches it while
running 1 blueprint instead of 11, that is the result.

---

## Which runs

Only families that have a blueprint, plus healthy runs.

| family | blueprint | SS | TT |
|---|---|---|---|
| `normal` | none, answer is "healthy" | 10 | 10 |
| `anomaly_cpu` | host-cpu-saturation | 5 | 5 |
| `anomaly_disk` | host-disk-saturation | 5 | 5 |
| `anomaly_net` | network-path-degradation | 8 | 8 |
| `noisy_neighbor` | cpu-contention-co-tenant | 8 | 8 |
| `slow_db` | db-latency-dependency-wait | 11 | 11 |
| `svc_cpu_cap` | service-cpu-throttle | 8 | 8 |
| `svc_mem_cap` | service-memory-cap | 8 | 8 |
| `fd_exhaustion` | fd-exhaustion | 5 | 5 |
| `fork_storm` | fork-storm | 5 | 5 |
| `data_exfiltration` | data-exfiltration | 5 | 5 |
| `dns_delay` | dns-delay | 5 | none |

About 83 Sock Shop and 78 Train Ticket runs. Far more than September's 57.

Drop runs the campaign marked as failed to inject. Known ones: `svc_cpu_cap` on Train Ticket
(8 of 8), `slow_db` on Train Ticket (10 of 11), `fd_exhaustion` on Sock Shop (5 of 5).

**Keep the healthy runs in.** They are the point.

---

## Order of work

1. Build the shared symptom word list. Rewrite all 11 blueprints to use it.
2. Make `cheap_precheck` executable. Capability, threshold, direction.
3. Finish `service-memory-cap`.
4. Build triage and measure it on the healthy runs alone.
5. Build ranking. Score it offline, with no model, against brute force.
6. Build the confirm loop.
7. Run the full study.

Steps 1 to 3 are corrections to existing blueprints. Nothing works properly until they are done.

Step 5 gives a real number with no model cost, because ranking runs on packs we already have.

---

## Honest notes

- Nothing here is measured. It is a design.
- The symptom word problem means our earlier selection numbers may be too kind. September
  had the model read blueprint text, so the same worry applies there.
- Triage does not exist. We have never asked the agent whether a trace is healthy.
- `service-memory-cap` cannot take part in the collection setup until it is finished.
