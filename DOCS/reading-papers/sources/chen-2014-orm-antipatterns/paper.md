# Paper Context: Detecting Performance Anti-patterns for Applications Developed using Object-Relational Mapping (ICSE 2014)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> The source for the **`code_n_plus_one`** fault family, which has no blueprint yet. Its
> **one-by-one processing** anti-pattern is our fault, named and measured. Its most important
> warning for us is in §8: **most instances of this anti-pattern do not measurably hurt.**

---

## 1. Bibliographic info

- **Title:** Detecting Performance Anti-patterns for Applications Developed using
  Object-Relational Mapping
- **Authors:** Tse-Hsun Chen, Weiyi Shang, Ahmed E. Hassan (Queen's University); Zhen Ming Jiang
  (York University); Mohamed Nasser, Parminder Flora (BlackBerry)
- **Venue:** ICSE 2014, 31 May - 7 June, Hyderabad
- **ISBN:** 978-1-4503-2756-5

```bibtex
@inproceedings{chen2014detecting,
  title     = {Detecting performance anti-patterns for applications developed using object-relational mapping},
  author    = {Chen, Tse-Hsun and Shang, Weiyi and Jiang, Zhen Ming and Hassan, Ahmed E. and Nasser, Mohamed and Flora, Parminder},
  booktitle = {ICSE 2014}, year = {2014}
}
```

---

## 2. One-paragraph summary

ORM hides the SQL, so developers *"may not be aware which source code snippets would result in a
database access nor whether such access is inefficient."* The authors build a **static analysis
framework** that finds two ORM anti-patterns in source code, and — the part that makes the paper
useful — **prioritises them by measured performance gain**, because a real system throws up
**hundreds or thousands** of instances and most of them do not matter. Evaluated on **Pet Clinic,
Broadleaf, and a large commercial system ("EA")**. Fixing the anti-patterns improved response
time **by up to 98%, on average 35%** — but only in **5 of 11** and **5 of 10** test suites; in
the rest the effect was trivial or zero.

---

## 3. The two anti-patterns

### Excessive data

An ORM relationship set to **EAGER** fetch pulls associated objects that the code never touches.
Their example: displaying company names also retrieves every department, because `department` is
EAGER. **Fix: change EAGER to LAZY.**

Micro-benchmark, 300 companies × 10 departments each: **1.68 s → 0.48 s, a 71% improvement.**

### One-by-one processing — this is `code_n_plus_one`

Iterate over a list of parents and fetch each one's children separately: **one `select` statement
per parent object**. They describe it as a **special case of the Empty Semi Trucks anti-pattern**
— *"a large number of requests is needed to perform a task."*

**Fix: batch it**, e.g. `@BatchSize(size=50)`, so the ORM fetches 50 children per round trip
instead of one. They warn the fix *"may vary in different situations (e.g. doing database updates
in loops) and can be sometimes difficult."*

Same micro-benchmark: **1.68 s → 1.39 s, a 17% improvement.**

**Note the asymmetry in their own micro-benchmark: excessive data gave 71%, one-by-one only 17%.**

---

## 4. The framework

Three phases:

1. **Data extraction** — per file, extract local call graphs, database-accessing functions, and
   ORM configurations; combine them into **code paths that touch the database**.
