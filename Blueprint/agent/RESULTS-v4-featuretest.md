# v4 feature test — does the skill/context stack work as intended? (2026-08-15)

20 leakage-audited runs (11 new + 9 prior smokes/partials) across S1 (skills-full), LOFO,
brief-injection, and query_source, compared per-incident against the S0 = gate-v3 baseline.
Auditor: PASS on every transcript. Verdict: **the machinery works as designed — the accuracy
lever is selector calibration, plus one genuine tool gap (topology can't see span-less
datastores).**

## What works as intended

- **Skill-guided wins**: TT `svc_cpu_cap` flipped S0 both=✗ → S1 **both=✓** (right skill chose
  cpu_throttling — the taxonomy fix skills were meant to deliver). Clean matches run cheaper
  (9–12 calls vs 12–16 in v3) and host-fault families stay fully correct.
- **Abstain + fallback**: SS `anomaly_disk` LOFO — correct abstain among 11 distractors,
  fallback fully correct (the never-seen-fault path).
- **Skill override**: TT `dependency_outage` LOFO — the selector picked a WRONG skill
  (db-latency), and the agent **abandoned it and still got both=✓**. The "abandon if evidence
  contradicts" instruction can work.
- **Brief injection**: no harm anywhere; one improvement (SS `svc_mem_cap` service ✗→✓); the
  correct case (SS `anomaly_mem`) stayed correct.
