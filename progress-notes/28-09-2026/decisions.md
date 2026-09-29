# 28 September 2026

## The five untested blueprints, checked against the traces before spending a campaign on them

All five were written on 22-09 by one generator and have never been run on an agent. They
assert the same three things word for word, and carry the same six-event collection list:

    "a container is new to the window"
    "its share profile matches the measured range below"
    "no sibling container shows the same profile"

Tested each claim on every indexed run, both applications, 30 runs.

### 1. "No sibling shows the same profile" is false, 0 of 30

| | the newcomer | the busiest sibling |
|---|---|---|
| Sock Shop | 47% futex | **33%** futex |
| Train Ticket | 5% futex | **60%** futex |

On Sock Shop the newcomer is 1.4x its sibling, not "far above". On Train Ticket it is an order
of magnitude BELOW.

### 2. On Train Ticket the futex discriminator is inverted, and that is a property of the JVM

Every ordinary Train Ticket service sits at 55-61% futex **in the baseline**, before anything
is injected:

| container | futex share BEFORE | DURING |
|---|---|---|
| ts-travel-service | 61.3% | 60.5% |
| ts-preserve-service | 60.3% | 58.0% |
| ts-execute-service | 55.8% | 55.8% |
| ts-notification-service | 55.7% | 55.7% |
| the injected lock container | - | **5.5%** |

JVM threads park on futexes, so a Java service is a futex-heavy workload by nature. **"The
container whose futex share is far above every other container" would name an innocent service
on every Train Ticket run, in every family.** Not weak - inverted.

This is exactly the trap the network blueprint fell into: a signature measured on one
application, asserted as a general rule.

### 3. dependency_outage contradicts itself, and its real signature is the best of the five

Its `verdict_when` says "a container is new to the window". Its own `apply_when` says "no new
container appeared". The trace agrees with `apply_when` - the fault is `docker pause` on an
existing container, and there is no newcomer on Sock Shop in 3 of 3 runs.

What there IS, on both applications, 6 of 6:

| | before | during |
|---|---|---|
| Sock Shop | 1360, 1382, 1521 events/s | **1, 2, 5** |
| Train Ticket | 377, 462, 422 events/s | **4, 3, 4** |

Exactly one container goes silent, and it ranks first by that measure. **This is the strongest
and most portable signature measured in this project so far** - and the blueprint currently
tells the agent to look for the opposite thing.

### 4. conn_pool_exhaustion points at the wrong container

Its newcomer is the process holding connections open. The ground-truth target is the DATASTORE
(`catalogue-db` / `mysql`). Naming the newcomer scores wrong by construction. The datastore
itself does drop on Sock Shop - to 0.40-0.62 of baseline, ranking #3-4 of 20 - and does not
move on Train Ticket at all (ratio 1.01-1.02).

### 5. What IS real: the Sock Shop profiles separate the sidecar faults from each other

| family | futex | softirq | net | events |
|---|---|---|---|---|
| lock_contention | **47%** | 6% | 0% | 7.9M |
| priority_inversion | **41%** | **13%** | 1% | 2.4M |
| deadlock | **4%** | 4% | 0% | 10.5k |
| conn_pool_exhaustion | **0%** | 10% | **36%** | 66k |

Those four are genuinely distinct from one another and stable across all three runs each. That
is a real finding and worth keeping - as a Sock Shop observation, not a universal law.

### Verdict

| blueprint | safe to run? | why |
|---|---|---|
| `dependency-outage-retry-storm` | **after a rewrite** | signature is excellent and portable; the blueprint looks for the wrong thing |
| `lock-contention-futex-storm` | Sock Shop only | inverted on Train Ticket |
| `priority-inversion-nice` | Sock Shop only | inverted on Train Ticket |
| `deadlock-lock-order` | Sock Shop only | 4% futex is below every sibling on both apps; only the low event RATE separates it |
| `connection-pool-exhaustion` | **no** | names the holder, target is the datastore |

**Running these five as they stand would produce five more `0/60` rows and read as "kernel
traces cannot do this".** It would be the same mistake we spent this week undoing on `svc_net`.

### A note on the scorer

`nsmap` mislabelled the silent Train Ticket container - it ranked it #7 of 45 while the raw
measurement shows it going 422 events/s to 4. The container identification on Train Ticket is
still the weakest link in the scoring, and it is now blocking two separate results.

