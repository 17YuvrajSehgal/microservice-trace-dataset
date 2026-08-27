# Ciena deck — speaker notes

Five slides. `ciena-slides.html`. Arrow keys or space to advance.

The through-line: **a blueprint is knowledge that accumulates.** Every slide should push that
idea forward. Slide 4 is where people usually expect a defensive answer — give them the
opposite, because the gap we found is the product working, not the product failing.

---

## Slide 1 — A finished investigation, written down so it can be run again

**Say this:**

Today, when one of your engineers solves a hard problem, three things happen: they decide
what data to collect, they decide what analysis to run, and they work out the answer. Then
the ticket closes and all of that disappears. The knowledge stays in their head.

A blueprint captures that whole investigation as one document — what to collect, what to
run, and how to decide. It is a JSON file with fields that force real content: actual event
names, runnable commands, a specification of the output, and rules for when *not* to
conclude something.

The important word is **executable**. This is not documentation someone reads later. A
person or an agent can run it directly, the next time the same problem appears.

**If asked "how is this different from a runbook?"**
A runbook is prose for a human. A blueprint carries the exact event names, the commands, the
stopping conditions, and a record of what does *not* work. It is written to be run without a
human in the loop.

---

## Slide 2 — Two problems that look identical from outside

**Say this:**

To test whether this idea actually works, we deliberately picked two problems that are very
hard to tell apart.

In the first, another workload on the same machine is stealing CPU. Your services are not
busy — they are ready to run and waiting for a turn.

In the second, the database is answering slowly. It is not busy either — it is blocked,
waiting on something else.

On a dashboard these look the same: things are slow, nothing is obviously broken. That is why
they are a fair test. If we can separate these two, the method is worth something.

**Then point at the table:**

Two measurements taken from the kernel trace. Read them across.

- Threads waiting for a CPU: **7.1× worse** in one case, **unchanged** in the other.
- The database sitting blocked: **unchanged** in one case, **36.8× worse** in the other.

Same two measurements. Same components. Opposite answers. That crossing pattern is what makes
the two problems separable — and it is exactly what the blueprint writes down.

---

## Slide 3 — Signals are measured, never guessed

**Say this:**

This is the part I want to be clear about, because it is what makes the blueprints
trustworthy.

We do not write these from intuition, and we do not ask a model to invent them. We start from
labelled failures — faults we injected deliberately, so we know the true answer — plus
published root-cause datasets. Then we run mining scripts that look for signals which are
*specific* to one problem and not to its look-alikes. Only a signal that survives that goes
into a blueprint, and the measurement stays attached to it.

**The honest example — use it, it lands well:**

Our own first draft had three signals that sounded obviously right. We measured them across
93 real failures and all three were wrong. One of them, we had claimed a particular wait
signal would rise during CPU contention — it never exceeded 4% in any failure we have.

We did not delete those. They stay in the blueprint marked "does not work", with the
measurement that killed them, so nobody on your team spends a week rediscovering the same
dead end.

---

## Slide 4 — We moved it to a completely different system

**This is the slide that sells the concept. Do not be defensive here.**

**Say this:**

The obvious question is whether this only works on the system it was built on. So we took the
blueprints, unchanged, to a completely different application — around forty Java services
sharing a single database, instead of fourteen services each with their own.

The CPU-contention blueprint found **4 of the 5** failures, with no changes, in seconds. That
is the transferability claim, tested.

The datastore blueprint dropped from **100% reliable to 44%**. And the reason is the
interesting part.

On the first system, the database polls constantly, so an injected delay shows up
immediately. On the second, the services hold long-lived pooled connections, so the database
sits idle instead — and the exact same signal is silent. Same database software, same fault,
completely different behaviour.

**The line to land:**

One feature cannot catch every database problem. We did not work that out by thinking about
it — we found it by running the blueprint somewhere new. That is what the blueprint is *for*.
And now that gap is a known fact we can encode, rather than a surprise waiting in production.

**If asked "so it failed?"**
It found the limit of one signal on one problem class. That is the system doing its job. The
alternative is not knowing — and being confidently wrong in front of a customer.

---

## Slide 5 — Every investigation makes the next one faster

**Say this:**

Here is the loop, and it is the whole product.

An agent runs the blueprint on a new incident. Where it was unsure or wrong, that gap is
visible. One of your engineers adds what they know — a better way to detect the problem, and
the evidence for it. Next time the same problem appears, it is solved in seconds, and more
precisely than before.

Tomorrow someone on your team finds a better way to detect CPU contention. They put it in the
blueprint. From then on, every agent run uses their method. That expertise is now permanent
and shared instead of sitting with one person.

**On control — say this without being asked:**

You are not handing a model free rein on production. Each blueprint carries a confidence
floor: below it, the agent reports what evidence is missing rather than guessing. And it
carries approval rules — reading data you already have is automatic, but switching on tracing
that costs more than 3% overhead needs your sign-off. You define both.

**Closing line:**

What your best engineers know stops walking out of the building. Every incident you solve
makes the library better, and the library is yours.

---

## Numbers on the slides, and where they come from

| Slide | Number | Source |
|---|---|---|
| 2 | 7.1× / 1.0× threads waiting for CPU | measured, both fault types, raw kernel trace |
| 2 | 1.1× / 36.8× database blocked | measured, same runs |
| 3 | 93 failures, 3 signals killed | our wait-signature measurement across the labelled set |
| 4 | 4 of 5 on the new system | Train Ticket co-tenant runs |
| 4 | 100% → 44% | datastore blueprint reliability, first system vs second |

Full detail: `RESULTS-comparison.md`, `blueprint-report.md`.

## Two things to keep off these slides but know cold

**A simple statistical baseline beat us overall** across both systems (71% vs 58% on
"named the right component and the right cause"). It is strong where metrics move and blind
where they do not — on the first system's datastore fault it scored zero and our approach
scored 5 of 7. The honest framing, if it comes up: *the kernel layer earns its place exactly
where metrics go quiet.* Do not volunteer this in a sales conversation, but do not deny it if
asked directly.

**The runtime is not built.** Blueprints are authored, measured and executable today;
selecting them automatically is manual for now. Say "the knowledge objects are proven, the
automatic selection layer is next" if pressed.