- **query_source**: used organically in 2/20 runs (didn't flip outcomes); infra works.

## What doesn't (ranked by impact)

1. **Selector calibration — S1 precision 6/11, LOFO abstention 1/4.** Three failure shapes:
   (a) *adjacent-class confusion*: noisy_neighbor→host-cpu-pressure, slow_db→service-network,
   svc_mem_cap→frozen-dependency, dep_outage→db-latency under LOFO. The look-alike
   discriminators exist — but they live in the Resolution template, which the selector never
   sees (it only reads Problem signatures).
   (b) *wrong abstains on absence-shaped faults*: TT anomaly_net and SS queue_backlog have
   skills whose signatures describe absences ("nothing saturated", "KPIs near-normal") — hard
   to match confidently.
   (c) LOFO distractors attract path-shaped/adjacent evidence instead of triggering abstain.
2. **Topology is blind to span-less components — the real cause of the slow_db misses.**
   Edges come from span parent→child links, so a datastore that emits no spans (mysql, *-db)
   NEVER appears as a callee. "Slow edges converge on the datastore" — the db-latency skill's
   signature and the agent's convergence reasoning — is structurally unobservable on TT; the
   evidence genuinely looks like service-network-path. Spans carry `network.peer.address` /
   `server.address`: client-span→peer edges would make datastores visible callees. Generic
   fix, not fault-specific.
3. **SS queue_backlog regressed to "normal" under S1** (v3 at least named a service). The
   silent-fault signature needs positive evidence the tools barely surface (consumer
   span-rate drop, broker asymmetry).
4. **Brief doesn't save calls yet** (12–27 calls with brief) — the agent re-surveys anyway
   because nothing tells it the survey is already done.

## Improvement plan (proposed, in order)

| # | Change | Type | Attacks |
|---|---|---|---|
| A | Topology: add client-span→peer edges (from `server.address`/`network.peer.address`) so span-less datastores appear as callees | tool, generic | slow_db misses, db vs service_network confusion |
| B | Selector v2: selector also sees each skill's discriminating boundary lines; instructed to compare top-2 candidates and check discriminators before committing; explicit pass over absence-shaped skills before abstaining | selector | 1a, 1b, 1c |
| C | Skill preamble: "FIRST verify this skill's signature via its discriminating checks; if any fails, state that and revert to the general method" — make the TT dep-outage override the norm | prompt | wrong-skill steering |
| D | Brief preamble: "the survey above already covers the no-filter overview — go straight to targeted queries" | prompt | call savings |
| E | Skills reference query_source where code confirmation helps (error-burst, memory-cap) | skills | unused synergy |
| F | queue_backlog: investigate surfacing consumer span-rate drop / broker asymmetry in traces or metrics | tool, later | known-hard silent fault |

Then ONE re-test of the same 11-incident set (plus slow_db/anomaly_net S1) before any bigger run.

## Raw table

See `results/v4_test/` + `v4_report.py` on Trillium. Selection: S1 6/11, LOFO abstain 1/4;
query_source 2/20; auditor PASS 20/20.

---

# Re-test after improvements A–D (13 runs, `results/v4_test2/`, auditor PASS)

Verdict per improvement (n=1 per cell — directional, not statistical):

- **A (topology peer-edges): the strategic win, with a side-effect.**
  **TT `slow_db` → mysql/db_latency BOTH-correct — first time in any leak-free
  configuration** (41 calls; the selector even picked a wrong skill and the agent overrode
  it to the right answer). Brief-mode slow_db now names toxiproxy (the actual injection
  proxy on the DB path) instead of a random victim. Side-effect: every TT service talks to
  the datastore through the proxy, so spanless DB edges now appear in MANY TT surveys and
  pull selector/agent toward db-flavored stories (anomaly_net S1 → db-latency; LOFO
  dependency_outage → mysql, losing the previous override win).
- **B (selector v2): no measurable gain** — S1 selection 2/7, LOFO abstain 0/2. Persistent
  confusions unchanged (noisy_neighbor→host-cpu, svc_mem_cap→frozen-dependency) plus the
  new db pull. Root cause identified: several decisive discriminators are NOT
  survey-visible — a memory working-set pinned at a flat ceiling and a throttled-seconds
  jump don't rank as "movers", so the selector literally cannot see them.
- **C (verify-first preamble): cuts both ways.** It enabled the slow_db override (wrong
  skill → right answer) — and it broke `svc_cpu_cap` (PRE both=✓ → POST miss): the agent
  SAW the throttle signal but discarded the correct skill because "cpu didn't flatten" and
  kernel called the wait "off-CPU external I/O" — which is precisely what cgroup
  throttling looks like (throttled = forcibly descheduled = off-CPU). Skill-content
  precision bug, not a mechanism bug.
- **D (brief survey-done line): clean win.** 27→10, 18→7, 18→14 calls with no accuracy
  cost. query_source usage rose to 4/13 runs.

Net on the hard-case set: both-correct 3→2, but the composition traded two fragile wins
for the structurally-important one (slow_db), and brief-mode cost dropped sharply.
SS `queue_backlog` remains unsolved in every mode (known-hard silent fault).

## Round 2 (applied 2026-08-15): survey-visible limit signals + skill precision

Changes: metrics `limit_signals` section (throttle rate always surfaced — verified it
exposes the ground-truth target directly on the real run; memory failcnt; working-set vs
*plausible* spec limit, stale/unset limits filtered) flowing into SIC/selector/brief;
skill-content fixes (throttle↔off-CPU consistency; memory-cap stale-limit caution;
db/network "background datastore edges" boundaries).

### Round-2 re-test (v4_test3 vs v4_test2, 13 runs, auditor PASS)

Targets hit:
- **svc_cpu_cap FIXED**: ts-travel-service/cpu_throttling both=✓ in 10 calls (the
  round-1 regression, repaired exactly by limit_signals + the throttle precision fix).
- **queue_backlog selector breakthrough**: async-queue-backlog-rca correctly selected
  for the FIRST time (absence-aware prompt working); agent now names queue-master
  (service ✓; fault still labeled dependency_outage).
- **brief svc_mem_cap: carts/memory_limit both=✓** (was service-only).
- **LOFO dependency_outage recovered both=✓** — wrong skill selected, agent overrode it
  using the new background-edges caution.
- Costs down where it matters (anomaly_net 21→11, svc_cpu_cap 27→10 calls).

Losses, both consistent with single-run variance on borderline incidents: TT slow_db
lost its round-1 both=✓ (across 5 leak-free runs of this incident: mysql✓ once, victim
4×SPAN — genuinely borderline); TT dependency_outage S1 slipped to fault-only.

Net: svc 7→8, both 2→3, S1 selection 2/7→3/7, src_used 4→5.

## Where this leaves v4 (recommendation)

Every engineered improvement has now demonstrably worked at least once; the remaining
misses are dominated by run-to-run variance on borderline incidents. Further prompt/skill
tuning against these 13 incidents would be overfitting. **Freeze v4 here; the next
information comes from the full S1/S2 campaign (with S0 re-measured on the v4 toolset),
where repeats and 23 incidents per condition give variance its denominator.**
