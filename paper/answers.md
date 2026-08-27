# Answers to Mahsa's questions (2026-08-19)

Each point: what we can answer today (with numbers from the recorded runs), and where
something new is needed, a concrete experiment design with its dependencies.

---

---

## 0. The dataset at a glance

### Runs

| Run type | Sock Shop | Train Ticket | Total |
|---|---|---|---|
| **Fault injections (labelled)** | 50 | 43 | **93** |
| Healthy controls (no fault) | 6 | 6 | 12 |
| Tracing-overhead runs | 4 | — | 4 |
| Pipeline smoke test | 1 | — | 1 |
| **All runs in the release** | 61 | 49 | **110** |

Of the 93 labelled injections, **89 are the canonical set** (46 Sock Shop from the v1
freeze + 43 Train Ticket). The other 4 are Sock Shop `anomaly_mem` calibration attempts
from one evening of tuning the memory stressor; **2 of those 4 are verified failures**
(the fault did not fire) and are kept for provenance, not for scoring.

Every run is 4 minutes: 60 s healthy, 120 s fault, 60 s recovery. Raw kernel data alone
is 109 GB for Sock Shop.

### Fault families

**12 families.** Sock Shop has all 12; Train Ticket has 11 (it has no message-queue
consumer, so `queue_backlog` does not apply). Both apps share the same recipes — only
the target and sizing differ.

| # | Family | Scope | Sock Shop target | runs | Train Ticket target | Expected winning modality |
|---|---|---|---|---|---|---|
| 1 | `anomaly_cpu` | host | host | 3 | host | kernel |
| 2 | `anomaly_disk` | host | host | 3 | host | kernel |
| 3 | `anomaly_mem` | host | host | 3 | host | kernel |
| 4 | `anomaly_net` | host | host | 3 | host | traces |
| 5 | `noisy_neighbor` | host (co-tenant) | host | 5 | host | kernel |
| 6 | `svc_cpu_cap` | service | carts | 5 | ts-travel-service | kernel |
| 7 | `svc_mem_cap` | service | carts | 3 | ts-order-service | logs |
| 8 | `svc_net` | service | carts | 3 | ts-basic-service | traces |
| 9 | `slow_db` | datastore | catalogue-db | 7 | **mysql (shared)** | kernel |
| 10 | `dependency_outage` | service | payment | 3 | ts-seat-service | traces |
| 11 | `error_storm` | service | catalogue | 5 | ts-order-service | logs |
| 12 | `queue_backlog` | broker | queue-master | 3 | — (n/a) | kernel |

Sock Shop counts are the v1 freeze (46 runs). Train Ticket totals 43 runs over its 11
families; the per-family split is in the release `manifest.csv`.

Verification status (Sock Shop): 43 of 46 `confirmed`, 3 `borderline` (all
`dependency_outage` — it degrades by hanging rather than erroring, so the metric gate is
weak by design). Every run carries a machine check that the fault actually fired.

### Components

Measured from each run's own container roster, not from deployment notes:

| | Components observed | Emit request traces | **Span-less** | Kernel-visible |
|---|---|---|---|---|
| Sock Shop | 16 (14 app + 2 injected) | 6 | **10** | 15 |
| Train Ticket | 46 (44 app + 2 injected) | 36 | **10** | 42 |

Span-less components are the databases, message broker, cache, service registry, proxies
and the injected fault containers. **Every datastore in both applications is span-less**
(0 of 4 and 0 of 3), while the kernel layer sees 4 of 4 and 2 of 3 — which is the whole
reason the kernel modality is in this dataset.

## 1. Total number of components — why more components than services?

"One service per container" holds for *business logic*, but a running deployment
contains three more kinds of containers, and that is where the extra components come
from:

**Sock Shop** (the app itself is 14 containers):
- 8 business services: front-end, catalogue, carts, orders, shipping, payment, user, queue-master
- 4 databases (one per stateful service): catalogue-db (MariaDB), carts-db, orders-db, user-db (MongoDB)
- 1 message broker: RabbitMQ
- 1 ingress: edge-router
- plus our collection stack (not part of the system under test): Toxiproxy (fault
  injection path), OTel collector, Prometheus, cAdvisor, node-exporter — ~19–20
  containers running in total.

**Train Ticket** (~67 containers running in total, from our deployment notes):
- ~39 Java business services (`ts-*-service`)
- 1 UI dashboard, 1 **shared MySQL** (all services use it — the architectural choke
  point we chose it for), plus a voucher-service MySQL, Redis, and the Nacos service
  registry
- plus the same collection stack.

