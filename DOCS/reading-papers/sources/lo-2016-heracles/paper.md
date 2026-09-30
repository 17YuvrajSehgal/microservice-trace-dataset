# Paper Context: Heracles — Improving Resource Efficiency at Scale (ACM TOCS 2016, orig. ISCA 2015)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited by blueprint 7 for *"even small amounts of interference can cause significant SLO
> violations."* That claim is sound and well supported. But the paper is a **controller**, not
> a diagnosis method, and §8 explains why most of it does not transfer to us.

---

## 1. Bibliographic info

- **Title:** Improving Resource Efficiency at Scale with Heracles
- **Authors:** David Lo, Liqun Cheng, Rama Govindaraju, Parthasarathy Ranganathan,
  Christos Kozyrakis (Google and Stanford)
- **Venue:** ACM Transactions on Computer Systems 34(2), Article 6, May 2016.
  Originally ISCA 2015.
- **DOI:** 10.1145/2882783 (TOCS); 10.1145/2749469.2749475 (ISCA)
- **PDF:** http://csl.stanford.edu/~christos/publications/2016.heracles.tocs.pdf

```bibtex
@article{lo2016heracles,
  title   = {Improving Resource Efficiency at Scale with Heracles},
  author  = {Lo, David and Cheng, Liqun and Govindaraju, Rama and Ranganathan, Parthasarathy and Kozyrakis, Christos},
  journal = {ACM Transactions on Computer Systems}, volume = {34}, number = {2}, year = {2016},
  doi     = {10.1145/2882783}
}
```

---

## 2. One-paragraph summary

Datacenter servers run at **10-50% utilization**, and servers are **50-70% of total cost of
ownership**. The obvious fix is to pack **best-effort batch** work onto the same machines as
**latency-critical** services — but interference in shared caches, memory, I/O and network
breaks the latency SLOs, so most systems either avoid colocation or kill it when it hurts.
Heracles instead **coordinates four isolation mechanisms in real time** — cache partitioning,
power/frequency control, core scheduling, and network traffic control — to push utilisation up
without breaking the SLO. It reaches **90% effective machine utilisation with no latency
violations**, improving throughput per TCO by **15% to 300%**.

---

## 3. The economics, which is the real motivation

- Servers are **50-70% of TCO** in a modern energy-efficient datacenter.
- Average server utilisation is **10-50%** across many published studies.
- **Google websearch servers average 30% idleness over 24 hours.** For a hypothetical 10,000
  server cluster, that is **3,000 servers of wasted capacity**.
- Why it stays low: latency-critical services scale across thousands of servers and hold
  distributed state in memory or Flash. Load varies diurnally and spikes unpredictably, and you
  cannot consolidate onto fewer machines because **the state does not fit and moving it is
  expensive**.

---

## 4. The claim blueprint 7 cites

> LC tasks operate with strict service level objectives on tail latency, and **even small
> amounts of interference can cause significant SLO violations**.

They cite three prior works for it (Mars et al., Meisner et al., Leverich & Kozyrakis) and it
motivates their whole design. **This is the sentence our blueprint uses, and it is used
correctly.**

The consequence they draw: earlier colocation work either restricted itself to throughput
workloads, or detected interference and then **avoided or terminated the colocation** — which
protects the latency-critical job but gives up the utilisation gain.

---

## 5. What Heracles actually does

Coordinates **four isolation mechanisms**, two hardware and two software:

| Kind | Mechanism |
|---|---|
| hardware | shared **cache partitioning** |
| hardware | fine-grained **power / frequency** settings |
| software | **core / thread scheduling** |
| software | **network traffic control** |

It is a **real-time controller**. It identifies which shared resources are **approaching
saturation and likely to cause an SLO violation**, and configures the appropriate isolation
mechanism **proactively** to prevent it.

### Their three stated findings

1. **Using application-level latency in the control algorithm is critical** for guaranteeing
   quality of service.
2. **Coordinating multiple isolation mechanisms** is key to high utilisation without SLO
   violations — no single mechanism suffices.
3. Evaluated on **real Google servers** with production LC and BE tasks.

---

## 6. Results

- **90% effective machine utilisation**, averaged across all colocation combinations, **without
  latency violations** at any load level evaluated.
