Just to give you a quick idea about the blueprint which was discussed by prof naser in person at Ciena.

## Slide 1 — A finished investigation, written down so it can be run again


**What is blueprint:**

It is an investigation document that decides what data to collect, what to run, and what the
answer is – all of this information is stored in this document, for example if Jason has a very good RCA technique that has 
90% chance that it will resolve the given x problem.
so that when the problem
arises – we or an agent can look into it to find the necessary information – and execute the
things according to the planned document. this document will contain each and every thing some would require to solve the 
given problem x.

---

## Slide 2 — One file. Six questions answered.

Each blueprint is a Json file → with fields that force real content → for ex. what observability data is required, 
names of kernel event that it needs for RCA, how to interpret them, an output spec, and other rules.

Each blueprint has key structure that the user of blueprint must follow such as:

Approval request – where you can define what is allowed automatically and what is not. For
example, if agents want to query already existing evidence – it can do so automatically, but
if it requires doing an active collection that has an overhead of above 3% then it will
require your approval.

And similarly we have other such properties that can be defined by you in the blueprint. and
utilized by agents.

I can also show you a working blue print at the end of the presentation.

---

## Slide 3 — Two problems that look identical from outside

Now in order to test if our blueprints are working or not, we chose 2 problems deliberately
as opposite

1. CPU contention
2. Slow datastore

These 2 look very similar from outside: things are slow, nothing is obviously broken

|                    | CPU Contention | Datastore |
|--------------------|----------------|-----------|
| Runqueue delay     | 7.12 x         | 0.97 x    |
| Database poll wait | 1.12 x         | 36.83 x   |

So these same measurements, same components had totals different answers – that makes them
separable.

---

## Slide 4 — Signals are measured, never guessed

We are not creating these skills blindly or using AI -> we are finding the key properties
that are unique to these given issues.

We have collected a dataset with anomalies injection, plus we are using some good published
dataset for RCA that contains anomalies.

Once we have these data, we also create scripts, that help us to mine signals that are
anomaly specific for example for these 2 bugs: CPU contention & Datastore we saw in last slide

Every time we tested harder, we found something wrong was missing - so we keep improving the
blueprints unitl it start performing well on different datasets.

Moreover, we also keep a track of the things that do not work on the given problem, so that the user or the agent can
avoid wasting time on them.

---

## Slide 5 — We moved it to a completely different system

But in order to test it's robustness – we tested our blueprint on LOFO – a train ticket
dataset – and found that CPU blueprint was able to detect 4/5 bugs with the same blueprint
within seconds – that means these blueprints are transferable.

but on the other hand datastore blueprints failed and went from 100% precision to 44% →
which was because in 1st dataset the database polls constantly → so contention were visible
immediately but on the other application the architecture was completely different.

And then again doing the research → we found new facts from the second dataset – which we improvised the blueprints
and then the results were equally good on both systems.

So this tells us that these blueprints will keep evolving overtime.


| Found the right component and the right cause | Shop app | Booking app |
|-----------------------------------------------|----------|-------------|
| Blueprint                                     | 83%      | 88%         |
| AI agent reading everything                   | 58%      | 0%          |
| Classic metrics analysis                      | 42%      | 100%        |

*1. The AI agent is beaten by both. Across all 10 CPU-contention failures on both systems it
named the cause correctly zero times. The blueprint got 9.*

*2. Knowing which method fits which problem is the valuable part — and that is what a
blueprint stores. This is the answer if someone says "so metrics won on the second app".*

---

## Slide 6 — Every investigation makes the next one faster

Now let says tomorrow someone in your company found even better way to find CPU contention –
all they have to do is update this blueprint with there strategy – (and/or evidence) and they
have given the agent that will utilize these blueprint – their idea which it can execute the
next time if a similar problem occurs – and this time it will be even better, and more
precise.

Similar one thing happened for the cpu starvation – the blueprint will evolve eventually as
we are consistently utilizing it – and once it has seen the given scenarios and debugged it –
next time it will only take few seconds to run the same RCA and fix the issues.

---