So: services ⊂ components. The non-service components (databases, broker, cache,
registry, proxy) are precisely the ones that emit **no request spans** — they only
appear in traces as callees, in container metrics, and in the kernel layer. That is
why they matter for the study (see #2).

*Done:* the census is now measured, not estimated — see the component table in §0. It is
generated from each run's own container roster (`component_census.py`), because the
telemetry-derived service list also picks up metric labels that are not containers at all
(os-version strings, scrape-job names) and inflated a first draft to 17/50. Per-component
detail: `agentic-rca/results/review/component_census.json`.

## 2. Faults injected into services vs. components — which are detected better?

Of the 12 fault types, by what the *culprit object* is (per app; 23 scored cases in
the standard setup):

| Target of injection                   | Fault types                                                               | Cases |
|---------------------------------------|---------------------------------------------------------------------------|-------|
| Host resource (whole machine)         | CPU, disk, memory, network stress                                         | 8     |
| A business **service** container      | error burst, frozen dependency, CPU cap, memory cap, per-service network  | 10    |
| A **non-service component**           | slow database (Toxiproxy on the DB path), silent queue backlog (RabbitMQ) | 3     |
| A **rogue container** outside the app | noisy neighbour                                                           | 2     |

Answer to the "vice versa" question: **faults injected into services are localized
far better (9/10) than faults injected into non-service components (1/3).** This is
not an accident — the non-service components are span-less (see #1), so ordinary
request telemetry points *near* them but not *at* them. It is also the pre-registered
blind-spot hypothesis of the dataset: these are exactly the cases where the kernel
layer is predicted to be decisive, and indeed the one non-service success (Sock Shop
slow database, fully correct) rests on the kernel wait analysis; it even survives
with traces removed entirely.

Caveat worth stating in any table: scoring is always at component granularity (the
agent must name the culprit component); the rows above differ in what kind of
component the ground-truth culprit is.

## 3. LLM-only baseline (no tools), with a citable prompt

Agreed — this closes the "is it the agent loop or just the LLM?" gap. Design:

- **Same model, zero tools, one shot.** The model receives the incident's *evidence
  briefing only* (the same deterministic symptom summary the agent gets, same
  masking) and must answer in the same schema. No tool loop, no follow-up queries.
- **Prompt provenance:** we follow Ahmed et al., ICSE 2023, *"Recommending Root-Cause
  and Mitigation Steps for Cloud Incidents using Large Language Models"* — the
  standard reference for one-shot LLM root-cause recommendation from an incident
  summary — adapting their incident-description prompt to our answer schema, and we
  cite it so the prompt design is defensible. (RCACopilot, Chen et al. EuroSys 2024,
  is the tool-augmented reference point on the other side.)
- Two variants if we want a lower bound too: (a) briefing-only as above; (b) a naive
  fixed dump of raw telemetry excerpts instead of the briefing.

Cost: 23 incidents × ~1 call ≈ well under $1. No new collection needed — runs on the
recorded dataset. **This slots directly into Table 1 of the report between the
statistical baselines and the full agent.**

## 4. CCR-style tooling

Noted as an example for the write-up context — skipping per your note.

## 5. Per-fault evaluation table

Already exists: the report appendix has the full per-fault outcome map — 23 fault
cases × 7 setups (standard, kernel full/raw/none, no traces, lean, minimal), showing
component-right vs fully-correct vs miss for each. It is generated by script from the
recorded results, so extending it with new setups (e.g. the LLM-only baseline, #3) is
one command.

## 6. Using skills interchangeably — showing guides are root-cause-specific

We have indirect evidence already: in the leave-one-out condition the selector picks
a *wrong* guide and costs ~18 points versus no guide at all — mismatched guides
actively mislead, which already implies specificity.

To show it directly, the clean experiment is a **forced-guide cross matrix**: bypass
the selector and force guide *g* onto fault *f* for every (g, f) pair (or a sampled
subset — 12 guides × 12 fault families is 144 cells; sampling the diagonal plus 2–3
off-diagonal cells per row keeps it ~$5). Expected picture: strong diagonal (right
guide helps), depressed off-diagonal (wrong guide hurts below the no-guide line).
That matrix *is* the specificity claim, in one figure. Runs entirely on the recorded
dataset; the harness already supports forcing a guide.

## 7. Code-level mutation faults (testing the source-code tool)

Good fit for the harness — the agent already has a source-query tool that current
faults never exercise (all 12 are operational). Design, respecting the "must be
captured in operational data" constraint:

- Mutate only in ways that *manifest in telemetry*: remove a third-party/downstream
  HTTP call (dependency edge disappears from traces, downstream errors appear);
  remove or reorder an already-logged statement (log-pattern change); mutate a
  database call (e.g. drop an index hint / widen a query → latency shifts to the DB,
  visible in kernel wait shares); introduce lock contention (kernel-visible).
- Practical scope: our two instrumented forks (Node front-end, Go catalogue) already
  have the fork-branch + compose-overlay rebuild pipeline, so mutations are a branch
  + rebuild away. Train Ticket Java rebuilds are heavier — phase 2.
- Each mutation gets the same treatment as existing faults: a machine-checked
  verification that the fault actually fired in telemetry before the run counts.

**Dependency:** this needs new collection runs, and the collection VM is currently
stopped (GCP billing paused since 2026-08-12). Everything up to "start the VM" can be
prepared now (mutation branches, verification targets).

## 8. Top-1 / Top-3 / Top-5 answers + MRR, hit@k, precision@k, MAP

Agreed, and half of it exists: the **non-LLM baselines already report AC@1 / AC@3 /
MRR** (46% / 63% / 0.54 overall), because RCAEval-style methods natively emit ranked
lists. The agent currently emits a single verdict, so:

- Change the final-answer schema to a **ranked list of up to 5 (component,
  fault type) candidates, each with its own supporting evidence** — not "give me 5
  guesses", but "which alternative hypotheses did your evidence actually leave open,
  in order". Then compute hit@1/3/5, MRR, precision@k, MAP against the same ground
  truth, directly comparable to the baseline table.
- On your ranking-semantics point (an LLM's list ranks "next most likely alternative
  in its reasoning", not calibrated probabilities): we will say exactly that in the
  method text, and mitigate it two ways — require independent evidence per candidate
  (a candidate without its own evidence is dropped, so the list is evidence-ranked
  rather than token-ranked), and optionally add a **self-consistency variant**
  (sample the diagnosis n times, rank candidates by frequency), which is the closest
  cheap approximation to probability ranking for LLMs. Comparing the two rankings is
  itself a small result.
- Cost: re-run needed (output format changes generation) — 23 incidents × the 2–3
  headline setups ≈ $1–2.

You're right that this raises the headline: today's "wrong-fault-type" cases are
mostly near-misses at label boundaries (our conservative secondary scoring already
moves 52%→65%), so hit@3 on fault type should land well above 57%.

## 9. Multi-fault cases

Currently out of scope by construction — every recording has exactly one injected
fault (that's what makes labels unambiguous). Adding them is a collection change, not
an analysis change:

- Design: concurrent fault pairs of two kinds — *entangled* (e.g. noisy neighbour +
  service CPU cap, symptoms overlap) and *independent* (e.g. slow database + error
  burst in another service). Ground truth becomes a set; report single-fault and
  multi-fault results separately (never pooled), scored with the set-aware metrics
  from #8 (this is exactly where MAP/precision@k earn their keep — hit@3 with 3
  guesses for 2 true faults must not be conflated with 3 guesses for 1).
- **Dependency:** same as #7 — needs the collection VM. The fault recipes compose
  (they're independent scripts writing to the same ground-truth state dir), so the
  rig work is small; the cost is VM time + new recording storage.

## 10. Modality fusion (mapping modalities to fault types)

Understood — not pursuing. Noted for the write-up: our direction is *fault types →
investigation skills* (and separately, *how much of each modality an agent needs*);
the fusion direction (*modalities → fault types*) is adjacent published territory
(TSE-track), and we should cite it as related rather than enter it.

## 11. Pipeline figure + why each skill is designed the way it is

Both accepted as write-up work:

- **Pipeline/novelty figure:** one diagram — collection (4 modalities, one clock) →
  derivation ladder (L0→L3) → masking → evidence briefing → selector/guides → agent
  loop → verdict → leakage audit + scoring — with the novel boxes highlighted
  (kernel ladder, leakage control, briefing, guide library + its evaluation).
- **Skill design rationale:** each guide is not folklore — it encodes the
  *pre-registered discriminative signature* from the fault catalog, written before
  any experiment. Example for your question: CPU exhaustion vs. a latency fault are
  mechanically different in the kernel wait decomposition — CPU exhaustion shows
  services *ready-but-waiting-for-CPU* (runnable share rises host-wide, everything
  slows together), while a slow-database fault shows the caller *blocked on external
  I/O with idle CPU* and the latency concentrated on one dependency path. Each
  guide's "checks" section is exactly that signature plus the known confusions (e.g.
  CPU *cap* vs CPU *exhaustion*: same symptom in one service, opposite host picture).
  We will add a table mapping guide → signature → catalog prediction, which makes the
  design auditable instead of intuitive.

## 12. How do *other* approaches behave under data reduction — and is our advantage just "more data"?

Already measured — this was run as part of the degradation program (the baselines
went through the same reduction grid; 1,395 evaluations per method):

- **Statistical rule-tree baseline:** drops 38%→34% under trace thinning; flat on the
  metric/log axes. **Multi-modal BARO:** flat at 48% everywhere.
- But *flat is not robust here* — they are flat because each leans on one modality
  and is already low. Neither can use the kernel layer at all: feeding kernel
  features into the academic method changed **nothing** (with-kernel == without, for
  every fault family). Their degradation curve is horizontal for the uninteresting
  reason.
- The decisive control for "it's just more data": at the **minimal budget** — 115×
  less data than full and *no kernel at all* — the agent still localizes **83%**,
  versus **46–48%** for the baselines given *everything*. So the gap survives when
  the data advantage is inverted; what remains is iterative hypothesis-driven
  querying and cross-modal reasoning, which is the claim.
- What the report should add (small): the baseline degradation curves plotted on the
  same figure as the agent's, so the comparison is visual — data exists, one plotting
  change.
