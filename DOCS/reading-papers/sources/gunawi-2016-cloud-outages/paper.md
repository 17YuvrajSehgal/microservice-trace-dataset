# Paper Context: Why Does the Cloud Stop Computing? Lessons from Hundreds of Service Outages (SoCC 2016)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited by blueprint 2 for the share of outages caused by network problems. **The number in
> our reference pack needs correcting** — see §7. The paper's most quotable finding is not
> about networks at all: **355 of 597 outages have an UNKNOWN root cause.**

---

## 1. Bibliographic info

- **Title:** Why Does the Cloud Stop Computing? Lessons from Hundreds of Service Outages
- **Authors:** Haryadi S. Gunawi, Mingzhe Hao, Riza O. Suminto, Agung Laksono,
  Anang D. Satria, Jeffry Adityatama, Kurnia J. Eliazar (University of Chicago and
  Surya University)
- **Venue:** SoCC 2016
- **DOI:** 10.1145/2987550.2987583
- **Study name:** Cloud Outage Study (COS)

```bibtex
@inproceedings{gunawi2016why,
  title     = {Why Does the Cloud Stop Computing? Lessons from Hundreds of Service Outages},
  author    = {Gunawi, Haryadi S. and Hao, Mingzhe and Suminto, Riza O. and Laksono, Agung and Satria, Anang D. and Adityatama, Jeffry and Eliazar, Kurnia J.},
  booktitle = {SoCC 2016}, year = {2016},
  doi       = {10.1145/2987550.2987583}
}
```

---

## 2. One-paragraph summary

The authors read **1,247 headline news articles and public post-mortem reports** covering
**597 unplanned outages** at **32 popular Internet services** over **seven years, 2009-2015**,
and tagged each one by duration, root cause, impact and fix. The question driving it: **why do
outages still happen when everything is redundant?** Their answer is that the no-single-point-
of-failure mantra is not about hardware redundancy — it requires **the entire recovery chain to
be perfect**, and they find many outages caused by an imperfection in one link of that chain.

---

## 3. Method

- **32 popular Internet services.**
- Found reports with search-engine queries of the form *"serviceName outage month year"*, for
  every month and year in range.
- **1,247 unique links describing 597 outages**, 2009-2015.
- Each outage was read across **1 to 12 sources, 2 on average**, because information is
  scattered — some articles report duration, others only the root cause.
- **There is no standardisation of outage reports**, so all metadata was extracted **manually**.
- **3,249 outage metadata tags** in total.
- **69% of outages have a reported duration.**

Root-cause vocabulary: `UPGRADE, NETWORK, BUGS, CONFIG, LOAD, CROSS, POWER, SECURITY, HUMAN,
STORAGE, SERVER, NATDIS, HARDWARE, UNKNOWN`. Impact vocabulary includes `PERFORMANCE, LOSS,
STALE, SECURITY`.

---

## 4. The root-cause table (their Table 3)

`#Sv` = number of services affected. `%` is of outages **with a known root cause**.

| Root cause | Services | Count | % |
|---|---|---|---|
| **UNKNOWN** | 29 | **355** | — |
| **UPGRADE** | 18 | 54 | **16%** |
| **NETWORK** | 21 | 52 | **15%** |
| **BUGS** | 18 | 51 | **15%** |
| CONFIG | 19 | 34 | 10% |
| LOAD | 18 | 31 | 9% |
| CROSS | 14 | 28 | 8% |
| POWER | 11 | 21 | 6% |
| SECURITY | 9 | 17 | 5% |
| HUMAN | 11 | 14 | 4% |
| STORAGE | 4 | 13 | 4% |
| SERVER | 6 | 11 | 3% |
| NATDIS | 5 | 9 | 3% |
| HARDWARE | 4 | 5 | 1% |

### The three things this table actually says

1. **355 of 597 outages — 59% — have an UNKNOWN root cause**, across 29 of the 32 services.
   The public record simply does not say what went wrong.
2. **UPGRADE is the single largest known cause** at 16%, and the authors call it out as needing
   "more research attention".
3. **Component failures still cause outages despite redundancy.** Network, storage, server,
   hardware and power are all things that "should be anticipated with extra redundancies", and
   they still bring services down — because redundancy is not enough without a perfect recovery
   chain.

---

## 5. The recovery-chain argument

