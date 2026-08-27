# Ciena Presentation – notes

Your notes, organised against the six slides in `ciena-slides.html`.
Wording is yours. Anything I added is marked *[added]* so you can strip it.

---

## Slide 1 — A finished investigation, written down so it can be run again

**What is blueprint:**

It is an investigation document that decides what data to collect, what to run, and what the
answer is – all of this information is stored in this document, so that when the problem
arises – we or an agent can look into it to find the necessary information – and execute the
things according to the planned document.

---

## Slide 2 — One file. Six questions answered.

Each blueprint is a Json file → with fields that force real content → for ex. Event names that we need to collect, how to interpret them
runnable steps, an output spec, and other rules etc.

Each blueprint has keys such as evidence sufficient --confidence floor -> that means if the
confidence is below the given number, then more effort is required.

Approval request – where you can define what is allowed automatically and what is not. For
example, if agents wants to query already existing evidence – it can do so automatically but
if it requires to do an active collection that has an overhead of above 3% then it will
require your approval.

And similarly we have other such properties that can be defined by you in the blueprint. and
utilized by agents.

*[added] Both of those keys are visible on this slide — `confidence_floor: 0.7` and
`requires_approval: tracing above 3% overhead` — so you can point at them on screen.*

---

## Slide 3 — Two problems that look identical from outside

Now in order to test if our blueprints are working or not, we chose 2 problems deliberately
as opposite

1. CPU contention
2. Slow datastore

These 2 look very similar from outside: things are slow, nothing is obviously broken

| | CPU Contention | Datastore |
|---|---|---|
| Runqueue delay | 7.12 x | 0.97 x |
| Database poll wait | 1.12 x | 36.83 x |

So these same measurements, same components had totals different answers – that makes them
separable.

*[added] On the slide these are worded as "how long threads waited for a CPU" and "how long
the database sat blocked", so a non-kernel person can follow.*

---

## Slide 4 — Signals are measured, never guessed

We are not creating these skills blindly or using AI -> we are finding the key properties
that are unique to these given issues.

We have collected a dataset with anomalies injection, plus we are using some good published
dataset for RCA that contains anomalies.

Once we have these data, we also create scripts, that help us to mine signals that are
anomaly specific for example for these 2 bugs: CPU contention & Datastore

Every time we tested harder, we found something wrong.

*[added] The slide carries one concrete example of that: our own first draft had three
signals that sounded obviously right, and measuring 93 real failures killed all three. They
stay in the blueprint marked "does not work" so nobody retries them.*

---

## Slide 5 — We moved it to a completely different system

But in order to test it's robustness – we tested our blueprint on LOFO – a train ticket
dataset – and found that CPU blueprint was able to detect 4/5 bugs with the same blueprint
within seconds – that means these blueprints are transferable.

but on the other hand datastore blueprints failed and went from 100% precision to 44% →
which was because in 1st dataset the database polls constantly → so contention were visible
immediately but on the other application – it was not because of long-lived pooled
connections.

These blueprints will keep evolving overtime. When we switched our dataset from One
microservice to another these above 2 properties that we thought are going to detect it –
but unfortunately it failed – which was expected as we cannot rely on just 1 feature to be
able to find all the database related issues – so

And then again doing the research → we found new facts from the second dataset – which will
improvise the system further.

*[added] The comparison table is now on this slide. What it shows, in your terms:*

| Found the right component and the right cause | Shop app | Booking app |
|---|---|---|
| Blueprint | 83% | 33% |
| AI agent reading everything | 58% | 0% |
| Classic metrics analysis | 42% | 100% |

*[added] Three things to say off this table:*

*1. The two strong methods are opposites. On the shop app's database fault, metrics found
none of them and the kernel found most. On the booking app it reverses. So the kernel earns
its place exactly where metrics go quiet — and the other way round.*

*2. The AI agent is beaten by both. Across all 10 CPU-contention failures on both systems it
named the cause correctly zero times. The blueprint got 9.*

*3. Knowing which method fits which problem is the valuable part — and that is what a
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

## *[added]* Two things to have ready, but not on the slides

**"LOFO" wording.** In the notes above you call the train-ticket test LOFO. In our work LOFO
(leave-one-family-out) is a different experiment — hiding the matching blueprint to see if
the system abstains. The train-ticket test is a *transfer* test: same blueprint, new system.
Worth saying "we tested it on a second, different application" so a technical person doesn't
ask what LOFO means and get a mismatched answer.

**A simple statistical baseline beat us overall** across both systems (71% vs 58% on naming
both the right component and the right cause). It is strong where metrics move and blind
where they don't — on the first system's datastore fault it scored 0/7 and ours scored 5/7.
If asked directly: *the kernel layer earns its place exactly where metrics go quiet.* Don't
volunteer it, don't deny it.

**The runtime is not built.** Blueprints are authored, measured and executable today;
choosing them automatically is manual for now.
