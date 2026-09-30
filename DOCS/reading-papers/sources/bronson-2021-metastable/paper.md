# Paper Context: Metastable Failures in Distributed Systems (HotOS 2021)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is a **7-page HotOS vision paper**. No system, no experiments, no numbers from a real
> deployment - the figures are from an *idealised* example. Its value is a **framework and a
> vocabulary**, and one sentence that our dependency-outage blueprint depends on. See §10.

---

## 1. Bibliographic info

- **Title:** Metastable Failures in Distributed Systems
- **Authors:** Nathan Bronson (Rockset; formerly Facebook), Abutalib Aghayev (Penn State),
  Aleksey Charapko (University of New Hampshire), Timothy Zhu (Penn State)
- **Venue:** Workshop on Hot Topics in Operating Systems (HotOS '21), Ann Arbor, MI,
  31 May - 2 June 2021, pp. 221-227. 7 pages
- **DOI:** 10.1145/3458336.3465286
- **Type:** vision paper

```bibtex
@inproceedings{bronson2021metastable,
  title     = {Metastable Failures in Distributed Systems},
  author    = {Bronson, Nathan and Aghayev, Abutalib and Charapko, Aleksey and Zhu, Timothy},
  booktitle = {Workshop on Hot Topics in Operating Systems (HotOS '21)},
  pages     = {221--227}, year = {2021},
  doi       = {10.1145/3458336.3465286}
}
```

---

## 2. One-paragraph summary

Some outages keep going **after the thing that caused them has gone away**. The authors call
these **metastable failures**. They happen with no hardware fault, no config error and no
software bug. A system runs fine, load creeps above an invisible threshold, something small
happens (a trigger), and then a **feedback loop** holds the system in a broken state until
someone reboots it or cuts the load hard. Useful throughput drops to almost nothing. The
paradox is that the loop is usually created by a feature meant to **improve** efficiency or
reliability - retries, caching, failover. The paper gives four real examples from a decade of
running hyperscale systems, surveys the ad-hoc fixes industry has found, and argues that
handling *unknown* metastable failures is an open problem.

---

## 3. The three states (Figure 1)

| State | What it means |
|---|---|
| **Stable** | A trigger causes errors, but they clear once the trigger goes. The system self-heals |
| **Vulnerable** | Still healthy and serving normally. But a trigger can now push it over |
| **Metastable** | Goodput is unusably low. It **stays** there after the trigger is removed |

Three things about this that are easy to miss:

1. **The vulnerable state is not overload.** A system can sit in it for months or years.
2. **Many production systems run in the vulnerable state on purpose**, because it is far more
   efficient than the stable state.
3. **Leaving the metastable state needs a strong push** - reboot, or a large load cut.

**What is *not* metastable:** anything that resolves when the trigger stops. The paper names
DoS attacks, limplock, and livelock as non-examples.

---

## 4. The sentence that matters most

> "It is common for an outage that involves a metastable failure to be initially blamed on the
> trigger, but the true root cause is the sustaining effect."

They restate it as a principle in §3:

> "We consider the root cause of a metastable failure to be the sustaining feedback loop,
> rather than the trigger. There are many triggers that can lead to the same failure state, so
> addressing the sustaining effect is much more likely to prevent future outages."

---

## 5. The four case studies

### 5.1 Request retries (the one we care about)

Setup: a stateless web app queries a database. DB answers under 100 ms below 300 QPS; above
that, latency gets an order of magnitude worse. Each user request makes one query, plus a
retry if the first does not return within 1 s.

The sequence:
1. App is running normally at **280 QPS**.
2. Trigger: a **10-second network outage** on the switch between app and DB.
3. Connectivity returns; every packet lost during those 10 s is retransmitted at once.
4. The surge overloads the DB and latency rises.
5. While latency is high, every request retries, so the DB sees **560 QPS**.
6. That prevents the DB recovering. Goodput is **zero** - every query times out.

Thresholds in their Figure 2: stable below **150 QPS**; vulnerable above it; recovery requires
dropping load below 150 QPS or limiting retries to under 20 QPS.

**Related: request failover.** Routing away from unhealthy replicas does not amplify work by
itself - each request is handled once - but it makes failures **cascade**. When replicas are
sharded differently, a transient point failure can grow into a total outage.

### 5.2 Look-aside cache

90% hit rate means the app can serve 3,000 QPS from a DB that handles 300. But anything above
300 QPS is vulnerable, because in the worst case every request hits the DB. If the cache is
lost, the DB is overloaded, and **the app cannot refill the cache because its own timeout marks
every query failed**. Losing a 90%-hit cache is a **10× query amplification**.

### 5.3 Slow error handling

Success paths are optimised down to TLB misses. Error paths are written for debuggability: a
stack trace (CPU), a reverse DNS lookup for the client name (blocks a thread), a detailed local
disk record (can block on I/O), and a send to a central logging service (network). If a trigger
exhausts any resource the error path uses, **error handling makes the shortage worse**. They
say they have seen this be strong enough to self-sustain.

### 5.4 Link imbalance (the hardest one)

Aggregated network links between a cache cluster and a DB cluster. A TCP connection is pinned
to one physical cable by a hash of source/dest IP and port. Averaged over many connections the
load should spread evenly - so all traffic landing on one cable looks impossible.

What actually happened: a spike of cache misses sends many queries in parallel, one per
connection. Queries crossing a congested link **finish last**. The connection pool uses an
**MRU policy** - most recently used connection first. So each miss spike **re-sorts the pool
with the slowest links on top**. In steady state, far fewer concurrent queries run, so nearly
all of them go to the congested link. The loop closes.

- Took **more than two years** to explain. Multiple outages.
- Root-caused to many different triggers, and **declared fixed several times prematurely**.
- Attempted fixes included switches from other vendors and a firmware change to the hash.
- Solving it needed engineers from several layers together: the application layer could not
  understand it with a simple model of the network, and the network layer could not solve it
  with a simple model of the application.
- **The fix was one line** - change the connection pool policy.

---

## 6. Handling metastability (their §3)

| Technique | Point, and the catch |
|---|---|
| **Change policy under overload** | disable retries/failover, retry budgets, LIFO scheduling, smaller queues, priorities, load shedding, circuit breaker. Catch: retry decisions are made per client, so coordination is hard, and sharing status can itself become a sustaining effect |
| **Detect persistent overload vs a spike** | measure **minimum queueing latency over a sliding window** (Codel-style). A small minimum means the queue drained at some point, so it is a manageable spike |
| **Prioritisation** | lower-priority retries would break the retry loop. Catch: priority systems cover only some resources. One geo-distributed system had **worst-case work amplification over 100×** despite a sophisticated end-to-end priority system, and still fell over |
| **Architecture encodes priority** | with a look-aside cache you *cannot* prioritise filling the cache over serving clients; with a **read-through cache** it is trivial - a permissive DB timeout refills the cache even after the app gives up |
| **Stress tests** | small-scale tests give little confidence, because loop strength varies with scale. Better: rebalance production traffic (Kraken-style) with engineers standing by |
| **Organisational incentives** | a better cache eviction algorithm lets you reclaim DB capacity - easy to measure and reward, and a false economy if the system can then no longer survive cache loss |
| **Fast error paths** | send failures to a dedicated logging thread over a bounded lock-free queue; on overflow just count them. Throttle stack traces - a sample is enough |
| **Outlier hygiene** | the same root cause usually shows up earlier as latency outliers or a cluster of errors, even when the loop is too weak to run away |
| **Autoscaling** | does not make you immune, but a capacity buffer reduces exposure |

---

## 7. Concepts proposed for future research (their §4)

- **Work amplification** - the sustaining effect nearly always involves extra wasted work in
  the atypical case. They want systems that **upper-bound** it.
- **Characteristic metric** - a metric that moves with the trigger and **only returns to normal
  once the failure resolves**. Observed ones: queueing delay, request latency, load level,
  working set size, cache hit rate, page faults, swapping, timeout rates, thread counts,
  **lock contention**, connection counts, operation mix. They note queueing delay is far more
  robust to workload changes than QPS.
- **Hidden capacity** - the stable/vulnerable boundary; the load below which the system
  self-heals. Different from advertised capacity. In the cache example, advertised is 3,000
  QPS and hidden is 300.
- **Trigger intensity** - in the vulnerable state the outcome is not binary. At 151 QPS the
  system survives a much bigger spike than at 299 QPS. Small triggers are more common, so
  systems near advertised capacity fail from very weak triggers.
- **Reconfiguration cost** - elastic scaling reduces capacity short-term (state transfers,
  metadata updates), so it may break the loop too slowly to be a recovery strategy.
- **Reproduction** - load generators used to trigger these must not suffer **coordinated
  omission**.

---

## 8. What kind of paper this is

- **HotOS vision paper.** 7 pages. Explicitly aims to start a discussion.
- **No implementation, no evaluation, no measurements from production.** The numbers (300 QPS,
  150 QPS, 90% hit rate, 10×) are from **worked idealised examples**, not measured systems.
- The case studies are described as "simplified versions" of failures observed in production.
- The 100× work amplification figure is the one concrete production number, given without
  detail.
- **No dataset, no tool, no detection method.**

---

## 9. Stated open problems

- Designing systems that avoid metastable failures while staying efficient.
- Detecting the vulnerable state at all - hard given system size.
- Predicting a failure, which needs both the vulnerable state *and* the future trigger.
- Estimating the probability of a **novel** metastable failure.
- Reproducing these without a full-scale replica.
- Knowing how a code or config change affects loop strength.

The paper opens §4 with a quote it attributes to a VP: *"Can you predict the next one of these,
rather than explain the last one?"*

---

## 10. What this means for our work

**This is the citation behind blueprint 5's two-part answer.** Our
`dependency-outage-retry-storm` blueprint is told to report the **trigger** (the dependency
goes silent) and the **sustaining loop** (the callers' retries) as **separate findings**. That
design comes straight from this paper's central claim, and the quote in §4 above is the exact
line to cite for it.

**Why it is a genuinely good citation for that.** It is not a vague warning. It says the
trigger and the root cause are **different things**, and that fixing the trigger does not
prevent recurrence because many triggers reach the same failure state. That is a structural
argument for reporting both.

**Where we should be careful.** Our injected `dependency_outage` is a *paused container*, which
is a trigger we control. We are not reproducing a metastable failure - our fault ends when we
un-pause it, which by this paper's own definition makes it **not metastable**. So:

- **Safe:** cite it for *why the blueprint separates trigger from sustaining effect*.
- **Not safe:** claim our runs contain metastable failures, or that we detect them.

**Two concepts worth borrowing into our vocabulary.**

- **Characteristic metric** - a signal that stays abnormal until the problem is actually
  resolved, rather than one that tracks the trigger. That is close to what a good
  discriminator is in our blueprints. Their list includes **lock contention** and **connection
  counts**, which map onto our blueprints 6 and 3.
- **Work amplification** - the callers' CPU rising from retry work is exactly this, and it is
  the observable side of the sustaining loop in kernel terms.

**One thing that argues against a naive reading of our own data.** The link-imbalance case took
**two years** and needed people from several layers, because neither the application view nor
the network view was enough alone. That is a caution worth keeping: a single-modality
diagnosis - even a good one - can be confidently wrong about a cross-layer feedback loop.

---

## 11. Safe claims

- Metastable failures persist after the trigger is removed, and need a strong corrective push
  (reboot or large load reduction) to clear.
- They occur with no hardware failure, configuration error, or software bug.
- The sustaining loop is usually created by features that improve efficiency or reliability:
  retries, caching, failover.
- **The root cause is the sustaining effect, not the trigger**, and outages are commonly
  blamed on the trigger.
- Many production systems deliberately run in the vulnerable state, because it is much more
  efficient than the stable state.
- Losing a cache with a 90% hit rate is a 10× query amplification.
- One production system reached worst-case work amplification of over 100× despite an
  end-to-end priority system.
- The link-imbalance failure took over two years to diagnose and was fixed by one line.
- Failures that clear when the trigger stops (DoS, limplock, livelock) are **not** metastable.

## 12. Do NOT claim

- Any measured detection rate, accuracy, or frequency. The paper has none.
- That the QPS thresholds (300, 150, 280) come from a real system. They are an idealised
  example.
- That the paper proposes a detection method. It proposes research directions.
- That our injected dependency outage is a metastable failure. It resolves when we stop it,
  which the paper explicitly excludes.

## 13. Reusable ideas

- **Separate trigger from sustaining effect** in any diagnosis output.
- **Characteristic metric**: prefer a signal that stays abnormal until the problem is truly
  resolved over one that merely tracks the trigger.
- **Hidden vs advertised capacity** - the load at which a system self-heals is not the load at
  which it still serves.
- **Minimum queueing latency over a sliding window** to tell a persistent overload from a
  spike. A neat, cheap discriminator.
- **Optimise the error path, not just the success path.**
- **Outlier hygiene** - the same loop usually shows as latency outliers long before it runs
  away. Worth checking whether a weak version of a fault is visible in our baselines.