## dependency_outage rewritten, and a generator bug it exposed

### The rewrite

Its deciding test is now silence, which is what the traces show:

| | |
|---|---|
| verdict | exactly one container falls to `SILENT_MAX_SHARE` (0.02) or less of its OWN baseline rate |
| contrast | the next quietest is still at `SILENT_PEER_MIN_SHARE` (0.20) or more |
| and | no new container appeared - this fault removes a workload |

Both numbers are new entries in `thresholds.json`, so they cannot drift from the prose. They
are deliberately self-relative - a share of the container's own baseline - which is why they
transfer: a stopped process emits nothing on any hardware, at any scale.

Measured basis: the silent container fell to 0.09-1.19% of its baseline in 6 of 6 runs across
both applications, while the next quietest sat at 23-89%. Separation of 20x to 75x.

**The getrusage storm is kept, with its scope stated.** It is real - 6.7/s against 2474-2701/s,
a 371-404x rise - but ONLY on one of the two applications; the other measured 1.0x. So the
blueprint says explicitly that its absence is not evidence against the problem, and that this
signal names the VICTIM rather than deciding the verdict. That is the distinction the previous
version got backwards.

**Dropped:** "one caller spins" as a general claim. Zero containers rose above 1.5x on total
event rate in any of the 6 runs. The blueprint is still named `-retry-storm`, which now
overstates what we can show on more than one application.

### The generator was leaking raw placeholders to the agent

`fill_thresholds` was called in exactly two places - `verdict_when` and `rule_out` - so a
`{NAME}` written in any other field reached the agent as a literal brace. Three skills were
affected:

| skill | leaked |
|---|---|
| `db-latency-dependency-wait` | `{BLOCK_PARKED_X}` `{RETRANS_VETO_PCT}` `{STARVED_RQ_X}` |
| `dns-delay` | `{RETRANS_VETO_PCT}` |
| `dependency-outage-retry-storm` | the two new ones |

**`db-latency-dependency-wait` is the `slow_db` problem in the published study**, which scored
24/60 and 3/60. It has been handing the agent `{STARVED_RQ_X}` where a number belonged. That
is not the whole explanation for 3/60 on the window, but it is a defect in a published result
and it was invisible because nothing checked the generated output for unresolved names.

Fixed by substituting once over the finished body rather than per section - a per-section call
has to be remembered every time a section is added, and it was not. A name absent from
`thresholds.json` is still left visible so the validator catches a typo rather than silently
blanking it.

All 16 blueprints regenerate clean with no placeholders remaining.

## The other three sidecar blueprints, and a measurement error of mine that nearly inverted the result

### I was measuring the wrong container on Train Ticket

My first pass found the injected container by asking which container was NEW to the window.
That works on one application and not the other: on Train Ticket the injector sometimes starts
a few seconds before `injection_start_utc`, so it appears in the baseline and the newcomer test
picks up a load generator instead - a container with ~81k events and a 5% futex share.

That is what produced "on Train Ticket the discriminator is inverted, the injector sits at 5%
futex". **Wrong.** Locating the injector by its process names instead:

| family | application | events/s | futex | softirq |
|---|---|---|---|---|
| lock_contention | one | 62,796-63,380 | 47% | 5.9% |
| lock_contention | the other | 62,774-63,060 | 57% | 4.8% |
| priority_inversion | one | 19,470-19,632 | 41% | 13.4% |
| priority_inversion | the other | 16,476-16,763 | 52% | 10.9% |

**The injector behaves almost identically on both applications** - its event rate matches to
within 1%. The earlier finding was my detection method, not the data.

### What was still wrong with the blueprints

The futex-share comparison really does invert, just not the way I first described:

| | injector futex | busiest sibling |
|---|---|---|
| one application | 41-47% | 33% - injector ABOVE |
| the other | 52-58% | 60% - injector BELOW |

Java services park threads on futexes, so a futex-heavy container is ordinary where the services
are JVMs. "The container whose futex share is far above every other container" names an innocent
service there. The claim was wrong; my explanation of why was also wrong.

**What transfers instead:** the newcomer test plus the injector's own event rate and softirq
share, neither of which is a comparison against siblings.

| family | events/s | softirq |
|---|---|---|
| lock_contention | 62.8-63.4k | 4.8-5.9% |
| priority_inversion | 16.5-19.6k | 10.9-13.4% |
| deadlock | 87-731 | 4.4% |