Their central explanation for why redundancy fails: the no-SPOF mantra *"is not merely about
hardware redundancies but requires the perfection of the complete recovery chain."* They observe
**numerous outages caused by an imperfection in one link** of that chain.

They also give a metastable-shaped example in passing: a service that **returned to life and
immediately went down again**, from over-capacity as millions of users reconnected. That is the
same pattern Bronson 2021 formalises.

---

## 6. What kind of paper this is

- A **public-record study**. Everything comes from news articles and post-mortems, manually
  tagged.
- **No telemetry, no traces, no measurements** of any system.
- The dataset is published as a research resource (the COS dataset).
- Its own limitation, which the authors discuss: it only sees outages **reported publicly**,
  and most reports do not state a cause.

---

## 7. What this means for our work — including a number to correct

**Our reference pack currently says:**

> NETWORK problems caused 52 outages across 21 services; the paper states "NETWORK problems are
> responsible for 15% of service outages" (among outages with a known root cause).

**The 52 outages and 21 services are exactly right.** The parenthetical is doing important work
and should be kept prominent: **15% is of the 242 outages with a known cause, not of all 597.**
As a share of all outages studied, network is **52/597 ≈ 8.7%**. Both framings are defensible;
quoting 15% without the qualifier is not.

**The more useful finding for us is the one we are not citing.** **59% of outages have no
publicly reported root cause.** That is a statement about how hard diagnosis is in practice,
from 597 real incidents — and it is a better motivation for automated RCA than the network
percentage. It belongs in the introduction alongside Dai's "60% produce no error message".

**Two numbers that now agree with each other,** from independent studies of different things:

| Source | Finding |
|---|---|
| **Dai 2018**, 156 timeout bugs | **60%** produce no error message, 12% misleading |
| **Gunawi 2016**, 597 outages | **59%** have no publicly reported root cause |

Different populations, different methods, nearly the same number. Together they say: **the
information needed to diagnose these failures is usually not in the record.** That is the
strongest joint argument in the whole pack for a diagnosis method that works from raw system
behaviour.

**A caution about what this paper can support.** It has no telemetry, so it cannot say anything
about *signatures*. Cite it for **prevalence and for the difficulty of attribution**, never for
what a network fault looks like.

**One connection worth drawing.** `UPGRADE` being the largest known cause, and their remark that
it needs more research, is relevant to a fault family we have but no blueprint for — none of our
24 families model a deployment or upgrade. If we ever extend the dataset, this is the
best-evidenced gap in it.

---

## 8. Safe claims

- 597 unplanned outages at 32 popular Internet services, 2009-2015, from 1,247 news and
  post-mortem reports, manually tagged into 3,249 metadata tags.
- **355 of 597 outages (59%) have an UNKNOWN root cause**, spanning 29 of the 32 services.
- Among outages with a known cause: **UPGRADE 16%, NETWORK 15%, BUGS 15%**, then CONFIG 10% and
  LOAD 9%.
- **NETWORK problems caused 52 outages across 21 services.**
- 69% of outages have a reported duration.
- There is **no standardisation of outage reports**; metadata had to be extracted by hand from
  1-12 sources per outage.
- Redundancy does not prevent outages: the no-SPOF property requires **the whole recovery chain
  to be perfect**, and many outages come from one imperfect link.
- Component failures that should be covered by redundancy — network, storage, server, hardware,
  power — still cause outages.

## 9. Do NOT claim

- That 15% of **all** outages are network-caused. It is 15% of those with a **known** cause;
  of all 597 it is about 8.7%.
- Anything about failure signatures or telemetry. The paper has none.
- That the root-cause distribution reflects reality rather than the public record. 59% unknown
  means the sample is heavily censored, and the authors say so.
- That these are microservice outages. They are whole-service outages at Internet companies.

## 10. Reusable ideas

- **Report the unknowns as a first-class result.** 59% UNKNOWN is the finding, not a gap in the
  data — it says the information is not being captured.
- **State the denominator.** Their table makes "percent of known causes" explicit, which is
  exactly the distinction our own citation was blurring.
- **Read several sources per incident.** Two on average, up to twelve, because no single report
  is complete. The analogue for us is that no single signal describes a fault.
- **Redundancy is not availability.** The recovery chain has to work, and that is where the
  failures are.