- **Throughput per TCO improved 15% to 300%**, depending on the initial average utilisation.

---

## 7. What kind of paper this is

- A **controller and its evaluation**, on production Google hardware and workloads.
- Depends on **hardware isolation features** (cache partitioning, fine-grained DVFS) that they
  note were not available in commercial chips until recently.
- It **prevents** interference. It does not diagnose a fault after the fact.
- The signal it steers on is **application-level latency**, not system telemetry.

---

## 8. What this means for our work

**The citation blueprint 7 uses is correct and worth keeping.** *"Even small amounts of
interference can cause significant SLO violations"* is the reason co-tenant CPU contention is
worth a blueprint at all — it establishes that the fault matters in production, not just in our
injection.

**Almost nothing else transfers, and it is worth being clear why:**

| Heracles | Us |
|---|---|
| **prevents** interference with a real-time controller | **diagnoses** it after the fact from a trace |
| steers on **application-level latency** | we never see application latency |
| needs **hardware cache partitioning and fine-grained DVFS** | we have neither |
| interference in **caches, memory, I/O, network** | our `noisy_neighbor` is **CPU time** |
| goal is **utilisation** | goal is **attribution** |

So this is a **motivation citation**, not a method one. It belongs in the blueprint's "why this
problem matters" framing and nowhere near its discriminators.

**One thing genuinely worth taking.** Their finding that **no single isolation mechanism is
enough** — you have to coordinate several — has an analogue on the diagnosis side: no single
signal separates our fault families either. Our own coverage sweep reached that conclusion
independently, and this is a citable precedent for the shape of the argument.

**And one number worth having.** Google websearch servers idle **30% of the time over 24
hours**. That is a concrete, citable statement of why co-tenancy exists at all — and therefore
why noisy-neighbour faults exist. Better than a vague "cloud providers oversubscribe".

**A caution about the pairing with CPI².** Both are Google, both about co-tenant interference,
and blueprint 7 cites both. They do different jobs: **CPI² detects and throttles an antagonist
after the fact; Heracles prevents interference before it happens.** Citing them as if they
support the same point would be sloppy — CPI² is the closer analogue to what we do.

---

## 9. Safe claims

- Servers are **50-70% of datacenter total cost of ownership**; average utilisation is
  **10-50%**.
- **Google websearch servers average 30% idleness over 24 hours** — 3,000 wasted servers in a
  10,000-server cluster.
- Latency-critical services cannot be consolidated onto fewer machines because their
  distributed state does not fit and moving it is expensive.
- **Even small amounts of interference can cause significant SLO violations** for
  latency-critical workloads.
- Prior colocation systems either restricted themselves to throughput workloads, or detected
  interference and avoided/terminated the colocation — protecting latency at the cost of
  utilisation.
- Heracles coordinates **four** isolation mechanisms: cache partitioning, power/frequency
  control, core scheduling, network traffic control.
- **Coordinating multiple mechanisms is necessary**; no single one suffices.
- Using **application-level latency** in the control loop is critical.
- Achieves **90% effective machine utilisation with no latency violations**, improving
  throughput/TCO by **15-300%**, evaluated on real Google servers with production tasks.

## 10. Do NOT claim

- That Heracles diagnoses or localises a fault. It is a preventive controller.
- That it uses kernel traces or system telemetry. It steers on application-level latency.
- That its mechanisms are available to us. Cache partitioning and fine-grained DVFS are
  hardware features we do not use.
- That it addresses CPU-time contention specifically. Its focus is cache, memory, I/O and
  network.
- That it and CPI² make the same point. One prevents, the other detects and throttles.

## 11. Reusable ideas

- **No single mechanism is enough** — on their side for isolation, on ours for detection. The
  same argument shape.
- **Quantify the waste before proposing the fix.** 30% idleness and 3,000 servers makes the
  case far better than "utilisation is low".
- **Proactive beats reactive when you can afford it.** They configure isolation *before* the
  SLO breaks. Our equivalent would be a collection-time check rather than post-hoc analysis.
- **Report the range, not a point.** 15% to 300% depending on starting utilisation is honest
  about when the technique helps most.