2. **Anti-pattern detection** — static analysis over those paths.
3. **Performance assessment** — run the test suites repeatedly with **enlarged data sets** and
   compute **statistical significance (p-value) and effect size (Cohen's d)** for the fix.

**Phase 3 is the novel part.** They state it plainly: prioritising anti-patterns by expected
performance gain *"is novel relative to prior anti-pattern detection efforts"*. And it exists
because phases 1-2 produce far more findings than anyone can act on.

They also motivate using **test suites rather than running each anti-pattern in isolation**:
*"rarely or never executed anti-patterns would have less performance impact compared to
frequently-executed ones."*

---

## 5. The systems and what was found

All three use **JPA** and follow MVC.

| System | KLOC | Files | One-by-one instances | Excessive data instances |
|---|---|---|---|---|
| **Pet Clinic** (Spring sample app) | 3.3K | 51 | **0** | **10** |
| **Broadleaf 3.0** (open-source e-commerce) | 206K | 1,795 | **228** (text elsewhere says 308) | **483** |
| **EA** (commercial, millions of daily users) | >300K | >3,000 | >10 | >10 |

*(The paper is internally inconsistent here: Table 1 lists 228 one-by-one instances for Broadleaf
while the Results text says "a total of 308 instances". Quote Table 1's figure or cite the range.)*

One of Pet Clinic's 10 excessive-data instances **was already known** — discussed online by
developers and shown to cause serious degradation. Their framework finds it statically, early.

Broadleaf had so many findings they **only emailed the top 10** to the developers.

---

## 6. Results — and the honest half

### Excessive data (Table 2a)

| System / suite | Before | After | Change | Effect size |
|---|---|---|---|---|
| **Pet Clinic, Browsing** | 130.09 s | 2.04 s | **-98%** | **42.41 (large)** |
| Broadleaf, Checkout | 30.75 s | 25.75 s | -16% | 6.45 (large) |
| Broadleaf, Order | 30.60 s | 25.62 s | -16% | 5.39 (large) |
| Broadleaf, Shopping Cart | 22.90 s | 20.14 s | -12% | 0.78 (medium) |
| Broadleaf, Customer Phone | 2.17 s | 2.17 s | **0%** | 0.00 (trivial) |
| Broadleaf, Payment Info | 2.18 s | 2.20 s | **+1%** | 0.02 (trivial) |
| **EA**, multiple features | — | — | -5% | 0.68 (medium) |

**Statistically significant in 5 of 11 test suites.** The Pet Clinic 98% is the headline number
and it comes from **one test suite of one 3.3 KLOC sample application**.

### One-by-one processing (Table 2b)

| System / suite | Before | After | Change | Effect size |
|---|---|---|---|---|
| Broadleaf, Shopping Cart | 21.46 s | 14.58 s | **-32%** | 2.07 (large) |
| Broadleaf, Customer Addr. | 1.49 s | 1.08 s | -27% | 0.59 (medium) |
| Broadleaf, Order | 13.12 s | 10.20 s | -22% | 4.54 (large) |
| Broadleaf, Checkout | 13.25 s | 10.63 s | -20% | 1.86 (large) |
| Broadleaf, Customer Phone | 1.00 s | 1.09 s | **+0.09%** | 0.10 (trivial) |
| Broadleaf, Payment Info | 1.08 s | 1.16 s | **+8%** | 0.08 (trivial) |
| **EA**, multiple features | — | — | **-69%** | **55.3 (large)** |

**Statistically significant in 5 of 10 test suites.** Pet Clinic is absent because it has **zero**
one-by-one instances.

### The finding that matters most

> *"These test suites have one common behaviour: very short response time. The results indicate
> that when the response time of a program is small, adding batches will not give much
> improvement. This also shows that **not all anti-patterns are worth fixing**."*

And on why the same anti-pattern varies so much: **the database schema decides.** In Pet Clinic
the excessive data is a **one-to-many** relationship (every pet's every visit), so eager fetching
explodes. In Broadleaf most instances are **one-to-one or many-to-one**, so it barely costs
anything.

---

## 7. What kind of paper this is

- A **static analysis tool** plus a **statistically rigorous performance assessment**.
- Java / JPA only. Two open-source systems plus one commercial system under NDA.
- The signal is **source code and test-suite response time**, not telemetry.
- The unit is a **test suite**, not a request or a container.

---

## 8. What this means for our work

**This is the naming source for `code_n_plus_one`.** "One-by-one processing", a special case of
Empty Semi Trucks, is precisely our fault: one extra query per returned row. It has a published
frequency (**228 instances in a 206 KLOC open-source e-commerce system**), a published fix
(`@BatchSize`), and measured effects (**20-32% on Broadleaf, 69% on the commercial system**).

**The strongest warning in the paper is for our fault injection, not our diagnosis.**

> when the response time of a program is small, adding batches will not give much improvement

Our injected `code_n_plus_one` has to be **calibrated hard enough to be detectable at all**. Chen
et al. show the same anti-pattern producing **+8%** (i.e. worse after the fix, inside noise) in
one suite and **-69%** in another, and the difference is **schema cardinality and baseline
response time**. Sock Shop's catalogue responses are short. **If our injection is mild, the fault
may be genuinely invisible — and that would be a property of the fault, not a failure of the
kernel modality.** This is exactly the `noisy_neighbor` "KPIs barely move" calibration problem
again, and we should check it before drawing conclusions from those runs.

**A kernel trace should see this better than a stopwatch does.** Their whole measurement is
**response time**, which is why the small suites show nothing. We count **round trips**. N
separate `sendto`/`recvfrom` pairs to the DB socket is a **count**, not a duration, and a count
is visible even when the total time is inside noise. **That is a real advantage of our modality
and it is worth stating and testing**: we should be able to detect one-by-one processing in cases
where Chen et al.'s own assessment calls the impact trivial.

**And it gives us the discriminator against excessive data.** Their two anti-patterns are
opposites on the wire, and this matches what Yang 2018 says about lazy versus eager loading:

| Anti-pattern | Round trips | Bytes per round trip |
|---|---|---|
| **One-by-one processing** (`code_n_plus_one`) | **many** | small |
| **Excessive data** (eager over-fetch) | **few** | **large** |

Both make a request slow. They look nothing alike in a kernel trace. Neither goes in a blueprint
until measured on our runs.

**Scope caution.** Java/JPA, and our only ORM application is Train Ticket. Sock Shop's catalogue
is Go with hand-written SQL, so `code_n_plus_one` there is a hand-written loop, not an ORM
configuration. The *shape* transfers; the *cause* does not.

**One method idea worth copying wholesale.** Their phase 3 — don't just detect, **rank by measured
effect with a p-value and an effect size** — is the correct answer to "the tool found 483 things".
Our blueprint results tables report detection; they do not rank by how much the fault actually
mattered. Cohen's d against a baseline window would be a cheap addition.

---

## 9. Safe claims

- ORM hides database access, so developers **may not know which code causes a query or whether it
  is efficient**.
- Two anti-patterns: **excessive data** (EAGER fetch of unused associations) and **one-by-one
  processing** (one query per parent object, a special case of **Empty Semi Trucks**).
- Micro-benchmark (300 companies × 10 departments): excessive data **1.68 s → 0.48 s (-71%)**;
  one-by-one processing **1.68 s → 1.39 s (-17%)**.
- The fix for one-by-one processing is **batching**, e.g. `@BatchSize(size=50)`; the authors note
  the fix can be difficult, especially for updates inside loops.
- Detection is **static analysis over database-accessing code paths**; a third phase ranks
  findings by **measured response-time gain with p-value and Cohen's d**, which the authors call
  novel.
- Systems: **Pet Clinic (3.3 KLOC), Broadleaf 3.0 (206 KLOC), and a commercial system with
  millions of daily users**, all JPA + MVC.
- Instances found: Pet Clinic **0 one-by-one, 10 excessive data**; Broadleaf **228 one-by-one
  (Table 1) and 483 excessive data**.
- Fixing anti-patterns improved response time **by up to 98%, on average 35%** — but was
  statistically significant in only **5 of 11** (excessive data) and **5 of 10** (one-by-one) test
  suites.
- Largest effects: Pet Clinic browsing **130.09 s → 2.04 s (-98%, d = 42.41)**; the commercial
  system's one-by-one fix **-69% (d = 55.3)**; Broadleaf shopping cart **-32%**.
- **Not all anti-patterns are worth fixing.** Suites with short response times showed trivial or
  negative change; **the database schema decides** — one-to-many relationships hurt far more than
  one-to-one or many-to-one.

## 10. Do NOT claim

- That the 98% is typical. It is **one test suite of a 3.3 KLOC sample application**, and it is
  the **excessive data** anti-pattern, not one-by-one processing.
- That every detected instance is a bug. Half the test suites showed **no significant change**,
  and the authors say so explicitly.
- That the tool uses runtime tracing. Detection is **static**; only the ranking phase runs the
  system.
- That the findings transfer beyond Java/JPA. All three systems use JPA.
- That Broadleaf had 308 one-by-one instances without noting that **Table 1 says 228** — the
  paper contradicts itself.

## 11. Reusable ideas

- **Detect, then rank by measured effect.** Hundreds of true positives with no ordering is not a
  usable result. p-value plus effect size turns a list into a work queue.
- **Assess through test suites, not in isolation.** A defect on a cold path costs nothing; the
  measurement should reflect how often the code actually runs.
- **The same anti-pattern has wildly different costs.** Schema cardinality and baseline latency
  decide. Any claim of the form "pattern X costs Y%" needs those two conditions attached.
- **Count, don't time.** Their whole difficulty — small effects hiding in short response times —
  is an argument for counting round trips instead of measuring duration.
- **Report the trivial cases.** Publishing the +1% and +8% rows is what makes the 98% credible.