Three bands about a hundredfold apart on rate, and softirq separates the two spinning faults
with no overlap on either application. Now `NEWCOMER_BUSY_PER_S` (10,000), `NEWCOMER_IDLE_PER_S`
(2,000) and `SOFTIRQ_INVERSION_MIN` (0.09) in thresholds.json.

### The caveat that goes in the paper, not just the code

`NEWCOMER_BUSY_PER_S` and `NEWCOMER_IDLE_PER_S` are ABSOLUTE rates, and their `transfers` field
says "partly" for a reason: they encode how hard our injector was configured to push and how
fast this testbed is. They held to within 1% across two applications **on identical hardware**.

More importantly, all three of these faults are injected as separate sidecar containers. **So
this signature is partly the signature of our injector rather than of lock contention arising
inside a service.** A real application holding a lock too long would show futex pressure in the
SERVICE container with no newcomer at all. Each blueprint now says this in its summary, and
tells the agent to report "an injected workload of this shape is present" rather than claiming
the application is contended.

That is worth stating plainly in the write-up. Three of our eleven problems test whether the
agent can spot a foreign container, not whether it can diagnose the named fault.

### Two more validator behaviours worth recording

`used_by` in thresholds.json must agree with `uses_thresholds` in each blueprint, and the
validator checks both directions. Rather than editing both lists by hand I now derive `used_by`
from what the blueprints declare - the validator exists because those two drift.

And the leak scanner rejected "two orders of magnitude" for a second time, because `orders` is
a service name. Reworded to "roughly a hundredfold". The scanner is right; the phrase is the
problem.

All 16 blueprints regenerate clean.

## connection-pool-exhaustion: name the datastore, not the holder

The generated version concluded on the container that was NEW to the window. That container is
the holder - the thing doing the exhausting. Ground truth names the DATASTORE being exhausted.
Naming the holder answers the wrong question by construction.

### What the datastore actually does

Asked the data rather than guessing which syscall should move. Inside the target container, the
per-connection setup path collapses while everything else keeps running:

| | before | during |
|---|---|---|
| `getpeername`, `gettid`, `access` | 169-177/s | **0.0-0.9/s** |
| the container's other events | continue | continue |

Ratio 0.00-0.01, ranked first among containers doing per-connection work in **3 of 3 runs**.

That is mechanically the right signature. An exhausted pool does not make a datastore quiet and
does not make it busy - it keeps serving the clients it already has and stops completing NEW
ones. So the work that stops is the work done per new connection.

### The scope limit is explainable, which makes it worth stating

On the second application the datastore does **0.7-1.1** of those calls per second at BASELINE,
against 169-177 on the first. Its callers hold pooled connections that are already established,
so the datastore barely does per-connection setup even when healthy. There is nothing to
collapse.

**That is not a weaker fault and not a failed detector - it is a different client architecture.**
The blueprint now gates on `SETUP_BASELINE_MIN_PER_S` (20/s) and tells the agent to report that
the check was not applicable, rather than falling back to naming the busiest container or the
newcomer. `SETUP_COLLAPSE_MAX` (0.05) is self-relative and transfers; the baseline floor is
marked `transfers: partly` because it is a gate on visibility, not a verdict.

### Where the five now stand

| blueprint | deciding signal | measured |
|---|---|---|
| `dependency-outage-retry-storm` | one container falls to <=2% of its own rate, next quietest >=20% | 6/6, both applications |
| `connection-pool-exhaustion` | datastore's per-connection setup collapses to <=5% | 3/3 where applicable; not applicable on the other |
| `lock-contention-futex-storm` | newcomer >=10k events/s, softirq <9% | 6/6, both applications |
| `priority-inversion-nice` | newcomer >=10k events/s, softirq >=9% | 6/6, both applications |
| `deadlock-lock-order` | newcomer <=2k events/s | 6/6, both applications |

Every one of the five now decides on something measured on the traces it will be run against,
and every threshold is a named entry in thresholds.json with its `transfers` field set honestly.
Three of them still carry the sidecar caveat: those faults are injected as separate containers,
so a match says an injected workload of that shape is present, not that the application itself
is contended.

All 16 blueprints validate and generate clean, with no unresolved placeholders.
