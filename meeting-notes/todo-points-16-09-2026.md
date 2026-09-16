# Todo: evaluation, after the 16 September meeting

From `transcript-16-09-2026.txt`. Naser, Mahsa, Sneh, Yuvraj.

---

## The one thing that changed

**Blueprint selection is parked.** I was building selection first. Naser says do not.

> "That's not a problem for today... We can assume that they're giving the blueprint along
> with the problem."

> "we are not automating everything 100%, just helping the analyzer to use that. So, this is
> a blueprint, this is the trace, then go ahead and do that."

So for now the agent is **told** the problem and **given** the blueprint. Someone sees the
system is slow, picks the blueprint, and hands both to the agent.

Selection becomes question 3. It is still real, just later.

---

## The three questions, in Naser's order

| # | question | status |
|---|---|---|
| 1 | How do we design a good blueprint? | open, and it is a research question on its own |
| 2 | Given the problem and the blueprint, does it help? | **this is the priority** |
| 3 | Given only a trace, find the right blueprint | later |

> "the second question is pretty much evaluating the first question."

---

## Question 2: the work to do now

This is what gets measured next.

- [ ] **Set the test up the agreed way.** Agent is told the problem. Agent is given the one
      blueprint. Agent is given the trace. Nothing else.
- [ ] **Run with and without the blueprint.** Naser asked this directly. He wants to know if
      the result comes from the agent or from the blueprint we designed.
- [ ] **Run every case 5 times.** Not once.
      > "each of them like five times, five different analysis, because agent, we don't know,
      > right? We need to run it several times."
- [ ] **Report one number per problem.** Without blueprint X%, with blueprint Y%. Naser's own
      example was 50% to 80%.
- [ ] **Say how we know the answer is right.** Naser asked this twice. Our answer: we injected
      the fault, so we know it. Write that down in the paper, do not leave it implied.
- [ ] **Test both ways of asking.** One with a hint, one without.
      > "We can test both of them. In the second question, we will tell it, hey, this is the problem."
- [ ] **Pick about 10 problems of a similar kind.** Naser suggested 10 latency-related ones.
      A blueprint each.
- [ ] **Use several runs of the same problem.** Not just one trace per problem.
      > "we'll create similar cases of that problem and see if the blueprint really helps."

## Question 1: improve the blueprints themselves

Naser was clear that this is where the effort goes.

> "The focus will be on the blueprint itself... more richer blueprint. Every problem you will
> need to understand and analyse and improve the blueprint for that problem."

- [ ] **Go problem by problem.** For each one, look at what data it needs and what worked.
      Improve that blueprint. Then test again.
- [ ] **Write down what makes a blueprint good.** This is the research question. What parts
      matter? Does it need a control flow? Does it need memory?
      > "creating the blueprint, there will be the design of it, that will be one question."
- [ ] **Keep it iterative.** Naser said start simple, improve, then work out afterwards what
      the important parts were.
- [ ] **Record what changed between versions**, so the improvement can be shown, not claimed.

## Question 3: finding the right blueprint (later)

Write it down now so it is not lost. Do not build it yet.

Naser's picture is a doctor.

> "this person is sick. What is the problem? We don't know. He has headache, he has this and
> that. And then doctor needs to narrow them, ask some questions... there's a systematic way."

- [ ] Narrow down step by step. Check one thing, then the next.
- [ ] End with a **small set** of blueprints, not one.
      > "I think that the problem is about latency and that kind of latency. Now we have 3
      > blueprints about..."
- [ ] Read the data directly. Do not ask the human questions if the trace has the answer.
- [ ] Allow a hint from the user. "The system is slow." Then translate that into something the
      system understands. Naser calls this intention analysis.
- [ ] Mahsa's note: pick candidate blueprints for different cases, then run the whole evaluation.

---

## What to report

Naser named the shape of the result himself.

> "we created a database of 50 problems, 100 problems, we categorise in different groups, and
> for each of them we have a blueprint, and the blueprint works very well, and this is the
> performance, compared to no blueprint."

So the table is: problem, without blueprint, with blueprint, over 5 runs each.

Also worth keeping:

- [ ] The blueprint is for **analysis**, not only detection. It should narrow the reasons down.
      > "there is a latency problem, and most likely the problem is because of network packets
      > or the dependency between this and that. Instead of many different reasons, you narrow
      > down, then the human analyst will go and check."
- [ ] So score whether the agent narrowed it down usefully, not only whether it was right.

---

## Things I found this week that affect this

**1. Selection was never really tested.** Each blueprint invented its own symptom words. 22 of
24 words were used by only one blueprint. A word matcher would score near-perfect because each
word names its own answer. Measured with `blueprints/lib/check_symptoms.py`.

This matters for question 3, not question 2. It is parked with the rest of question 3. The
finding stands and the checker is in the repo.

**2. My visualisation is not clear yet.** Naser said so.
> "Well, I don't understand this view for now."

- [ ] Fix the blueprint card so the picture reads on its own. He did not follow it.

**3. Numbers I quoted in the meeting were from memory.** I said under 50% without a blueprint
and 70 to 80% with one.

- [ ] Get the real numbers from the result files before quoting them again. Our written record
      (`RESULTS-withwithout.md`) says 56% without and 51% with, which is a tie, not a gain. The
      two do not agree. **This needs checking before the next meeting.**

---

## Order of work

1. Get the true with/without numbers from the existing result files. Settle point 3 above.
2. Set up question 2 properly. Problem given, blueprint given, 5 repeats.
3. Pick the 10 problems.
4. Run it. Report one table.
5. Improve the blueprints that do badly. Run again.
6. Leave question 3 alone until 1 to 5 are done.
