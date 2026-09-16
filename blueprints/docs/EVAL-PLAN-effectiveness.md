# Plan: do blueprints help an agent do RCA?

Written 16 September 2026. This is a plan. Nothing here is measured yet.

The goal is to answer three questions:

1. Do blueprints make an agent better at finding the fault?
2. What are the good and bad sides of using one?
3. Can a blueprint agent spot the problem earlier?

---

## What we already know

We ran a with/without test on 2 September. 57 incidents, both apps, one model.
Full write-up: `RESULTS-withwithout.md`.

**The result was a tie.**

| | got it fully right |
|---|---|
| without blueprints | 32 of 57 |
| with blueprints | 29 of 57 |

The gap is 3 runs. Our noise floor is about 2 runs. So the two are level.

Three things from that test shape this plan.

**1. Picking the wrong blueprint is the problem.**
The model picked a blueprint 27 times. It picked the right one 19 times.
Every run that got worse was a wrong pick. No blueprint gave bad advice about its own fault.
The network blueprint was never picked, in 9 network incidents.

**2. Rules work. The same rules as text do not.**
Our rule engine reads the same kernel data and names the right fault 38 times out of 41.
The model, given those rules as text, gets about half.

**3. We only tested half a blueprint.**
Both sides got the evidence pack. That pack already holds the numbers the blueprint asks for.
So we tested "how to read the numbers". We never tested "what to collect".

That third point is the main gap this plan fills.

---

## The four setups

Same runs. Same scorer. Same model.

| setup | gets the evidence pack | gets a blueprint |
|---|---|---|
| A | yes | no |
| B | yes | as text |
| C | yes | as an executable rule, plus the model for the rest |
| D | **no** | yes. The blueprint says what to collect |

A and B are what we ran in September. We repeat them so all four sit in one table.

**D is the important one.** The agent gets no pack. It must work out what to collect.
This is the half we never tested. A blueprint should help most here.
The model has no way to guess that it should measure how long threads wait for a CPU.

C tests the fix our own numbers point to. Ship the decision as code, not as text.
The rule does the number check. The model does selection, explaining, and faults with no blueprint.

---

## What we measure

For every run, in every setup:

| what | why it matters |
|---|---|
| right fault | the main score |
| right service | did it point at the right place |
| picked the right blueprint | this is where September went wrong |
| abstained when it should | a fault with no blueprint should get no blueprint |
| number of tool calls | cost |
| tokens | cost |
| wall time | cost |

The harness already records all of these (`agentic-rca/evaluate.py`).

### Good and bad sides

We report these as a table, not a single score:

| side | how we show it |
|---|---|
| helps | runs A got wrong and C or D got right |
| hurts | runs A got right and C or D got wrong |
| wrong pick | blueprint chosen did not match the real fault |
| cost | tool calls, tokens, time vs setup A |

In September every "hurts" case was a wrong pick. If that repeats, the fix is selection,
not blueprint content.

---

## Early detection

Nothing measures this today. It needs no new data.

Every run is 60 s baseline, 120 s incident, 60 s recovery. The incident start and end are
stamped in each run.

Give the agent a growing slice of the incident window. Try 10 s, then 20 s, then 30 s.
Record the first slice where the answer is right and stays right.

**Score: how many seconds of incident data were needed.**

Then compare the four setups.

This may be where a blueprint helps most. A blueprint names one thing to look at.
So it should need less data to cross a line. An agent with no blueprint has to search.

**Not yet measured. This is a guess we are setting out to test.**

Early detection is also worth having on its own. A setup that ties on accuracy but answers
in 30 s instead of 120 s is still better.

---

## Which runs to use

Do not use every family. Two rules.

**Skip faults that are already solved without help.**
Host CPU and disk scored 6 of 6 with no blueprint. There is no room to improve.

**Use faults with room to move.**

| family | why |
|---|---|
| `noisy_neighbor` | 0 of 6 without a blueprint, 2 of 6 with one. The model cannot do this alone |
| `anomaly_net`, `svc_net` | 9 network incidents, blueprint never picked once |
| `slow_db` | went down by 1 in September. Worth a second look |
| `svc_cpu_cap` | the blueprint fires too easily. 7 picks, right 3 times |
| the 5 `code_*` families | new. Metrics cannot see 3 of the 5. Kernel trace is the only source |

The `code_*` families are interesting for a second reason. Two of the five move a metric and
three do not (see `CAMPAIGN-ISSUES.md` issue 21). So they test whether a blueprint helps when
metrics show nothing.

### Run count

September used 57 incidents. That was too few. Only a change bigger than about 4 runs meant
anything.

v2 has 303 runs. Use more runs per family, and repeat each one. Report a range, not one number.

---

## What would count as a win

We set these before running, so we cannot move the line later.

| claim | what we need to see |
|---|---|
| blueprints help | setup C or D beats A by more than the noise floor |
| the collection half works | D beats A, even though D gets less data |
| executable beats text | C beats B |
| earlier answers | C or D needs fewer seconds of data than A |

If none of these hold, we say so. A tie is a result.

---

## Order of work

1. Measure the noise floor properly. Repeat the same run several times in setup A.
   September guessed it from a side case. That was weak.
2. Run A, B and C on the chosen families. A is the control. B against C tests text against code.
3. Build setup D. It needs the agent to request telemetry instead of being handed it.
4. Run the early-detection test on all setups.
5. Fix selection. Every bad case in September was a wrong pick.

Step 5 may turn out to be the whole answer. We will know after step 2.

---

## Honest limits

- One model. We do not know if this holds for others.
- The noise floor is about 2 runs and is not measured well yet. Step 1 fixes this.
- Setup D does not exist yet. It is the most work in this plan.
- Early detection is untested. We think a blueprint should help. We have no data for it.
- Cost in dollars is not recorded per run today.
