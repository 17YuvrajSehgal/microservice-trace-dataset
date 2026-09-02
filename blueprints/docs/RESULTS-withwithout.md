# With vs without a blueprint — the test the supervisor asked for

Run: 2 September 2026. 57 incidents, both apps, same model (gpt-5.4), same evidence.
Raw data: `blueprints/results/withwithout.json`.

---

## Short answer

**No difference.**

| | Fully correct |
|---|---|
| Without blueprints | 32 of 57 (56%) |
| With blueprints | 29 of 57 (51%) |

That looks like blueprints made it worse. **It did not.** See the noise check below — the
gap is inside the noise.

---

## The noise check (this is the important part)

On **30 of the 57 runs the model picked no blueprint at all.** On those runs both arms got
exactly the same input. Same evidence, same prompt, same model.

| Same input, both arms | Fully correct |
|---|---|
| Without arm | 15 of 30 |
| With arm | 13 of 30 |

**Two runs differ on identical input.** That is the model being random, nothing else.

So our noise floor is about ±2 runs. The overall gap is 3 runs. **The result is a tie.**

---

## What actually happened

Only **27 of 57** runs used a blueprint at all.

| | Fully correct |
|---|---|
| Without | 17 of 27 |
| With | 16 of 27 |

Also a tie. But underneath, real things moved in both directions.

### Blueprints fixed 3 runs

| Fault | Blueprint used |
|---|---|
| Noisy neighbour ×2 | cpu-contention-co-tenant |
| Hung dependency ×1 | db-latency-dependency-wait |

Noisy neighbour matters. **Without a blueprint the model got it right 0 times out of 6.**
With one, 2 of 6. This is a fault the model could not do at all on its own.

### Blueprints broke 4 runs

| Fault | Blueprint that fired | |
|---|---|---|
| Memory fault ×2 | cpu-contention-co-tenant | wrong blueprint |
| Hung dependency ×1 | service-cpu-throttle | wrong blueprint |
| Slow database ×1 | service-cpu-throttle | wrong blueprint |

**Every single break is the wrong blueprint being chosen.** Not one is a blueprint giving bad
advice about its own fault.

The memory one is the same mistake our rule engine makes. Memory stress really does eat a CPU
core, so it looks like a noisy neighbour. We already knew this. Now we have seen it twice, in
two different systems, which makes it a property of the data and not a bug in one of them.

---

## The real problem: picking the right blueprint

The model picked a blueprint 27 times. It picked the **right** one 19 times (70%).

| Blueprint | Times picked | Right fault | Fully correct |
|---|---|---|---|
| cpu-contention-co-tenant | 9 | 6 | 3 |
| service-cpu-throttle | 7 | **3** | 3 |
| host-cpu-saturation | 5 | 5 | 5 |
| host-disk-saturation | 3 | 3 | 3 |
| db-latency-dependency-wait | 3 | 2 | 2 |
| **network-path-degradation** | **0** | – | – |

Two things stand out.

**1. The network blueprint was never picked. Not once.** There were 9 network incidents. On
all 9 the model either picked nothing or picked the CPU-cap blueprint. Our own rule engine
scores 9/12 on network faults using that same blueprint. So the knowledge is fine — the model
never reaches for it.

**2. The CPU-cap blueprint fires too easily.** Picked 7 times, right only 3. It fired on
network faults, a slow database, and a hung dependency.

---

## Where the lift landed

| Group | Without | With |
|---|---|---|
| Faults a blueprint covers | 20 of 36 | 20 of 36 |
| Faults no blueprint covers | 12 of 21 | 9 of 21 |

On covered faults: exactly level. On uncovered faults: 3 worse, which is our 4 wrong picks
minus 1 lucky fix, and sits at the noise floor.

Per fault:

| Fault | Covered | Without | With | Change |
|---|---|---|---|---|
| Host out of CPU | yes | 6/6 | 6/6 | – |
| Disk fault | yes | 3/3 | 3/3 | – |
| Noisy neighbour | yes | 0/6 | **2/6** | **+2** |
| Service CPU cap | yes | 4/6 | 4/6 | – |
| Slow database | yes | 4/6 | 3/6 | −1 |
| Service network | yes | 3/6 | 2/6 | −1 |
| Network fault | yes | 0/3 | 0/3 | – |
| Memory fault | no | 6/6 | 4/6 | **−2** |
| Hung dependency | no | 4/6 | 4/6 | – |
| Service memory cap | no | 2/3 | 1/3 | −1 |
| Error storm | no | 0/3 | 0/3 | – |
| Queue backlog | no | 0/3 | 0/3 | – |

**Host CPU and disk were already perfect without any blueprint.** There was no room to
improve. That is a ceiling, and it is our own doing — see the next section.

---

## Why this test was hard to win

**Both arms got the evidence pack.** The pack already contains the kernel measurements the
blueprint tells you to collect.

A blueprint has two halves:

1. **what to collect and how to measure it** — already done for both arms
2. **how to read the numbers** — the only half being tested here

So this measures the second half only. We chose that on purpose: the control had to be the
strong version, the one that already tied the full tool-using agent in earlier work. Beating
a weak control would have proved nothing.

The honest cost of that choice: we gave the control the blueprint's best part for free.

---

## The bigger finding

Our **deterministic rule engine**, reading the same kernel data with no model at all, names
the right fault **38 times out of 41 when it fires** (93%), and correctly stays quiet on 26
of 29 runs it should say nothing about.

The model, handed the same blueprints as text, gets about half.

**The rules work. Handing the same rules to a model as prose does not transfer them.**

That is worth saying plainly, because it changes what a blueprint should ship as. Right now we
generate a markdown file and hope the model follows it. The measurement says: ship the
executable decision instead, and let the model do the parts a rule cannot do.

---

## Honest limits

- **57 incidents, 3 per fault per app.** With a ±2 noise floor, only changes bigger than
  about 4 runs mean anything. Only the memory break (−2) and the noisy-neighbour fix (+2) are
  near that line, and neither clears it alone.
- **One model, one temperature.** No repeats, so we measured the noise floor from the
  no-blueprint subset rather than from repeated runs.
- **Both arms got the evidence pack**, so the collection half of a blueprint was never tested.
- **No cost numbers.** The harness does not record per-run dollars. Tool calls and wall time
  were level (median 6–7 calls, 79 s both arms), so blueprints did not make it slower.

---

## What to do next, in order

1. **Fix selection, not content.** Every break was a wrong pick. The network blueprint was
   never picked despite 9 chances. This is the cheapest large gain available.
2. **Run the other half** — neither arm gets the evidence pack. Then the blueprint has to say
   what to collect, which is the part we did not test and the part it is best at.
3. **Score the rule engine on these same 57 incidents** so the three numbers sit in one table
   on equal terms.
4. **Give the CPU-contention blueprint a way to decline on memory faults.** Same fix helps
   both the rule engine and the model.
