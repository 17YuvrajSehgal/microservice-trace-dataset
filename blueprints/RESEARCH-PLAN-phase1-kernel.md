# Phase 1 research plan — kernel traces only

Goal: make each blueprint **reliable**, not just accurate on the runs it was written from.
Scope for this phase: **kernel traces (L0) only.** Metrics, logs and spans come later.

Written 2026-08-29. Branch `blueprints`.

---

## 1. Where we actually stand

| | |
|---|---|
| Blueprints | 2 — `cpu-contention-co-tenant` (v6), `db-latency-dependency-wait` (v5) |
| Incidents evaluated | 24 — 12 Sock Shop + 12 Train Ticket |
| Families evaluated | **2 of 14** — `noisy_neighbor` and `slow_db` only |
| Best result | SS 83% fully correct, TT 88%, 100% precision |
| Known failure | datastore blueprint fell to 44% precision on Train Ticket before being fixed |

## 2. The problem with the current evidence

Every evidence pack we have is from one of the two families the blueprints are designed to
fire on. **A false positive was structurally impossible in that test set.** The 100%
precision number is therefore not a specificity measurement — it is a sensitivity
measurement with no negative class.

For an agent that must be reliable in the wild, the missing question is the important one:

> When a blueprint is offered an incident that is **not** its problem, does it stay quiet?

We have 12 more fault families and 13 no-fault runs sitting in the dataset, and neither
blueprint has ever been run against any of them.

## 3. Why the datastore blueprint broke on the second app

Recorded so we do not repeat the mistake. The rule fires on one socket-waiting syscall
inflating ≥5×. On Sock Shop the datastore polls continuously, so the inflation is huge and
obvious (36.8×). On Train Ticket the architecture differs, the same signal is weaker, and
precision fell to 44%.

The lesson generalises: **a threshold measured on one application encodes that
application's architecture.** Robustness work in this phase is mostly about finding
discriminators that do not carry that hidden dependency — or making the dependency explicit
and measurable rather than baked into a constant.

## 4. What "various datasets" can mean here — an honest constraint

Phase 1 is kernel-only, and this limits where we can go for external validation:

- Public microservice RCA datasets (RCAEval, LEMMA-RCA, LO2, Loghub) carry **metrics, logs
  and spans — not kernel traces**. They cannot exercise a kernel discriminator at all.
- So external-dataset validation is **not available** for phase 1. It becomes available in
  later phases as we add modalities.

Therefore robustness in this phase is bought from **diversity axes inside our own data**,
which is larger than it first appears:

| Axis | Levels available |
|---|---|
| Application | 2 — Sock Shop (polyglot, small), Train Ticket (Java, 40+ services) |
| Fault family | 14 including `normal` |
| Intensity | aggressive, subtle |
| Workload pattern | steady, burst |
| Repeats | 3–7 per family |
| Total runs | **110** |

The negative class — 12 non-target families plus 13 no-fault runs — is the part we have
never used, and it is what turns a sensitivity number into a reliability number.

---

## 5. Experiments

### E1 — Specificity sweep (running first)

Run both blueprints' decision rules against runs from families they should **decline**.

Nearest neighbours first, because that is where a false fire is most likely:

| Run family | Why it is dangerous | Which blueprint is at risk |
|---|---|---|
| `anomaly_cpu` | host CPU saturation also inflates runqueue delay broadly | cpu-contention |
| `svc_cpu_cap` | cgroup throttling also makes threads wait for CPU | cpu-contention |
| `dependency_outage` | a hung dependency also blocks a socket syscall | datastore-wait |
| `svc_net` | added network delay also inflates socket waits | datastore-wait |
| `normal` | nothing is wrong; **neither** may fire | both |

Then the remaining families: `anomaly_mem`, `anomaly_disk`, `anomaly_net`, `queue_backlog`,
`svc_mem_cap`, `error_storm`.

**Outputs:** a fire/decline matrix over all families; for every false fire, the measured
values that caused it; and the margin distribution — how close each family sits to the
5× and 2× thresholds.

**Success is not "zero false fires."** It is *knowing the false-fire rate and why*, and
having a discriminator that closes the gap without being fitted to this test set.

### E2 — Threshold margin and sensitivity analysis

For every run, record the actual measured statistics rather than the boolean. Then:

- plot the separation between target and non-target families per discriminator
- report how much the threshold could move before a decision flips
- identify discriminators whose margin is thin — those are the fragile ones

The current thresholds (5× blocking, 2× runqueue) were set from two runs. E1+E2 tells us
whether they survive contact with 110.

### E3 — Cross-application invariance

Re-express each discriminator so it does not depend on one app's architecture. Candidates:

- ratios between processes within a run instead of absolute inflation
- rank-based rather than threshold-based comparisons
- normalising by the run's own baseline spread rather than a fixed multiplier

Test: a rule fitted on Sock Shop only, evaluated on Train Ticket only, and vice versa.
That is the honest transfer measurement, and it is what the 44% episode was really about.

### E4 — Per-problem research dossier

For each blueprint, a written record of:

- what the literature establishes about the signal (runqueue delay, syscall blocking) —
  grounded in `DOCS/reading-papers/`
- what we measured ourselves, with the run count behind each number
- what we tested and retracted, and why

This is the "collect the research and findings" part, and it is what makes a blueprint
defensible rather than merely tuned.

### E5 — Abstention quality

The blueprint's advertised strength is that it declines rather than guessing. E1 gives the
first real test: on 12 families it has never seen, how often does it correctly decline, and
when it declines on a target family, is that a threshold problem or a genuine weak signal?

---

## 6. Order of work

1. **E1 nearest neighbours** — Sock Shop: `anomaly_cpu`, `svc_cpu_cap`, `dependency_outage`,
   `svc_net`, `normal`. This is the decisive first result.
2. E1 remaining Sock Shop families.
3. E1 repeated on Train Ticket — the cross-app specificity question.
4. E2 margins from the data E1 produces (no new decoding needed).
5. E3 invariance, informed by where E1/E2 show fragility.
6. E4 dossiers, written alongside.

## 7. Rules carried over

- **Measure first, then write.** No claim enters a blueprint before it is measured. The
  validator rejects a discriminator with no cited measurement.
- **Do not fit to the test set.** If a threshold change would rescue a run, that is recorded
  as a finding, not applied silently. The 5× threshold was deliberately not lowered to
  capture two subtle runs; the same discipline applies here.
- **Retractions are kept**, with the measurement that killed them, and are rendered into the
  skill so the agent is warned off them too.

## 8. Cost

Decoding is the expensive part: ~6–9 minutes per run, ~13–37 GB staged per run. Scratch has
~22 TB free, so the constraint is time, not space. E1's first batch is 12 runs.
